"""Chunked full ORDER SQLite -> TiDB mirror transport.

Large mirrors are loaded into deterministic staging tables and become visible only
when finalize verifies every expected row count and atomically swaps the tables.

Transport is deliberately split into short requests:
1. begin: validate snapshot/state only (no multi-table DDL)
2. table: recreate one staging table + its indexes
3. chunk: append bounded rows to that staging table
4. finalize: verify all row counts and atomically swap into place

This prevents Render/Gunicorn request timeouts during bulk DDL and keeps the live WAN
ORDER untouched until a complete snapshot succeeds.
"""
from __future__ import annotations

import re
from typing import Any

from services.order_tidb_connection import get_order_tidb_connection
from services.order_full_mirror_service import (
    MAX_ROWS,
    _STATE_TABLE,
    _create_indexes,
    _create_table_sql,
    _decode_value,
    _ensure_state_table,
    _normalize_tables,
    _qi,
    _safe_stage_name,
    _watermark_dt,
    get_full_mirror_state,
)

_MAX_CHUNK_ROWS = 20000
_HASH_RE = re.compile(r'^[0-9a-f]{64}$')
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _hash(value: Any) -> str:
    result = str(value or '').strip().lower()
    if not _HASH_RE.fullmatch(result):
        raise ValueError('snapshot_hash must be SHA-256 hex')
    return result


def _manifest(manifest: Any) -> tuple[list[dict], int]:
    if not isinstance(manifest, list) or not manifest:
        raise ValueError('manifest must be a non-empty list')

    shell = []
    expected_by_name = {}
    total = 0
    for raw in manifest:
        if not isinstance(raw, dict):
            raise ValueError('each manifest table must be an object')
        name = str(raw.get('name') or '').strip()
        expected = int(raw.get('expected_rows') or 0)
        if expected < 0:
            raise ValueError(f'expected_rows may not be negative: {name}')
        total += expected
        if total > MAX_ROWS:
            raise ValueError(f'too many rows in snapshot (max {MAX_ROWS})')
        expected_by_name[name] = expected
        shell.append({
            'name': name,
            'columns': raw.get('columns') or [],
            'indexes': raw.get('indexes') or [],
            'rows': [],
        })

    normalized, _ = _normalize_tables(shell)
    for table in normalized:
        table['expected_rows'] = expected_by_name[table['name']]
    return normalized, total


def _stale_result(snapshot_hash: str, source_watermark, force: bool):
    current = get_full_mirror_state()
    if current.get('snapshot_hash') == snapshot_hash and not force:
        return {
            'changed': False,
            'ready': False,
            'reason': 'same_hash',
            'snapshot_hash': snapshot_hash,
            'tables': int(current.get('table_count') or 0),
            'rows': int(current.get('row_count') or 0),
        }

    incoming_dt = _watermark_dt(source_watermark)
    current_dt = _watermark_dt(current.get('source_watermark'))
    if not force and incoming_dt and current_dt and incoming_dt < current_dt:
        return {
            'changed': False,
            'ready': False,
            'reason': 'stale_source',
            'stale': True,
            'snapshot_hash': snapshot_hash,
            'source_watermark': source_watermark,
            'cloud_watermark': current.get('source_watermark'),
            'cloud_source_site': current.get('source_site'),
        }
    return None


def begin_chunked_mirror(manifest: Any, snapshot_hash: str, source_watermark=None,
                         source_site=None, force=False) -> dict:
    """Validate a full snapshot without doing multi-table DDL.

    Earlier versions dropped/created every staging table in this single request.
    That can cross Render/Gunicorn request limits, especially when retrying after a
    partially loaded staging set. Each table is now prepared by a separate request.
    """
    snapshot_hash = _hash(snapshot_hash)
    normalized, total_rows = _manifest(manifest)
    source_watermark = str(source_watermark or '').strip() or None

    early = _stale_result(snapshot_hash, source_watermark, bool(force))
    if early is not None:
        return early

    conn = get_order_tidb_connection()
    try:
        _ensure_state_table(conn)
    finally:
        conn.close()

    return {
        'changed': True,
        'ready': True,
        'snapshot_hash': snapshot_hash,
        'tables': len(normalized),
        'rows': total_rows,
        'source_site': str(source_site or '').strip().upper()[:32] or None,
        'prepare_mode': 'per_table',
    }


def prepare_chunked_table(snapshot_hash: str, table_spec: Any) -> dict:
    """Recreate exactly one deterministic staging table for this snapshot."""
    snapshot_hash = _hash(snapshot_hash)
    normalized, _ = _manifest([table_spec])
    table = normalized[0]
    name = table['name']
    token = snapshot_hash[:8]
    stage = _safe_stage_name('__stg', name, token)

    conn = get_order_tidb_connection()
    try:
        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS {_qi(stage)}')
        cur.execute(_create_table_sql(stage, table))
        _create_indexes(cur, stage, table)
        conn.commit()
        return {
            'snapshot_hash': snapshot_hash,
            'table': name,
            'ready': True,
            'expected_rows': int(table.get('expected_rows') or 0),
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def append_chunk(snapshot_hash: str, table_name: str, columns: Any, rows: Any) -> dict:
    """Append one bounded row chunk into the deterministic staging table."""
    snapshot_hash = _hash(snapshot_hash)
    table_name = str(table_name or '').strip()
    if not _IDENT_RE.fullmatch(table_name):
        raise ValueError(f'invalid table name: {table_name!r}')
    if not isinstance(columns, list) or not columns:
        raise ValueError('columns must be a non-empty list')
    columns = [str(x or '').strip() for x in columns]
    if any(not _IDENT_RE.fullmatch(x) for x in columns) or len(columns) != len(set(columns)):
        raise ValueError(f'invalid columns for {table_name}')
    if not isinstance(rows, list):
        raise ValueError('rows must be a list')
    if len(rows) > _MAX_CHUNK_ROWS:
        raise ValueError(f'chunk exceeds {_MAX_CHUNK_ROWS} rows')
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError(f'row width mismatch in {table_name}')

    token = snapshot_hash[:8]
    stage = _safe_stage_name('__stg', table_name, token)
    conn = get_order_tidb_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT COLUMN_NAME FROM information_schema.columns
               WHERE table_schema=DATABASE() AND table_name=%s
               ORDER BY ORDINAL_POSITION""",
            (stage,),
        )
        actual = [str(r.get('COLUMN_NAME') or '') for r in (cur.fetchall() or [])]
        if not actual:
            raise ValueError(f'staging table does not exist for {table_name}; prepare table again')
        if actual != columns:
            raise ValueError(f'column order mismatch for {table_name}')

        if rows:
            placeholders = ','.join(['%s'] * len(columns))
            insert_sql = (
                f'INSERT INTO {_qi(stage)} (' + ','.join(_qi(c) for c in columns) +
                f') VALUES ({placeholders})'
            )
            decoded = []
            inserted = 0
            for row in rows:
                decoded.append(tuple(_decode_value(v) for v in row))
                if len(decoded) >= 500:
                    cur.executemany(insert_sql, decoded)
                    inserted += len(decoded)
                    decoded.clear()
            if decoded:
                cur.executemany(insert_sql, decoded)
                inserted += len(decoded)
        else:
            inserted = 0
        conn.commit()
        return {
            'snapshot_hash': snapshot_hash,
            'table': table_name,
            'inserted': inserted,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def finalize_chunked_mirror(manifest: Any, snapshot_hash: str, source_watermark=None,
                            source_site=None, force=False) -> dict:
    """Verify all stages, atomically swap them into place, and publish state."""
    snapshot_hash = _hash(snapshot_hash)
    normalized, total_rows = _manifest(manifest)
    source_watermark = str(source_watermark or '').strip() or None
    source_site = str(source_site or '').strip().upper()[:32] or None

    early = _stale_result(snapshot_hash, source_watermark, bool(force))
    if early is not None:
        return early

    token = snapshot_hash[:8]
    conn = get_order_tidb_connection()
    backups = []
    try:
        _ensure_state_table(conn)
        cur = conn.cursor()

        for table in normalized:
            stage = _safe_stage_name('__stg', table['name'], token)
            cur.execute(f'SELECT COUNT(*) AS n FROM {_qi(stage)}')
            row = cur.fetchone() or {}
            actual = int(row.get('n') or 0)
            expected = int(table.get('expected_rows') or 0)
            if actual != expected:
                raise ValueError(
                    f'incomplete staging table {table["name"]}: expected {expected}, got {actual}'
                )

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
            stage = _safe_stage_name('__stg', name, token)
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

        from datetime import datetime, timezone
        committed_at = datetime.now(timezone.utc).isoformat()
        cur.execute(f'SELECT id FROM {_qi(_STATE_TABLE)} WHERE id=1')
        if cur.fetchone():
            cur.execute(
                f"""UPDATE {_qi(_STATE_TABLE)}
                    SET snapshot_hash=%s, source_watermark=%s, source_site=%s,
                        table_count=%s, row_count=%s, committed_at=%s WHERE id=1""",
                (snapshot_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        else:
            cur.execute(
                f"""INSERT INTO {_qi(_STATE_TABLE)}
                    (id, snapshot_hash, source_watermark, source_site, table_count, row_count, committed_at)
                    VALUES (1,%s,%s,%s,%s,%s,%s)""",
                (snapshot_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        conn.commit()

        for backup in backups:
            cur.execute(f'DROP TABLE IF EXISTS {_qi(backup)}')
        conn.commit()

        return {
            'changed': True,
            'snapshot_hash': snapshot_hash,
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
        raise
    finally:
        conn.close()
