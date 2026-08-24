"""Cheap request views for prewarmed ORDER public-share snapshots.

The hot cache stores a full customer snapshot for a day.  The public page only mutates
`space['orders']` and each order's `workflows` list while applying share scope, so a
full deepcopy of every asset/history row on every GET is unnecessary.  Build a small
copy-on-filter view instead and keep the canonical cached snapshot untouched.

No database, B2, schema, LAN or storage behaviour is changed here.
"""
from __future__ import annotations

import time

from flask import g, has_request_context

from services import order_customer_share_hot_cache as _hot
from services import order_public_share_multi_b2_page as _page

_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data


def _request_bundle_view(cached_bundle):
    """Copy only containers that `_filter_space()` can mutate."""
    started = time.perf_counter()

    bundle = dict(cached_bundle or {})
    source_space = bundle.get("space") or {}
    if isinstance(source_space, dict):
        space = dict(source_space)
        source_orders = source_space.get("orders") or []
        orders = []
        if isinstance(source_orders, list):
            for source_order in source_orders:
                if not isinstance(source_order, dict):
                    continue
                order = dict(source_order)
                workflows = source_order.get("workflows")
                if isinstance(workflows, list):
                    # _filter_space replaces this list but does not mutate workflow rows.
                    order["workflows"] = list(workflows)
                orders.append(order)
        space["orders"] = orders
        bundle["space"] = space

    copy_ms = (time.perf_counter() - started) * 1000.0
    return bundle, copy_ms


def _mark(path, copy_ms=0.0):
    if has_request_context():
        g._order_load_path = str(path or "unknown")
        g._order_load_copy_ms = float(copy_ms or 0.0)


def _memory_share(token):
    """Resolve valid share metadata from raw-token cache or prewarmed hash cache."""
    cached_share = _page._cache_get(_page._token_cache, token)
    if cached_share is not None:
        share, error = _page._validate_share(cached_share)
        if error:
            return share, error, "token-memory"
        return share, None, "token-memory"

    token_hash = _hot._token_hash(token)
    prewarmed_share = _page._cache_get(_hot._HASH_TOKEN_CACHE, token_hash)
    if prewarmed_share is None:
        return None, None, "missing"

    share, error = _page._validate_share(prewarmed_share)
    if error:
        return share, error, "hash-memory"
    if share:
        _page._cache_put(_page._token_cache, token, dict(share), _page._TOKEN_TTL)
    return share, None, "hash-memory"


def _fast_request_load_page_data(token):
    token = str(token or "").strip()
    if not token:
        _mark("fallback-empty-token")
        return _ORIGINAL_LOAD_PAGE_DATA(token)

    share, error, share_path = _memory_share(token)
    if error:
        _mark(share_path)
        return share, None, error

    if share:
        customer_key = str(share.get("customer_key") or "").strip()
        cached_bundle = _page._cache_get(_page._space_cache, customer_key)
        if cached_bundle is not None:
            bundle, copy_ms = _request_bundle_view(cached_bundle)
            bundle["cache_state"] = "HIT"
            bundle["data_mode"] = "persistent-snapshot-prewarmed"
            _mark(f"{share_path}+space-shallow", copy_ms)
            return share, bundle, None

    # Correctness fallback stays exactly where it was.  The existing hot loader can
    # perform the persistent one-row TiDB read and repopulate memory if startup data is
    # genuinely unavailable.
    _mark("fallback-hot-loader")
    return _ORIGINAL_LOAD_PAGE_DATA(token)


def install():
    _page._load_page_data = _fast_request_load_page_data


install()
