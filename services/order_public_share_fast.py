"""Fast/scoped ORDER public-share layer.

This module is imported before b2_test_bp is registered. It intercepts the ORDER
public-share endpoints and keeps hot public reads away from repeated schema checks
and repeated TiDB token/asset lookups.
"""
from datetime import datetime
from io import BytesIO
import hashlib
import threading
import time

from flask import Response, jsonify, redirect, render_template, request
from PIL import Image, ImageOps

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from database import check_column_exists, get_cursor, get_db_connection, get_row_dict

_SCOPE_RANK = {'current': 0, '6m': 1, '12m': 2, 'all': 3}

# Public-share hot-path cache.  Share/order data changes comparatively rarely but a
# customer page can request hundreds of images in a short burst.  Keep token and
# customer-space lookups in-process briefly so those requests do not each cross the
# Render <-> TiDB network.
_SHARE_CACHE_TTL = 60.0
_SPACE_CACHE_TTL = 30.0
_ASSET_CACHE_TTL = 120.0
_cache_lock = threading.RLock()
_share_cache = {}
_space_cache = {}
_asset_cache = {}
_share_columns_ready = False
_share_columns_lock = threading.Lock()


def _cache_get(cache, key):
    now = time.monotonic()
    with _cache_lock:
        item = cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            cache.pop(key, None)
            return None
        return value


def _cache_put(cache, key, value, ttl):
    with _cache_lock:
        cache[key] = (time.monotonic() + float(ttl), value)
    return value


def _scope(value):
    value = str(value or 'current').strip().lower()
    aliases = {'default':'current','same':'current','3m':'current','6':'6m','6months':'6m','halfyear':'6m','12':'12m','1y':'12m','year':'12m','history':'all','all_history':'all'}
    value = aliases.get(value, value)
    return value if value in _SCOPE_RANK else 'current'


def _ensure_share_columns():
    """Run the idempotent migration once per Render process, never per request."""
    global _share_columns_ready
    if _share_columns_ready:
        return
    with _share_columns_lock:
        if _share_columns_ready:
            return
        conn = get_db_connection(); cur = get_cursor(conn)
        try:
            if not check_column_exists(cur, 'cloud_share_tokens', 'history_scope'):
                cur.execute("ALTER TABLE cloud_share_tokens ADD COLUMN history_scope VARCHAR(16) NULL")
            if not check_column_exists(cur, 'cloud_share_tokens', 'include_cancelled'):
                cur.execute("ALTER TABLE cloud_share_tokens ADD COLUMN include_cancelled BOOLEAN NOT NULL DEFAULT FALSE")
            conn.commit()
            _share_columns_ready = True
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()


def _resolve_share(token):
    token = str(token or '').strip()
    if not token:
        return None, 'not_found'

    cached = _cache_get(_share_cache, token)
    if cached is not None:
        share, state = cached
        return dict(share) if share else None, state

    _ensure_share_columns()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute("""SELECT token_hash, customer_key, mode, status, source_site, created_at,
                              expires_at, history_scope, include_cancelled
                       FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""", (token_hash,))
        row = cur.fetchone()
        if not row:
            _cache_put(_share_cache, token, (None, 'not_found'), 10.0)
            return None, 'not_found'
        share = get_row_dict(row, cur) or {}
    finally:
        conn.close()
    share['history_scope'] = _scope(share.get('history_scope') or 'current')
    share['include_cancelled'] = bool(share.get('include_cancelled'))
    if str(share.get('status') or '') != 'active':
        state = 'revoked'
    else:
        state = 'active'
        expiry = share.get('expires_at')
        if isinstance(expiry, str):
            try: expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception: expiry = None
        if expiry and datetime.utcnow() >= expiry:
            state = 'expired'
    _cache_put(_share_cache, token, (dict(share), state), _SHARE_CACHE_TTL)
    return share, state


def _error_response(state):
    if state == 'not_found': return Response('Enlace no encontrado.', 404, mimetype='text/plain')
    if state == 'expired': return Response('Este enlace ha expirado.', 410, mimetype='text/plain')
    return Response('Este enlace ya no está disponible.', 410, mimetype='text/plain')


def _months_ago_first(months):
    now = datetime.utcnow(); month0 = now.month - 1 - int(months)
    return datetime(now.year + month0 // 12, month0 % 12 + 1, 1)


def _parse_dt(value):
    if not value: return None
    text = str(value).strip().replace('Z', '+00:00')
    try: return datetime.fromisoformat(text).replace(tzinfo=None)
    except Exception:
        try: return datetime.strptime(text[:10], '%Y-%m-%d')
        except Exception: return None


def _wf_visible(wf, scope, include_cancelled):
    status = str((wf or {}).get('status') or '').strip().upper()
    if scope == 'all':
        return include_cancelled or status != 'CANCELLED'
    if status not in {'COMPLETED', 'CANCELLED'}:
        return True
    if status == 'CANCELLED' and not include_cancelled:
        return False
    changed = _parse_dt((wf or {}).get('last_status_change_date') or (wf or {}).get('updated_at'))
    if not changed:
        return False
    return changed >= _months_ago_first({'current':3,'6m':6,'12m':12}.get(scope, 3))


def _filter_space(space, share):
    if not isinstance(space, dict): return space
    scope = _scope((share or {}).get('history_scope'))
    include_cancelled = bool((share or {}).get('include_cancelled'))
    filtered = []
    for order in list(space.get('orders') or []):
        workflows = list(order.get('workflows') or [])
        if workflows:
            visible = [wf for wf in workflows if _wf_visible(wf, scope, include_cancelled)]
            if not visible: continue
            order['workflows'] = visible
        filtered.append(order)
    space['orders'] = filtered
    return space


def _load_customer_space(customer_key):
    """Cache the fully asset-attached customer payload for a short period."""
    customer_key = str(customer_key or '').strip()
    cached = _cache_get(_space_cache, customer_key)
    if cached is not None:
        # JSON round-trip is unnecessary; caller only filters workflow lists for render.
        # Re-fetch shallow container copies below to avoid mutating cached top-level data.
        import copy
        return copy.deepcopy(cached)

    from services.order_cloud_service import get_customer_space
    from services.order_cloud_asset_service import attach_assets_to_space
    space = get_customer_space(customer_key)
    if not space:
        return None
    attach_assets_to_space(space)
    _cache_put(_space_cache, customer_key, space, _SPACE_CACHE_TTL)
    import copy
    return copy.deepcopy(space)


def _asset_for_share(token, asset_key):
    share, state = _resolve_share(token)
    if state != 'active': return None, None, _error_response(state)

    asset = _cache_get(_asset_cache, asset_key)
    if asset is None:
        from services.order_cloud_asset_service import get_asset
        asset = get_asset(asset_key)
        if asset:
            _cache_put(_asset_cache, asset_key, dict(asset), _ASSET_CACHE_TTL)
    if not asset or asset.get('customer_key') != share.get('customer_key'):
        return share, None, Response('Archivo no encontrado.', 404, mimetype='text/plain')
    return share, dict(asset), None


def _presigned_get(asset, seconds=900):
    from services.order_cloud_asset_service import _b2_client, _b2_config
    cfg = _b2_config(); s3 = _b2_client(cfg)
    return s3.generate_presigned_url('get_object', Params={'Bucket': cfg['bucket_name'], 'Key': asset['object_key']}, ExpiresIn=int(seconds))


def _thumb_redirect(asset):
    from services.order_cloud_asset_service import _b2_client, _b2_config, _is_not_found
    from botocore.exceptions import ClientError
    cfg = _b2_config(); s3 = _b2_client(cfg)
    sha = str(asset.get('sha256') or '')
    thumb_key = f"order-cloud/thumbs/{sha[:2]}/{sha}.jpg"
    try:
        s3.head_object(Bucket=cfg['bucket_name'], Key=thumb_key)
    except ClientError as exc:
        if not _is_not_found(exc): raise
        original = s3.get_object(Bucket=cfg['bucket_name'], Key=asset['object_key'])['Body'].read()
        with Image.open(BytesIO(original)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ('RGB', 'L'): im = im.convert('RGB')
            elif im.mode == 'L': im = im.convert('RGB')
            im.thumbnail((480, 480), Image.Resampling.LANCZOS)
            out = BytesIO(); im.save(out, format='JPEG', quality=85, subsampling=0, optimize=True, progressive=True)
            body = out.getvalue()
        s3.put_object(Bucket=cfg['bucket_name'], Key=thumb_key, Body=body, ContentType='image/jpeg', CacheControl='private, max-age=2592000')
    url = s3.generate_presigned_url('get_object', Params={'Bucket': cfg['bucket_name'], 'Key': thumb_key}, ExpiresIn=3600)
    resp = redirect(url, code=302); resp.headers['Cache-Control'] = 'private, max-age=1800'; return resp


def _create_scoped_share():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error: return auth_error
    _ensure_order_cloud_tables(); _ensure_share_columns()
    from services.order_cloud_service import create_live_share
    payload = request.get_json(silent=True) or {}
    scope = _scope(payload.get('history_scope'))
    include_cancelled = bool(payload.get('include_cancelled'))
    try:
        result = create_live_share(payload.get('customer_key'), source_site=source_site,
                                   expires_hours=payload.get('expires_hours', 24),
                                   permanent=bool(payload.get('permanent', False)))
        token = result.pop('token'); token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        conn = get_db_connection(); cur = get_cursor(conn)
        try:
            cur.execute('UPDATE cloud_share_tokens SET history_scope=?, include_cancelled=? WHERE token_hash=?',
                        (scope, bool(include_cancelled), token_hash)); conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
        expiry = result.get('expires_at'); result['expires_at'] = expiry.isoformat() if expiry else None
        result['history_scope'] = scope; result['include_cancelled'] = include_cancelled
        result['share_url'] = request.host_url.rstrip('/') + '/share/' + token
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc: return jsonify({'ok':False,'error':str(exc)}), 400
    except Exception as exc: return jsonify({'ok':False,'error':str(exc)}), 500


def _prune_customer_scope():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error: return auth_error
    _ensure_order_cloud_tables(); _ensure_share_columns()
    payload = request.get_json(silent=True) or {}
    customer = str(payload.get('customer_key') or '').strip(); allowed = {str(x).strip() for x in (payload.get('order_numbers') or []) if str(x).strip()}
    requested_scope = _scope(payload.get('history_scope')); requested_cancelled = bool(payload.get('include_cancelled'))
    if not customer: return jsonify({'ok':False,'error':'customer_key is required'}), 400
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute("SELECT history_scope, include_cancelled FROM cloud_share_tokens WHERE customer_key=? AND status='active'", (customer,))
        for row in cur.fetchall():
            d = get_row_dict(row, cur) or {}; other_scope = _scope(d.get('history_scope'))
            if _SCOPE_RANK[other_scope] > _SCOPE_RANK[requested_scope] or (bool(d.get('include_cancelled')) and not requested_cancelled):
                return jsonify({'ok':True,'pruned':False,'reason':'broader_active_share'}), 200
        cur.execute('SELECT order_number FROM cloud_orders WHERE customer_key=?', (customer,))
        existing = [str((get_row_dict(r, cur) or {}).get('order_number') or '') for r in cur.fetchall()]
        stale = [x for x in existing if x and x not in allowed]
        for number in stale:
            cur.execute('DELETE FROM cloud_assets WHERE customer_key=? AND order_number=?', (customer, number))
            cur.execute('DELETE FROM cloud_workflow_history WHERE order_number=?', (number,))
            cur.execute('DELETE FROM cloud_workflows WHERE order_number=?', (number,))
            cur.execute('DELETE FROM cloud_orders WHERE order_number=? AND customer_key=?', (number, customer))
        conn.commit()
        with _cache_lock:
            _space_cache.pop(customer, None)
        return jsonify({'ok':True,'pruned':True,'deleted_orders':len(stale)})
    except Exception as exc:
        conn.rollback(); return jsonify({'ok':False,'error':str(exc)}), 500
    finally: conn.close()


@b2_test_bp.before_app_request
def _order_public_share_fast_interceptor():
    path = request.path or ''
    if path == '/api/order-cloud/share/create' and request.method == 'POST':
        return _create_scoped_share()
    if path == '/api/order-cloud/sync/customer-scope' and request.method == 'POST':
        return _prune_customer_scope()
    if not path.startswith('/share/') or path.startswith('/share/test'):
        return None
    parts = path.strip('/').split('/')
    if len(parts) < 2: return None
    token = parts[1]
    try:
        if len(parts) == 2 and request.method == 'GET':
            _ensure_order_cloud_tables()
            share, state = _resolve_share(token)
            if state != 'active': return _error_response(state)
            space = _load_customer_space(share.get('customer_key'))
            if not space: return Response('No hay información disponible.', 404, mimetype='text/plain')
            _filter_space(space, share)
            html = render_template('customer_share_live_fast.html', space=space, share=share, share_token=token)
            html = html.replace('img.src=img.dataset.thumb;', 'img.src=img.dataset.full;')
            html = html.replace('Las fotos grandes se cargan solo al abrirlas', 'Miniaturas rápidas · alta calidad al abrir')
            resp = Response(html, mimetype='text/html')
            resp.headers['Cache-Control'] = 'private, max-age=15'
            return resp
        if len(parts) == 4 and parts[2] in {'asset', 'image'} and request.method == 'GET':
            _share, asset, error = _asset_for_share(token, parts[3])
            if error: return error
            resp = redirect(_presigned_get(asset), code=302)
            resp.headers['Cache-Control']='private, max-age=300'
            return resp
        if len(parts) == 4 and parts[2] == 'thumb' and request.method == 'GET':
            _share, asset, error = _asset_for_share(token, parts[3])
            if error: return error
            return _thumb_redirect(asset)
    except Exception as exc:
        print(f'[WARN] ORDER public-share fast path failed: {exc}')
        return Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
    return None
