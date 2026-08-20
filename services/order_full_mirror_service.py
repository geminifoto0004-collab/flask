"""Full ORDER SQLite -> TiDB mirror.

This mirrors the complete ORDER SQLite schema/data into a dedicated ``order_tracking``
TiDB logical database so the exact same ORDER routes can run on LAN (SQLite) and WAN
(TiDB). External attachment/image/PDF bytes are not part of SQLite and are never
uploaded here.
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
        return 'VARCHAR(64)'

    m = re.search(r'(?:VAR)?CHAR\s*\(\s*(\d+)\s*\)', declared)
    if m:
        n = max(1, int(m.group(1)))
        if indexed:
            # Indexed identifiers keep a bounded VARCHAR so TiDB can build the
            # mirrored indexes. ORDER's indexed keys are short identifiers.
            return f'VARCHAR({min(n, 191)})'

        # SQLite treats VARCHAR(n) as TEXT affinity and DOES NOT enforce n. The
        # live ORDER database already contains values longer than declarations
        # such as workflows.product_code VARCHAR(50). Mirroring that declaration
        # literally to TiDB causes error 1406 (Data too long). Non-indexed text
        # must therefore stay unbounded on the read-only WAN mirror.
        return 'LONGTEXT'

    # SQLite TEXT is unbounded. Only indexed/PK text needs a finite MySQL type.
    return 'VARCHAR(191)' if indexed else 'LONGTEXT'


def _index_columns(table: dict) -> set[str]:
    result = set()
    for col in table.get('columns') or []:
        if int(col.get('pk') or 0) > 0:
            result.add(str(col.get('name') or ''))
    for idx in table.get('indexes') or []:
        if bool(idx.get('partial')):
            continue
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
    suffix = hashlib.sha1(str(table_name).encode('utf-8')).hexdigest()[:6]
    room = 64 - len(prefix) - len(token) - len(suffix) - 3
    base = base[:max(1, room)]
    name = f'{prefix}_{token}_{base}_{suffix}'
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
            'source_site': None,
            'table_count': 0,
            'row_count': 0,
            'committed_at': None,
        }
    finally:
        conn.close()


def _normalize_tables(tables: Any) -> tuple[list[dict], int]:
    if not isinstance(tables, list):
        raise ValueError('tables must be a list')
    if not tables:
        raise ValueError('full ORDER snapshot contains no tables')
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
        if not isinstance(raw, dict) or bool(raw.get('partial')):
            # SQLite partial indexes have a WHERE clause which PRAGMA index_info
            # does not preserve. Creating them as full indexes could change unique
            # semantics, so the read-only WAN mirror safely omits them.
            continue
        columns = [str(x) for x in (raw.get('columns') or []) if str(x) in known_cols]
        if not columns:
            continue
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


def _watermark_dt(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        normalized = raw.replace('Z', '+00:00')
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def replace_full_mirror(tables: Any, snapshot_hash: str, source_watermark=None,
                        source_site=None, force=False) -> dict:
    normalized, total_rows = _normalize_tables(tables)
    supplied_hash = str(snapshot_hash or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', supplied_hash):
        raise ValueError('snapshot_hash must be SHA-256 hex')
    calculated = _canonical_hash(normalized)
    if calculated != supplied_hash:
        raise ValueError('snapshot_hash does not match received full ORDER snapshot')

    source_watermark = str(source_watermark or '').strip() or None
    source_site = str(source_site or '').strip().upper()[:32] or None
    current = get_full_mirror_state()

    if current.get('snapshot_hash') == supplied_hash and not force:
        return {
            'changed': False,
            'reason': 'same_hash',
            'snapshot_hash': supplied_hash,
            'tables': int(current.get('table_count') or 0),
            'rows': int(current.get('row_count') or 0),
        }

    # HASH only proves "different", not "newer". When both CN/CL machines may
    # refresh the cloud, reject a clearly older SQLite watermark unless force=True.
    incoming_dt = _watermark_dt(source_watermark)
    current_dt = _watermark_dt(current.get('source_watermark'))
    if not force and incoming_dt and current_dt and incoming_dt < current_dt:
        return {
            'changed': False,
            'reason': 'stale_source',
            'stale': True,
            'snapshot_hash': supplied_hash,
            'source_watermark': source_watermark,
            'cloud_watermark': current.get('source_watermark'),
            'cloud_source_site': current.get('source_site'),
        }

    token = supplied_hash[:8]
    conn = get_order_tidb_connection()
    stages = {}
    backups = []
    try:
        _ensure_state_table(conn)
        cur = conn.cursor()

        # Build/load every stage before touching the visible mirror. If anything
        # fails, the previous WAN ORDER remains intact.
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
            value = next(iter(row.values()), None) if isinstance(row, dict) else (row[0] if row else None)
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
