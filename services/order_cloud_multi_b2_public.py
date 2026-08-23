"""Token-authorized ORDER image redirects for multiple private B2 backends.

Formal read path:
Browser -> Render (single TiDB authorization query) -> 302 signed B2 URL -> B2.
Render never downloads or returns image bytes.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
import threading
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from flask import Response, redirect, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, config_for_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}
_CLIENTS = {}
_CLIENTS_LOCK = threading.Lock()


def _region_from_endpoint(endpoint):
    host = str(urlparse(str(endpoint or '')).hostname or '').lower()
    match = re.search(r'(?:^|\.)s3\.([^.]+)\.backblazeb2\.com$', host)
    if match:
        return match.group(1)
    return 'us-east-1'


def _cached_client(backend):
    """Return a cached Backblaze S3 client that is forced to AWS SigV4."""
    backend = str(backend or PRIMARY).strip().lower()
    if backend not in _ALLOWED_BACKENDS:
        backend = PRIMARY
    cfg = config_for_backend(backend, required=True)
    cache_key = (backend, cfg['endpoint'], cfg['key_id'])
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(cache_key)
        if client is None:
            client = boto3.client(
                's3',
                endpoint_url=cfg['endpoint'],
                aws_access_key_id=cfg['key_id'],
                aws_secret_access_key=cfg['application_key'],
                region_name=_region_from_endpoint(cfg['endpoint']),
                config=Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'},
                ),
            )
            _CLIENTS[cache_key] = client
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
    """Authorize token + canonical asset ownership in ONE indexed TiDB query."""
    token = str(token or '').strip()
    asset_key = str(asset_key or '').strip().lower()
    if not token or len(asset_key) != 64:
        return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT s.status AS share_status, s.expires_at AS share_expires_at,
                      a.asset_key, a.order_number, a.workflow_key, a.sha256,
                      a.object_key, a.content_type, a.file_size, a.storage_backend
               FROM cloud_share_tokens s
               INNER JOIN cloud_assets a ON a.asset_key=? AND a.active=TRUE
               INNER JOIN cloud_orders o ON o.order_number=a.order_number
                                         AND o.customer_key=s.customer_key
                                         AND o.active=TRUE
               WHERE s.token_hash=?
               LIMIT 1""",
            (asset_key, token_hash),
        )
        row = cur.fetchone()
        data = get_row_dict(row, cur) if row else None
        if not data:
            return None, Response('Archivo no encontrado.', 404, mimetype='text/plain')
        if str(data.get('share_status') or '') != 'active':
            return None, Response('Este enlace ya no está disponible.', 410, mimetype='text/plain')
        expiry = _parse_expiry(data.get('share_expires_at'))
        if expiry and datetime.utcnow() >= expiry:
            return None, Response('Este enlace ha expirado.', 410, mimetype='text/plain')

        asset = {
            'asset_key': data.get('asset_key'),
            'order_number': data.get('order_number'),
            'workflow_key': data.get('workflow_key'),
            'sha256': data.get('sha256'),
            'object_key': data.get('object_key'),
            'content_type': data.get('content_type'),
            'file_size': data.get('file_size'),
            'storage_backend': data.get('storage_backend'),
        }
        if not asset.get('object_key'):
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
    if 'X-Amz-Algorithm=AWS4-HMAC-SHA256' not in str(url):
        raise RuntimeError('public B2 GET presigned URL is not AWS Signature V4')
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
        resp.headers['Cache-Control'] = 'private, max-age=60'
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-one-tidb-query-sigv4'
        resp.headers['X-Order-Storage-Backend'] = backend
        if parts[2] != 'image':
            resp.headers['X-Order-Legacy-Media-Alias'] = parts[2]
        return resp
    except Exception as exc:
        resp = Response('Imagen temporalmente no disponible.', 503, mimetype='text/plain')
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-one-tidb-query-sigv4'
        resp.headers['X-Order-Media-Error'] = type(exc).__name__
        return resp
