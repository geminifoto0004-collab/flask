"""Public ORDER media routing across multiple B2 backends.

Authorization follows the canonical ownership relation cloud_orders.order_number ->
customer_key, not the denormalized customer_key copied into cloud_assets.  No B2 HEAD
request is performed.
"""
from flask import Response, redirect, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection
from services.order_cloud_multi_b2 import get_asset_multi, presigned_get_for_asset


def _authorized_asset(token, asset_key):
    from services.order_public_share_fast import _resolve_share, _error_response
    share, state = _resolve_share(token)
    if state != 'active':
        return None, _error_response(state)

    asset = get_asset_multi(asset_key)
    if not asset:
        return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')

    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT 1 FROM cloud_orders
               WHERE order_number=? AND customer_key=? AND active=TRUE LIMIT 1""",
            (asset.get('order_number'), share.get('customer_key')),
        )
        if not cur.fetchone():
            return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')
    finally:
        conn.close()
    return asset, None


@b2_test_bp.before_app_request
def _multi_b2_public_media_interceptor():
    path = request.path or ''
    if not path.startswith('/share/') or request.method != 'GET':
        return None
    parts = path.strip('/').split('/')
    if len(parts) != 4 or parts[2] not in ('asset', 'thumb'):
        return None

    asset, error = _authorized_asset(parts[1], parts[3])
    if error:
        return error

    if parts[2] == 'thumb':
        sha = str(asset.get('sha256') or '')
        key = f'order-cloud/thumbs/{sha[:2]}/{sha}.jpg'
        url = presigned_get_for_asset(asset, seconds=3600, object_key=key)
        resp = redirect(url, code=302)
        resp.headers['Cache-Control'] = 'private, max-age=1800'
        return resp

    url = presigned_get_for_asset(asset, seconds=900)
    resp = redirect(url, code=302)
    resp.headers['Cache-Control'] = 'private, max-age=300'
    return resp
