"""Final ORDER share rendering patch for real thumbnails and look-ahead loading."""
from __future__ import annotations

import hashlib
import time

from blueprints.b2_test_bp import b2_test_bp
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_multi_b2_page as _page
from services import order_share_direct_cover_cache as _direct
from services import order_share_native_order_ui as _native
from services import order_share_render_cache as _render
# Install visibility first; this module intentionally becomes the final render owner.
from services import order_share_image_source_patch as _source_visibility  # noqa: F401
from services.order_cloud_multi_b2 import PRIMARY
from services.order_share_thumb_metadata_patch import signed_thumb_get

_PATCH_VERSION = "thumb-render-v2-20260906"


class _ThumbSafeHTML(str):
    """Ignore only the legacy /thumb/ -> /image/ post-render rewrite."""
    def replace(self, old, new, count=-1):
        if str(old).endswith("/thumb/") and str(new).endswith("/image/"):
            return self
        return _ThumbSafeHTML(super().replace(old, new, count))


_ORIGINAL_PAGE_RENDER = _page.render_template


def _render_template_keep_thumbs(*args, **kwargs):
    html = _ORIGINAL_PAGE_RENDER(*args, **kwargs)
    if not isinstance(html, str):
        return html
    html = html.replace(
        "[index-1,index,index+1].forEach",
        "[index,index+1,index+2,index+3].forEach",
    )
    html = html.replace(
        "loadSlide(index - 1);\n            loadSlide(index);\n            loadSlide(index + 1);",
        "loadSlide(index);\n            loadSlide(index + 1);\n            loadSlide(index + 2);\n            loadSlide(index + 3);",
    )
    return _ThumbSafeHTML(html)


_page.render_template = _render_template_keep_thumbs


_ORIGINAL_NATIVE_IMAGES = _native._images


def _native_images(order, workflow, token):
    rows = _ORIGINAL_NATIVE_IMAGES(order, workflow, token)
    for item in rows or []:
        if isinstance(item, dict) and str(item.get("media_type") or "") == "image":
            url = str(item.get("url") or "")
            if "/image/" in url:
                item["preview_url"] = url.replace("/image/", "/thumb/", 1)
    return rows


_native._images = _native_images


def _cached_signed_thumb_get(asset):
    thumb_key = str((asset or {}).get("thumb_object_key") or "").strip()
    if not thumb_key:
        raise ValueError("thumb_object_key is required")
    backend = str((asset or {}).get("storage_backend") or PRIMARY).strip().lower() or PRIMARY
    key = ("thumb", backend, thumb_key, str((asset or {}).get("asset_key") or "").strip().lower())
    now = time.monotonic()
    with _direct._LOCK:
        item = _direct._URL_CACHE.get(key)
        if item and item[0] > now:
            return item[1], item[2], True, 0.0
        if item:
            _direct._URL_CACHE.pop(key, None)
    started = time.perf_counter()
    url, backend = signed_thumb_get(asset, seconds=600)
    sign_ms = (time.perf_counter() - started) * 1000.0
    customer_key = str((asset or {}).get("customer_key") or "").strip()
    with _direct._LOCK:
        _direct._URL_CACHE[key] = (now + 480.0, url, backend, customer_key)
    return url, backend, False, sign_ms


def _safe_route_markers(token, asset_key, attr):
    # The old optimizer replaced data-full with the cover URL too; never do that.
    if str(attr or "") == "data-full":
        return
    for alias in ("thumb", "image", "asset"):
        yield f'{attr}="/share/{token}/{alias}/{asset_key}"'


_direct._cached_signed_get = _cached_signed_thumb_get
_direct._cached_signed_thumb_get = _cached_signed_thumb_get
_direct._route_markers = _safe_route_markers


# Change the persisted HTML fingerprint so pre-fix /image card previews are not reused.
_ORIGINAL_TEMPLATE_HASH = _render._compute_template_hash


def _template_hash(app):
    base = str(_ORIGINAL_TEMPLATE_HASH(app) or "")
    return hashlib.sha256((base + "|" + _PATCH_VERSION).encode("utf-8")).hexdigest()


_render._compute_template_hash = _template_hash


def _bundle_has_thumb_schema(bundle):
    space = (bundle or {}).get("space") or {}
    for order in space.get("orders") or []:
        for asset in (order or {}).get("assets") or []:
            if isinstance(asset, dict) and str(asset.get("asset_type") or "").upper() == "IMAGE":
                if "thumb_object_key" not in asset:
                    return False
    return True


@b2_test_bp.record_once
def _thumb_render_patch_startup(state):
    """Rebuild old snapshots asynchronously; first requests remain safe via TiDB fallback."""
    queued = 0
    try:
        with _page._cache_lock:
            customer_keys = list(_page._space_cache.keys())
        for customer_key in customer_keys:
            bundle = _page._cache_get(_page._space_cache, customer_key)
            if bundle and not _bundle_has_thumb_schema(bundle):
                try:
                    _snapshot.queue_snapshot_refresh(customer_key, delay=0.1 + min(queued, 20) * 0.05)
                    queued += 1
                except Exception:
                    pass
        print(f"[ORDER] thumb render patch ready version={_PATCH_VERSION} refresh_queued={queued}")
    except Exception as exc:
        print(f"[WARN] thumb render patch startup: {type(exc).__name__}: {exc}")


# Old assets can legitimately predate thumb metadata. Keep them visible by signing
# their existing WEB object directly while backfill catches up; no B2 HEAD/resize occurs.
from services import order_share_thumb_legacy_fallback as _legacy_fallback  # noqa: E402,F401

# Share access counters, admin state and mutable expiry are control-plane only.
from services import order_share_admin_runtime_patch as _share_admin_runtime  # noqa: E402,F401
