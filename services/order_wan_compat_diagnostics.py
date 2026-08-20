"""Protected diagnostics for the unified ORDER SQLite/TiDB compatibility layer.

This module never returns business rows. It only reports backend selection, row
counts, and whether the exact LAN homepage loader can execute through the TiDB
compatibility connection. It is invoked only from the existing sync-key protected
endpoint.
"""
from __future__ import annotations

import time


def _step(result: dict, name: str, fn):
    started = time.monotonic()
    try:
        value = fn()
        result[name] = {
            'ok': True,
            'ms': round((time.monotonic() - started) * 1000, 1),
            'value': value,
        }
    except Exception as exc:
        result[name] = {
            'ok': False,
            'ms': round((time.monotonic() - started) * 1000, 1),
            'error_type': type(exc).__name__,
            'error': str(exc),
        }


def run_order_wan_compat_diagnostics() -> dict:
    result = {}

    from services.order_full_mirror_service import get_full_mirror_state
    from services.order_tidb_connection import get_order_tidb_connection, order_database_name

    result['order_database'] = order_database_name()
    result['mirror_state'] = get_full_mirror_state()

    def raw_counts():
        conn = get_order_tidb_connection()
        try:
            cur = conn.cursor()
            out = {}
            for table in ('users', 'orders', 'workflows', 'workflow_status_history', 'notifications'):
                cur.execute(f'SELECT COUNT(*) AS n FROM `{table}`')
                row = cur.fetchone() or {}
                out[table] = int(row.get('n') or 0)
            return out
        finally:
            conn.close()

    _step(result, 'raw_tidb_counts', raw_counts)

    def runtime_flags():
        from order_tracking.runtime_mode import unified_remote_db_enabled
        from order_tracking.cloud_mode import cloud_mode_enabled, cloud_read_only_enabled
        from order_tracking.data_provider import get_order_data_provider
        return {
            'unified_remote_db_enabled': bool(unified_remote_db_enabled()),
            'cloud_mode_enabled': bool(cloud_mode_enabled()),
            'cloud_read_only_enabled': bool(cloud_read_only_enabled()),
            'legacy_provider_active': get_order_data_provider() is not None,
        }

    _step(result, 'runtime_flags', runtime_flags)

    def wrapped_smoke():
        from order_tracking.db_backend import get_tracking_db_connection
        conn = get_tracking_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('PRAGMA table_info(orders)')
            order_cols = [row['name'] for row in cur.fetchall()]
            cur.execute('SELECT COUNT(*) AS n FROM orders')
            order_count = int((cur.fetchone() or {}).get('n') or 0)
            cur.execute('''
                SELECT COUNT(*) AS n
                FROM workflows w
                INNER JOIN orders o ON o.order_number = w.order_number
                LEFT JOIN users u ON u.id = w.handler_id
            ''')
            join_count = int((cur.fetchone() or {}).get('n') or 0)
            cur.execute("SELECT date('now', '-3 months') AS d")
            date_value = (cur.fetchone() or {}).get('d')
            return {
                'orders_columns': len(order_cols),
                'orders_count': order_count,
                'workflow_order_user_join_count': join_count,
                'date_translation_value': str(date_value or ''),
            }
        finally:
            conn.close()

    _step(result, 'compat_wrapper_smoke', wrapped_smoke)

    def exact_home_loader():
        # Exercise the exact LAN homepage loader against the active backend. We use
        # an admin role so permission filtering cannot hide valid rows. No row data
        # is returned; only the count and a few structural facts are exposed.
        from flask import session
        from order_tracking import _load_home_orders_dataset
        from order_tracking.db_backend import get_tracking_db_connection

        old = {k: session.get(k) for k in ('user_id', 'username', 'role')}
        conn = None
        try:
            session['user_id'] = 1
            session['username'] = '__compat_check__'
            session['role'] = 'admin'
            conn = get_tracking_db_connection()
            rows = _load_home_orders_dataset(conn, 'admin', 1)
            workflow_rows = sum(1 for row in rows if not row.get('no_workflow'))
            no_workflow_rows = sum(1 for row in rows if row.get('no_workflow'))
            return {
                'rows': len(rows),
                'workflow_rows': workflow_rows,
                'orders_without_workflow_rows': no_workflow_rows,
            }
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            for key, value in old.items():
                if value is None:
                    session.pop(key, None)
                else:
                    session[key] = value

    _step(result, 'exact_home_loader', exact_home_loader)

    result['overall_ok'] = all(
        isinstance(value, dict) and value.get('ok')
        for key, value in result.items()
        if key in {'raw_tidb_counts', 'runtime_flags', 'compat_wrapper_smoke', 'exact_home_loader'}
    )
    return result
