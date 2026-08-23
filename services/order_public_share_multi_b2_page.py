"""Render ORDER customer share HTML from TiDB metadata only.

Hot path goals:
- no B2 calls while rendering the page;
- token lookup is cached briefly;
- customer/orders/workflows/history/assets are fetched in parallel instead of five
  sequential Render -> TiDB round trips;
- the assembled customer payload is cached briefly so refreshes are near-Render-only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import copy
import hashlib
import threading
import time

from flask import Response, jsonify, render_template, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables
from database import get_cursor, get_db_connection, get_row_dict

_TOKEN_TTL = 30.0
_SPACE_TTL = 20.0
_token_cache = {}
_space_cache = {}
_cache_lock = threading.RLock()
_page_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix='order-share-tidb')


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


def _resolve(token):
    """Resolve a share with one indexed query; cache valid metadata briefly."""
    token = str(token or '').strip()
    if not token:
        return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')

    cached = _cache_get(_token_cache, token)
    if cached is not None:
        share = dict(cached)
    else:
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT token_hash, customer_key, mode, status, source_site, created_at,
                          expires_at, history_scope, include_cancelled
                   FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
                (token_hash,),
            )
            row = cur.fetchone()
            share = get_row_dict(row, cur) if row else None
        finally:
            conn.close()
        if share:
            _cache_put(_token_cache, token, dict(share), _TOKEN_TTL)

    if not share:
        return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')
    if str(share.get('status') or '') != 'active':
        return share, Response('Este enlace ya no está disponible.', 410, mimetype='text/plain')
    expiry = _parse_expiry(share.get('expires_at'))
    if expiry and datetime.utcnow() >= expiry:
        return share, Response('Este enlace ha expirado.', 410, mimetype='text/plain')
    share['history_scope'] = str(share.get('history_scope') or 'current')
    share['include_cancelled'] = bool(share.get('include_cancelled'))
    return share, None


def _query_all(sql, params):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(sql, params)
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def _load_customer_bundle(customer_key):
    """Fetch all safe public-share metadata in one parallel TiDB wave."""
    customer_key = str(customer_key or '').strip()
    cached = _cache_get(_space_cache, customer_key)
    if cached is not None:
        return copy.deepcopy(cached)

    sql_customer = (
        "SELECT customer_key, customer_name, updated_at "
        "FROM cloud_customers WHERE customer_key=? AND active=TRUE LIMIT 1"
    )
    sql_orders = """SELECT order_number, customer_key, customer_name, order_status, order_date,
                           expected_delivery_date, production_type, product_name, product_code,
                           pattern_code, quantity, active, source_site, updated_at
                    FROM cloud_orders
                    WHERE customer_key=? AND active=TRUE
                    ORDER BY order_date DESC, order_number DESC"""
    sql_workflows = """SELECT w.workflow_key, w.workflow_number, w.order_number, w.workflow_type,
                              w.status, w.production_type, w.product_name, w.product_code,
                              w.quantity, w.expected_delivery_date, w.last_status_change_date,
                              w.draft_date, w.sort_order, w.active, w.updated_at
                       FROM cloud_workflows w
                       INNER JOIN cloud_orders o ON o.order_number=w.order_number
                       WHERE o.customer_key=? AND o.active=TRUE AND w.active=TRUE
                       ORDER BY w.order_number, w.sort_order, w.workflow_key"""
    sql_history = """SELECT h.history_key, h.workflow_key, h.order_number, h.status,
                            h.action_date, h.sort_order
                     FROM cloud_workflow_history h
                     INNER JOIN cloud_orders o ON o.order_number=h.order_number
                     WHERE o.customer_key=? AND o.active=TRUE AND h.active=TRUE
                     ORDER BY h.order_number, h.workflow_key, h.sort_order,
                              h.action_date, h.history_key"""
    sql_assets = """SELECT a.asset_key, a.customer_key, a.order_number, a.workflow_key,
                           a.asset_type, a.sha256, a.object_key, a.content_type, a.file_size,
                           a.display_name, a.source_site, a.storage_backend, a.updated_at
                    FROM cloud_assets a
                    INNER JOIN cloud_orders o ON o.order_number=a.order_number
                    WHERE o.customer_key=? AND o.active=TRUE AND a.active=TRUE
                    ORDER BY a.order_number, a.created_at, a.asset_key"""

    futures = [
        _page_executor.submit(_query_all, sql_customer, (customer_key,)),
        _page_executor.submit(_query_all, sql_orders, (customer_key,)),
        _page_executor.submit(_query_all, sql_workflows, (customer_key,)),
        _page_executor.submit(_query_all, sql_history, (customer_key,)),
        _page_executor.submit(_query_all, sql_assets, (customer_key,)),
    ]
    customer_rows, orders, workflows, history, assets = [f.result() for f in futures]
    if not customer_rows:
        return None

    customer = customer_rows[0]
    by_order = {str(order.get('order_number') or ''): order for order in orders}
    for order in orders:
        order['workflows'] = []
        order['assets'] = []

    by_workflow = {}
    for wf in workflows:
        wf['timeline'] = []
        wf_key = str(wf.get('workflow_key') or '')
        if wf_key:
            by_workflow[wf_key] = wf
        parent = by_order.get(str(wf.get('order_number') or ''))
        if parent is not None:
            parent['workflows'].append(wf)

    for item in history:
        parent = by_workflow.get(str(item.get('workflow_key') or ''))
        if parent is not None:
            parent['timeline'].append(item)

    for asset in assets:
        parent = by_order.get(str(asset.get('order_number') or ''))
        if parent is not None:
            parent['assets'].append(asset)

    bundle = {
        'space': {'customer': customer, 'orders': orders},
        'asset_count': len(assets),
        'asset_order_count': len({str(a.get('order_number') or '') for a in assets if a.get('order_number')}),
    }
    _cache_put(_space_cache, customer_key, bundle, _SPACE_TTL)
    return copy.deepcopy(bundle)


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
            _ensure_order_cloud_tables()
            share, error = _resolve(token)
            if error:
                return error
            customer_key = str(share.get('customer_key') or '').strip()
            assets = _assets_owned_by_customer(customer_key)
            bundle = _load_customer_bundle(customer_key) or {}
            orders = [str(o.get('order_number') or '') for o in ((bundle.get('space') or {}).get('orders') or [])]
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
                'data_mode': 'parallel-tidb-cache',
            })
            resp.headers['Cache-Control'] = 'no-store'
            return resp
        except Exception as exc:
            return jsonify({'ok': False, 'error_type': type(exc).__name__}), 500

    if len(parts) != 2:
        return None

    token = parts[1]
    try:
        _ensure_order_cloud_tables()
        from services.order_public_share_fast import _filter_space

        share, error = _resolve(token)
        if error:
            return error
        customer_key = str(share.get('customer_key') or '').strip()

        bundle = _load_customer_bundle(customer_key)
        if not bundle:
            return Response('No hay información disponible.', 404, mimetype='text/plain')
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
        response.headers['X-Order-Data-Mode'] = 'parallel-tidb-cache'
        return response
    except Exception as exc:
        print(f'[WARN] ORDER share page failed: {exc}')
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
