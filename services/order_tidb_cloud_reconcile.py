"""Background repair for TiDB1/TiDB2 ORDER cloud metadata.

Normal cloud_* writes are mirrored synchronously by database.CloudMirroredConnection.
This repair pass exists for two cases:
1. TiDB2 already differed before dual-write was deployed.
2. The standby was temporarily unreachable and missed one or more writes.

It copies only ORDER cloud tables, never unrelated application tables, and never B2
image bytes. Rows unique to the standby are preserved for an explicit audit: absence
cannot distinguish an intentional delete from a write missed during an outage.
For matching keys the newer stream version selects the source of truth.
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
    'cloud_share_order_visibility',
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
    'cloud_share_order_visibility': ('token_hash', 'order_number'),
    'cloud_assets': 'asset_key',
    'cloud_order_snapshot_state': 'snapshot_key',
    'cloud_order_users': 'username',
    'cloud_customer_share_snapshot': 'customer_key',
    'cloud_tidb_mirror_state': 'stream_key',
}
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_started = False
_start_lock = threading.Lock()
_reconcile_lock = threading.Lock()


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


def _upsert_table(source_conn, dest_conn, table):
    import hashlib, json
    source_cur, dest_cur = source_conn.cursor(), dest_conn.cursor()
    if not _table_exists(source_cur, table):
        return {'table': table, 'rows': 0, 'changed': 0, 'skipped': 'source_missing'}
    _ensure_destination_schema(source_cur, dest_cur, table)
    dest_conn.commit()
    pk = _PRIMARY_KEYS.get(table)
    keys = (pk,) if isinstance(pk, str) else tuple(pk or ())
    if not keys: raise ValueError('mirror key is missing')
    def key(row): return tuple(row.get(col) for col in keys)
    def digest(row):
        return hashlib.sha256(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode()).digest()
    dest_cur.execute(f'SELECT * FROM {_qi(table)}')
    existing = {}
    while True:
        batch = dest_cur.fetchmany(250)
        if not batch: break
        for row in batch: existing[key(row)] = digest(row)
    source_cur.execute(f'SELECT * FROM {_qi(table)}')
    total = changed = 0
    while True:
        batch = source_cur.fetchmany(250)
        if not batch: break
        columns = [col for col in batch[0] if _IDENT.fullmatch(col)]
        if not columns: raise ValueError('mirror columns are missing')
        quoted = ','.join(_qi(col) for col in columns)
        updates = ','.join(f'{_qi(col)}=VALUES({_qi(col)})' for col in columns)
        values = [tuple(row.get(col) for col in columns) for row in batch if existing.get(key(row)) != digest(row)]
        if values:
            sql = f'INSERT INTO {_qi(table)} ({quoted}) VALUES (' + ','.join('?' for _ in columns) + f') ON DUPLICATE KEY UPDATE {updates}'
            dest_cur.executemany(sql, values)
            changed += len(values)
            dest_conn.commit()
        total += len(batch)
    return {'table': table, 'rows': total, 'changed': changed}


def _invalidate_derived_views(conn):
    """Snapshots and rendered HTML may omit newly merged image/share rows."""
    cur = conn.cursor()
    for table in ('cloud_customer_share_snapshot', 'cloud_customer_share_html_cache'):
        if _table_exists(cur, table):
            cur.execute(f'DELETE FROM {_qi(table)}')
    conn.commit()


def _invalidate_process_views():
    # A Render process can continue serving the same share after AUTO changes target.
    # Do not let one day's prewarmed HTML hide rows just recovered in TiDB.
    try:
        from services import order_public_share_multi_b2_page as page
        from services import order_share_render_cache as render
        with page._cache_lock:
            page._space_cache.clear()
            page._token_cache.clear()
        with render._LOCK:
            render._HTML.clear()
            render._TOKEN_HTML.clear()
    except Exception as exc:
        print(f'[WARN] TiDB reconciled, local share cache reset skipped: {exc}')


def _standby_only_counts(source_conn, dest_conn):
    counts = {}
    source_cur, dest_cur = source_conn.cursor(), dest_conn.cursor()
    for table in _TABLES:
        if table in ('cloud_customer_share_snapshot', _STATE_TABLE): continue
        pk = _PRIMARY_KEYS.get(table)
        keys = (pk,) if isinstance(pk, str) else tuple(pk or ())
        if not keys or not _table_exists(source_cur, table) or not _table_exists(dest_cur, table): continue
        fields = ','.join(_qi(col) for col in keys)
        def key(row): return tuple(row.get(col) for col in keys) if isinstance(row,dict) else tuple(row)
        source_cur.execute(f'SELECT {fields} FROM {_qi(table)}')
        source_keys = {key(row) for row in source_cur.fetchall() or []}
        dest_cur.execute(f'SELECT {fields} FROM {_qi(table)}')
        count = sum(1 for row in dest_cur.fetchall() or [] if key(row) not in source_keys)
        if count: counts[table] = count
    return counts


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
    with _reconcile_lock:
        return _reconcile_once(source_target)


def align_verified_backup(source_target):
    """Caller must hold local-content proof; retain every old standby table."""
    import secrets
    import tidb_integrity
    from services.order_sync_integrity import table_digest
    with _reconcile_lock:
        source = get_db_connection_for_target(source_target, pooled=False)
        destination_target = other_target(source_target)
        destination = None
        shadows, archives = {}, {}
        swapped = False
        token = secrets.token_hex(5)
        try:
            destination = get_db_connection_for_target(destination_target, pooled=False)
            tidb_integrity.invalidate()
            generation = tidb_integrity.generation()
            version = _mirror_version(source_target)
            if version is None: raise RuntimeError('source version unavailable')
            for index, table in enumerate(_TABLES):
                if table == 'cloud_customer_share_snapshot': continue
                shadow = '__v255_sync_' + str(index) + '_' + token
                archive = '__v255_archive_' + str(index) + '_' + token
                source_cursor, dest_cursor = source.cursor(), destination.cursor()
                if not _table_exists(source_cursor, table):
                    raise RuntimeError('required source table missing: '+table)
                ddl = _show_create(source_cursor, table)
                if 'FOREIGN KEY' in ddl.upper():
                    raise RuntimeError('backup table has foreign keys; manual schema audit required')
                ddl, count = re.subn(r'^(CREATE\s+TABLE\s+)(?:`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)',
                                     lambda match: match.group(1)+_qi(shadow), ddl, count=1, flags=re.I)
                if count != 1: raise RuntimeError('invalid source table definition')
                dest_cursor.execute(ddl)
                shadows[table] = shadow
                source_cursor.execute('SELECT * FROM '+_qi(table))
                while True:
                    rows = source_cursor.fetchmany(250)
                    if not rows: break
                    columns = list(rows[0])
                    sql = 'INSERT INTO '+_qi(shadow)+' ('+','.join(_qi(col) for col in columns)+') VALUES ('+','.join('?' for _ in columns)+')'
                    dest_cursor.executemany(sql,[tuple(row.get(col) for col in columns) for row in rows])
                destination.commit()
                if table_digest(source, table) != table_digest(destination, shadow):
                    raise RuntimeError('backup shadow content mismatch: '+table)
                if _table_exists(dest_cursor, table): archives[table] = archive
            if _mirror_version(source_target) != version or tidb_integrity.generation() != generation:
                raise RuntimeError('source_changed_during_backup_alignment')
            renames = []
            for table, shadow in shadows.items():
                if table in archives: renames.append(_qi(table)+' TO '+_qi(archives[table]))
                renames.append(_qi(shadow)+' TO '+_qi(table))
            destination.cursor().execute('RENAME TABLE '+','.join(renames))
            destination.commit()
            swapped = True
            _invalidate_derived_views(destination)
            _invalidate_process_views()
            print('[ORDER Backup Archive] target='+destination_target+' preserved_tables='+str(len(archives)),flush=True)
            return {'source':source_target,'destination':destination_target,'archives':archives,'preserved':True}
        finally:
            # Only unfinished temporary shadows are removed. Archive tables remain.
            if destination is not None:
                if not swapped:
                    for shadow in shadows.values():
                        try: destination.cursor().execute('DROP TABLE IF EXISTS '+_qi(shadow))
                        except Exception: pass
                destination.close()
            source.close()


def align_order_backup(source_target, expected):
    """Repair the dedicated ORDER backup from locally verified live tables."""
    import secrets
    import tidb_integrity
    from database import AdaptedConnection
    from services.order_tidb_connection import _connect_target, order_database_name
    from services.order_full_mirror_service import _STATE_TABLE as state_table
    from services.order_sync_integrity import table_digest
    with _reconcile_lock:
        destination_target = other_target(source_target)
        source = AdaptedConnection(_connect_target(source_target, database=order_database_name()))
        destination = None
        shadows, archives = {}, {}
        swapped = False
        token = secrets.token_hex(5)
        def current_hash():
            connection = _connect_target(source_target, database=order_database_name())
            try:
                cursor = connection.cursor()
                cursor.execute('SELECT snapshot_hash FROM '+_qi(state_table)+' WHERE id=1')
                row=cursor.fetchone() or {}
                return row.get('snapshot_hash')
            finally: connection.close()
        try:
            destination = AdaptedConnection(_connect_target(destination_target, database=order_database_name()))
            tidb_integrity.invalidate()
            generation = tidb_integrity.generation()
            version = current_hash()
            if not version: raise RuntimeError('source ORDER version unavailable')
            cursor = destination.cursor()
            cursor.execute('SHOW TABLES')
            old_names = {str(next(iter(row.values()))) for row in cursor.fetchall()}
            old_names = {name for name in old_names if not name.startswith('__') or name==state_table}
            names = list(expected) + [state_table]
            for index, table in enumerate(names):
                shadow = '__v255_order_' + str(index) + '_' + token
                source_cursor, dest_cursor = source.cursor(), destination.cursor()
                ddl = _show_create(source_cursor, table)
                if 'FOREIGN KEY' in ddl.upper(): raise RuntimeError('ORDER foreign key requires manual schema audit')
                ddl,count=re.subn(r'^(CREATE\s+TABLE\s+)(?:`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)',lambda match:match.group(1)+_qi(shadow),ddl,count=1,flags=re.I)
                if count!=1: raise RuntimeError('invalid ORDER table definition')
                dest_cursor.execute(ddl);shadows[table]=shadow
                source_cursor.execute('SELECT * FROM '+_qi(table))
                while True:
                    rows=source_cursor.fetchmany(250)
                    if not rows:break
                    columns=list(rows[0]);sql='INSERT INTO '+_qi(shadow)+' ('+','.join(_qi(col) for col in columns)+') VALUES ('+','.join('?' for _ in columns)+')'
                    dest_cursor.executemany(sql,[tuple(row.get(col) for col in columns) for row in rows])
                destination.commit()
                if table_digest(source,table)!=table_digest(destination,shadow):raise RuntimeError('ORDER shadow mismatch: '+table)
            if current_hash()!=version or tidb_integrity.generation()!=generation:raise RuntimeError('source_ORDER_changed_during_backup_alignment')
            renames=[]
            for index,table in enumerate(sorted(old_names)):
                archive='__v255_old_order_'+str(index)+'_'+token
                archives[table]=archive;renames.append(_qi(table)+' TO '+_qi(archive))
            for table,shadow in shadows.items():renames.append(_qi(shadow)+' TO '+_qi(table))
            destination.cursor().execute('RENAME TABLE '+','.join(renames));destination.commit();swapped=True
            return {'source':source_target,'destination':destination_target,'archives':archives,'preserved':True}
        finally:
            if destination is not None:
                if not swapped:
                    for shadow in shadows.values():
                        try:destination.cursor().execute('DROP TABLE IF EXISTS '+_qi(shadow))
                        except Exception:pass
                destination.close()
            source.close()


def _reconcile_once(source_target=None):
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
    import tidb_integrity
    tidb_integrity.invalidate()
    destination = None
    results = []
    source_version_before = _mirror_version(source_target)
    try:
        destination = get_db_connection_for_target(destination_target, pooled=False)
        # Never infer a DELETE from absence. The standby may have a still-valid
        # order, or an intentionally deleted image. Keep it and report the drift.
        standby_only = _standby_only_counts(source, destination)
        for table in _TABLES:
            if table != _STATE_TABLE:
                results.append(_upsert_table(source, destination, table))
        if _mirror_version(source_target) != source_version_before:
            raise RuntimeError('source_changed_during_reconcile: retry incrementally')
        results.append(_upsert_table(source, destination, _STATE_TABLE))
        if standby_only or any(item.get('changed') for item in results if item['table'] not in
                               ('cloud_customer_share_snapshot', _STATE_TABLE)):
            _invalidate_derived_views(destination)
            _invalidate_process_views()
        if not standby_only:
            clear_cloud_mirror_dirty()
        print(
            f'[ORDER] TiDB cloud reconcile {source_target}->{destination_target} complete: '
            + ', '.join(
                f"{x['table']}={x.get('rows', 0)}/changed{x.get('changed', 0)}" for x in results
            )
        )
        if standby_only:
            print(f'[WARN] TiDB standby-only ORDER rows retained for audit: {standby_only}')
        return {
            'ok': not bool(standby_only),
            'source': source_target,
            'destination': destination_target,
            'versions_before': versions,
            'standby_only': standby_only,
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
    # Keep standby repair outside the HTTP request path. In particular, a
    # permanently divergent standby (preserved rows not present on the active
    # DB) must not trigger another full-table scan every ten minutes.
    import os
    time.sleep(30.0 if (os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_NAME')) else 4.0)
    event = cloud_mirror_dirty_event()
    first = True
    last_pass = 0.0
    last_completed_versions = None
    failures = 0
    next_retry_at = 0.0
    while True:
        if not first:
            event.wait(timeout=600.0)
            now = time.monotonic()
            remaining = max(300.0 - (now - last_pass), next_retry_at - now)
            if remaining > 0:
                time.sleep(min(remaining, 30.0))
                continue

        dirty = event.is_set()
        was_first = first
        first = False
        event.clear()
        try:
            if not dirty and not was_first:
                # A successful pass already reconciled every row possible
                # without deleting standby-only audit records. Their presence
                # is expected to keep integrity.verified=False. Versions are
                # the cheap change detector; do not reread entire tables.
                versions = (_mirror_version('TIDB1'), _mirror_version('TIDB2'))
                if (
                    last_completed_versions is not None
                    and all(version is not None for version in versions)
                    and versions == last_completed_versions
                ):
                    continue
                if versions[0] is not None and versions[0] == versions[1] and versions[0] > 0:
                    import tidb_integrity
                    prior = tidb_integrity.snapshot()
                    if prior.get('verified') and prior.get('versions') == dict(zip(('TIDB1', 'TIDB2'), versions)):
                        tidb_integrity.publish(prior, tidb_integrity.generation())
                        continue

            last_pass = time.monotonic()
            reconcile_once()
            from services.order_sync_integrity import verify_once
            verify_once()
            # Capture versions only after BOTH steps finish. If a new source
            # write arrives during repair, its dirty signal forces a new pass.
            checked = (_mirror_version('TIDB1'), _mirror_version('TIDB2'))
            last_completed_versions = checked if all(v is not None for v in checked) else None
            failures = 0
            next_retry_at = 0.0
        except Exception as exc:
            # A broken TiDB connection must not hammer both databases with
            # repeated full scans or compete with the public share endpoint.
            # Back off from five to thirty minutes; keep repair pending.
            last_completed_versions = None
            failures = min(failures + 1, 10)
            delay = min(1800.0, 300.0 * (2 ** (failures - 1)))
            next_retry_at = time.monotonic() + delay
            print(
                f'[WARN] TiDB cloud reconcile pending: {type(exc).__name__}: {exc}; '
                f'retry_not_before_seconds={int(delay)}'
            )
            event.set()


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

