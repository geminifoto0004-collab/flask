"""Render ORDER public share pages from TiDB multi-B2 asset metadata directly.

Asset ownership is resolved through cloud_orders.order_number -> customer_key. The
customer_key copied into cloud_assets is treated as denormalized metadata only, so an
old/mismatched asset customer key cannot hide otherwise valid images from a share.

Performance rule:
- gallery/detail browsing uses the already-published 480px thumbnail directly from a
  short-lived B2 signed URL (signing itself does not call B2);
- 2560px WEB data is loaded only when the user opens the full-screen viewer;
- if a direct thumbnail fails, the browser falls back to the token-protected Render
  media route, which can in turn fall back to the WEB object.
"""
from __future__ import annotations

from html import escape

from flask import Response, jsonify, render_template, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_multi_b2 import presigned_get_for_asset


def _assets_owned_by_customer(customer_key):
    conn = get_db_connection(); cur = get_cursor(conn)
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


def _resolve(token):
    from services.order_public_share_fast import _resolve_share, _error_response
    share, state = _resolve_share(token)
    if state != 'active':
        return share, _error_response(state)
    return share, None


def _apply_fast_thumbnail_urls(html, token, assets):
    """Replace only thumbnail URLs with direct B2 signed URLs.

    Full/2560 URLs intentionally remain token-protected Render URLs and therefore are
    fetched only when the full-screen viewer is opened.  Each direct thumbnail keeps a
    Render fallback URL in a data attribute for reliability.
    """
    for asset in assets:
        asset_key = str(asset.get('asset_key') or '').strip()
        sha = str(asset.get('sha256') or '').strip().lower()
        if not asset_key or len(sha) != 64:
            continue
        thumb_key = f'order-cloud/thumbs/{sha[:2]}/{sha}.jpg'
        try:
            direct_thumb = presigned_get_for_asset(asset, seconds=3600, object_key=thumb_key)
        except Exception:
            continue

        proxy_thumb = f'/share/{token}/thumb/{asset_key}'
        signed = escape(direct_thumb, quote=True)
        proxy = escape(proxy_thumb, quote=True)

        html = html.replace(
            f'data-src="{proxy_thumb}"',
            f'data-src="{signed}" data-proxy-src="{proxy}"',
        )
        html = html.replace(
            f'data-thumb="{proxy_thumb}"',
            f'data-thumb="{signed}" data-proxy-thumb="{proxy}"',
        )

    # Install the fallback handler before body images start lazy-loading.  It only
    # handles direct-thumbnail failures; full-size WEB image handling stays unchanged.
    fallback_script = r'''<script id="order-direct-thumb-fallback">
window.addEventListener('error',function(ev){
  var img=ev.target;
  if(!img||img.tagName!=='IMG'||img.dataset.orderFallbackDone==='1')return;
  var proxy=img.dataset.proxySrc||img.dataset.proxyThumb||'';
  if(!proxy)return;
  img.dataset.orderFallbackDone='1';
  img.src=proxy;
},true);
</script>'''
    if 'order-direct-thumb-fallback' not in html:
        if '</head>' in html:
            html = html.replace('</head>', fallback_script + '</head>', 1)
        else:
            html = fallback_script + html
    return html


@b2_test_bp.before_app_request
def _order_public_share_multi_b2_page():
    if request.method != 'GET':
        return None
    path = request.path or ''
    if not path.startswith('/share/') or path.startswith('/share/test'):
        return None
    parts = path.strip('/').split('/')

    # Safe live diagnostic: token authorizes only this customer's relationship counts.
    if len(parts) == 3 and parts[2] == 'asset-debug':
        token = parts[1]
        try:
            _ensure_order_cloud_tables()
            share, error = _resolve(token)
            if error: return error
            customer_key = str(share.get('customer_key') or '').strip()
            assets = _assets_owned_by_customer(customer_key)
            conn = get_db_connection(); cur = get_cursor(conn)
            try:
                cur.execute('SELECT order_number FROM cloud_orders WHERE customer_key=? AND active=TRUE ORDER BY order_number', (customer_key,))
                orders = [str((get_row_dict(r, cur) or {}).get('order_number') or '') for r in cur.fetchall()]
            finally:
                conn.close()
            by_backend = {}
            by_order = {}
            for a in assets:
                b = str(a.get('storage_backend') or 'b2_primary')
                n = str(a.get('order_number') or '')
                by_backend[b] = by_backend.get(b, 0) + 1
                by_order[n] = by_order.get(n, 0) + 1
            resp = jsonify({'ok': True, 'customer_key': customer_key, 'orders': orders,
                            'asset_count': len(assets), 'by_order': by_order,
                            'by_backend': by_backend})
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
        if error: return error
        customer_key = str(share.get('customer_key') or '').strip()
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
        html = render_template('customer_share_live_fast.html', space=space, share=share, share_token=token)

        # Keep the template's original behaviour: gallery and detail views load 480px
        # thumbnails.  Do NOT replace detail thumbnails with 2560px images here.
        html = html.replace('Las fotos grandes se cargan solo al abrirlas', 'Miniaturas rápidas · alta calidad al abrir')
        html = _apply_fast_thumbnail_urls(html, token, assets)

        response = Response(html, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Order-Asset-Count'] = str(len(assets))
        response.headers['X-Order-Asset-Orders'] = str(len(by_order))
        response.headers['X-Order-Thumb-Mode'] = 'direct-b2-signed-with-render-fallback'
        return response
    except Exception as exc:
        response = Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
        response.headers['X-Order-Share-Error'] = type(exc).__name__
        return response
