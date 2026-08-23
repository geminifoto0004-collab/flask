"""ORDER cloud web-image variants.

The office PC publishes only two colour-managed derivatives for customer sharing:
- 480px JPEG thumbnail for the order gallery.
- 2560px JPEG web image for order detail / zoom.

The local original is never uploaded.  This module only issues protected short-lived
private-B2 URLs and removes stale cloud asset metadata after a successful full rescan.
"""
import re

from flask import jsonify, request
from botocore.exceptions import ClientError

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_asset_service import (
    _asset_key,
    _b2_client,
    _b2_config,
    _is_not_found,
    _validate_sha256,
)


def _thumb_object_key(web_sha256: str) -> str:
    web_sha256 = _validate_sha256(web_sha256)
    return f"order-cloud/thumbs/{web_sha256[:2]}/{web_sha256}.jpg"


@b2_test_bp.route('/api/order-cloud/assets/presign-thumb', methods=['POST'])
def order_cloud_asset_presign_thumb():
    """Return a short-lived direct-B2 PUT URL for one 480px JPEG thumbnail."""
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        web_sha256 = _validate_sha256(payload.get('sha256'))
        object_key = _thumb_object_key(web_sha256)
        cfg = _b2_config()
        s3 = _b2_client(cfg)
        try:
            info = s3.head_object(Bucket=cfg['bucket_name'], Key=object_key)
            return jsonify({
                'ok': True,
                'result': {
                    'exists': True,
                    'sha256': web_sha256,
                    'content_type': 'image/jpeg',
                    'file_size': int(info.get('ContentLength') or 0),
                    'variant': 'thumb_480_q85',
                },
            })
        except ClientError as exc:
            if not _is_not_found(exc):
                raise

        upload_url = s3.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': cfg['bucket_name'],
                'Key': object_key,
                'ContentType': 'image/jpeg',
            },
            ExpiresIn=600,
            HttpMethod='PUT',
        )
        return jsonify({
            'ok': True,
            'result': {
                'exists': False,
                'sha256': web_sha256,
                'content_type': 'image/jpeg',
                'upload_url': upload_url,
                'expires_seconds': 600,
                'variant': 'thumb_480_q85',
            },
        })
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/prune', methods=['POST'])
def order_cloud_asset_prune():
    """Deactivate stale asset rows after a complete successful local customer rescan.

    B2 objects are deliberately not deleted because content-addressed objects may be
    reused.  Only TiDB relationship rows outside the freshly published set are hidden.
    """
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        customer_key = str(payload.get('customer_key') or '').strip()
        order_numbers = []
        seen_orders = set()
        for value in payload.get('order_numbers') or []:
            number = str(value or '').strip()
            if number and number not in seen_orders:
                seen_orders.add(number)
                order_numbers.append(number)
        if not customer_key:
            return jsonify({'ok': False, 'error': 'customer_key is required'}), 400
        if len(order_numbers) > 5000:
            return jsonify({'ok': False, 'error': 'too many order_numbers'}), 400

        allowed_by_order = {number: set() for number in order_numbers}
        for item in payload.get('assets') or []:
            if not isinstance(item, dict):
                continue
            order_number = str(item.get('order_number') or '').strip()
            if order_number not in allowed_by_order:
                continue
            workflow_key = str(item.get('workflow_key') or '').strip() or None
            sha256_hex = _validate_sha256(item.get('sha256'))
            allowed_by_order[order_number].add(_asset_key(order_number, workflow_key, sha256_hex))

        conn = get_db_connection()
        cur = get_cursor(conn)
        deactivated = 0
        try:
            for order_number in order_numbers:
                # Never let one customer prune another customer's rows.
                cur.execute(
                    'SELECT order_number FROM cloud_orders WHERE order_number=? AND customer_key=? AND active=TRUE',
                    (order_number, customer_key),
                )
                if not cur.fetchone():
                    continue
                cur.execute(
                    'SELECT asset_key FROM cloud_assets WHERE customer_key=? AND order_number=? AND active=TRUE',
                    (customer_key, order_number),
                )
                current = []
                for row in cur.fetchall():
                    data = get_row_dict(row, cur) or {}
                    key = str(data.get('asset_key') or '')
                    if key:
                        current.append(key)
                allowed = allowed_by_order.get(order_number) or set()
                stale = [key for key in current if key not in allowed]
                for key in stale:
                    cur.execute(
                        'UPDATE cloud_assets SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE asset_key=?',
                        (key,),
                    )
                    deactivated += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return jsonify({'ok': True, 'deactivated': deactivated, 'orders': len(order_numbers)})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.after_app_request
def order_cloud_use_web_variant_inside_order(response):
    """Keep gallery thumbnails tiny, but use the 2560 web asset inside order detail.

    customer_share_live_fast.html already lazy-loads detail images.  Its existing
    `data-thumb` attribute is rewritten only for detail images, so the gallery cover
    still uses /thumb while order detail / viewer use /asset (the 2560 web derivative).
    """
    try:
        if request.method != 'GET' or not (request.path or '').startswith('/share/'):
            return response
        ctype = str(response.headers.get('Content-Type') or '').lower()
        if 'text/html' not in ctype:
            return response
        html = response.get_data(as_text=True)
        if 'class="detail-img"' not in html or 'data-thumb=' not in html:
            return response
        html = re.sub(r'(data-thumb="[^"]*)/thumb/', r'\1/asset/', html)
        html = html.replace('Las fotos grandes se cargan solo al abrirlas',
                            'Miniaturas rápidas; detalle en alta calidad al abrir el pedido')
        response.set_data(html)
        response.headers['Content-Length'] = str(len(response.get_data()))
    except Exception:
        pass
    return response
