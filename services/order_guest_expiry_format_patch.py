"""Format Render ORDER guest expiry as DDd HHh MMm SSs.

The native ORDER guest templates historically rendered the whole remaining duration as
`total_minutes:ss`, which turns multi-day links into values such as `9773:08`.  Keep the
same one-second countdown/expiry behaviour, but present an explicit days/hours/minutes/
seconds value on both the customer wall and the order detail page.
"""
from __future__ import annotations

from services import order_share_native_order_ui as _native

_OLD_TIMER = """        const m = Math.floor(left / 60000), s = Math.floor((left % 60000) / 1000);\n        el.textContent = `${m}:${String(s).padStart(2,'0')}`;"""
_NEW_TIMER = """        const totalSeconds = Math.max(0, Math.floor(left / 1000));\n        const d = Math.floor(totalSeconds / 86400);\n        const h = Math.floor((totalSeconds % 86400) / 3600);\n        const m = Math.floor((totalSeconds % 3600) / 60);\n        const s = totalSeconds % 60;\n        el.textContent = `${String(d).padStart(2,'0')}d ${String(h).padStart(2,'0')}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;"""

_ORIGINAL_SOURCE = _native._source


def _source_with_readable_expiry(name):
    text = _ORIGINAL_SOURCE(name)
    if name not in {"guest_customer.html", "guest_order.html"}:
        return text
    text = text.replace(_OLD_TIMER, _NEW_TIMER)
    # Avoid a brief `--:--` flash before the immediate first tick runs.
    text = text.replace(">--:--</strong>", ">00d 00h 00m 00s</strong>")
    return text


_native._source = _source_with_readable_expiry
try:
    _native._fingerprint.cache_clear()
except Exception:
    pass
try:
    with _native._LOCK:
        _native._COMPILED.clear()
except Exception:
    pass

print("[ORDER] guest expiry format patch ready: DDd HHh MMm SSs")
