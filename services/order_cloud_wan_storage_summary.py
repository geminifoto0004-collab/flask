"""WAN-only B2 distribution/health and repair APIs for ORDER customer shares.

These endpoints are used only by the overseas/Render public-share provider. LAN
sharing never calls them and remains entirely local/SQLite based.

Design:
- summary: one TiDB GROUP BY + cached backend health, no per-image HEAD;
- repair-plan: return only active IMAGE metadata currently assigned to an unreadable
  backend so the office PC can repair exactly those assets;
- repair-register: after PC uploads replacement bytes directly to a healthy B2,
  atomically replace/deactivate the old cloud_assets row instead of creating a broken
  duplicate card.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services import order_cloud_direct_multi_b2 as direct
from services.order_cloud_asset_service import _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, backend_ready, _ensure_storage_backend_column
from services.order_cloud_multi_b2_auto import probe_backend_class_b

_MAX_CUSTOMERS = 200
_ALLOWED = {PRIMARY, SECONDARY}


def _ensure_asset_schema():
    _ensure_order_cloud_tables()
    _ensure_storage_backend_column()


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


def _health_pair():
    primary = _public_health(probe_backend_class_b(PRIMARY, force=False))
    secondary = _public_health(probe_backend_class_b(SECONDARY, force=False))
    return primary, secondary


def _health_ok_map(primary, secondary):
    return {
        PRIMARY: bool((primary or {}).get('class_b_ok')),
        SECONDARY: bool((secondary or {}).get('class_b_ok')),
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
    _ensure_asset_schema()

    payload = request.get_json(silent=True) or {}
    customer_keys = _normalize_customer_keys(payload.get('customer_keys'))
    if not customer_keys:
        return jsonify({'ok': True, 'result': {'customers': {}, 'health': {}}})

    primary, secondary = _health_pair()
    health_ok = _health_ok_map(primary, secondary)
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
            if backend in _ALLOWED:
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


@b2_test_bp.route('/api/order-cloud/assets/wan-repair-plan', methods=['POST'])
def order_cloud_wan_repair_plan():
    """Return only assets whose recorded B2 backend is currently unreadable."""
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    _ensure_asset_schema()

    payload = request.get_json(silent=True) or {}
    customer_key = str(payload.get('customer_key') or '').strip()
    if not customer_key:
        return jsonify({'ok': False, 'error': 'customer_key is required'}), 400

    primary, secondary = _health_pair()
    health_ok = _health_ok_map(primary, secondary)
    selected = (
        PRIMARY if primary.get('class_b_ok')
        else SECONDARY if secondary.get('class_b_ok')
        else None
    )

    conn = get_db_connection()
    cur = get_cursor(conn)
    items = []
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                      content_type, file_size, storage_backend
               FROM cloud_assets
               WHERE active=TRUE AND asset_type='IMAGE' AND customer_key=?
               ORDER BY order_number, workflow_key, created_at, asset_key""",
            (customer_key,),
        )
        for row in cur.fetchall():
            data = get_row_dict(row, cur) or {}
            backend = str(data.get('storage_backend') or PRIMARY).strip().lower()
            if backend in _ALLOWED and health_ok.get(backend, False):
                continue
            items.append({
                'asset_key': str(data.get('asset_key') or ''),
                'order_number': str(data.get('order_number') or ''),
                'workflow_key': str(data.get('workflow_key') or ''),
                'sha256': str(data.get('sha256') or ''),
                'content_type': str(data.get('content_type') or 'image/jpeg'),
                'file_size': int(data.get('file_size') or 0),
                'storage_backend': backend,
            })
    finally:
        conn.close()

    response = jsonify({'ok': True, 'result': {
        'customer_key': customer_key,
        'repair_needed': len(items),
        'selected_readable': selected,
        'items': items,
        'health': {PRIMARY: primary, SECONDARY: secondary},
    }})
    response.headers['Cache-Control'] = 'no-store, private, max-age=0'
    return response


@b2_test_bp.route('/api/order-cloud/assets/direct-repair-register', methods=['POST'])
def order_cloud_direct_repair_register():
    """Replace one broken WAN asset after PC -> B2 direct upload.

    The caller supplies the OLD asset_key plus the NEW optimized sha/object/backend.
    If the sha changes, the new canonical asset row is activated and the old row is
    deactivated in the same transaction. This prevents duplicate/broken cards.
    """
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    _ensure_asset_schema()

    try:
        payload = request.get_json(silent=True) or {}
        old_asset_key = str(payload.get('asset_key') or '').strip().lower()
        if len(old_asset_key) != 64:
            raise ValueError('asset_key must be a 64-character hexadecimal value')
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        backend = str(payload.get('storage_backend') or '').strip().lower()
        if backend not in _ALLOWED or not backend_ready(backend):
            raise ValueError('storage_backend is invalid or not configured')
        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            raise ValueError('file_size must be an integer')
        if file_size <= 0 or file_size > direct._NEW_IMAGE_MAX_BYTES:
            raise ValueError('replacement image must be between 1 and 1,000,000 bytes')

        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT asset_key, customer_key, order_number, workflow_key,
                          display_name, source_site
                   FROM cloud_assets
                   WHERE asset_key=? AND active=TRUE AND asset_type='IMAGE'
                   LIMIT 1""",
                (old_asset_key,),
            )
            old = get_row_dict(cur.fetchone(), cur) or None
            if not old:
                raise ValueError('active asset to repair was not found')

            order_number = str(old.get('order_number') or '')
            customer_key = str(old.get('customer_key') or '')
            workflow_key = str(old.get('workflow_key') or '').strip() or None
            canonical_object_key = direct._scoped_object_key(
                customer_key, order_number, workflow_key, sha256_hex, content_type
            )
            supplied_object_key = str(payload.get('object_key') or '').strip()
            if supplied_object_key != canonical_object_key:
                raise ValueError('object_key does not match canonical repaired asset path')

            new_asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
            display_name = str(old.get('display_name') or f'Imagen {order_number}')
            final_source = str(source_site or old.get('source_site') or '').strip().upper()[:16] or None

            cur.execute('SELECT asset_key FROM cloud_assets WHERE asset_key=?', (new_asset_key,))
            already = bool(cur.fetchone())
            if new_asset_key == old_asset_key:
                cur.execute(
                    """UPDATE cloud_assets
                       SET sha256=?, object_key=?, content_type=?, file_size=?,
                           storage_backend=?, source_site=?, active=TRUE,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE asset_key=?""",
                    (sha256_hex, canonical_object_key, content_type, file_size,
                     backend, final_source, old_asset_key),
                )
            elif already:
                cur.execute(
                    """UPDATE cloud_assets
                       SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                           sha256=?, object_key=?, content_type=?, file_size=?, display_name=?,
                           source_site=?, storage_backend=?, active=TRUE,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE asset_key=?""",
                    (customer_key, order_number, workflow_key, sha256_hex,
                     canonical_object_key, content_type, file_size, display_name,
                     final_source, backend, new_asset_key),
                )
                cur.execute(
                    "UPDATE cloud_assets SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE asset_key=?",
                    (old_asset_key,),
                )
            else:
                cur.execute(
                    """INSERT INTO cloud_assets
                       (customer_key, order_number, workflow_key, asset_type, sha256,
                        object_key, content_type, file_size, display_name, source_site,
                        storage_backend, active, asset_key)
                       VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?, TRUE, ?)""",
                    (customer_key, order_number, workflow_key, sha256_hex,
                     canonical_object_key, content_type, file_size, display_name,
                     final_source, backend, new_asset_key),
                )
                cur.execute(
                    "UPDATE cloud_assets SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE asset_key=?",
                    (old_asset_key,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return jsonify({'ok': True, 'result': {
            'repaired': True,
            'old_asset_key': old_asset_key,
            'asset_key': new_asset_key,
            'sha256': sha256_hex,
            'object_key': canonical_object_key,
            'storage_backend': backend,
            'file_size': file_size,
            'render_received_image_bytes': False,
            'old_b2_object_deleted': False,
        }})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
