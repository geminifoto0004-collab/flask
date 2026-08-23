"""Keep URL-first ORDER share pages visually in sync with background image publishing.

The share URL is intentionally returned before images finish uploading.  A browser may
therefore render the page while TiDB still has zero cloud_assets rows.  This extension
adds a tiny TiDB-only asset-state endpoint and injects client-side refresh/fallback
logic into the public share HTML:

- no B2 HEAD is used;
- when the first image metadata appears, an already-open zero-image page reloads;
- later batches reload only after the asset count has been stable briefly;
- a failed 480px thumbnail transparently falls back to the 2560px WEB asset;
- the share HTML itself is no-store so reopening the same URL cannot retain a stale
  zero-image document.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp
from services.order_cloud_multi_b2 import list_customer_assets_multi


def _share_parts():
    path = request.path or ''
    if not path.startswith('/share/'):
        return []
    return path.strip('/').split('/')


@b2_test_bp.before_app_request
def _order_share_asset_state():
    parts = _share_parts()
    if request.method != 'GET' or len(parts) != 3 or parts[2] != 'asset-state':
        return None

    # Reuse the same token/customer authorization as the normal public share page.
    from services.order_public_share_fast import _resolve_share, _error_response

    token = parts[1]
    share, state = _resolve_share(token)
    if state != 'active':
        return _error_response(state)

    assets = [
        item for item in list_customer_assets_multi(share.get('customer_key'))
        if str(item.get('asset_type') or '').upper() == 'IMAGE'
    ]
    by_order = {}
    for item in assets:
        number = str(item.get('order_number') or '')
        if number:
            by_order[number] = by_order.get(number, 0) + 1

    response = jsonify({
        'ok': True,
        'asset_count': len(assets),
        'orders_with_images': len(by_order),
        'by_order': by_order,
    })
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


_REFRESH_SCRIPT = r"""
<script id="order-live-image-refresh">
(function(){
  function wireCoverFallback(img){
    if(!img || img.dataset.fullFallbackWired==='1') return;
    img.dataset.fullFallbackWired='1';
    img.addEventListener('error', function(){
      if(this.dataset.triedFull==='1') return;
      const src=this.dataset.src||this.getAttribute('src')||'';
      const full=src.replace('/thumb/','/asset/');
      if(full && full!==src){
        this.dataset.triedFull='1';
        this.src=full;
      }
    });
  }
  document.querySelectorAll('.cover-img').forEach(wireCoverFallback);

  const path=location.pathname.replace(/\/$/,'');
  const stateUrl=path+'/asset-state';
  let rendered=document.querySelectorAll('.detail-img').length;
  let seen=rendered;
  let changedAt=0;
  const started=Date.now();
  const maxMs=5*60*1000;

  async function poll(){
    if(Date.now()-started>maxMs) return;
    try{
      const r=await fetch(stateUrl,{cache:'no-store',credentials:'same-origin'});
      if(r.ok){
        const data=await r.json();
        const count=Number(data.asset_count||0);
        if(count>rendered){
          // URL-first: show the first published image as soon as it exists.
          if(rendered===0){ location.reload(); return; }
          // For later batches, wait until the count is stable for 10 seconds so a
          // 100-image publish does not make the browser reload after every few files.
          if(count!==seen){ seen=count; changedAt=Date.now(); }
          else if(changedAt && Date.now()-changedAt>=10000){ location.reload(); return; }
        }else{
          seen=count;
          changedAt=0;
        }
      }
    }catch(_e){}
    setTimeout(poll,5000);
  }
  setTimeout(poll,3000);
})();
</script>
"""


@b2_test_bp.after_app_request
def _inject_order_share_live_refresh(response):
    try:
        parts = _share_parts()
        if request.method != 'GET' or len(parts) != 2:
            return response
        if response.status_code != 200 or not response.mimetype.startswith('text/html'):
            return response
        html = response.get_data(as_text=True)
        if 'id="profileView"' not in html or 'order-live-image-refresh' in html:
            return response
        if '</body>' in html:
            html = html.replace('</body>', _REFRESH_SCRIPT + '</body>', 1)
        else:
            html += _REFRESH_SCRIPT
        response.set_data(html)
        response.headers['Cache-Control'] = 'no-store, max-age=0, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    except Exception:
        # Never break the customer page because this is only a live-refresh enhancer.
        return response
    return response
