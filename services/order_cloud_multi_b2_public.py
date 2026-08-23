"""Token-authorized ORDER image redirects for multiple private B2 backends.

Formal read path:
Browser -> Render (token/ownership check only) -> 302 signed B2 URL -> Browser reads B2.
Render never downloads or returns image bytes.  The stable public path is
/share/<token>/image/<asset_key>.  Legacy /asset and /thumb paths remain aliases during
rollout and point to the same single cloud object.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import threading

import boto3
from flask import Response, redirect, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, config_for_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}
_CLIENTS = {}
_CLIENTS_LOCK = threading.Lock()


def _cached_client(backend):
    backend = str(backend or PRIMARY).strip().lower()
    if backend not in _ALLOWED_BACKENDS:
        backend = PRIMARY
    cfg = config_for_backend(backend, required=True)
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(backend)
        if client is None:
            client = boto3.client(
                's3',
                endpoint_url=cfg['endpoint'],
                aws_access_key_id=cfg['key_id'],
                aws_secret_access_key=cfg['application_key'],
            )
            _CLIENTS[backend] = client
        return client, cfg


def _parse_expiry(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except Exception:
        return None


def _authorized_asset(token, asset_key):
    """Resolve token and canonical order ownership in one TiDB connection."""
    token = str(token or '').strip()
    asset_key = str(asset_key or '').strip().lower()
    if not token or len(asset_key) != 64:
        return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT customer_key, status, expires_at
               FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
            (token_hash,),
        )
        row = cur.fetchone()
        share = get_row_dict(row, cur) if row else None
        if not share:
            return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')
        if str(share.get('status') or '') != 'active':
            return None, Response('Este enlace ya no está disponible.', 410, mimetype='text/plain')
        expiry = _parse_expiry(share.get('expires_at'))
        if expiry and datetime.utcnow() >= expiry:
            return None, Response('Este enlace ha expirado.', 410, mimetype='text/plain')

        cur.execute(
            """SELECT a.asset_key, a.order_number, a.workflow_key, a.sha256,
                      a.object_key, a.content_type, a.file_size, a.storage_backend
               FROM cloud_assets a
               INNER JOIN cloud_orders o ON o.order_number=a.order_number
               WHERE a.asset_key=? AND a.active=TRUE
                 AND o.customer_key=? AND o.active=TRUE
               LIMIT 1""",
            (asset_key, share.get('customer_key')),
        )
        row = cur.fetchone()
        asset = get_row_dict(row, cur) if row else None
        if not asset or not asset.get('object_key'):
            return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')
        return asset, None
    finally:
        conn.close()


def _signed_get(asset, seconds=600):
    backend = str((asset or {}).get('storage_backend') or PRIMARY).strip().lower()
    if backend not in _ALLOWED_BACKENDS:
        backend = PRIMARY
    client, cfg = _cached_client(backend)
    url = client.generate_presigned_url(
        'get_object',
        Params={'Bucket': cfg['bucket_name'], 'Key': asset['object_key']},
        ExpiresIn=int(seconds),
    )
    return url, backend


@b2_test_bp.before_app_request
def _multi_b2_public_media_interceptor():
    path = request.path or ''
    if not path.startswith('/share/') or request.method != 'GET':
        return None
    parts = path.strip('/').split('/')
    if len(parts) != 4 or parts[2] not in ('image', 'asset', 'thumb'):
        return None

    asset, error = _authorized_asset(parts[1], parts[3])
    if error:
        return error

    try:
        url, backend = _signed_get(asset, seconds=600)
        resp = redirect(url, code=302)
        # Cache the authorization redirect briefly. The signed B2 URL itself expires
        # quickly, so revoking a share does not grant long-lived future access.
        resp.headers['Cache-Control'] = 'private, max-age=300'
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-single-image'
        resp.headers['X-Order-Storage-Backend'] = backend
        if parts[2] != 'image':
            resp.headers['X-Order-Legacy-Media-Alias'] = parts[2]
        return resp
    except Exception as exc:
        resp = Response('Imagen temporalmente no disponible.', 503, mimetype='text/plain')
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-single-image'
        resp.headers['X-Order-Media-Error'] = type(exc).__name__
        return resp
