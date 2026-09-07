"""Make ORDER desktop share modals open immediately without slowing the wall.

The existing detail endpoint remains the source of truth. This patch injects two small
browser runtimes into the cached customer wall: the first opens the modal immediately
from already-rendered card data and hydrates text/detail in the background; the second
keeps that zero-wait thumbnail first paint, then upgrades only the visible slide to the
WEB image after it is already on screen.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from services import order_share_native_order_ui as _native
from services import order_share_render_cache as _render

_ROOT = Path(__file__).resolve().parents[1]
_JS_PATH = _ROOT / "order_tracking" / "static" / "js" / "order_modal_fast.js"
_QUALITY_JS_PATH = _ROOT / "order_tracking" / "static" / "js" / "order_modal_quality_upgrade.js"
_MARKER = "ORDER_MODAL_FAST_RUNTIME_V2"
_VERSION = "order-modal-fast-v2-quality-20260906"
_ORIGINAL_SOURCE = _native._source
_PREVIOUS_TEMPLATE_HASH = _render._compute_template_hash


def _source_with_fast_modal(name):
    text = _ORIGINAL_SOURCE(name)
    if name != "guest_customer.html" or _MARKER in text:
        return text
    try:
        js = _JS_PATH.read_text("utf-8")
        quality_js = _QUALITY_JS_PATH.read_text("utf-8")
    except Exception:
        return text
    runtime = (
        f"\n<script>/* {_MARKER} */\n{js}\n</script>\n"
        f"<script>/* ORDER_MODAL_QUALITY_UPGRADE */\n{quality_js}\n</script>\n"
    )
    return text.replace("</body>", runtime + "</body>", 1)


def _template_hash_with_fast_modal(app):
    base = str(_PREVIOUS_TEMPLATE_HASH(app) or "")
    try:
        js_hash = hashlib.sha256(_JS_PATH.read_bytes()).hexdigest()
    except Exception:
        js_hash = "missing-fast"
    try:
        quality_hash = hashlib.sha256(_QUALITY_JS_PATH.read_bytes()).hexdigest()
    except Exception:
        quality_hash = "missing-quality"
    payload = base + "|" + _VERSION + "|" + js_hash + "|" + quality_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_native._source = _source_with_fast_modal
_render._compute_template_hash = _template_hash_with_fast_modal
try:
    _native._fingerprint.cache_clear()
except Exception:
    pass
try:
    with _native._LOCK:
        _native._COMPILED.clear()
except Exception:
    pass

print("[ORDER] modal speed patch ready: instant thumb first paint + background WEB quality upgrade")
