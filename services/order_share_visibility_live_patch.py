"""Compatibility layer for mutable ORDER share visibility and flicker-free live refresh.

This module intentionally keeps the Render patch small.  It migrates the three
customer-facing share flags, makes the existing create/update endpoints persist them,
adds a short settings cache to the final public-page loader, and injects a DOM-patch
shim for older guest_customer.html revisions that still call location.reload().
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time

from flask import Response, jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import check_column_exists, get_cursor, get_db_connection, get_row_dict
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page

_LOCK = threading.RLock()
_SETTINGS = {}
_TTL = 60.0
_ORIG_ENSURE = _fast._ensure_share_columns
_ORIG_LOAD = _page._load_page_data
_ORIG_RESOLVE = _fast._resolve_share
_ORIG_FILTER = _fast._filter_space
_ORIG_ASSET = _fast._asset_for_share


def _ensure_columns():
    _ensure_order_cloud_tables()
    _ORIG_ENSURE()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        for name, definition in (
            ('show_pdf_pages', 'BOOLEAN NOT NULL DEFAULT TRUE'),
            ('allow_report_pdf_download', 'BOOLEAN NOT NULL DEFAULT FALSE'),
            ('show_images', 'BOOLEAN NOT NULL DEFAULT TRUE'),
        ):
            if not check_column_exists(cur, 'cloud_share_tokens', name):
                cur.execute(f'ALTER TABLE cloud_share_tokens ADD COLUMN {name} {definition}')
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def _scope(value):
    return _fast._scope(value)


def _mode(value):
    return _fast._status_filter_mode(value)


def _flags(payload):
    return (
        bool(payload.get('show_pdf_pages', True)),
        bool(payload.get('allow_report_pdf_download', False)),
        bool(payload.get('show_images', True)),
    )


def _drop_caches(token, token_hash):
    with _LOCK:
        _SETTINGS.pop(token_hash, None)
    try:
        with _fast._cache_lock:
            _fast._share_cache.pop(token, None)
    except Exception:
        pass
    try:
        from services import order_customer_share_hot_cache as hot
        from services import order_share_render_cache as html_cache
        with _page._cache_lock:
            _page._token_cache.pop(token, None)
            hot._HASH_TOKEN_CACHE.pop(token_hash, None)
        with html_cache._LOCK:
            html_cache._TOKEN_HTML.pop(token_hash, None)
    except Exception:
        pass


def _settings(token):
    token = str(token or '').strip()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = time.monotonic()
    with _LOCK:
        cached = _SETTINGS.get(token_hash)
        if cached and cached[0] > now:
            return dict(cached[1])
    _ensure_columns()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT history_scope, status_filter_mode, show_pdf_pages,
                      allow_report_pdf_download, show_images, include_cancelled
               FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
            (token_hash,),
        )
        row = cur.fetchone(); data = get_row_dict(row, cur) if row else {}
    finally:
        conn.close()
    result = {
        'history_scope': _scope(data.get('history_scope')),
        'status_filter_mode': _mode(data.get('status_filter_mode')),
        'show_pdf_pages': True if data.get('show_pdf_pages') is None else bool(data.get('show_pdf_pages')),
        'allow_report_pdf_download': bool(data.get('allow_report_pdf_download')),
        'show_images': True if data.get('show_images') is None else bool(data.get('show_images')),
        'include_cancelled': False,
    }
    with _LOCK:
        _SETTINGS[token_hash] = (now + _TTL, dict(result))
    return result


def _strip_images(bundle):
    value = copy.deepcopy(bundle)
    for order in (((value or {}).get('space') or {}).get('orders') or []):
        if isinstance(order, dict):
            order['assets'] = []
    return value


def _load_with_settings(token):
    share, bundle, error = _ORIG_LOAD(token)
    if error or not share:
        return share, bundle, error
    try:
        share = dict(share); share.update(_settings(token))
        if share.get('show_images') is False and bundle:
            bundle = _strip_images(bundle)
    except Exception as exc:
        print(f'[WARN] ORDER mutable share settings fallback: {type(exc).__name__}: {exc}')
    return share, bundle, error


def _resolve_with_settings(token):
    share, state = _ORIG_RESOLVE(token)
    if share:
        try:
            share = dict(share); share.update(_settings(token))
        except Exception:
            pass
    return share, state


def _filter_with_settings(space, share):
    result = _ORIG_FILTER(space, share)
    target = result if isinstance(result, dict) else space
    if (share or {}).get('show_images') is False:
        for order in ((target or {}).get('orders') or []):
            if isinstance(order, dict):
                order['assets'] = []
    elif (share or {}).get('show_pdf_pages') is False:
        for order in ((target or {}).get('orders') or []):
            if isinstance(order, dict):
                order['assets'] = [a for a in (order.get('assets') or []) if str((a or {}).get('asset_kind') or '').upper() != 'PDF_PAGE']
    return result


def _asset_with_settings(token, asset_key):
    share, asset, error = _ORIG_ASSET(token, asset_key)
    if error or not share:
        return share, asset, error
    try:
        share = dict(share); share.update(_settings(token))
        if share.get('show_images') is False:
            return share, None, (Response('Not found', 404, mimetype='text/plain'))
        if share.get('show_pdf_pages') is False and str((asset or {}).get('asset_kind') or '').upper() == 'PDF_PAGE':
            return share, None, (Response('Not found', 404, mimetype='text/plain'))
    except Exception:
        pass
    return share, asset, error


def _create_scoped_share():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error: return auth_error
    try:
        _ensure_columns()
        from services.order_cloud_service import create_live_share
        payload = request.get_json(silent=True) or {}
        scope = _scope(payload.get('history_scope')); mode = _mode(payload.get('status_filter_mode'))
        show_pdf, allow_report, show_images = _flags(payload)
        result = create_live_share(
            payload.get('customer_key'), source_site=source_site,
            expires_hours=payload.get('expires_hours', 24), permanent=bool(payload.get('permanent', False)),
            history_scope=scope, include_cancelled=False, status_filter_mode=mode,
            show_pdf_pages=show_pdf, allow_report_pdf_download=allow_report, show_images=show_images,
        )
        token = result.pop('token'); token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        expiry = result.get('expires_at'); result['expires_at'] = expiry.isoformat() if expiry else None
        result.update({'history_scope':scope, 'status_filter_mode':mode, 'show_pdf_pages':show_pdf,
                       'allow_report_pdf_download':allow_report, 'show_images':show_images,
                       'include_cancelled':False, 'share_url':request.host_url.rstrip('/') + '/share/' + token})
        _drop_caches(token, token_hash)
        return jsonify({'ok':True, 'result':result})
    except ValueError as exc:
        return jsonify({'ok':False, 'error':str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok':False, 'error':str(exc)}), 500


def _update_share_settings():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error: return auth_error
    try:
        _ensure_columns()
        payload = request.get_json(silent=True) or {}
        token = str(payload.get('token') or '').strip()
        if not token: return jsonify({'ok':False, 'error':'token is required'}), 400
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        scope = _scope(payload.get('history_scope')); mode = _mode(payload.get('status_filter_mode'))
        show_pdf, allow_report, show_images = _flags(payload)
        conn = get_db_connection(); cur = get_cursor(conn)
        try:
            cur.execute("SELECT customer_key FROM cloud_share_tokens WHERE token_hash=? AND status='active' LIMIT 1", (token_hash,))
            row = cur.fetchone()
            if not row: return jsonify({'ok':False, 'error':'active share not found'}), 404
            customer_key = str((get_row_dict(row, cur) or {}).get('customer_key') or '')
            cur.execute(
                """UPDATE cloud_share_tokens SET history_scope=?, status_filter_mode=?,
                          show_pdf_pages=?, allow_report_pdf_download=?, show_images=?, include_cancelled=FALSE
                   WHERE token_hash=? AND status='active'""",
                (scope, mode, show_pdf, allow_report, show_images, token_hash),
            ); conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
        _drop_caches(token, token_hash)
        return jsonify({'ok':True, 'result':{'share_id':token_hash, 'customer_key':customer_key,
            'history_scope':scope, 'status_filter_mode':mode, 'show_pdf_pages':show_pdf,
            'allow_report_pdf_download':allow_report, 'show_images':show_images, 'include_cancelled':False}})
    except Exception as exc:
        return jsonify({'ok':False, 'error':str(exc)}), 500


# The existing interceptor resolves these names at request time, so replacing the
# functions is enough; no duplicate Flask routes are registered.
_fast._ensure_share_columns = _ensure_columns
_fast._create_scoped_share = _create_scoped_share
_fast._update_share_settings = _update_share_settings
_fast._resolve_share = _resolve_with_settings
_fast._filter_space = _filter_with_settings
_fast._asset_for_share = _asset_with_settings
_page._load_page_data = _load_with_settings


_LIVE_PATCH_JS = r"""
<script id="trackingGuestDomPatchV2">
(function(){
 if(window.__trackingGuestDomPatchV2||typeof fetch!=='function'||typeof DOMParser==='undefined')return;
 window.__trackingGuestDomPatchV2=1;
 const nativeFetch=window.fetch.bind(window);
 const baseline='<!doctype html>'+document.documentElement.outerHTML;
 function isAuto(init){try{const h=new Headers((init||{}).headers||{});return h.get('X-Guest-Auto-Refresh')==='1';}catch(_){return false;}}
 function sig(n){if(!n)return'';const c=n.cloneNode(true);c.hidden=false;c.removeAttribute('style');return c.outerHTML.replace(/\s+/g,' ').trim();}
 function loadImg(card){const i=card&&card.querySelector('.guest-cover-slide img');if(i&&!i.getAttribute('src')&&i.dataset.src){i.src=i.dataset.src;i.removeAttribute('data-src');}}
 function bindCarousel(root){(root||document).querySelectorAll('[data-guest-carousel]').forEach(function(t){
   if(t.dataset.livePatchBound==='1')return;t.dataset.livePatchBound='1';const cover=t.closest('.guest-cover');const count=Math.max(1,Number(t.dataset.imageCount||1));if(!cover||count<=1)return;
   function show(idx){idx=Math.max(0,Math.min(count-1,idx));const imgs=t.querySelectorAll('img');const img=imgs[idx];if(img&&!img.getAttribute('src')&&img.dataset.src){img.src=img.dataset.src;img.removeAttribute('data-src');}t.scrollTo({left:idx*(t.clientWidth||1),behavior:'smooth'});const c=cover.querySelector('[data-guest-image-count]');if(c)c.textContent=(idx+1)+'/'+count;cover.querySelectorAll('[data-guest-dot]').forEach(d=>d.classList.toggle('active',Number(d.dataset.guestDot)===idx));}
   cover.querySelectorAll('[data-guest-nav]').forEach(function(b){b.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();const idx=Math.round(t.scrollLeft/(t.clientWidth||1))+Number(b.dataset.guestNav||0);show(idx);});});
 });}
 function rebuildFilters(){const row=document.querySelector('[data-guest-status-filters]');if(!row)return;const cards=Array.from(document.querySelectorAll('[data-guest-card]'));const active=row.querySelector('.guest-status-chip.active')?.dataset.guestStatusFilter||'all';cards.forEach(loadImg);row.querySelectorAll('[data-guest-status-filter]').forEach(function(b){if(String(b.dataset.guestStatusFilter||'')===active)b.classList.add('active');});}
 function patch(next){['guestStatusFilterMode','guestShowImages','guestShowPdfPages','guestAllowReportPdfDownload'].forEach(function(k){if(next.body&&Object.prototype.hasOwnProperty.call(next.body.dataset,k))document.body.dataset[k]=next.body.dataset[k];});
   const cc=document.getElementById('guestShareControls'),nc=next.getElementById('guestShareControls');if(cc&&nc&&cc.innerHTML!==nc.innerHTML)cc.innerHTML=nc.innerHTML;
   const cg=document.getElementById('guestGrid'),ng=next.getElementById('guestGrid');let changed=false;
   if(!cg||!ng){const ca=document.getElementById('guestOrderArea'),na=next.getElementById('guestOrderArea');if(ca&&na&&ca.innerHTML!==na.innerHTML){ca.replaceWith(document.importNode(na,true));changed=true;}}
   else{const old=new Map(Array.from(cg.querySelectorAll('[data-guest-card]')).map(c=>[String(c.dataset.guestOrderKey||''),c]));const incoming=Array.from(ng.querySelectorAll('[data-guest-card]'));const keys=new Set(incoming.map(c=>String(c.dataset.guestOrderKey||'')));old.forEach((c,k)=>{if(!keys.has(k)){c.remove();changed=true;}});incoming.forEach(function(n){const k=String(n.dataset.guestOrderKey||'');let c=old.get(k);if(!c){c=document.importNode(n,true);c.style.opacity='0';cg.appendChild(c);changed=true;requestAnimationFrame(()=>{c.style.transition='opacity 160ms ease';c.style.opacity='1';});}else if(sig(c)!==sig(n)){const r=document.importNode(n,true);r.style.opacity='0';c.replaceWith(r);c=r;changed=true;requestAnimationFrame(()=>{r.style.transition='opacity 160ms ease';r.style.opacity='1';});}cg.appendChild(c);});}
   if(changed){bindCarousel(document);rebuildFilters();document.dispatchEvent(new CustomEvent('tracking:guestcardsupdated',{detail:{cardsChanged:true}}));if(typeof window.applyTrackingLanguage==='function')window.applyTrackingLanguage(document);}
 }
 window.fetch=function(input,init){if(!isAuto(init))return nativeFetch(input,init);return nativeFetch(input,init).then(async function(resp){try{if(resp.ok){const text=await resp.clone().text();patch(new DOMParser().parseFromString(text,'text/html'));}}catch(_){}return new Response(baseline,{status:resp.status,statusText:resp.statusText,headers:resp.headers});});};
 bindCarousel(document);
})();
</script>
"""


@b2_test_bp.after_app_request
def _inject_live_dom_patch(response):
    try:
        path = request.path or ''
        parts = path.strip('/').split('/')
        ctype = str(response.headers.get('Content-Type') or '').lower()
        if request.method != 'GET' or response.status_code != 200 or 'text/html' not in ctype:
            return response
        html = response.get_data(as_text=True)
        changed = False
        # The fast Render page historically rewrote thumbnail loading back to the full image.
        if 'img.src=img.dataset.full;' in html:
            html = html.replace('img.src=img.dataset.full;', 'img.src=img.dataset.thumb;')
            changed = True
        # Old guest template grouping used an over-broad "confirmed = everything else" bucket.
        replacements = (
            ("{key:'unconfirmed', zh:'未确认', es:'Sin confirmar', statuses:new Set(['QUOTE_CONFIRMING','DRAFT_CONFIRMING','SAMPLE_CONFIRMING'])}",
             "{key:'pending', zh:'待确认', es:'Por confirmar', statuses:new Set(['QUOTE_CONFIRMING','DRAFT_CONFIRMING','SAMPLE_CONFIRMING'])}"),
            ("{key:'confirmed', zh:'已确认', es:'Confirmado', statuses:null}",
             "{key:'processing', zh:'处理中', es:'En proceso', statuses:null}"),
            ("{key:'done', zh:'已完成', es:'Completado', statuses:new Set(['COMPLETED','ALL_SHIPPED','SHIPPED'])}",
             "{key:'ended', zh:'已结束', es:'Finalizados', statuses:new Set(['COMPLETED','ALL_SHIPPED','SHIPPED'])}"),
            ("return 'unconfirmed';", "return 'pending';"),
            ("return 'done';", "return 'ended';"),
            ("return 'confirmed';", "return 'processing';"),
        )
        for before, after in replacements:
            if before in html:
                html = html.replace(before, after)
                changed = True
        # Inject flicker-free DOM refresh only when the old reload implementation is present.
        if 'data-guest-card' in html and 'tracking:guestcardsupdated' not in html and 'trackingGuestDomPatchV2' not in html and '</body>' in html:
            html = html.replace('</body>', _LIVE_PATCH_JS + '</body>', 1)
            changed = True
        if changed:
            response.set_data(html)
            response.headers.pop('Content-Length', None)
    except Exception as exc:
        print(f'[WARN] guest live DOM compatibility patch skipped: {type(exc).__name__}: {exc}')
    return response


try:
    _ensure_columns()
except Exception as exc:
    print(f'[WARN] ORDER share visibility migration deferred: {type(exc).__name__}: {exc}')
