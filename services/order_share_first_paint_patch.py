"""Accelerate the first paint of the ORDER public customer wall.

Hot customer pages already have two things in process memory before a visitor arrives:
validated share metadata and a token-neutral pre-rendered HTML skeleton.  The legacy
request path still copied/filtered the full customer bundle before returning that cached
HTML.  For the top-level customer wall only, skip that unnecessary request copy when a
matching HTML variant is already hot.  Image/detail routes keep their existing loaders.

The response is also gzip-compressed when the browser accepts gzip.  This matters for
large customer walls because repeated HTML/card markup and inline runtimes compress very
well, reducing transfer time without changing TiDB/B2 behaviour.
"""
from __future__ import annotations

import gzip
import hashlib
import time

from flask import g, has_request_context, request

from blueprints.b2_test_bp import b2_test_bp
from services import order_customer_share_hot_cache as _hot
from services import order_public_share_multi_b2_page as _page
from services import order_share_native_order_ui as _native
from services import order_share_render_cache as _render

_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data
_ORIGINAL_SOURCE = _native._source
_PREVIOUS_TEMPLATE_HASH = _render._compute_template_hash
_VERSION = "first-paint-v1-20260906"
_STYLE_MARKER = "ORDER_FIRST_PAINT_V1"


def _is_customer_wall(token: str) -> bool:
    if not has_request_context() or request.method not in {"GET", "HEAD"}:
        return False
    path = str(request.path or "")
    return path in {f"/share/{token}", f"/share/{token}/"}


def _memory_share(token: str):
    cached = _page._cache_get(_page._token_cache, token)
    if cached is not None:
        share, error = _page._validate_share(cached)
        return share, error

    token_hash = _hot._token_hash(token)
    cached = _page._cache_get(_hot._HASH_TOKEN_CACHE, token_hash)
    if cached is None:
        return None, None
    share, error = _page._validate_share(cached)
    if share and not error:
        _page._cache_put(_page._token_cache, token, dict(share), _page._TOKEN_TTL)
    return share, error


def _html_is_hot(token: str, share: dict) -> bool:
    try:
        variant_key = _render._variant_key(share)
        token_hash = _render._token_hash(token)
        with _render._LOCK:
            token_item = _render._TOKEN_HTML.get(token_hash)
            if token_item and token_item.get("variant_key") == variant_key and token_item.get("html"):
                return True
            return bool(variant_key and _render._HTML.get(variant_key))
    except Exception:
        return False


def _html_only_load_page_data(token):
    token = str(token or "").strip()
    if token and _is_customer_wall(token):
        share, error = _memory_share(token)
        if error:
            return share, None, error
        if share and _html_is_hot(token, share):
            customer_key = str(share.get("customer_key") or "").strip()
            cached_bundle = _page._cache_get(_page._space_cache, customer_key)
            asset_count = 0
            asset_order_count = 0
            if isinstance(cached_bundle, dict):
                try:
                    asset_count = int(cached_bundle.get("asset_count") or 0)
                    asset_order_count = int(cached_bundle.get("asset_order_count") or 0)
                except Exception:
                    pass

            # Server-timing normally starts inside the wrapped full loader.  This hot
            # branch deliberately bypasses it, so seed the same diagnostic fields here.
            if has_request_context():
                g._order_timing_started = time.perf_counter()
                g._order_load_path = "html-memory-zero-bundle"
                g._order_load_copy_ms = 0.0
                g._order_load_ms = 0.0

            return share, {
                "space": {"customer": {}, "orders": []},
                "asset_count": asset_count,
                "asset_order_count": asset_order_count,
                "data_mode": "pre-rendered-html-memory",
                "cache_state": "HIT",
            }, None

    return _ORIGINAL_LOAD_PAGE_DATA(token)


def _source_first_paint(name):
    text = _ORIGINAL_SOURCE(name)
    if name != "guest_customer.html" or _STYLE_MARKER in text:
        return text

    # Only the first row needs eager images.  The next cards are below/near the fold
    # and should not compete with the first visible thumbnails on a fresh connection.
    text = text.replace("loop.first and card_loop.index <= 4", "loop.first and card_loop.index <= 2")
    style = (
        f"<style>/* {_STYLE_MARKER} */"
        "@supports (content-visibility:auto){"
        "@media (min-width:700px){"
        ".guest-card:nth-child(n+7){content-visibility:auto;contain-intrinsic-size:auto 520px}"
        "}"
        "}"
        "</style>"
    )
    return text.replace("</head>", style + "</head>", 1)


def _template_hash_first_paint(app):
    base = str(_PREVIOUS_TEMPLATE_HASH(app) or "")
    return hashlib.sha256((base + "|" + _VERSION).encode("utf-8")).hexdigest()


_page._load_page_data = _html_only_load_page_data
_native._source = _source_first_paint
_render._compute_template_hash = _template_hash_first_paint
try:
    _native._fingerprint.cache_clear()
except Exception:
    pass
try:
    with _native._LOCK:
        _native._COMPILED.clear()
except Exception:
    pass


@b2_test_bp.after_app_request
def _gzip_order_share_html(response):
    try:
        if request.method != "GET":
            return response
        parts = str(request.path or "").strip("/").split("/")
        if len(parts) != 2 or parts[0] != "share":
            return response
        if response.status_code != 200 or response.direct_passthrough:
            return response
        if response.headers.get("Content-Encoding"):
            return response
        if "gzip" not in str(request.headers.get("Accept-Encoding") or "").lower():
            return response
        if not str(response.mimetype or "").lower().startswith("text/html"):
            return response

        raw = response.get_data()
        if len(raw) < 4096:
            return response
        compressed = gzip.compress(raw, compresslevel=4)
        if len(compressed) + 128 >= len(raw):
            return response

        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        vary = [x.strip() for x in str(response.headers.get("Vary") or "").split(",") if x.strip()]
        if not any(x.lower() == "accept-encoding" for x in vary):
            vary.append("Accept-Encoding")
        response.headers["Vary"] = ", ".join(vary)
        response.headers["X-Order-HTML-Raw-Bytes"] = str(len(raw))
        response.headers["X-Order-HTML-Gzip-Bytes"] = str(len(compressed))
    except Exception as exc:
        print(f"[WARN] ORDER share gzip skipped: {type(exc).__name__}: {exc}")
    return response


print("[ORDER] first-paint patch ready: hot HTML zero-bundle + gzip + 2 eager covers")
