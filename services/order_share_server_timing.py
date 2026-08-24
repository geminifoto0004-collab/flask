"""Lightweight timing diagnostics for ORDER public share pages.

This module does not change share data, TiDB schema, B2, LAN or cache behaviour. It
only measures the existing hot public-page path so curl can distinguish Flask work
from time spent before the handler is actually running inside Render.
"""
from __future__ import annotations

import threading
import time

from flask import g, request

from blueprints.b2_test_bp import b2_test_bp
from services import order_customer_share_hot_cache as _hot
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page
from services import order_share_direct_cover_cache as _direct_cover_cache  # noqa: F401

_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data
_ORIGINAL_FILTER_SPACE = _fast._filter_space
_ORIGINAL_RENDER_TEMPLATE = _page.render_template
_ORIGINAL_WARM_ONCE = _hot._warm_once

_SWEEP_LOCK = threading.Lock()
_SWEEP_ACTIVE = False
_SWEEP_LAST_MS = 0.0
_SWEEP_LAST_END = 0.0


def _is_share_page():
    if request.method != "GET":
        return False
    path = request.path or ""
    if not path.startswith("/share/") or path.startswith("/share/test"):
        return False
    return len(path.strip("/").split("/")) == 2


def _timed_load_page_data(token):
    if not _is_share_page():
        return _ORIGINAL_LOAD_PAGE_DATA(token)
    started = time.perf_counter()
    g._order_timing_started = started
    try:
        return _ORIGINAL_LOAD_PAGE_DATA(token)
    finally:
        g._order_load_ms = (time.perf_counter() - started) * 1000.0


def _timed_filter_space(space, share):
    if not _is_share_page():
        return _ORIGINAL_FILTER_SPACE(space, share)
    started = time.perf_counter()
    try:
        return _ORIGINAL_FILTER_SPACE(space, share)
    finally:
        g._order_filter_ms = (time.perf_counter() - started) * 1000.0


def _timed_render_template(*args, **kwargs):
    if not _is_share_page():
        return _ORIGINAL_RENDER_TEMPLATE(*args, **kwargs)
    started = time.perf_counter()
    try:
        return _ORIGINAL_RENDER_TEMPLATE(*args, **kwargs)
    finally:
        g._order_render_ms = (time.perf_counter() - started) * 1000.0


def _timed_warm_once(*args, **kwargs):
    global _SWEEP_ACTIVE, _SWEEP_LAST_MS, _SWEEP_LAST_END
    started = time.perf_counter()
    with _SWEEP_LOCK:
        _SWEEP_ACTIVE = True
    try:
        return _ORIGINAL_WARM_ONCE(*args, **kwargs)
    finally:
        ended = time.perf_counter()
        with _SWEEP_LOCK:
            _SWEEP_ACTIVE = False
            _SWEEP_LAST_MS = (ended - started) * 1000.0
            _SWEEP_LAST_END = ended


def _sweep_state():
    now = time.perf_counter()
    with _SWEEP_LOCK:
        active = bool(_SWEEP_ACTIVE)
        last_ms = float(_SWEEP_LAST_MS)
        last_end = float(_SWEEP_LAST_END)
    age_ms = -1.0 if not last_end else max(0.0, (now - last_end) * 1000.0)
    return active, last_ms, age_ms


@b2_test_bp.after_app_request
def _add_order_share_server_timing(response):
    started = getattr(g, "_order_timing_started", None)
    if started is None:
        return response

    app_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    load_ms = float(getattr(g, "_order_load_ms", 0.0) or 0.0)
    filter_ms = float(getattr(g, "_order_filter_ms", 0.0) or 0.0)
    render_ms = float(getattr(g, "_order_render_ms", 0.0) or 0.0)
    cover_sign_ms = float(getattr(g, "_order_direct_cover_sign_ms", 0.0) or 0.0)
    cover_inject_ms = float(getattr(g, "_order_direct_cover_inject_ms", 0.0) or 0.0)
    direct_covers = int(getattr(g, "_order_direct_cover_count", 0) or 0)
    cover_hits = int(getattr(g, "_order_direct_cover_cache_hits", 0) or 0)
    cover_misses = int(getattr(g, "_order_direct_cover_cache_misses", 0) or 0)
    rest_ms = max(0.0, app_ms - load_ms - filter_ms - render_ms)
    active, sweep_ms, sweep_age_ms = _sweep_state()

    response.headers["Server-Timing"] = (
        f"order_load;dur={load_ms:.1f}, "
        f"order_filter;dur={filter_ms:.1f}, "
        f"order_render;dur={render_ms:.1f}, "
        f"order_cover_sign;dur={cover_sign_ms:.1f}, "
        f"order_cover_inject;dur={cover_inject_ms:.1f}, "
        f"order_rest;dur={rest_ms:.1f}, "
        f"order_app;dur={app_ms:.1f}"
    )
    response.headers["X-Order-App-MS"] = f"{app_ms:.1f}"
    response.headers["X-Order-Load-MS"] = f"{load_ms:.1f}"
    response.headers["X-Order-Render-MS"] = f"{render_ms:.1f}"
    response.headers["X-Order-Direct-Covers"] = str(direct_covers)
    response.headers["X-Order-Direct-Cover-Sign-MS"] = f"{cover_sign_ms:.1f}"
    response.headers["X-Order-Direct-Cover-Inject-MS"] = f"{cover_inject_ms:.1f}"
    response.headers["X-Order-Direct-Cover-Cache-Hits"] = str(cover_hits)
    response.headers["X-Order-Direct-Cover-Cache-Misses"] = str(cover_misses)
    response.headers["X-Order-Sweep-Active"] = "1" if active else "0"
    response.headers["X-Order-Sweep-Last-MS"] = f"{sweep_ms:.1f}"
    response.headers["X-Order-Sweep-Age-MS"] = f"{sweep_age_ms:.1f}"
    return response


def install():
    _page._load_page_data = _timed_load_page_data
    _fast._filter_space = _timed_filter_space
    _page.render_template = _timed_render_template
    _hot._warm_once = _timed_warm_once


install()
