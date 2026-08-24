"""Token-authorized ORDER image redirects for multiple private B2 backends.

Formal read path:
Browser -> Render (prewarmed token/snapshot authorization, TiDB fallback) ->
302 signed B2 URL -> B2.

Render never downloads or returns image bytes.  The same canonical cloud object is
used for card, detail and full-image reads; this module never copies or moves images.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
import threading
import time
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


def _asset_from_bundle(bundle, asset_key):
    """Find one already-authorized asset in the prewarmed customer snapshot."""
    asset_key = str(asset_key or '').strip().lower()
    space = (bundle or {}).get('space') or {}
    orders = space.get('orders') if isinstance(space, dict) else None
    if not isinstance(orders, list):
        return None

    for order in orders:
        if not isinstance(order, dict):
            continue
        assets = order.get('assets')
        if not isinstance(assets, list):
            continue
        for item in assets:
            if not isinstance(item, dict):
                continue
            if str(item.get('asset_key') or '').strip().lower() != asset_key:
                continue
            if not item.get('object_key'):
                return None
            return {
                'asset_key': item.get('asset_key'),
                'order_number': item.get('order_number') or order.get('order_number'),
                'workflow_key': item.get('workflow_key'),
                'sha256': item.get('sha256'),
                'object_key': item.get('object_key'),
                'content_type': item.get('content_type'),
                'file_size': item.get('file_size'),
                'storage_backend': item.get('storage_backend'),
            }
    return None


def _authorized_asset_from_memory(token, asset_key):
    """Authorize from the same hot token/customer snapshot used by /share/<token>.

    Returns (asset, error, available).  available=False means the hot cache could not
    answer safely and the caller must use the canonical one-query TiDB fallback.
    """
    try:
        from services import order_customer_share_hot_cache as hot
        from services import order_public_share_multi_b2_page as page
    except Exception:
        return None, None, False

    token = str(token or '').strip()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    share = page._cache_get(page._token_cache, token)
    if share is None:
        share = page._cache_get(hot._HASH_TOKEN_CACHE, token_hash)
    if share is None:
        return None, None, False

    share, error = page._validate_share(share)
    if error:
        return None, error, True

    customer_key = str((share or {}).get('customer_key') or '').strip()
    if not customer_key:
        return None, None, False

    bundle = page._cache_get(page._space_cache, customer_key)
    if bundle is None:
        return None, None, False

    asset = _asset_from_bundle(bundle, asset_key)
    if asset is None:
        # Do not turn a possibly stale/mid-refresh snapshot into a false 404.  The
        # indexed TiDB query below remains the canonical correctness fallback.
        return None, None, False
    return asset, None, True


def _authorized_asset_from_tidb(token, asset_key):
    """Canonical token + asset ownership check in ONE indexed TiDB query."""
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


def _authorized_asset(token, asset_key):
    """Memory-first authorization with the existing indexed TiDB fallback."""
    token = str(token or '').strip()
    asset_key = str(asset_key or '').strip().lower()
    if not token or len(asset_key) != 64:
        return None, Response('Archivo no encontrado.', 404, mimetype='text/plain'), 'invalid'

    asset, error, available = _authorized_asset_from_memory(token, asset_key)
    if available:
        return asset, error, 'memory-prewarmed'

    asset, error = _authorized_asset_from_tidb(token, asset_key)
    return asset, error, 'tidb-one-query'


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


def _timing_headers(resp, auth_mode, auth_ms, sign_ms, total_ms):
    resp.headers['X-Order-Media-Auth'] = str(auth_mode or 'unknown')
    resp.headers['X-Order-Media-Auth-MS'] = f'{auth_ms:.1f}'
    resp.headers['X-Order-Media-Sign-MS'] = f'{sign_ms:.1f}'
    resp.headers['X-Order-Media-App-MS'] = f'{total_ms:.1f}'
    resp.headers['Server-Timing'] = (
        f'order_media_auth;dur={auth_ms:.1f}, '
        f'order_media_sign;dur={sign_ms:.1f}, '
        f'order_media_app;dur={total_ms:.1f}'
    )
    return resp


@b2_test_bp.before_app_request
def _multi_b2_public_media_interceptor():
    path = request.path or ''
    if not path.startswith('/share/') or request.method != 'GET':
        return None
    parts = path.strip('/').split('/')
    if len(parts) != 4 or parts[2] not in ('image', 'asset', 'thumb'):
        return None

    started = time.perf_counter()
    auth_started = started
    asset, error, auth_mode = _authorized_asset(parts[1], parts[3])
    auth_ms = (time.perf_counter() - auth_started) * 1000.0
    if error:
        total_ms = (time.perf_counter() - started) * 1000.0
        error.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-memory-first-sigv4'
        return _timing_headers(error, auth_mode, auth_ms, 0.0, total_ms)

    sign_started = time.perf_counter()
    try:
        url, backend = _signed_get(asset, seconds=600)
        sign_ms = (time.perf_counter() - sign_started) * 1000.0
        resp = redirect(url, code=302)
        resp.headers['Cache-Control'] = 'private, max-age=60'
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-memory-first-sigv4'
        resp.headers['X-Order-Storage-Backend'] = backend
        if parts[2] != 'image':
            resp.headers['X-Order-Legacy-Media-Alias'] = parts[2]
        total_ms = (time.perf_counter() - started) * 1000.0
        return _timing_headers(resp, auth_mode, auth_ms, sign_ms, total_ms)
    except Exception as exc:
        sign_ms = (time.perf_counter() - sign_started) * 1000.0
        resp = Response('Imagen temporalmente no disponible.', 503, mimetype='text/plain')
        resp.headers['X-Order-Media-Mode'] = 'direct-b2-redirect-memory-first-sigv4'
        resp.headers['X-Order-Media-Error'] = type(exc).__name__
        total_ms = (time.perf_counter() - started) * 1000.0
        return _timing_headers(resp, auth_mode, auth_ms, sign_ms, total_ms)
