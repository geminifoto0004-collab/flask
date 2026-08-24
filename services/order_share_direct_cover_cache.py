"""Cache short-lived direct B2 cover URLs for ORDER public shares.

This module sits on top of order_share_render_cache. It keeps the current one-object
storage model intact while removing repeated local SigV4 work from hot page renders.
It also injects preconnect/preload hints for the first visible covers so the browser
can start the B2 connection while the rest of the HTML is still being parsed.

No image bytes are proxied or copied. Raw share tokens are never stored in this cache.
"""
from __future__ import annotations

import threading
import time
from html import escape as _html_escape
from urllib.parse import urlparse

from flask import g, has_request_context

from services import order_cloud_multi_b2_public as _media
from services import order_customer_share_hot_cache as _hot
from services import order_share_render_cache as _render
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY

_SIGN_SECONDS = 600
_CACHE_SECONDS = 480.0
_PRELOAD_COUNT = 2

_LOCK = threading.RLock()
_URL_CACHE = {}

_ORIGINAL_HOT_CACHE_SPACE = _hot._cache_space


def _asset_cache_key(asset):
    return (
        str((asset or {}).get("storage_backend") or PRIMARY).strip().lower(),
        str((asset or {}).get("object_key") or "").strip(),
        str((asset or {}).get("asset_key") or "").strip().lower(),
    )


def _cached_signed_get(asset):
    key = _asset_cache_key(asset)
    if not key[1]:
        raise ValueError("object_key is required")

    now = time.monotonic()
    with _LOCK:
        item = _URL_CACHE.get(key)
        if item and item[0] > now:
            return item[1], item[2], True, 0.0
        if item:
            _URL_CACHE.pop(key, None)

    started = time.perf_counter()
    url, backend = _media._signed_get(asset, seconds=_SIGN_SECONDS)
    sign_ms = (time.perf_counter() - started) * 1000.0
    customer_key = str((asset or {}).get("customer_key") or "").strip()
    with _LOCK:
        _URL_CACHE[key] = (now + _CACHE_SECONDS, url, backend, customer_key)
        if len(_URL_CACHE) > 4096:
            stale = [k for k, value in _URL_CACHE.items() if value[0] <= now]
            for stale_key in stale:
                _URL_CACHE.pop(stale_key, None)
    return url, backend, False, sign_ms


def _drop_customer(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return
    with _LOCK:
        stale = [
            key
            for key, value in _URL_CACHE.items()
            if str(value[3] or "").strip() == customer_key
        ]
        for key in stale:
            _URL_CACHE.pop(key, None)


def _cache_space_and_clear_urls(customer_key, bundle):
    _drop_customer(customer_key)
    return _ORIGINAL_HOT_CACHE_SPACE(customer_key, bundle)


def _route_markers(token, asset_key, attr):
    for alias in ("thumb", "image", "asset"):
        yield f'{attr}="/share/{token}/{alias}/{asset_key}"'


def _inject_resource_hints(html, urls):
    if not urls or "</head>" not in html:
        return html

    origins = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in origins:
                origins.append(origin)

    hints = []
    for origin in origins:
        parsed = urlparse(origin)
        hints.append(f'<link rel="dns-prefetch" href="//{_html_escape(parsed.netloc, quote=True)}">')
        hints.append(f'<link rel="preconnect" href="{_html_escape(origin, quote=True)}" crossorigin>')

    for url in urls[:_PRELOAD_COUNT]:
        hints.append(
            f'<link rel="preload" as="image" href="{_html_escape(str(url), quote=True)}">'
        )

    return html.replace("</head>", "".join(hints) + "</head>", 1)


def _inject_direct_cover_urls(html, token, space):
    if not isinstance(html, str) or not html or not token:
        return html

    started = time.perf_counter()
    direct_count = 0
    cache_hits = 0
    cache_misses = 0
    sign_ms = 0.0
    direct_urls = []

    try:
        for asset in _render._cover_assets(space):
            asset_key = str(asset.get("asset_key") or "").strip().lower()
            if len(asset_key) != 64:
                continue

            cover_marker = None
            for marker in _route_markers(token, asset_key, "data-src"):
                if marker in html:
                    cover_marker = marker
                    break
            if not cover_marker:
                continue

            try:
                url, _backend, hit, one_sign_ms = _cached_signed_get(asset)
            except Exception:
                continue

            escaped_url = _html_escape(str(url), quote=True)
            html = html.replace(
                cover_marker,
                f'data-src="{escaped_url}"',
                1,
            )

            # The same canonical object is also the first image inside that order.
            # Reuse the same signed URL there instead of paying another Render 302.
            for attr in ("data-thumb", "data-full"):
                for marker in _route_markers(token, asset_key, attr):
                    if marker in html:
                        html = html.replace(marker, f'{attr}="{escaped_url}"')

            direct_urls.append(url)
            direct_count += 1
            sign_ms += float(one_sign_ms or 0.0)
            if hit:
                cache_hits += 1
            else:
                cache_misses += 1

        html = _inject_resource_hints(html, direct_urls)
        return html
    finally:
        if has_request_context():
            g._order_direct_cover_count = direct_count
            g._order_direct_cover_sign_ms = sign_ms
            g._order_direct_cover_cache_hits = cache_hits
            g._order_direct_cover_cache_misses = cache_misses
            g._order_direct_cover_inject_ms = (
                time.perf_counter() - started
            ) * 1000.0


def _warm_b2_clients():
    # Client construction is local work only; no object request is made here.
    for backend in (PRIMARY, SECONDARY):
        try:
            _media._cached_client(backend)
        except Exception:
            pass


def install():
    _warm_b2_clients()
    _hot._cache_space = _cache_space_and_clear_urls
    _render._inject_direct_cover_urls = _inject_direct_cover_urls


install()
