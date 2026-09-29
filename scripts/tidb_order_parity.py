"""Read-only ORDER cloud parity check for a single order on TiDB1/TiDB2.

Run with the same TiDB environment as Render:
    python scripts/tidb_order_parity.py 1007742

No image bytes, passwords or raw share tokens are printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tidb_targets import pymysql_kwargs


def _exists(cur, table):
    cur.execute("SHOW TABLES LIKE %s", (table,))
    return bool(cur.fetchone())


def _rows(cur, sql, args):
    cur.execute(sql, args)
    return list(cur.fetchall() or [])


def inspect(target, order):
    import pymysql
    conn = pymysql.connect(**pymysql_kwargs(target), cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            out = {'target': target, 'order': order, 'tables': {}}
            statements = {
                'cloud_orders': ("SELECT order_number, customer_key, active FROM cloud_orders WHERE order_number=%s", (order,)),
                'cloud_workflows': ("SELECT workflow_key, active FROM cloud_workflows WHERE order_number=%s ORDER BY workflow_key", (order,)),
                'cloud_assets': ("SELECT asset_key, workflow_key, active, object_key, storage_backend FROM cloud_assets WHERE order_number=%s ORDER BY asset_key", (order,)),
                'cloud_share_tokens': ("SELECT status, COUNT(*) AS total FROM cloud_share_tokens WHERE customer_key=(SELECT customer_key FROM cloud_orders WHERE order_number=%s LIMIT 1) GROUP BY status", (order,)),
            }
            for table, (sql, args) in statements.items():
                out['tables'][table] = _rows(cur, sql, args) if _exists(cur, table) else None
            if _exists(cur, 'cloud_tidb_mirror_state'):
                out['mirror_state'] = _rows(cur, "SELECT version, writer_target FROM cloud_tidb_mirror_state WHERE stream_key=%s", ('order_cloud',))
            return out
    finally:
        conn.close()


def summarize(out):
    tables = out['tables']
    assets = tables.get('cloud_assets') or []
    return {
        'target': out['target'], 'order': out['order'],
        'order_rows': tables.get('cloud_orders'),
        'workflows': tables.get('cloud_workflows'),
        'share_status_counts': tables.get('cloud_share_tokens'),
        'assets': [
            {'asset_key_prefix': str(a['asset_key'])[:12],
             'workflow_key': a.get('workflow_key'), 'active': bool(a.get('active')),
             'b2_key_present': bool(a.get('object_key')), 'backend': a.get('storage_backend')}
            for a in assets
        ],
        'mirror_state': out.get('mirror_state'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('order_number', help='e.g. 1007742')
    args = parser.parse_args()
    results = {}
    for target in ('TIDB1', 'TIDB2'):
        try:
            results[target] = inspect(target, args.order_number)
            print(json.dumps(summarize(results[target]), ensure_ascii=False, default=str, indent=2))
        except Exception as exc:
            print(f'{target}: {type(exc).__name__}; check TiDB credentials and reachability',
                  file=sys.stderr)
    if len(results) == 2:
        a = {str(x['asset_key']) for x in results['TIDB1']['tables'].get('cloud_assets') or [] if x.get('active')}
        b = {str(x['asset_key']) for x in results['TIDB2']['tables'].get('cloud_assets') or [] if x.get('active')}
        print(json.dumps({'active_assets_only_in_tidb1': len(a - b),
                          'active_assets_only_in_tidb2': len(b - a)}, indent=2))
    else:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
