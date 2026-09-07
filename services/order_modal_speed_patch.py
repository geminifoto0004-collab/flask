"""Make ORDER desktop share modals open immediately without slowing the wall.

The existing detail endpoint remains the source of truth. This patch only injects a
small browser runtime into the cached customer wall. The runtime shows the card's
already-loaded thumbnail/text immediately, prefetches nearby detail HTML after the
initial page load, caches it in browser memory, and keeps modal images on /thumb/.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from services import order_share_native_order_ui as _native
from services import order_share_render_cache as _render

_JS_PATH = Path(__file__).resolve().parents[1] / "order_tracking" / "static" / "js" / "order_modal_fast.js"
_MARKER = "ORDER_MODAL_FAST_RUNTIME_V1"
_VERSION = "order-modal-fast-v1-20260906"
_ORIGINAL_SOURCE = _native._source
_PREVIOUS_TEMPLATE_HASH = _render._compute_template_hash


def _source_with_fast_modal(name):
    text = _ORIGINAL_SOURCE(name)
    if name != "guest_customer.html" or _MARKER in text:
        return text
    try:
        js = _JS_PATH.read_text("utf-8")
    except Exception:
        return text
    runtime = f"\n<script>/* {_MARKER} */\n{js}\n</script>\n"
    return text.replace("</body>", runtime + "</body>", 1)


def _template_hash_with_fast_modal(app):
    base = str(_PREVIOUS_TEMPLATE_HASH(app) or "")
    try:
        js_hash = hashlib.sha256(_JS_PATH.read_bytes()).hexdigest()
    except Exception:
        js_hash = "missing"
    return hashlib.sha256((base + "|" + _VERSION + "|" + js_hash).encode("utf-8")).hexdigest()


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

print("[ORDER] modal speed patch ready: instant shell + memory prefetch + thumb-only modal")
