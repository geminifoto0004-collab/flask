"""MySQL/TiDB derived-table compatibility for ORDER's SQLite-style queries."""
from __future__ import annotations

import re

from .db_compat import TiDBSQLiteCompatConnection, TiDBSQLiteCompatCursor


_ALIAS_BOUNDARY_KEYWORDS = {
    'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET',
    'UNION', 'EXCEPT', 'INTERSECT', 'JOIN', 'LEFT', 'RIGHT',
    'INNER', 'OUTER', 'CROSS', 'ON', 'USING', 'WINDOW', 'FOR',
}


def _find_matching_paren(sql: str, open_pos: int):
    depth = 0
    quote = None
    i = open_pos
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote and quote in {"'", '"'}:
                    i += 1
                else:
                    quote = None
            elif ch == '\\' and i + 1 < len(sql):
                i += 1
        else:
            if ch in {"'", '"', '`'}:
                quote = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def ensure_mysql_derived_aliases(sql: str) -> str:
    """Add aliases required by MySQL/TiDB after anonymous FROM/JOIN subqueries.

    SQLite accepts ``FROM (SELECT ...)`` without an alias. MySQL/TiDB raises
    error 1248. ORDER has several legacy SQLite queries that use this form, so
    the WAN compatibility boundary fixes it without changing LAN SQL/routes.
    """
    text = str(sql or '')
    pattern = re.compile(r'\b(?:FROM|JOIN)\s*\(', flags=re.I)
    search_from = 0
    serial = 0

    while True:
        match = pattern.search(text, search_from)
        if not match:
            break
        open_pos = text.find('(', match.start(), match.end())
        close_pos = _find_matching_paren(text, open_pos)
        if close_pos is None:
            break

        tail = text[close_pos + 1:]
        stripped = tail.lstrip()
        needs_alias = False
        if not stripped or stripped.startswith((';', ',')):
            needs_alias = True
        else:
            token = re.match(r'([A-Za-z_][A-Za-z0-9_]*)', stripped)
            if token and token.group(1).upper() in _ALIAS_BOUNDARY_KEYWORDS:
                needs_alias = True

        if needs_alias:
            serial += 1
            alias = f' AS order_derived_{serial}'
            insert_at = close_pos + 1
            text = text[:insert_at] + alias + text[insert_at:]
            search_from = insert_at + len(alias)
        else:
            search_from = close_pos + 1

    return text


class TiDBDerivedAliasCompatCursor(TiDBSQLiteCompatCursor):
    def execute(self, sql: str, params=None):
        return super().execute(ensure_mysql_derived_aliases(sql), params)

    def executemany(self, sql: str, params_list):
        return super().executemany(ensure_mysql_derived_aliases(sql), params_list)


class TiDBDerivedAliasCompatConnection(TiDBSQLiteCompatConnection):
    def cursor(self, *args, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if k not in ('cursor_factory', 'cursorclass')}
        return TiDBDerivedAliasCompatCursor(self._conn.cursor(*args, **kwargs))


class DerivedAliasCursorProxy:
    """Alias-only proxy for the legacy cloud DB factory path.

    The parent Flask database layer already performs its own placeholder/dialect
    translation. This proxy deliberately changes only anonymous derived-table
    aliases so we do not translate the same SQL twice.
    """

    def __init__(self, raw_cursor):
        self._cursor = raw_cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def execute(self, sql: str, params=None):
        fixed = ensure_mysql_derived_aliases(sql)
        return self._cursor.execute(fixed, params) if params is not None else self._cursor.execute(fixed)

    def executemany(self, sql: str, params_list):
        return self._cursor.executemany(ensure_mysql_derived_aliases(sql), params_list)


class DerivedAliasConnectionProxy:
    """Connection proxy used only when Render is still on the legacy factory path."""

    def __init__(self, raw_connection):
        self._conn = raw_connection

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        return DerivedAliasCursorProxy(self._conn.cursor(*args, **kwargs))

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, params_list):
        cur = self.cursor()
        cur.executemany(sql, params_list)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False
