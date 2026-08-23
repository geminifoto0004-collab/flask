"""Render ORDER customer share HTML from TiDB metadata only.

The first page request never talks to B2 and never creates per-image signed URLs.
Render reads the customer's safe text + asset metadata from TiDB, renders HTML once,
and returns it immediately.  All image attributes point to the same lazy
/share/<token>/image/<asset_key> URL; that endpoint performs authorization and a 302 to
B2 only when the browser actually needs that image.
"""
from __future__ import annotations

from datetime import datetime
import hashlib

from flask import Response, jsonify, render_template, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables
from database import get_cursor, get_db_connection, get_row_dict


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
    """Resolve a share with one indexed TiDB query and no request-time migration."""
    token = str(token or '').strip()
    if not token:
        return None, Response('Enlace no encontrado.', 404, mimetype='text/plain')
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


def _assets_owned_by_customer(customer_key):
    """One indexed metadata query; no B2 calls and no storage schema migration."""
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT a.asset_key, a.customer_key, a.order_number, a.workflow_key,
                      a.asset_type, a.sha256, a.object_key, a.content_type, a.file_size,
                      a.display_name, a.source_site, a.storage_backend, a.updated_at
               FROM cloud_assets a
               INNER JOIN cloud_orders o ON o.order_number=a.order_number
               WHERE o.customer_key=? AND o.active=TRUE AND a.active=TRUE
               ORDER BY a.order_number, a.created_at, a.asset_key""",
            (customer_key,),
        )
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


@b2_test_bp.before_app_request
def _order_public_share_multi_b2_page():
    if request.method != 'GET':
        return None
    path = request.path or ''
    if not path.startswith('/share/') or path.startswith('/share/test'):
        return None
    parts = path.strip('/').split('/')

    # Safe diagnostic: token authorizes only this customer's relationship counts.
    if len(parts) == 3 and parts[2] == 'asset-debug':
        token = parts[1]
        try:
            _ensure_order_cloud_tables()
            share, error = _resolve(token)
            if error:
                return error
            customer_key = str(share.get('customer_key') or '').strip()
            assets = _assets_owned_by_customer(customer_key)
            conn = get_db_connection()
            cur = get_cursor(conn)
            try:
                cur.execute(
                    'SELECT order_number FROM cloud_orders '
                    'WHERE customer_key=? AND active=TRUE ORDER BY order_number',
                    (customer_key,),
                )
                orders = [str((get_row_dict(r, cur) or {}).get('order_number') or '') for r in cur.fetchall()]
            finally:
                conn.close()
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
        from services.order_cloud_service import get_customer_space

        share, error = _resolve(token)
        if error:
            return error
        customer_key = str(share.get('customer_key') or '').strip()

        # get_customer_space is the bounded-query implementation registered by
        # services.__init__: customer/orders/workflows/history are fetched in four
        # indexed queries, then grouped in Python.
        space = get_customer_space(customer_key)
        if not space:
            return Response('No hay información disponible.', 404, mimetype='text/plain')

        assets = _assets_owned_by_customer(customer_key)
        by_order = {}
        for asset in assets:
            number = str(asset.get('order_number') or '').strip()
            if number:
                by_order.setdefault(number, []).append(asset)
        for order in space.get('orders') or []:
            number = str(order.get('order_number') or '').strip()
            order['assets'] = by_order.get(number, [])

        _filter_space(space, share)
        html = render_template(
            'customer_share_live_fast.html',
            space=space,
            share=share,
            share_token=token,
        )

        # The existing template still has historical data-thumb/data-full names. Make
        # every attribute use the exact same stable application URL so the browser can
        # reuse its cache; no physical thumbnail object exists in the formal design.
        prefix = f'/share/{token}/'
        image_prefix = prefix + 'image/'
        html = html.replace(prefix + 'thumb/', image_prefix)
        html = html.replace(prefix + 'asset/', image_prefix)
        html = html.replace(
            'Las fotos grandes se cargan solo al abrirlas',
            'Fotos optimizadas · carga bajo demanda',
        )
        html = html.replace(
            'Miniaturas rápidas · alta calidad al abrir',
            'Fotos optimizadas · carga bajo demanda',
        )
        # Load fewer off-screen covers in advance. Detail still loads current +/- 1.
        html = html.replace("rootMargin:'700px 0px'", "rootMargin:'250px 0px'")

        response = Response(html, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Order-Asset-Count'] = str(len(assets))
        response.headers['X-Order-Asset-Orders'] = str(len(by_order))
        response.headers['X-Order-Share-B2-Calls'] = '0'
        response.headers['X-Order-Image-Mode'] = 'lazy-single-image-redirect'
        return response
    except Exception as exc:
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
