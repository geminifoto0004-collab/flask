"""Pre-render cache for ORDER public share HTML.

Snapshot/token caches keep TiDB off the hot path, but rendering a large Jinja page can
still be preempted by a small Render instance. Cache the rendered template with a
fixed token placeholder so the normal public request only substitutes its raw token.

The cache stores HTML only. It does not store image bytes, B2 credentials, local
paths, phone/payment/deposit data, or raw share tokens.
"""
from __future__ import annotations

import copy
import hashlib
import threading

from blueprints.b2_test_bp import b2_test_bp
from services import order_cloud_service as _cloud_service
from services import order_customer_share_hot_cache as _hot
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page

_TEMPLATE = "customer_share_live_fast.html"
_TOKEN_PLACEHOLDER = "__ORDER_SHARE_TOKEN_PLACEHOLDER_6E61C970__"
_HTML_CACHE = {}
_LOCK = threading.RLock()
_APP = None

_ORIGINAL_RENDER_TEMPLATE = _page.render_template
_ORIGINAL_CACHE_SPACE = _hot._cache_space
_ORIGINAL_REVOKE = getattr(_cloud_service, "revoke_live_share", None)


def _token_hash(raw_token):
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _share_variant(share):
    share = share or {}
    return (
        str(share.get("customer_key") or "").strip(),
        str(share.get("history_scope") or "current").strip().lower(),
        bool(share.get("include_cancelled")),
    )


def _put_html(token_hash, share, html):
    token_hash = str(token_hash or "").strip().lower()
    customer_key = str((share or {}).get("customer_key") or "").strip()
    if not token_hash or not customer_key or not html:
        return
    with _LOCK:
        _HTML_CACHE[token_hash] = {
            "customer_key": customer_key,
            "variant": _share_variant(share),
            "html": html,
        }


def _drop_customer(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return
    with _LOCK:
        stale = [
            key
            for key, item in _HTML_CACHE.items()
            if str((item or {}).get("customer_key") or "").strip() == customer_key
        ]
        for key in stale:
            _HTML_CACHE.pop(key, None)


def _render_placeholder(app, share, bundle):
    if not app or not share or not bundle:
        return None
    space = copy.deepcopy((bundle or {}).get("space") or {})
    if not space:
        return None
    _fast._filter_space(space, share)
    with app.app_context():
        template = app.jinja_env.get_template(_TEMPLATE)
        return template.render(
            space=space,
            share=share,
            share_token=_TOKEN_PLACEHOLDER,
        )


def _prebuild_customer(customer_key, bundle=None):
    app = _APP
    customer_key = str(customer_key or "").strip()
    if not app or not customer_key:
        return

    if bundle is None:
        cached = _page._cache_get(_page._space_cache, customer_key)
        bundle = copy.deepcopy(cached) if cached is not None else None
    if not bundle:
        return

    shares = []
    with _page._cache_lock:
        for token_hash, item in list(_hot._HASH_TOKEN_CACHE.items()):
            try:
                share = item[1]
            except Exception:
                continue
            if str((share or {}).get("customer_key") or "").strip() == customer_key:
                shares.append((str(token_hash).lower(), dict(share or {})))

    rendered = {}
    for token_hash, share in shares:
        variant = _share_variant(share)
        html = rendered.get(variant)
        if html is None:
            try:
                html = _render_placeholder(app, share, bundle)
            except Exception as exc:
                print(
                    f"[WARN] ORDER share HTML pre-render failed for {customer_key}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if not html:
                continue
            rendered[variant] = html
        _put_html(token_hash, share, html)


def _cache_space_and_prerender(customer_key, bundle):
    _drop_customer(customer_key)
    result = _ORIGINAL_CACHE_SPACE(customer_key, bundle)
    try:
        _prebuild_customer(customer_key, bundle)
    except Exception as exc:
        print(
            f"[WARN] ORDER share HTML cache refresh skipped for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _cached_render_template(template_name, *args, **kwargs):
    if template_name != _TEMPLATE:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token = str(kwargs.get("share_token") or "").strip()
    share = kwargs.get("share") or {}
    if not token:
        return _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)

    token_hash = _token_hash(token)
    variant = _share_variant(share)
    with _LOCK:
        item = _HTML_CACHE.get(token_hash)
        if item and item.get("variant") == variant:
            html = item.get("html")
        else:
            html = None
    if html:
        return html.replace(_TOKEN_PLACEHOLDER, token)

    rendered = _ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)
    if isinstance(rendered, str) and rendered:
        skeleton = rendered.replace(token, _TOKEN_PLACEHOLDER)
        _put_html(token_hash, share, skeleton)
    return rendered


def _revoke_and_drop_html(raw_token):
    changed = _ORIGINAL_REVOKE(raw_token)
    if changed:
        with _LOCK:
            _HTML_CACHE.pop(_token_hash(raw_token), None)
    return changed


@b2_test_bp.record_once
def _order_share_html_startup(state):
    global _APP
    _APP = state.app

    customers = set()
    with _page._cache_lock:
        for _token_hash_value, item in list(_hot._HASH_TOKEN_CACHE.items()):
            try:
                share = item[1]
            except Exception:
                continue
            customer_key = str((share or {}).get("customer_key") or "").strip()
            if customer_key:
                customers.add(customer_key)

    for customer_key in customers:
        _prebuild_customer(customer_key)


def install():
    _hot._cache_space = _cache_space_and_prerender
    _page.render_template = _cached_render_template
    if callable(_ORIGINAL_REVOKE):
        _cloud_service.revoke_live_share = _revoke_and_drop_html


install()
