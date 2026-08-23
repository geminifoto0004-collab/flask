"""WAN-only B2 distribution/health summary for ORDER customer shares.

This endpoint is used only by the overseas/Render public-share provider. LAN sharing
never calls it and remains entirely local/SQLite based.

The summary is intentionally aggregate-only: one TiDB GROUP BY for all requested
customers plus one cached health probe per configured B2 backend. No per-image HEAD,
no credentials, bucket names, object keys or signed URLs are returned.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY
from services.order_cloud_multi_b2_auto import probe_backend_class_b

_MAX_CUSTOMERS = 200


def _public_health(item):
    item = dict(item or {})
    return {
        'backend': item.get('backend'),
        'configured': bool(item.get('configured')),
        'class_b_ok': bool(item.get('class_b_ok')),
        'status': str(item.get('status') or 'unknown'),
        'http_status': item.get('http_status'),
        'aws_code': item.get('aws_code'),
        'cached': item.get('cached'),
    }


def _normalize_customer_keys(values):
    result = []
    seen = set()
    for raw in values or []:
        value = str(raw or '').strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= _MAX_CUSTOMERS:
            break
    return result


@b2_test_bp.route('/api/order-cloud/assets/wan-storage-summary', methods=['POST'])
def order_cloud_wan_storage_summary():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    customer_keys = _normalize_customer_keys(payload.get('customer_keys'))
    if not customer_keys:
        return jsonify({'ok': True, 'result': {'customers': {}, 'health': {}}})

    primary_raw = probe_backend_class_b(PRIMARY, force=False)
    secondary_raw = probe_backend_class_b(SECONDARY, force=False)
    primary = _public_health(primary_raw)
    secondary = _public_health(secondary_raw)
    health_ok = {
        PRIMARY: bool(primary.get('class_b_ok')),
        SECONDARY: bool(secondary.get('class_b_ok')),
    }

    customers = {
        key: {
            'available': True,
            'total': 0,
            PRIMARY: 0,
            SECONDARY: 0,
            'unknown': 0,
            'repair_needed': 0,
        }
        for key in customer_keys
    }

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        placeholders = ','.join(['?'] * len(customer_keys))
        cur.execute(
            f"""SELECT customer_key,
                       COALESCE(NULLIF(storage_backend, ''), ?) AS storage_backend,
                       COUNT(*) AS image_count
                FROM cloud_assets
                WHERE active=TRUE
                  AND asset_type='IMAGE'
                  AND customer_key IN ({placeholders})
                GROUP BY customer_key, COALESCE(NULLIF(storage_backend, ''), ?)""",
            [PRIMARY] + customer_keys + [PRIMARY],
        )
        for row in cur.fetchall():
            data = get_row_dict(row, cur) or {}
            customer_key = str(data.get('customer_key') or '').strip()
            target = customers.get(customer_key)
            if target is None:
                continue
            backend = str(data.get('storage_backend') or PRIMARY).strip().lower()
            try:
                count = int(data.get('image_count') or 0)
            except Exception:
                count = 0
            target['total'] += count
            if backend in (PRIMARY, SECONDARY):
                target[backend] += count
                if not health_ok.get(backend, False):
                    target['repair_needed'] += count
            else:
                target['unknown'] += count
                target['repair_needed'] += count
    finally:
        conn.close()

    for target in customers.values():
        target['b2_primary'] = int(target.pop(PRIMARY, 0))
        target['b2_secondary'] = int(target.pop(SECONDARY, 0))
        target['primary_ok'] = bool(primary.get('class_b_ok'))
        target['secondary_ok'] = bool(secondary.get('class_b_ok'))
        target['primary_status'] = primary.get('status')
        target['secondary_status'] = secondary.get('status')
        target['selected_readable'] = (
            PRIMARY if primary.get('class_b_ok')
            else SECONDARY if secondary.get('class_b_ok')
            else None
        )

    response = jsonify({'ok': True, 'result': {
        'customers': customers,
        'health': {PRIMARY: primary, SECONDARY: secondary},
    }})
    response.headers['Cache-Control'] = 'no-store, private, max-age=0'
    return response
