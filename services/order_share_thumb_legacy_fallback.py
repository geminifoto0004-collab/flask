"""Compatibility fallback for ORDER images that predate thumbnail metadata.

New assets with thumb_object_key use the real 480px thumbnail path. Older assets
remain visible by signing their existing WEB object directly. This fallback performs
no B2 HEAD/GET/resize/PUT work and can disappear after thumbnail backfill is complete.
"""
from __future__ import annotations

import time

from flask import has_request_context, redirect, request

from services import order_cloud_multi_b2_public as _media
from services import order_public_share_fast as _fast
from services import order_share_direct_cover_cache as _direct
from services import order_share_thumb_metadata_patch as _thumb
from services.order_cloud_multi_b2 import PRIMARY

_PREVIOUS_ROUTER = _media._signed_get
_PREVIOUS_DIRECT_THUMB = _direct._cached_signed_get
_PREVIOUS_LEGACY_THUMB = _fast._thumb_redirect


def _is_thumb_request():
    if not has_request_context():
        return False
    parts = (request.path or "").strip("/").split("/")
    return len(parts) == 4 and parts[0] == "share" and parts[2] == "thumb"


def _has_thumb(asset):
    return bool(str((asset or {}).get("thumb_object_key") or "").strip())


def _signed_get_compat(asset, seconds=600):
    # The before_app_request interceptor calls _media._signed_get for all media
    # aliases. Only old /thumb requests without metadata need compatibility.
    if _is_thumb_request() and not _has_thumb(asset):
        return _thumb._ORIGINAL_SIGNED_GET(asset, seconds=seconds)
    return _PREVIOUS_ROUTER(asset, seconds=seconds)


def _cached_direct_compat(asset):
    if _has_thumb(asset):
        return _PREVIOUS_DIRECT_THUMB(asset)

    object_key = str((asset or {}).get("object_key") or "").strip()
    if not object_key:
        raise ValueError("object_key is required")
    backend = str((asset or {}).get("storage_backend") or PRIMARY).strip().lower() or PRIMARY
    key = ("legacy-full", backend, object_key, str((asset or {}).get("asset_key") or "").strip().lower())
    now = time.monotonic()
    with _direct._LOCK:
        item = _direct._URL_CACHE.get(key)
        if item and item[0] > now:
            return item[1], item[2], True, 0.0
        if item:
            _direct._URL_CACHE.pop(key, None)

    started = time.perf_counter()
    url, backend = _thumb._ORIGINAL_SIGNED_GET(asset, seconds=600)
    sign_ms = (time.perf_counter() - started) * 1000.0
    customer_key = str((asset or {}).get("customer_key") or "").strip()
    with _direct._LOCK:
        _direct._URL_CACHE[key] = (now + 480.0, url, backend, customer_key)
    return url, backend, False, sign_ms


def _legacy_thumb_redirect_compat(asset):
    if _has_thumb(asset):
        return _PREVIOUS_LEGACY_THUMB(asset)
    url, backend = _thumb._ORIGINAL_SIGNED_GET(asset, seconds=600)
    resp = redirect(url, code=302)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Order-Storage-Backend"] = backend
    resp.headers["X-Order-Thumbnail-Fallback"] = "legacy-web-image"
    return resp


_media._signed_get = _signed_get_compat
_direct._cached_signed_get = _cached_direct_compat
_direct._cached_signed_thumb_get = _cached_direct_compat
_fast._thumb_redirect = _legacy_thumb_redirect_compat

print("[ORDER] legacy thumbnail fallback ready")
