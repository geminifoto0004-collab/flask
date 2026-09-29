"""Background repair for TiDB1/TiDB2 ORDER cloud metadata.

Normal cloud_* writes are mirrored synchronously by database.CloudMirroredConnection.
This repair pass exists for two cases:
1. TiDB2 already differed before dual-write was deployed.
2. The standby was temporarily unreachable and missed one or more writes.

It copies only ORDER cloud tables, never unrelated application tables, and never B2
image bytes. Rows are upserted from the authoritative/newer TiDB into the standby, and
standby-only rows are deleted for the known ORDER cloud tables so both sides converge.
"""
from __future__ import annotations

import re
import threading
import time

from config import config
from database import (
    clear_cloud_mirror_dirty,
    cloud_mirror_dirty_event,
    get_db_connection_for_target,
    get_cloud_mirror_source_hint,
)
from tidb_targets import mirror_enabled, other_target, preferred_target, target_configured

_TABLES = (
    'cloud_customers',
    'cloud_orders',
    'cloud_workflows',
    'cloud_workflow_history',
    'cloud_share_tokens',
    'cloud_assets',
    'cloud_order_snapshot_state',
    'cloud_order_users',
    'cloud_customer_share_snapshot',
    'cloud_tidb_mirror_state',
)
_STATE_TABLE = 'cloud_tidb_mirror_state'
_PRIMARY_KEYS = {
    'cloud_customers': 'customer_key',
    'cloud_orders': 'order_number',
    'cloud_workflows': 'workflow_key',
    'cloud_workflow_history': 'history_key',
    'cloud_share_tokens': 'token_hash',
    'cloud_assets': 'asset_key',
    'cloud_order_snapshot_state': 'snapshot_key',
    'cloud_order_users': 'username',
    'cloud_customer_share_snapshot': 'customer_key',
    'cloud_tidb_mirror_state': 'stream_key',
}
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_started = False
_start_lock = threading.Lock()


def _qi(name):
    name = str(name or '')
    if not _IDENT.fullmatch(name):
        raise ValueError(f'invalid SQL identifier: {name!r}')
    return f'`{name}`'


def _table_exists(cur, table):
    cur.execute('SHOW TABLES LIKE ?', (table,))
    return bool(cur.fetchone())


def _show_create(cur, table):
    cur.execute(f'SHOW CREATE TABLE {_qi(table)}')
    row = cur.fetchone() or {}
    if isinstance(row, dict):
        for key, value in row.items():
            if 'create table' in str(key).lower():
                return str(value or '')
        values = list(row.values())
        if len(values) >= 2:
            return str(values[1] or '')
    elif row and len(row) >= 2:
        return str(row[1] or '')
    return ''


def _column_definitions(create_sql):
    result = {}
    for raw in str(create_sql or '').splitlines():
        line = raw.strip().rstrip(',')
        if not line.startswith('`'):
            continue
        parts = line.split('`', 2)
        if len(parts) >= 3 and _IDENT.fullmatch(parts[1]):
            result[parts[1]] = line
    return result


def _columns(cur, table):
    cur.execute(f'SHOW COLUMNS FROM {_qi(table)}')
    result = []
    for row in cur.fetchall() or []:
        if isinstance(row, dict):
            field = row.get('Field') or row.get('field')
        else:
            field = row[0] if row else None
        if field:
            result.append(str(field))
    return result


def _ensure_destination_schema(source_cur, dest_cur, table):
    create_sql = _show_create(source_cur, table)
    if not create_sql:
        raise RuntimeError(f'cannot read CREATE TABLE for {table}')
    if not _table_exists(dest_cur, table):
        dest_cur.execute(create_sql)
        return

    source_cols = _columns(source_cur, table)
    dest_cols = set(_columns(dest_cur, table))
    missing = [name for name in source_cols if name not in dest_cols]
    if not missing:
        return
    definitions = _column_definitions(create_sql)
    for name in missing:
        definition = definitions.get(name)
        if not definition:
            raise RuntimeError(f'cannot reconstruct missing column {table}.{name}')
        dest_cur.execute(f'ALTER TABLE {_qi(table)} ADD COLUMN {definition}')


def _delete_destination_extras(source_cur, dest_cur, table):
    pk = _PRIMARY_KEYS.get(table)
    if not pk:
        return 0
    source_cur.execute(f'SELECT {_qi(pk)} FROM {_qi(table)}')
    source_keys = set()
    for row in source_cur.fetchall() or []:
        value = row.get(pk) if isinstance(row, dict) else (row[0] if row else None)
        if value is not None:
            source_keys.add(value)
    dest_cur.execute(f'SELECT {_qi(pk)} FROM {_qi(table)}')
    extras = []
    for row in dest_cur.fetchall() or []:
        value = row.get(pk) if isinstance(row, dict) else (row[0] if row else None)
        if value is not None and value not in source_keys:
            extras.append(value)
    deleted = 0
    for pos in range(0, len(extras), 250):
        chunk = extras[pos:pos + 250]
        placeholders = ','.join(['?'] * len(chunk))
        dest_cur.execute(
            f'DELETE FROM {_qi(table)} WHERE {_qi(pk)} IN ({placeholders})',
            tuple(chunk),
        )
        try:
            deleted += max(int(dest_cur.rowcount or 0), 0)
        except Exception:
            deleted += len(chunk)
    return deleted


def _upsert_table(source_conn, dest_conn, table):
    source_cur = source_conn.cursor()
    dest_cur = dest_conn.cursor()
    if not _table_exists(source_cur, table):
        return {'table': table, 'rows': 0, 'skipped': 'source_missing'}

    _ensure_destination_schema(source_cur, dest_cur, table)
    dest_conn.commit()

    source_cur.execute(f'SELECT * FROM {_qi(table)}')
    first = source_cur.fetchmany(250)
    if not first:
        deleted = _delete_destination_extras(source_cur, dest_cur, table)
        dest_conn.commit()
        return {'table': table, 'rows': 0, 'deleted': deleted}

    sample = first[0]
    if not isinstance(sample, dict):
        raise RuntimeError(f'{table} did not return DictCursor rows')
    columns = [str(x) for x in sample.keys() if _IDENT.fullmatch(str(x))]
    if not columns:
        raise RuntimeError(f'{table} has no mirrorable columns')

    placeholders = ','.join(['?'] * len(columns))
    quoted = ','.join(_qi(x) for x in columns)
    updates = ','.join(f'{_qi(x)}=VALUES({_qi(x)})' for x in columns)
    sql = (
        f'INSERT INTO {_qi(table)} ({quoted}) VALUES ({placeholders}) '
        f'ON DUPLICATE KEY UPDATE {updates}'
    )

    total = 0
    batch = first
    while batch:
        values = [tuple(row.get(col) for col in columns) for row in batch]
        dest_cur.executemany(sql, values)
        total += len(values)
        if total % 1000 == 0:
            dest_conn.commit()
        batch = source_cur.fetchmany(250)
    deleted = _delete_destination_extras(source_cur, dest_cur, table)
    dest_conn.commit()
    return {'table': table, 'rows': total, 'deleted': deleted}


def _mirror_version(target):
    if not target_configured(target):
        return None
    conn = None
    try:
        conn = get_db_connection_for_target(target, pooled=False)
        cur = conn.cursor()
        if not _table_exists(cur, _STATE_TABLE):
            return 0
        cur.execute(
            f'SELECT version FROM {_qi(_STATE_TABLE)} WHERE stream_key=? LIMIT 1',
            ('order_cloud',),
        )
        row = cur.fetchone() or {}
        if isinstance(row, dict):
            value = row.get('version')
        else:
            value = row[0] if row else 0
        return int(value or 0)
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _choose_source_target():
    hint = str(get_cloud_mirror_source_hint() or '').strip().upper()
    versions = {target: _mirror_version(target) for target in ('TIDB1', 'TIDB2')}
    reachable = [target for target, version in versions.items() if version is not None]
    if not reachable:
        return preferred_target(), versions
    if hint in reachable:
        other = other_target(hint)
        if versions.get(other) is None or int(versions.get(hint) or 0) >= int(versions.get(other) or 0):
            return hint, versions
    if len(reachable) == 1:
        return reachable[0], versions
    v1 = int(versions.get('TIDB1') or 0)
    v2 = int(versions.get('TIDB2') or 0)
    if v1 != v2:
        return ('TIDB1' if v1 > v2 else 'TIDB2'), versions
    return preferred_target(), versions


def reconcile_once(source_target=None):
    if config.DATABASE_TYPE not in ('mysql', 'tidb') or not mirror_enabled():
        clear_cloud_mirror_dirty()
        return {'ok': True, 'skipped': 'mirror_disabled'}

    versions = None
    if source_target:
        source_target = str(source_target).strip().upper()
    else:
        source_target, versions = _choose_source_target()
    destination_target = other_target(source_target)
    if not target_configured(source_target) or not target_configured(destination_target):
        return {'ok': False, 'skipped': 'target_not_configured'}

    source = get_db_connection_for_target(source_target, pooled=False)
    destination = None
    results = []
    try:
        destination = get_db_connection_for_target(destination_target, pooled=False)
        for table in _TABLES:
            results.append(_upsert_table(source, destination, table))
        clear_cloud_mirror_dirty()
        print(
            f'[ORDER] TiDB cloud reconcile {source_target}->{destination_target} complete: '
            + ', '.join(
                f"{x['table']}={x.get('rows', 0)}/del{x.get('deleted', 0)}" for x in results
            )
        )
        return {
            'ok': True,
            'source': source_target,
            'destination': destination_target,
            'versions_before': versions,
            'tables': results,
        }
    except Exception:
        cloud_mirror_dirty_event().set()
        try:
            if destination is not None:
                destination.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            source.close()
        except Exception:
            pass
        if destination is not None:
            try:
                destination.close()
            except Exception:
                pass


def _worker():
    time.sleep(4.0)
    event = cloud_mirror_dirty_event()
    first = True
    while True:
        if not first:
            event.wait(timeout=300.0)
        first = False
        event.clear()
        try:
            reconcile_once()
        except Exception as exc:
            print(f'[WARN] TiDB cloud reconcile pending: {type(exc).__name__}: {exc}')
            event.set()
            time.sleep(60.0)


def install():
    global _started
    if config.DATABASE_TYPE not in ('mysql', 'tidb') or not mirror_enabled():
        return
    with _start_lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_worker, name='order-tidb-cloud-reconcile', daemon=True)
        thread.start()


install()
