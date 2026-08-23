"""Render ORDER public share pages from TiDB multi-B2 asset metadata directly.

This hook intentionally handles only GET /share/<token>.  It avoids relying on the
legacy asset-service monkey patch when attaching image metadata to orders.  Media byte
routes remain handled by order_cloud_multi_b2_public and therefore route each asset to
the B2 backend recorded in cloud_assets.storage_backend.
"""
from __future__ import annotations

from flask import Response, render_template, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables
from services.order_cloud_multi_b2 import list_customer_assets_multi


@b2_test_bp.before_app_request
def _order_public_share_multi_b2_page():
    if request.method != 'GET':
        return None
    path = request.path or ''
    if not path.startswith('/share/') or path.startswith('/share/test'):
        return None
    parts = path.strip('/').split('/')
    if len(parts) != 2:
        return None

    token = parts[1]
    try:
        _ensure_order_cloud_tables()
        from services.order_public_share_fast import _resolve_share, _error_response, _filter_space
        from services.order_cloud_service import get_customer_space

        share, state = _resolve_share(token)
        if state != 'active':
            return _error_response(state)

        customer_key = str(share.get('customer_key') or '').strip()
        space = get_customer_space(customer_key)
        if not space:
            return Response('No hay información disponible.', 404, mimetype='text/plain')

        # Attach assets explicitly from the multi-B2 table/query.  This is the key
        # difference from the legacy page path.
        by_order = {}
        assets = list_customer_assets_multi(customer_key)
        for asset in assets:
            order_number = str(asset.get('order_number') or '').strip()
            if order_number:
                by_order.setdefault(order_number, []).append(asset)
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
        # Detail/gallery high-quality images use the 2560 WEB object.  Cover cards
        # keep the small thumbnail first; order_share_live_refresh falls back to the
        # WEB object automatically if that thumbnail is absent.
        html = html.replace('img.src=img.dataset.thumb;', 'img.src=img.dataset.full;')
        html = html.replace(
            'Las fotos grandes se cargan solo al abrirlas',
            'Miniaturas rápidas · alta calidad al abrir',
        )
        response = Response(html, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Order-Asset-Count'] = str(len(assets))
        response.headers['X-Order-Asset-Orders'] = str(len(by_order))
        return response
    except Exception as exc:
        # Keep a concrete error marker in headers while avoiding leaking credentials
        # or object keys in the public response body.
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
