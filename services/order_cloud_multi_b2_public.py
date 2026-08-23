"""Public ORDER media routing across multiple B2 backends.

Authorization follows the canonical ownership relation cloud_orders.order_number ->
customer_key.  Public media is proxied through Render so the browser never depends on
a B2 presigned redirect.  No B2 HEAD request is performed.
"""
from __future__ import annotations

from flask import Response, request
from botocore.exceptions import ClientError

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    client_for_backend,
    config_for_backend,
    get_asset_multi,
)


def _authorized_asset(token, asset_key):
    from services.order_public_share_fast import _resolve_share, _error_response

    share, state = _resolve_share(token)
    if state != 'active':
        return None, _error_response(state)

    asset = get_asset_multi(asset_key)
    if not asset:
        return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')

    conn = get_db_connection()
    cur = get_cursor(conn)
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


def _backend(asset):
    value = str((asset or {}).get('storage_backend') or PRIMARY).strip().lower()
    return value if value in {PRIMARY, SECONDARY} else PRIMARY


def _is_not_found(exc):
    if not isinstance(exc, ClientError):
        return False
    status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
    code = str(exc.response.get('Error', {}).get('Code') or '')
    return status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}


def _get_bytes(asset, object_key):
    backend = _backend(asset)
    cfg = config_for_backend(backend, required=True)
    obj = client_for_backend(backend).get_object(
        Bucket=cfg['bucket_name'],
        Key=object_key,
    )
    return (
        obj['Body'].read(),
        obj.get('ContentType') or asset.get('content_type') or 'application/octet-stream',
        backend,
    )


def _media_response(data, content_type, backend, cache_seconds, *, fallback=False):
    resp = Response(data, mimetype=content_type)
    resp.headers['Cache-Control'] = f'private, max-age={int(cache_seconds)}'
    resp.headers['X-Order-Media-Mode'] = 'render-proxy'
    resp.headers['X-Order-Storage-Backend'] = backend
    if fallback:
        resp.headers['X-Order-Thumb-Fallback'] = 'web'
    return resp


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

    try:
        if parts[2] == 'thumb':
            sha = str(asset.get('sha256') or '')
            thumb_key = f'order-cloud/thumbs/{sha[:2]}/{sha}.jpg'
            try:
                data, content_type, backend = _get_bytes(asset, thumb_key)
                return _media_response(data, content_type, backend, 1800)
            except ClientError as exc:
                if not _is_not_found(exc):
                    raise
                # Thumbnail absence must never make the whole customer image disappear.
                data, content_type, backend = _get_bytes(asset, asset['object_key'])
                return _media_response(data, content_type, backend, 600, fallback=True)

        data, content_type, backend = _get_bytes(asset, asset['object_key'])
        return _media_response(data, content_type, backend, 600)
    except ClientError as exc:
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        code = str(exc.response.get('Error', {}).get('Code') or '')
        resp = Response('Imagen temporalmente no disponible.', 503, mimetype='text/plain')
        resp.headers['X-Order-Media-Mode'] = 'render-proxy'
        resp.headers['X-Order-B2-HTTP'] = str(status or '')
        resp.headers['X-Order-B2-Code'] = code[:64]
        resp.headers['X-Order-Storage-Backend'] = _backend(asset)
        return resp
    except Exception as exc:
        resp = Response('Imagen temporalmente no disponible.', 503, mimetype='text/plain')
        resp.headers['X-Order-Media-Mode'] = 'render-proxy'
        resp.headers['X-Order-Media-Error'] = type(exc).__name__
        resp.headers['X-Order-Storage-Backend'] = _backend(asset)
        return resp
