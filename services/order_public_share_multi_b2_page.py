"""Fast public ORDER share page for Render/TiDB.

Cold-path goals:
- no B2 calls while rendering HTML;
- no request-time schema checks/migrations;
- one TiDB round trip returns share header + render_payload orders + asset metadata;
- hot requests still use a short in-process cache;
- public image bytes remain Browser -> B2 through the separate signed-redirect route.
"""
from __future__ import annotations

from datetime import datetime
import copy
import hashlib
import json
import os
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
    order = dict(payload or {})
    order_number = str(db_row.get('order_number') or order.get('order_number') or '').strip()
    customer_key = str(db_row.get('row_customer_key') or order.get('customer_key') or '').strip()
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
    order['source_site'] = db_row.get('row_source_site')
    order['updated_at'] = db_row.get('row_updated_at')
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


def _legacy_bundle(customer_key, assets):
    """Fallback only for old rows that predate cloud_orders.render_payload."""
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
        'cache_state': 'MISS',
    }


def _single_roundtrip_rows(token):
    """Return share header, ORDER payloads and asset metadata in ONE TiDB execute()."""
    token_hash = hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()
    sql = """
        SELECT
            'H' AS row_kind,
            s.token_hash,
            s.customer_key AS share_customer_key,
            s.mode,
            s.status,
            s.source_site AS share_source_site,
            s.created_at,
            s.expires_at,
            s.history_scope,
            s.include_cancelled,
            NULL AS order_number,
            NULL AS row_customer_key,
            NULL AS customer_name,
            NULL AS order_status,
            NULL AS order_date,
            NULL AS expected_delivery_date,
            NULL AS production_type,
            NULL AS product_name,
            NULL AS product_code,
            NULL AS pattern_code,
            NULL AS quantity,
            NULL AS row_source_site,
            NULL AS row_updated_at,
            NULL AS render_payload,
            NULL AS asset_key,
            NULL AS workflow_key,
            NULL AS asset_type,
            NULL AS sha256,
            NULL AS object_key,
            NULL AS content_type,
            NULL AS file_size,
            NULL AS display_name,
            NULL AS storage_backend,
            NULL AS asset_created_at
        FROM cloud_share_tokens s
        WHERE s.token_hash=?

        UNION ALL

        SELECT
            'O' AS row_kind,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            o.order_number,
            o.customer_key,
            o.customer_name,
            o.order_status,
            o.order_date,
            o.expected_delivery_date,
            o.production_type,
            o.product_name,
            o.product_code,
            o.pattern_code,
            o.quantity,
            o.source_site,
            o.updated_at,
            o.render_payload,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
        FROM cloud_orders o
        INNER JOIN cloud_share_tokens s ON s.customer_key=o.customer_key
        WHERE s.token_hash=? AND o.active=TRUE

        UNION ALL

        SELECT
            'A' AS row_kind,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            a.order_number,
            a.customer_key,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            a.source_site,
            a.updated_at,
            NULL,
            a.asset_key,
            a.workflow_key,
            a.asset_type,
            a.sha256,
            a.object_key,
            a.content_type,
            a.file_size,
            a.display_name,
            a.storage_backend,
            a.created_at
        FROM cloud_assets a
        INNER JOIN cloud_share_tokens s ON s.customer_key=a.customer_key
        INNER JOIN cloud_orders o ON o.order_number=a.order_number
                                AND o.customer_key=s.customer_key
                                AND o.active=TRUE
        WHERE s.token_hash=? AND a.active=TRUE
    """

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(sql, (token_hash, token_hash, token_hash))
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def _bundle_from_rows(rows):
    header = None
    order_rows = []
    assets = []

    for row in rows or []:
        kind = str(row.get('row_kind') or '')
        if kind == 'H' and header is None:
            header = {
                'token_hash': row.get('token_hash'),
                'customer_key': row.get('share_customer_key'),
                'mode': row.get('mode'),
                'status': row.get('status'),
                'source_site': row.get('share_source_site'),
                'created_at': row.get('created_at'),
                'expires_at': row.get('expires_at'),
                'history_scope': row.get('history_scope'),
                'include_cancelled': row.get('include_cancelled'),
            }
        elif kind == 'O':
            order_rows.append(row)
        elif kind == 'A':
            assets.append({
                'asset_key': row.get('asset_key'),
                'customer_key': row.get('row_customer_key'),
                'order_number': row.get('order_number'),
                'workflow_key': row.get('workflow_key'),
                'asset_type': row.get('asset_type'),
                'sha256': row.get('sha256'),
                'object_key': row.get('object_key'),
                'content_type': row.get('content_type'),
                'file_size': row.get('file_size'),
                'display_name': row.get('display_name'),
                'source_site': row.get('row_source_site'),
                'storage_backend': row.get('storage_backend'),
                'updated_at': row.get('row_updated_at'),
                'created_at': row.get('asset_created_at'),
            })

    share, error = _validate_share(header)
    if error:
        return share, None, error

    customer_key = str(share.get('customer_key') or '').strip()
    if not order_rows:
        return share, None, Response('No hay información disponible.', 404, mimetype='text/plain')

    orders = []
    for db_row in order_rows:
        payload = _decode_payload(db_row.get('render_payload'))
        if payload is None:
            bundle = _legacy_bundle(customer_key, assets)
            return share, bundle, None if bundle else Response(
                'No hay información disponible.', 404, mimetype='text/plain'
            )
        orders.append(_normalize_order_payload(payload, db_row))

    orders.sort(
        key=lambda x: (str(x.get('order_date') or ''), str(x.get('order_number') or '')),
        reverse=True,
    )
    assets.sort(
        key=lambda x: (
            str(x.get('order_number') or ''),
            str(x.get('created_at') or ''),
            str(x.get('asset_key') or ''),
        )
    )

    by_order = {str(order.get('order_number') or ''): order for order in orders}
    for asset in assets:
        parent = by_order.get(str(asset.get('order_number') or ''))
        if parent is not None:
            parent['assets'].append(asset)

    first = order_rows[0]
    customer = {
        'customer_key': customer_key,
        'customer_name': str(first.get('customer_name') or '').strip(),
        'updated_at': first.get('row_updated_at'),
    }
    bundle = {
        'space': {'customer': customer, 'orders': orders},
        'asset_count': len(assets),
        'asset_order_count': len({str(a.get('order_number') or '') for a in assets if a.get('order_number')}),
        'data_mode': 'single-tidb-union',
        'cache_state': 'MISS',
    }
    return share, bundle, None


def _load_page_data(token):
    token = str(token or '').strip()
    if not token:
        return None, None, Response('Enlace no encontrado.', 404, mimetype='text/plain')

    cached_share = _cache_get(_token_cache, token)
    if cached_share is not None:
        share, error = _validate_share(cached_share)
        if error:
            return share, None, error
        customer_key = str(share.get('customer_key') or '').strip()
        cached_bundle = _cache_get(_space_cache, customer_key)
        if cached_bundle is not None:
            bundle = copy.deepcopy(cached_bundle)
            bundle['cache_state'] = 'HIT'
            return share, bundle, None

    rows = _single_roundtrip_rows(token)
    share, bundle, error = _bundle_from_rows(rows)
    if error:
        return share, bundle, error
    if share:
        _cache_put(_token_cache, token, dict(share), _TOKEN_TTL)
    if bundle:
        customer_key = str(share.get('customer_key') or '').strip()
        cached_bundle = copy.deepcopy(bundle)
        cached_bundle['cache_state'] = 'HIT'
        _cache_put(_space_cache, customer_key, cached_bundle, _SPACE_TTL)
    return share, bundle, None


def _load_customer_bundle(customer_key):
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        return None
    cached = _cache_get(_space_cache, customer_key)
    if cached is not None:
        bundle = copy.deepcopy(cached)
        bundle['cache_state'] = 'HIT'
        return bundle

    # Diagnostic fallback when only customer_key is known. Normal public page traffic
    # uses _load_page_data() and therefore one network round trip.
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT order_number, customer_key AS row_customer_key, customer_name,
                      order_status, order_date, expected_delivery_date, production_type,
                      product_name, product_code, pattern_code, quantity, source_site AS row_source_site,
                      updated_at AS row_updated_at, render_payload
               FROM cloud_orders
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_date DESC, order_number DESC""",
            (customer_key,),
        )
        order_rows = [get_row_dict(row, cur) for row in cur.fetchall()]
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, content_type, file_size, display_name, source_site,
                      storage_backend, updated_at, created_at
               FROM cloud_assets
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        assets = [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()

    if not order_rows:
        return None
    orders = []
    for row in order_rows:
        payload = _decode_payload(row.get('render_payload'))
        if payload is None:
            return _legacy_bundle(customer_key, assets)
        orders.append(_normalize_order_payload(payload, row))
    by_order = {str(order.get('order_number') or ''): order for order in orders}
    for asset in assets:
        parent = by_order.get(str(asset.get('order_number') or ''))
        if parent is not None:
            parent['assets'].append(asset)
    first = order_rows[0]
    return {
        'space': {
            'customer': {
                'customer_key': customer_key,
                'customer_name': str(first.get('customer_name') or ''),
                'updated_at': first.get('row_updated_at'),
            },
            'orders': orders,
        },
        'asset_count': len(assets),
        'asset_order_count': len({str(a.get('order_number') or '') for a in assets if a.get('order_number')}),
        'data_mode': 'diagnostic-2-query',
        'cache_state': 'MISS',
    }


def _assets_owned_by_customer(customer_key):
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
            share, bundle, error = _load_page_data(token)
            if error:
                return error
            assets = []
            for order in (bundle.get('space') or {}).get('orders') or []:
                assets.extend(order.get('assets') or [])
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
                'customer_key': str(share.get('customer_key') or ''),
                'orders': orders,
                'asset_count': len(assets),
                'asset_bytes': total_bytes,
                'by_order': by_order,
                'by_backend': by_backend,
                'page_b2_calls': 0,
                'image_mode': 'lazy-single-image-redirect',
                'data_mode': bundle.get('data_mode') or 'single-tidb-union',
                'cache_state': bundle.get('cache_state') or 'MISS',
                'worker_pid': os.getpid(),
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
        response.headers['X-Order-Data-Mode'] = str(bundle.get('data_mode') or 'single-tidb-union')
        response.headers['X-Order-Cache'] = str(bundle.get('cache_state') or 'MISS')
        response.headers['X-Order-Worker-PID'] = str(os.getpid())
        return response
    except Exception as exc:
        print(f'[WARN] ORDER share page failed: {exc}')
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
