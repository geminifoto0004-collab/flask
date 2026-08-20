"""Full ORDER SQLite -> TiDB mirror.

This is intentionally separate from the older customer-safe cloud_* publishing
mirror.  It mirrors the complete ORDER SQLite schema/data into the dedicated
``order_tracking`` TiDB logical database so the exact same ORDER routes can run on
LAN (SQLite) and WAN (TiDB).

Actual attachment/image bytes are not part of SQLite and are never uploaded here.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from services.order_tidb_connection import get_order_tidb_connection

_STATE_TABLE = '__order_mirror_state'
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MAX_TABLES = 256
MAX_ROWS = 500000


def _qi(name: str) -> str:
    name = str(name or '')
    if not _IDENT.fullmatch(name):
        raise ValueError(f'invalid SQL identifier: {name!r}')
    return f'`{name}`'


def _canonical_hash(tables: list[dict]) -> str:
    raw = json.dumps(
        tables,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _decode_value(value: Any):
    if isinstance(value, dict) and set(value.keys()) == {'__bytes__'}:
        return base64.b64decode(str(value['__bytes__']).encode('ascii'))
    return value


def _type_for(column: dict, indexed: bool) -> str:
    declared = str(column.get('type') or '').strip().upper()
    if 'INT' in declared:
        return 'BIGINT'
    if any(x in declared for x in ('REAL', 'FLOA', 'DOUB')):
        return 'DOUBLE'
    if any(x in declared for x in ('NUMERIC', 'DECIMAL')):
        return 'DECIMAL(38,10)'
    if 'BLOB' in declared:
        return 'LONGBLOB'
    if 'BOOL' in declared:
        return 'TINYINT(1)'
    if any(x in declared for x in ('DATE', 'TIME')):
        # SQLite stores these flexibly. VARCHAR preserves exact values and keeps
        # YYYY-MM-DD ordering semantics used by ORDER.
        return 'VARCHAR(64)'

    m = re.search(r'(?:VAR)?CHAR\s*\(\s*(\d+)\s*\)', declared)
    if m:
        n = max(1, int(m.group(1)))
        if indexed:
            n = min(n, 512)
        return f'VARCHAR({min(n, 4096)})'

    # Indexed/PK text must be indexable under utf8mb4; free text stays unlimited.
    return 'VARCHAR(512)' if indexed else 'LONGTEXT'


def _index_columns(table: dict) -> set[str]:
    result = set()
    for col in table.get('columns') or []:
        if int(col.get('pk') or 0) > 0:
            result.add(str(col.get('name') or ''))
    for idx in table.get('indexes') or []:
        for name in idx.get('columns') or []:
            if name:
                result.add(str(name))
    return result


def _create_table_sql(physical_name: str, table: dict) -> str:
    columns = table.get('columns') or []
    if not columns:
        raise ValueError(f'table {table.get("name")} has no columns')
    indexed = _index_columns(table)
    parts = []
    pk_cols = []
    for col in columns:
        name = str(col.get('name') or '')
        _qi(name)
        pk_order = int(col.get('pk') or 0)
        if pk_order > 0:
            pk_cols.append((pk_order, name))
        data_type = _type_for(col, name in indexed)
        not_null = bool(col.get('notnull')) or pk_order > 0
        parts.append(f'{_qi(name)} {data_type}' + (' NOT NULL' if not_null else ' NULL'))
    if pk_cols:
        pk_cols.sort()
        parts.append('PRIMARY KEY (' + ','.join(_qi(name) for _, name in pk_cols) + ')')
    return (
        f'CREATE TABLE {_qi(physical_name)} (' + ','.join(parts) + ') '
        'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
    )


def _safe_stage_name(prefix: str, table_name: str, token: str) -> str:
    base = re.sub(r'[^A-Za-z0-9_]', '_', table_name)
    room = 63 - len(prefix) - len(token) - 2
    base = base[:max(8, room)]
    name = f'{prefix}_{token}_{base}'
    if len(name) > 64:
        name = name[:64]
    _qi(name)
    return name


def _ensure_state_table(conn):
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {_qi(_STATE_TABLE)} (
            id TINYINT NOT NULL PRIMARY KEY,
            snapshot_hash CHAR(64) NULL,
            source_watermark VARCHAR(128) NULL,
            source_site VARCHAR(32) NULL,
            table_count INT NOT NULL DEFAULT 0,
            row_count BIGINT NOT NULL DEFAULT 0,
            committed_at VARCHAR(64) NULL
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    conn.commit()


def get_full_mirror_state() -> dict:
    conn = get_order_tidb_connection()
    try:
        _ensure_state_table(conn)
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM {_qi(_STATE_TABLE)} WHERE id=1')
        row = cur.fetchone() or {}
        return dict(row) if row else {
            'snapshot_hash': None,
            'source_watermark': None,
            'table_count': 0,
            'row_count': 0,
            'committed_at': None,
        }
    finally:
        conn.close()


def _normalize_tables(tables: Any) -> tuple[list[dict], int]:
    if not isinstance(tables, list):
        raise ValueError('tables must be a list')
    if len(tables) > MAX_TABLES:
        raise ValueError(f'too many tables (max {MAX_TABLES})')

    seen = set()
    total_rows = 0
    normalized = []
    for raw in tables:
        if not isinstance(raw, dict):
            raise ValueError('each table must be an object')
        name = str(raw.get('name') or '').strip()
        _qi(name)
        if name.startswith('sqlite_') or name == _STATE_TABLE:
            raise ValueError(f'internal table may not be mirrored: {name}')
        if name in seen:
            raise ValueError(f'duplicate table: {name}')
        seen.add(name)

        columns = raw.get('columns') or []
        if not isinstance(columns, list) or not columns:
            raise ValueError(f'table {name} has no columns')
        col_names = []
        for col in columns:
            if not isinstance(col, dict):
                raise ValueError(f'invalid column metadata in {name}')
            col_name = str(col.get('name') or '')
            _qi(col_name)
            col_names.append(col_name)
        if len(col_names) != len(set(col_names)):
            raise ValueError(f'duplicate columns in {name}')

        rows = raw.get('rows') or []
        if not isinstance(rows, list):
            raise ValueError(f'rows for {name} must be a list')
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError(f'row width mismatch in {name}')
        total_rows += len(rows)
        if total_rows > MAX_ROWS:
            raise ValueError(f'too many rows in snapshot (max {MAX_ROWS})')

        indexes = raw.get('indexes') or []
        if not isinstance(indexes, list):
            raise ValueError(f'indexes for {name} must be a list')
        normalized.append({
            'name': name,
            'columns': columns,
            'indexes': indexes,
            'rows': rows,
        })
    normalized.sort(key=lambda t: t['name'])
    return normalized, total_rows


def _create_indexes(cur, stage_name: str, table: dict):
    known_cols = {str(c.get('name')) for c in table.get('columns') or []}
    seq = 0
    for raw in table.get('indexes') or []:
        if not isinstance(raw, dict):
            continue
        columns = [str(x) for x in (raw.get('columns') or []) if str(x) in known_cols]
        if not columns:
            continue
        # PRIMARY is already represented by PRAGMA table_info(pk).
        if str(raw.get('origin') or '').lower() == 'pk' or str(raw.get('name') or '').upper() == 'PRIMARY':
            continue
        seq += 1
        unique = 'UNIQUE ' if bool(raw.get('unique')) else ''
        source_name = str(raw.get('name') or f'idx_{seq}')
        clean = re.sub(r'[^A-Za-z0-9_]', '_', source_name)
        idx_name = f'm_{seq}_{clean}'[:60]
        if not _IDENT.fullmatch(idx_name):
            idx_name = f'm_idx_{seq}'
        cur.execute(
            f'CREATE {unique}INDEX {_qi(idx_name)} ON {_qi(stage_name)} '
            '(' + ','.join(_qi(c) for c in columns) + ')'
        )


def replace_full_mirror(tables: Any, snapshot_hash: str, source_watermark=None,
                        source_site=None, force=False) -> dict:
    normalized, total_rows = _normalize_tables(tables)
    supplied_hash = str(snapshot_hash or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', supplied_hash):
        raise ValueError('snapshot_hash must be SHA-256 hex')
    calculated = _canonical_hash(normalized)
    if calculated != supplied_hash:
        raise ValueError('snapshot_hash does not match received full ORDER snapshot')

    current = get_full_mirror_state()
    if current.get('snapshot_hash') == supplied_hash and not force:
        return {
            'changed': False,
            'reason': 'same_hash',
            'snapshot_hash': supplied_hash,
            'tables': int(current.get('table_count') or 0),
            'rows': int(current.get('row_count') or 0),
        }

    token = supplied_hash[:8]
    conn = get_order_tidb_connection()
    stages = {}
    backups = []
    try:
        _ensure_state_table(conn)
        cur = conn.cursor()

        # Build and load every staging table before touching the currently visible
        # ORDER mirror. A failed upload therefore leaves the old WAN ORDER intact.
        for table in normalized:
            name = table['name']
            stage = _safe_stage_name('__stg', name, token)
            stages[name] = stage
            cur.execute(f'DROP TABLE IF EXISTS {_qi(stage)}')
            cur.execute(_create_table_sql(stage, table))

            columns = [str(c.get('name')) for c in table['columns']]
            rows = table['rows']
            if rows:
                placeholders = ','.join(['%s'] * len(columns))
                insert_sql = (
                    f'INSERT INTO {_qi(stage)} (' + ','.join(_qi(c) for c in columns) +
                    f') VALUES ({placeholders})'
                )
                batch = []
                for row in rows:
                    batch.append(tuple(_decode_value(v) for v in row))
                    if len(batch) >= 500:
                        cur.executemany(insert_sql, batch)
                        batch.clear()
                if batch:
                    cur.executemany(insert_sql, batch)
            _create_indexes(cur, stage, table)
        conn.commit()

        cur.execute('SHOW TABLES')
        existing = set()
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                value = next(iter(row.values()), None)
            else:
                value = row[0] if row else None
            if value:
                existing.add(str(value))

        incoming = {t['name'] for t in normalized}
        visible_existing = {
            name for name in existing
            if name != _STATE_TABLE and not name.startswith('__stg_') and not name.startswith('__old_')
        }

        rename_parts = []
        for name in sorted(incoming):
            stage = stages[name]
            if name in visible_existing:
                backup = _safe_stage_name('__old', name, token)
                cur.execute(f'DROP TABLE IF EXISTS {_qi(backup)}')
                rename_parts.append(f'{_qi(name)} TO {_qi(backup)}')
                backups.append(backup)
            rename_parts.append(f'{_qi(stage)} TO {_qi(name)}')

        for name in sorted(visible_existing - incoming):
            backup = _safe_stage_name('__old', name, token)
            cur.execute(f'DROP TABLE IF EXISTS {_qi(backup)}')
            rename_parts.append(f'{_qi(name)} TO {_qi(backup)}')
            backups.append(backup)

        if rename_parts:
            cur.execute('RENAME TABLE ' + ', '.join(rename_parts))
        conn.commit()

        for backup in backups:
            cur.execute(f'DROP TABLE IF EXISTS {_qi(backup)}')

        committed_at = datetime.now(timezone.utc).isoformat()
        source_watermark = str(source_watermark or '').strip() or None
        source_site = str(source_site or '').strip().upper()[:32] or None
        cur.execute(f'SELECT id FROM {_qi(_STATE_TABLE)} WHERE id=1')
        if cur.fetchone():
            cur.execute(
                f"""UPDATE {_qi(_STATE_TABLE)}
                    SET snapshot_hash=%s, source_watermark=%s, source_site=%s,
                        table_count=%s, row_count=%s, committed_at=%s WHERE id=1""",
                (supplied_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        else:
            cur.execute(
                f"""INSERT INTO {_qi(_STATE_TABLE)}
                    (id, snapshot_hash, source_watermark, source_site, table_count, row_count, committed_at)
                    VALUES (1,%s,%s,%s,%s,%s,%s)""",
                (supplied_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        conn.commit()
        return {
            'changed': True,
            'snapshot_hash': supplied_hash,
            'tables': len(normalized),
            'rows': total_rows,
            'source_watermark': source_watermark,
            'committed_at': committed_at,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # Staging tables are disposable; never remove visible mirror tables here.
        try:
            cur = conn.cursor()
            for stage in stages.values():
                cur.execute(f'DROP TABLE IF EXISTS {_qi(stage)}')
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        conn.close()
