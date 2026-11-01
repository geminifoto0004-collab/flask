"""Bounded, explicit verification; GET polling never queries either TiDB."""
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import threading
import time
import uuid

import tidb_integrity as evidence

_lock = threading.Lock()
_verify_lock = threading.Lock()
_job = {}


def _canonical(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(type(value).__name__)


def table_digest(connection, table, *, limit=250000):
    import re
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', table):
        raise ValueError('invalid table')
    cursor = connection.cursor()
    cursor.execute('SHOW TABLES LIKE %s', (table,))
    if not cursor.fetchone():
        return {'exists': False, 'rows': 0, 'digest': None}
    cursor.execute('SHOW COLUMNS FROM `' + table + '`')
    schema = cursor.fetchall()
    columns = [str(row.get('Field') if isinstance(row, dict) else row[0]) for row in schema]
    if not columns or any(not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', col) for col in columns):
        raise ValueError('invalid columns')
    # Bounded sorting of row hashes also supports composite keys and NULL values.
    hashes = []
    cursor.execute('SELECT * FROM `' + table + '`')
    while True:
        batch = cursor.fetchmany(250)
        if not batch:
            break
        if len(hashes) + len(batch) > limit:
            raise RuntimeError('verification row limit exceeded')
        for row in batch:
            values = [row.get(col) for col in columns] if isinstance(row, dict) else list(row)
            raw = json.dumps(values, ensure_ascii=False, separators=(',', ':'), default=_canonical)
            hashes.append(hashlib.sha256(raw.encode()).digest())
    digest = hashlib.sha256(json.dumps(schema, sort_keys=True, default=_canonical).encode())
    for row_hash in sorted(hashes):
        digest.update(row_hash)
    return {'exists': True, 'rows': len(hashes), 'digest': digest.hexdigest()}


def verify_once(expected=None):
    with _verify_lock:
        return _verify_once(expected)


def _verify_once(expected=None):
    from database import get_db_connection_for_target
    from tidb_targets import target_configured, mirror_enabled
    from services.order_tidb_cloud_reconcile import _TABLES, _STATE_TABLE, _mirror_version
    from services.order_tidb_connection import _connect_target, order_database_name
    from services.order_full_mirror_service import _STATE_TABLE as mirror_table
    generation = evidence.generation()
    result = {'state': 'checking', 'verified': False, 'targets': {}, 'differences': [], 'mirror_enabled': mirror_enabled(),
              'cloud_equal': False, 'order_equal': False}
    before = {target: _mirror_version(target) for target in ('TIDB1', 'TIDB2')}
    values = {}
    local_matches = {}
    for target in ('TIDB1', 'TIDB2'):
        if not target_configured(target):
            result['targets'][target] = {'reachable': False, 'reason': 'not_configured'}
            continue
        cloud = order = None
        try:
            cloud = get_db_connection_for_target(target, pooled=False)
            tables = {table: table_digest(cloud, table) for table in _TABLES
                      if table not in {_STATE_TABLE, 'cloud_customer_share_snapshot'}}
            # The full ORDER mirror is separate from customer-safe cloud_* data.
            order = _connect_target(target, database=order_database_name())
            cursor = order.cursor()
            cursor.execute('SELECT snapshot_hash, table_count, row_count FROM `' + mirror_table + '` WHERE id=1')
            state = cursor.fetchone() or {}
            cursor.execute('SHOW TABLES')
            names = sorted(str(next(iter(row.values())) if isinstance(row, dict) else row[0]) for row in cursor.fetchall())
            names = [name for name in names if not name.startswith('__')]
            if len(names) > 256: raise RuntimeError('verification table limit exceeded')
            order_tables = {name: table_digest(order, name) for name in names}
            if expected is not None:
                from order_content_digest import digest_rows
                matched = set(names) == set(expected)
                for name, item in expected.items():
                    columns = item['columns']
                    cursor.execute('SELECT ' + ','.join('`'+col['name']+'`' for col in columns) + ' FROM `'+name+'`')
                    def rows():
                        while True:
                            batch = cursor.fetchmany(250)
                            if not batch: break
                            yield from batch
                    actual = digest_rows(columns, rows())
                    if actual != {'rows':item['rows'], 'digest':item['digest']}: matched = False
                local_matches[target] = matched
            values[target] = {'tables': tables, 'order': dict(state), 'order_tables': order_tables}
            result['targets'][target] = {'reachable': True, 'tables': tables, 'order': dict(state), 'order_tables': order_tables}
        except Exception as error:
            evidence.target_failed(target, error)
            result['targets'][target] = {'reachable': False,
                'reason': 'quota_exceeded' if evidence.quota_error(error) else 'read_failed',
                'error_type': type(error).__name__}
        finally:
            for connection in (cloud, order):
                if connection is not None:
                    try: connection.close()
                    except Exception: pass
    after = {target: _mirror_version(target) for target in ('TIDB1', 'TIDB2')}
    result['versions'] = after
    result['local_equal'] = all(local_matches.values()) if len(local_matches)==2 else False if expected is not None else None
    if len(values) == 2:
        left, right = values['TIDB1'], values['TIDB2']
        result['differences'] = [table for table in left['tables']
                                if left['tables'][table] != right['tables'][table]
                                or not left['tables'][table]['exists']]
        result['cloud_equal'] = not result['differences']
        a, b = left['order'], right['order']
        result['order_equal'] = bool(a.get('snapshot_hash') and a == b
                                     and left['order_tables'] == right['order_tables']
                                     and len(left['order_tables']) == int(a.get('table_count') or 0))
        stable = before == after and all(value is not None for value in after.values())
        result['verified'] = bool(result['mirror_enabled'] and stable and result['cloud_equal'] and result['order_equal'] and (expected is None or result['local_equal']))
        result['state'] = 'verified' if result['verified'] else 'different' if stable else 'changed_during_check'
    else:
        result['state'] = 'unavailable'
    published = evidence.publish(result, generation)
    print('[ORDER Integrity] state=' + str(published['state']) + ' verified=' + str(published['verified'])
          + ' cloud_equal=' + str(result['cloud_equal']) + ' order_equal=' + str(result['order_equal'])
          + ' local_equal=' + str(result['local_equal']) + ' differences=' + ','.join(result['differences']), flush=True)
    return published


def read_job(start=False, repair=False, expected=None):
    global _job
    with _lock:
        expected_hash = hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
        if start and (_job.get('state') != 'running') and (time.time() - _job.get('started_at_epoch', 0) >= 60 or _job.get('generation') != evidence.generation() or _job.get('expected_hash') != expected_hash):
            job = {'id': uuid.uuid4().hex, 'state': 'running', 'started_at_epoch': time.time(), 'generation': evidence.generation(), 'expected_hash':expected_hash}
            _job = job
            def run():
                try:
                    if repair:
                        from services.order_tidb_cloud_reconcile import reconcile_once
                        reconcile_once()
                    result = verify_once(expected)
                    with _lock: job.update(state='completed', result=result, generation=evidence.generation())
                except Exception as error:
                    with _lock: job.update(state='failed', error_type=type(error).__name__)
                finally:
                    with _lock: job['finished_at_epoch'] = time.time()
            threading.Thread(target=run, daemon=True, name='order-integrity-check').start()
        return {**_job, 'evidence': evidence.snapshot()}


def install(blueprint):
    from flask import jsonify, request
    from blueprints.b2_test_bp import _order_cloud_auth_source
    @blueprint.route('/api/order-cloud/sync/integrity', methods=['GET', 'POST'])
    def order_sync_integrity():
        _, error = _order_cloud_auth_source()
        if error: return error
        from services.order_desktop_grant import authorized
        if not authorized():
            return jsonify({'ok': False, 'error': 'desktop_pairing_required'}), 401
        repair = request.method == 'POST' and (request.get_json(silent=True) or {}).get('repair') is True
        expected = (request.get_json(silent=True) or {}).get('expected') if request.method == 'POST' else None
        if request.method == 'POST':
            if expected is not None:
                import re
                valid = isinstance(expected,dict) and 0<len(expected)<=256
                if valid:
                    for name,item in expected.items():
                        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name) or not isinstance(item,dict): valid=False;break
                        columns=item.get('columns')
                        if (not isinstance(columns,list) or not 0<len(columns)<=256 or any(not isinstance(col,dict) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',str(col.get('name') or '')) or len(str(col.get('type') or ''))>100 for col in columns)
                                or not isinstance(item.get('rows'),int) or not 0<=item['rows']<=500000 or not re.fullmatch(r'[0-9a-f]{64}',str(item.get('digest')or''))): valid=False;break
                if not valid: return jsonify({'ok':False,'error':'invalid verification manifest'}),400
        from tidb_targets import selected_target, target_configured, mirror_enabled
        result = read_job(start=request.method == 'POST', repair=repair, expected=expected)
        result['configuration'] = {'selected_target': selected_target(), 'mirror_enabled': mirror_enabled(),
                                   'configured_targets': [target for target in ('TIDB1','TIDB2') if target_configured(target)]}
        response = jsonify({'ok': True, 'result': result})
        response.headers['Cache-Control'] = 'no-store, private'
        return response
