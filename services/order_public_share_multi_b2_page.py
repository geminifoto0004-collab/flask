"""Render ORDER customer share HTML from TiDB metadata only.

Hot path goals:
- public GET never runs schema migration/checks;
- token lookup is cached briefly;
- cold customer pages reuse cloud_orders.render_payload instead of rebuilding
  workflows/history from separate TiDB tables;
- one TiDB connection reads render_payload rows and asset metadata;
- the assembled customer payload is cached briefly so refreshes are Render-only.
"""
from __future__ import annotations

from datetime import datetime
import copy
import hashlib
import json
import threading
import time

from flask import Response, jsonify, render_template, request

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict

_TOKEN_TTL = 30.0
_SPACE_TTL = 20.0
_token_cache = {}
_space_cache = {}
_cache_lock = threading.RLock()


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


def _validate_share(share):
    if not share:
        return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')
    share = dict(share)
    if str(share.get('status') or '') != 'active':
        return share, Response('Este enlace ya no está disponible.', 410, mimetype='text/plain')
    expiry = _parse_expiry(share.get('expires_at'))
    if expiry and datetime.utcnow() >= expiry:
        return share, Response('Este enlace ha expirado.', 410, mimetype='text/plain')
    share['history_scope'] = str(share.get('history_scope') or 'current')
    share['include_cancelled'] = bool(share.get('include_cancelled'))
    return share, None


def _query_share(cur, token):
    token_hash = hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()
    cur.execute(
        """SELECT token_hash, customer_key, mode, status, source_site, created_at,
                  expires_at, history_scope, include_cancelled
           FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
        (token_hash,),
    )
    row = cur.fetchone()
    return get_row_dict(row, cur) if row else None


def _resolve(token):
    """Resolve a share with one indexed query; cache valid metadata briefly."""
    token = str(token or '').strip()
    if not token:
        return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')

    cached = _cache_get(_token_cache, token)
    if cached is not None:
        return _validate_share(cached)

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        share = _query_share(cur, token)
    finally:
        conn.close()

    if share:
        _cache_put(_token_cache, token, dict(share), _TOKEN_TTL)
    return _validate_share(share)


def _decode_payload(raw):
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode('utf-8')
        except Exception:
            return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _normalize_timeline(workflow, workflow_key):
    timeline = workflow.get('timeline')
    if not isinstance(timeline, list):
        timeline = workflow.get('history')
    if not isinstance(timeline, list):
        timeline = []

    normalized = []
    for pos, item in enumerate(timeline):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row['history_key'] = str(
            row.get('history_key')
            or row.get('id')
            or f"{workflow_key}:{pos}:{row.get('status') or row.get('to_status') or ''}:{row.get('action_date') or ''}"
        )
        row['workflow_key'] = workflow_key
        row['status'] = row.get('status') or row.get('to_status')
        try:
            row['sort_order'] = int(row.get('sort_order', pos) or 0)
        except (TypeError, ValueError):
            row['sort_order'] = pos
        normalized.append(row)

    normalized.sort(
        key=lambda x: (
            int(x.get('sort_order') or 0),
            str(x.get('action_date') or ''),
            str(x.get('history_key') or ''),
        )
    )
    return normalized


def _normalize_order_payload(payload, db_row):
    """Shape the already-whitelisted render_payload like the legacy public bundle."""
    order = dict(payload or {})
    order_number = str(db_row.get('order_number') or order.get('order_number') or '').strip()
    customer_key = str(db_row.get('customer_key') or order.get('customer_key') or '').strip()
    customer_name = str(db_row.get('customer_name') or order.get('customer_name') or '').strip()

    order['order_number'] = order_number
    order['customer_key'] = customer_key
    order['customer_name'] = customer_name
    order['order_status'] = order.get('order_status') or order.get('current_status') or db_row.get('order_status')
    order['order_date'] = order.get('order_date') or db_row.get('order_date')
    order['expected_delivery_date'] = (
        order.get('expected_delivery_date')
        or order.get('delivery_date')
        or db_row.get('expected_delivery_date')
    )
    for key in ('production_type', 'product_name', 'product_code', 'pattern_code', 'quantity'):
        if order.get(key) is None:
            order[key] = db_row.get(key)
    order['active'] = True
    order['source_site'] = db_row.get('source_site')
    order['updated_at'] = db_row.get('updated_at')
    order['assets'] = []

    workflows = order.get('workflows')
    if not isinstance(workflows, list):
        workflows = []
    normalized_workflows = []
    for pos, item in enumerate(workflows):
        if not isinstance(item, dict):
            continue
        wf = dict(item)
        workflow_number = str(wf.get('workflow_number') or '').strip()
        workflow_key = str(
            wf.get('workflow_key')
            or workflow_number
            or wf.get('id')
            or f'{order_number}:{pos}'
        ).strip()
        if not workflow_key:
            continue
        wf['workflow_key'] = workflow_key
        wf['workflow_number'] = workflow_number or workflow_key
        wf['order_number'] = order_number
        wf['workflow_type'] = wf.get('workflow_type') or wf.get('production_type') or wf.get('type')
        wf['status'] = wf.get('status') or wf.get('current_status')
        try:
            wf['sort_order'] = int(wf.get('sort_order', pos) or 0)
        except (TypeError, ValueError):
            wf['sort_order'] = pos
        wf['active'] = True
        wf['timeline'] = _normalize_timeline(wf, workflow_key)
        normalized_workflows.append(wf)

    normalized_workflows.sort(
        key=lambda x: (
            int(x.get('sort_order') or 0),
            str(x.get('workflow_key') or ''),
        )
    )
    order['workflows'] = normalized_workflows
    return order


def _load_legacy_bundle(customer_key, assets):
    """Rare fallback for pre-render_payload rows; normal synced rows never use it."""
    from services.order_cloud_service import get_customer_space

    space = get_customer_space(customer_key)
    if not space:
        return None
    by_order = {}
    for asset in assets:
        number = str(asset.get('order_number') or '').strip()
        if number:
            by_order.setdefault(number, []).append(asset)
    for order in space.get('orders') or []:
        order['assets'] = by_order.get(str(order.get('order_number') or '').strip(), [])

    return {
        'space': space,
        'asset_count': len(assets),
        'asset_order_count': len(by_order),
        'data_mode': 'legacy-fallback',
    }


def _load_customer_bundle_uncached(customer_key, conn):
    """Cold path: two indexed SELECTs on one TiDB connection.

    Text/workflow/history is already serialized in cloud_orders.render_payload by the
    protected sync path, so public rendering does not rebuild it from three child tables.
    """
    cur = get_cursor(conn)
    cur.execute(
        """SELECT order_number, customer_key, customer_name, order_status, order_date,
                  expected_delivery_date, production_type, product_name, product_code,
                  pattern_code, quantity, source_site, updated_at, render_payload
           FROM cloud_orders
           WHERE customer_key=? AND active=TRUE
           ORDER BY order_date DESC, order_number DESC""",
        (customer_key,),
    )
    order_rows = [get_row_dict(row, cur) for row in cur.fetchall()]
    if not order_rows:
        return None

    cur.execute(
        """SELECT a.asset_key, a.customer_key, a.order_number, a.workflow_key,
                  a.asset_type, a.sha256, a.object_key, a.content_type, a.file_size,
                  a.display_name, a.source_site, a.storage_backend, a.updated_at
           FROM cloud_assets a
           WHERE a.customer_key=? AND a.active=TRUE
           ORDER BY a.order_number, a.created_at, a.asset_key""",
        (customer_key,),
    )
    assets = [get_row_dict(row, cur) for row in cur.fetchall()]

    orders = []
    missing_payload = False
    for db_row in order_rows:
        payload = _decode_payload(db_row.get('render_payload'))
        if payload is None:
            missing_payload = True
            break
        orders.append(_normalize_order_payload(payload, db_row))

    if missing_payload:
        return _load_legacy_bundle(customer_key, assets)

    by_order = {str(order.get('order_number') or ''): order for order in orders}
    for asset in assets:
        parent = by_order.get(str(asset.get('order_number') or ''))
        if parent is not None:
            parent['assets'].append(asset)

    first = order_rows[0]
    customer = {
        'customer_key': customer_key,
        'customer_name': str(first.get('customer_name') or '').strip(),
        'updated_at': first.get('updated_at'),
    }
    bundle = {
        'space': {'customer': customer, 'orders': orders},
        'asset_count': len(assets),
        'asset_order_count': len({str(a.get('order_number') or '') for a in assets if a.get('order_number')}),
        'data_mode': 'render-payload-2-query',
    }
    return bundle


def _load_customer_bundle(customer_key, conn=None):
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        return None

    cached = _cache_get(_space_cache, customer_key)
    if cached is not None:
        return copy.deepcopy(cached)

    own_conn = conn is None
    if own_conn:
        conn = get_db_connection()
    try:
        bundle = _load_customer_bundle_uncached(customer_key, conn)
    finally:
        if own_conn and conn is not None:
            conn.close()

    if bundle:
        _cache_put(_space_cache, customer_key, bundle, _SPACE_TTL)
        return copy.deepcopy(bundle)
    return None


def _load_page_data(token):
    """Use at most one TiDB checkout for a cold public page."""
    token = str(token or '').strip()
    if not token:
        return None, None, Response('Enlace no encontrado.', 404, mimetype='text/plain')

    cached_share = _cache_get(_token_cache, token)
    if cached_share is not None:
        share, error = _validate_share(cached_share)
        if error:
            return share, None, error
        cached_bundle = _cache_get(_space_cache, str(share.get('customer_key') or '').strip())
        if cached_bundle is not None:
            return share, copy.deepcopy(cached_bundle), None

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        if cached_share is None:
            share = _query_share(cur, token)
            if share:
                _cache_put(_token_cache, token, dict(share), _TOKEN_TTL)
            share, error = _validate_share(share)
            if error:
                return share, None, error
        else:
            share, error = _validate_share(cached_share)
            if error:
                return share, None, error

        customer_key = str(share.get('customer_key') or '').strip()
        bundle = _load_customer_bundle(customer_key, conn=conn)
        if not bundle:
            return share, None, Response('No hay información disponible.', 404, mimetype='text/plain')
        return share, bundle, None
    finally:
        conn.close()


def _assets_owned_by_customer(customer_key):
    """Compatibility helper used by the safe asset-debug endpoint."""
    bundle = _load_customer_bundle(customer_key)
    if not bundle:
        return []
    assets = []
    for order in (bundle.get('space') or {}).get('orders') or []:
        assets.extend(order.get('assets') or [])
    return assets


@b2_test_bp.before_app_request
def _order_public_share_multi_b2_page():
    if request.method != 'GET':
        return None
    path = request.path or ''
    if not path.startswith('/share/') or path.startswith('/share/test'):
        return None
    parts = path.strip('/').split('/')

    if len(parts) == 3 and parts[2] == 'asset-debug':
        token = parts[1]
        try:
            share, error = _resolve(token)
            if error:
                return error
            customer_key = str(share.get('customer_key') or '').strip()
            assets = _assets_owned_by_customer(customer_key)
            bundle = _load_customer_bundle(customer_key) or {}
            orders = [
                str(o.get('order_number') or '')
                for o in ((bundle.get('space') or {}).get('orders') or [])
            ]
            by_backend = {}
            by_order = {}
            total_bytes = 0
            for asset in assets:
                backend = str(asset.get('storage_backend') or 'b2_primary')
                number = str(asset.get('order_number') or '')
                by_backend[backend] = by_backend.get(backend, 0) + 1
                by_order[number] = by_order.get(number, 0) + 1
                total_bytes += int(asset.get('file_size') or 0)
            resp = jsonify({
                'ok': True,
                'customer_key': customer_key,
                'orders': orders,
                'asset_count': len(assets),
                'asset_bytes': total_bytes,
                'by_order': by_order,
                'by_backend': by_backend,
                'page_b2_calls': 0,
                'image_mode': 'lazy-single-image-redirect',
                'data_mode': bundle.get('data_mode') or 'render-payload-2-query-cache',
            })
            resp.headers['Cache-Control'] = 'no-store'
            return resp
        except Exception as exc:
            return jsonify({'ok': False, 'error_type': type(exc).__name__}), 500

    if len(parts) != 2:
        return None

    token = parts[1]
    try:
        from services.order_public_share_fast import _filter_space

        share, bundle, error = _load_page_data(token)
        if error:
            return error

        space = bundle['space']
        _filter_space(space, share)

        html = render_template(
            'customer_share_live_fast.html',
            space=space,
            share=share,
            share_token=token,
        )

        prefix = f'/share/{token}/'
        image_prefix = prefix + 'image/'
        html = html.replace(prefix + 'thumb/', image_prefix)
        html = html.replace(prefix + 'asset/', image_prefix)
        html = html.replace('Las fotos grandes se cargan solo al abrirlas', 'Fotos optimizadas · carga bajo demanda')
        html = html.replace('Miniaturas rápidas · alta calidad al abrir', 'Fotos optimizadas · carga bajo demanda')
        html = html.replace("rootMargin:'700px 0px'", "rootMargin:'250px 0px'")

        response = Response(html, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Order-Asset-Count'] = str(bundle.get('asset_count') or 0)
        response.headers['X-Order-Asset-Orders'] = str(bundle.get('asset_order_count') or 0)
        response.headers['X-Order-Share-B2-Calls'] = '0'
        response.headers['X-Order-Image-Mode'] = 'lazy-single-image-redirect'
        response.headers['X-Order-Data-Mode'] = str(bundle.get('data_mode') or 'render-payload-2-query-cache')
        return response
    except Exception as exc:
        print(f'[WARN] ORDER share page failed: {exc}')
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
