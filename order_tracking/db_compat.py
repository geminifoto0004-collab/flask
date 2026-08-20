"""SQLite-flavoured SQL compatibility for the unified ORDER codebase.

LAN keeps using sqlite3 directly.  Render/WAN uses TiDB, but the existing ORDER
routes are deliberately allowed to keep their SQLite-style SQL (``?`` parameters,
PRAGMA inspection, date('now', ...), COLLATE NOCASE, etc.).  This wrapper adapts
those reads at the connection boundary so there is still only one ORDER UI and one
set of business routes.

The WAN deployment intentionally exposes no local attachment bytes.  File metadata
can still be mirrored into TiDB for completeness, but SELECTs against ORDER's local
file tables are returned as empty in remote mode so the existing UI simply shows no
local images/files.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


_MEDIA_TABLES = {"order_files", "workflow_files"}


class CompatRow(dict):
    """Dict row that also supports sqlite3.Row-style numeric indexing."""

    def __getitem__(self, key):
        if isinstance(key, int):
            values = list(dict.values(self))
            return values[key]
        return dict.__getitem__(self, key)



def _qmark_to_percent(sql: str) -> str:
    """Replace SQLite ? placeholders outside quoted strings/backticks."""
    out = []
    quote = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                # SQL escapes quotes by doubling them.
                if i + 1 < len(sql) and sql[i + 1] == quote and quote in {"'", '"'}:
                    out.append(sql[i + 1])
                    i += 1
                else:
                    quote = None
            elif ch == "\\" and i + 1 < len(sql):
                out.append(sql[i + 1])
                i += 1
        else:
            if ch in {"'", '"', '`'}:
                quote = ch
                out.append(ch)
            elif ch == '?':
                out.append('%s')
            else:
                out.append(ch)
        i += 1
    return ''.join(out)


def _translate_date_functions(sql: str) -> str:
    # date('now', '-3 months') / date('now', '-7 days') / date('now', '-1 year')
    unit_map = {"day": "DAY", "days": "DAY", "month": "MONTH", "months": "MONTH", "year": "YEAR", "years": "YEAR"}

    def repl_date_sub(match):
        n = int(match.group(1))
        unit = unit_map[match.group(2).lower()]
        return f"DATE_SUB(CURDATE(), INTERVAL {n} {unit})"

    def repl_date_add(match):
        n = int(match.group(1))
        unit = unit_map[match.group(2).lower()]
        return f"DATE_ADD(CURDATE(), INTERVAL {n} {unit})"

    sql = re.sub(
        r"date\(\s*['\"]now['\"]\s*,\s*['\"]-(\d+)\s+(day|days|month|months|year|years)['\"]\s*\)",
        repl_date_sub,
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"date\(\s*['\"]now['\"]\s*,\s*['\"]\+(\d+)\s+(day|days|month|months|year|years)['\"]\s*\)",
        repl_date_add,
        sql,
        flags=re.I,
    )
    sql = re.sub(r"date\(\s*['\"]now['\"]\s*\)", "CURDATE()", sql, flags=re.I)
    sql = re.sub(r"datetime\(\s*['\"]now['\"](?:\s*,\s*['\"]localtime['\"])?\s*\)", "NOW()", sql, flags=re.I)

    # Common ORDER report/date rendering patterns.
    sql = re.sub(
        r"strftime\(\s*['\"]%Y-%m-%d['\"]\s*,\s*([^\)]+)\)",
        r"DATE_FORMAT(\1, '%Y-%m-%d')",
        sql,
        flags=re.I,
    )
    sql = re.sub(
        r"strftime\(\s*['\"]%Y-%m['\"]\s*,\s*([^\)]+)\)",
        r"DATE_FORMAT(\1, '%Y-%m')",
        sql,
        flags=re.I,
    )
    return sql


def translate_sqlite_sql(sql: str) -> str:
    """Translate the SQLite dialect used by ORDER into TiDB/MySQL syntax."""
    text = str(sql or '')
    text = _translate_date_functions(text)
    text = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT IGNORE INTO", text, flags=re.I)
    text = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "REPLACE INTO", text, flags=re.I)
    text = re.sub(r"\bAUTOINCREMENT\b", "AUTO_INCREMENT", text, flags=re.I)
    text = re.sub(r"\s+COLLATE\s+NOCASE\b", "", text, flags=re.I)
    text = re.sub(r"\bCAST\((.*?)\s+AS\s+INTEGER\)", r"CAST(\1 AS SIGNED)", text, flags=re.I | re.S)

    # SQLite ltrim(x, 'ABC...xyz') is used for numeric ORDER sorting.
    text = re.sub(
        r"ltrim\(\s*([^,\)]+)\s*,\s*['\"]ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz['\"]\s*\)",
        r"REGEXP_REPLACE(\1, '^[A-Za-z]+', '')",
        text,
        flags=re.I,
    )

    # BEGIN IMMEDIATE/EXCLUSIVE are SQLite locking modes. TiDB uses a normal txn.
    text = re.sub(r"^\s*BEGIN\s+(IMMEDIATE|EXCLUSIVE)\b", "START TRANSACTION", text, flags=re.I)
    return _qmark_to_percent(text)


class TiDBSQLiteCompatCursor:
    def __init__(self, raw_cursor):
        self._cursor = raw_cursor
        self._synthetic = None
        self._synthetic_pos = 0
        self._synthetic_description = None
        self._synthetic_rowcount = -1

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    @property
    def description(self):
        return self._synthetic_description if self._synthetic is not None else self._cursor.description

    @property
    def rowcount(self):
        return self._synthetic_rowcount if self._synthetic is not None else self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    def _set_rows(self, rows: Iterable[dict]):
        items = [r if isinstance(r, CompatRow) else CompatRow(r) for r in rows]
        self._synthetic = items
        self._synthetic_pos = 0
        self._synthetic_rowcount = len(items)
        keys = list(items[0].keys()) if items else []
        self._synthetic_description = [(k, None, None, None, None, None, None) for k in keys]
        return self

    def _clear_rows(self):
        self._synthetic = None
        self._synthetic_pos = 0
        self._synthetic_description = None
        self._synthetic_rowcount = -1

    def _table_info(self, table_name: str):
        self._cursor.execute(
            """SELECT ORDINAL_POSITION, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                      COLUMN_DEFAULT, COLUMN_KEY
               FROM information_schema.columns
               WHERE table_schema=DATABASE() AND table_name=%s
               ORDER BY ORDINAL_POSITION""",
            (table_name,),
        )
        rows = []
        for raw in self._cursor.fetchall() or []:
            d = dict(raw)
            rows.append(CompatRow({
                'cid': int(d.get('ORDINAL_POSITION') or 1) - 1,
                'name': d.get('COLUMN_NAME'),
                'type': d.get('COLUMN_TYPE') or '',
                'notnull': 0 if str(d.get('IS_NULLABLE') or '').upper() == 'YES' else 1,
                'dflt_value': d.get('COLUMN_DEFAULT'),
                'pk': 1 if str(d.get('COLUMN_KEY') or '').upper() == 'PRI' else 0,
            }))
        return self._set_rows(rows)

    def _index_list(self, table_name: str):
        self._cursor.execute(
            """SELECT INDEX_NAME, MIN(NON_UNIQUE) AS NON_UNIQUE
               FROM information_schema.statistics
               WHERE table_schema=DATABASE() AND table_name=%s
               GROUP BY INDEX_NAME
               ORDER BY INDEX_NAME""",
            (table_name,),
        )
        rows = []
        for pos, raw in enumerate(self._cursor.fetchall() or []):
            d = dict(raw)
            name = d.get('INDEX_NAME')
            rows.append(CompatRow({
                'seq': pos,
                'name': name,
                'unique': 0 if int(d.get('NON_UNIQUE') or 0) else 1,
                'origin': 'pk' if str(name).upper() == 'PRIMARY' else 'c',
                'partial': 0,
            }))
        return self._set_rows(rows)

    def _index_info(self, index_name: str):
        self._cursor.execute(
            """SELECT SEQ_IN_INDEX, COLUMN_NAME
               FROM information_schema.statistics
               WHERE table_schema=DATABASE() AND index_name=%s
               ORDER BY SEQ_IN_INDEX""",
            (index_name,),
        )
        rows = []
        for raw in self._cursor.fetchall() or []:
            d = dict(raw)
            rows.append(CompatRow({
                'seqno': int(d.get('SEQ_IN_INDEX') or 1) - 1,
                'cid': -1,
                'name': d.get('COLUMN_NAME'),
            }))
        return self._set_rows(rows)

    def _sqlite_master(self, sql: str, params):
        low = sql.lower()
        if "type='table'" in low or 'type = \'table\'' in low or 'type="table"' in low:
            name = None
            if params:
                name = params[0]
            if name is not None:
                self._cursor.execute(
                    """SELECT table_name AS name FROM information_schema.tables
                       WHERE table_schema=DATABASE() AND table_name=%s LIMIT 1""",
                    (name,),
                )
            else:
                self._cursor.execute(
                    """SELECT table_name AS name FROM information_schema.tables
                       WHERE table_schema=DATABASE() ORDER BY table_name"""
                )
            rows = [CompatRow(dict(r)) for r in (self._cursor.fetchall() or [])]
            return self._set_rows(rows)
        if "type='index'" in low or 'type = \'index\'' in low or 'type="index"' in low:
            self._cursor.execute(
                """SELECT DISTINCT index_name AS name FROM information_schema.statistics
                   WHERE table_schema=DATABASE() ORDER BY index_name"""
            )
            return self._set_rows([CompatRow(dict(r)) for r in (self._cursor.fetchall() or [])])
        return self._set_rows([])

    def _media_select(self, sql: str):
        low = sql.lower()
        if not low.lstrip().startswith(('select', 'with')):
            return False
        if not any(re.search(rf"\b{re.escape(name)}\b", low) for name in _MEDIA_TABLES):
            return False
        # Mirror metadata exists in TiDB, but WAN has no local bytes. Make existing
        # ORDER UI behave exactly like an empty local attachment folder.
        if 'count(' in low:
            alias = 'count'
            m = re.search(r"count\s*\([^\)]*\)\s+(?:as\s+)?([a-zA-Z_][\w]*)", low)
            if m:
                alias = m.group(1)
            self._set_rows([CompatRow({alias: 0})])
        else:
            self._set_rows([])
        return True

    def execute(self, sql: str, params=None):
        self._clear_rows()
        raw_sql = str(sql or '')
        stripped = raw_sql.strip()
        low = stripped.lower()
        params = () if params is None else params

        pragma = re.match(r"pragma\s+(table_info|table_xinfo)\s*\(\s*['\"`]?([^\)'\"`]+)", stripped, flags=re.I)
        if pragma:
            return self._table_info(pragma.group(2).strip())
        pragma = re.match(r"pragma\s+index_list\s*\(\s*['\"`]?([^\)'\"`]+)", stripped, flags=re.I)
        if pragma:
            return self._index_list(pragma.group(1).strip())
        pragma = re.match(r"pragma\s+index_info\s*\(\s*['\"`]?([^\)'\"`]+)", stripped, flags=re.I)
        if pragma:
            return self._index_info(pragma.group(1).strip())
        if low.startswith('pragma '):
            # journal_mode/query_only/foreign_keys/etc. are local SQLite controls.
            return self._set_rows([])

        if 'sqlite_master' in low:
            return self._sqlite_master(raw_sql, params)

        if low.startswith(('vacuum', 'analyze')):
            return self._set_rows([])

        if self._media_select(raw_sql):
            return self

        translated = translate_sqlite_sql(raw_sql)
        return self._cursor.execute(translated, params) if params else self._cursor.execute(translated)

    def executemany(self, sql: str, params_list):
        self._clear_rows()
        translated = translate_sqlite_sql(sql)
        return self._cursor.executemany(translated, params_list)

    def fetchone(self):
        if self._synthetic is not None:
            if self._synthetic_pos >= len(self._synthetic):
                return None
            row = self._synthetic[self._synthetic_pos]
            self._synthetic_pos += 1
            return row
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return CompatRow(row)
        return row

    def fetchmany(self, size=None):
        if self._synthetic is not None:
            n = int(size or 1)
            start = self._synthetic_pos
            end = min(len(self._synthetic), start + n)
            self._synthetic_pos = end
            return self._synthetic[start:end]
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        return [CompatRow(r) if isinstance(r, dict) else r for r in rows]

    def fetchall(self):
        if self._synthetic is not None:
            rows = self._synthetic[self._synthetic_pos:]
            self._synthetic_pos = len(self._synthetic)
            return rows
        rows = self._cursor.fetchall() or []
        return [CompatRow(r) if isinstance(r, dict) else r for r in rows]


class TiDBSQLiteCompatConnection:
    """Connection facade exposing sqlite3-like cursor/execute behaviour."""

    def __init__(self, raw_connection):
        self._conn = raw_connection

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        # Dedicated ORDER TiDB connections are created with DictCursor already.
        kwargs = {k: v for k, v in kwargs.items() if k not in ('cursor_factory', 'cursorclass')}
        return TiDBSQLiteCompatCursor(self._conn.cursor(*args, **kwargs))

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, params_list):
        cur = self.cursor()
        cur.executemany(sql, params_list)
        return cur

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

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
