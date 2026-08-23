"""Keep active ORDER share snapshots hot before customers arrive.

The persistent snapshot removed the large public-page rebuild, but a process-local
cache miss still had to open TiDB once to validate the token and read the snapshot.
This module moves that remaining read off the customer request path:

- active share token hashes and persisted snapshots are preloaded at Render startup;
- a small background sweep refreshes them every 15 seconds;
- public requests validate the raw token by hashing it locally and looking up the
  prewarmed hash cache, so a normal first request does not need TiDB;
- snapshot rebuilds immediately repopulate the same in-process cache instead of
  invalidating it until the next sweep;
- startup prewarm retries quickly if TiDB was not ready on the first import attempt;
- the existing one-row TiDB loader remains the safe fallback if prewarming ever fails.

No image bytes, B2 credentials, raw share tokens, LAN SQLite data, phone/payment or
other private fields are cached here.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time

from database import get_cursor, get_db_connection, get_row_dict
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_multi_b2_page as _page

_SWEEP_SECONDS = 15.0
_HASH_TTL = 180.0
_SPACE_TTL = 300.0
_HASH_TOKEN_CACHE = {}
_STOP = threading.Event()
_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data
_ORIGINAL_REBUILD_SNAPSHOT = _snapshot.rebuild_snapshot
_LAST_ACTIVE_HASHES = set()
_LAST_WARM_ERROR = "not-run"
_LAST_WARM_AT = 0.0


def _token_hash(raw_token):
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _share_from_row(row):
    return {
        "token_hash": row.get("token_hash"),
        "customer_key": row.get("customer_key"),
        "mode": row.get("mode"),
        "status": row.get("status"),
        "source_site": row.get("source_site"),
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "history_scope": row.get("history_scope"),
        "include_cancelled": row.get("include_cancelled"),
    }


def _cache_space(customer_key, bundle):
    customer_key = str(customer_key or "").strip()
    if not customer_key or not bundle:
        return
    hot = copy.deepcopy(bundle)
    hot["cache_state"] = "HIT"
    hot["data_mode"] = "persistent-snapshot-prewarmed"
    _page._cache_put(_page._space_cache, customer_key, hot, _SPACE_TTL)


def _rebuild_snapshot_and_rewarm(customer_key):
    """Rebuild persisted data, then immediately keep the fresh bundle hot."""
    bundle = _ORIGINAL_REBUILD_SNAPSHOT(customer_key)
    if bundle:
        _cache_space(customer_key, bundle)
    return bundle


def _warm_once():
    """Load active token hashes + persisted snapshots in one query.

    Do not filter expiry in SQL. TiDB/server timezone and legacy rows can differ; the
    shared Python validator is the canonical expiry check and keeps startup prewarm
    consistent with the real public-share request path.
    """
    global _LAST_ACTIVE_HASHES, _LAST_WARM_ERROR, _LAST_WARM_AT

    _snapshot._ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            f"""SELECT s.token_hash, s.customer_key, s.mode, s.status, s.source_site,
                       s.created_at, s.expires_at, s.history_scope, s.include_cancelled,
                       p.payload AS snapshot_payload
                FROM cloud_share_tokens s
                LEFT JOIN {_snapshot._TABLE} p ON p.customer_key=s.customer_key
                WHERE s.status='active'
                  AND s.customer_key IS NOT NULL"""
        )
        rows = [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()

    active_hashes = set()
    missing_customers = set()
    for row in rows:
        share = _share_from_row(row)
        share, error = _page._validate_share(share)
        if error or not share:
            continue
        token_hash = str(share.get("token_hash") or "").strip().lower()
        customer_key = str(share.get("customer_key") or "").strip()
        if not token_hash or not customer_key:
            continue

        active_hashes.add(token_hash)
        _page._cache_put(_HASH_TOKEN_CACHE, token_hash, dict(share), _HASH_TTL)

        bundle = _snapshot._decode_snapshot(row.get("snapshot_payload"))
        if bundle:
            _cache_space(customer_key, bundle)
        else:
            missing_customers.add(customer_key)

    with _page._cache_lock:
        for token_hash in list(_HASH_TOKEN_CACHE.keys()):
            if token_hash not in active_hashes:
                _HASH_TOKEN_CACHE.pop(token_hash, None)
        for raw_token in list(_page._token_cache.keys()):
            if _token_hash(raw_token) not in active_hashes:
                _page._token_cache.pop(raw_token, None)

    for customer_key in missing_customers:
        try:
            _snapshot.queue_snapshot_refresh(customer_key, delay=0.05)
        except Exception:
            pass

    _LAST_ACTIVE_HASHES = set(active_hashes)
    _LAST_WARM_ERROR = ""
    _LAST_WARM_AT = time.monotonic()
    return {"active_tokens": len(active_hashes), "missing_snapshots": len(missing_customers)}


def _mark_warm_error(exc):
    global _LAST_WARM_ERROR, _LAST_WARM_AT
    _LAST_WARM_ERROR = type(exc).__name__
    _LAST_WARM_AT = time.monotonic()


def _hot_load_page_data(token):
    """Serve from prewarmed process memory; fall back to the persistent snapshot loader."""
    token = str(token or "").strip()
    if not token:
        return _ORIGINAL_LOAD_PAGE_DATA(token)

    cached_share = _page._cache_get(_page._token_cache, token)
    if cached_share is not None:
        share, error = _page._validate_share(cached_share)
        if error:
            return share, None, error
        customer_key = str(share.get("customer_key") or "").strip()
        cached_bundle = _page._cache_get(_page._space_cache, customer_key)
        if cached_bundle is not None:
            bundle = copy.deepcopy(cached_bundle)
            bundle["cache_state"] = "HIT"
            return share, bundle, None

    token_hash = _token_hash(token)
    prewarmed_share = _page._cache_get(_HASH_TOKEN_CACHE, token_hash)
    if prewarmed_share is not None:
        share, error = _page._validate_share(prewarmed_share)
        if error:
            return share, None, error
        customer_key = str(share.get("customer_key") or "").strip()
        cached_bundle = _page._cache_get(_page._space_cache, customer_key)
        if cached_bundle is not None:
            _page._cache_put(_page._token_cache, token, dict(share), _page._TOKEN_TTL)
            bundle = copy.deepcopy(cached_bundle)
            bundle["cache_state"] = "HIT"
            bundle["data_mode"] = "persistent-snapshot-prewarmed"
            return share, bundle, None

    # Safe fallback: current persistent snapshot route performs one indexed TiDB read.
    # Tag the response mode so a single curl can tell whether this module is installed
    # and whether startup prewarm knew this token hash, without exposing the token.
    share, bundle, error = _ORIGINAL_LOAD_PAGE_DATA(token)
    if error:
        return share, bundle, error
    if share:
        _page._cache_put(_HASH_TOKEN_CACHE, token_hash, dict(share), _HASH_TTL)
    if share and bundle:
        _cache_space(share.get("customer_key"), bundle)
        known = "known" if token_hash in _LAST_ACTIVE_HASHES else "missing"
        err = _LAST_WARM_ERROR or "none"
        bundle = copy.deepcopy(bundle)
        bundle["data_mode"] = f"persistent-snapshot-prewarm-fallback-{known}-e-{err}"
        bundle["cache_state"] = "MISS"
    return share, bundle, None


def _bootstrap_retry_loop():
    """Retry quickly during startup; normal 15-second sweeps take over afterwards."""
    for delay in (1.0, 2.0, 4.0, 8.0):
        if _STOP.wait(delay):
            return
        try:
            result = _warm_once()
            if int((result or {}).get("active_tokens") or 0) > 0:
                return
        except Exception as exc:
            _mark_warm_error(exc)
            print(f"[WARN] ORDER share bootstrap prewarm retry failed: {type(exc).__name__}: {exc}")


def _sweep_loop():
    while not _STOP.wait(_SWEEP_SECONDS):
        try:
            _warm_once()
        except Exception as exc:
            _mark_warm_error(exc)
            print(f"[WARN] ORDER share hot-cache sweep skipped: {type(exc).__name__}: {exc}")


def install():
    _page._SPACE_TTL = _SPACE_TTL
    _snapshot.rebuild_snapshot = _rebuild_snapshot_and_rewarm

    try:
        _warm_once()
    except Exception as exc:
        _mark_warm_error(exc)
        print(f"[WARN] ORDER share startup prewarm skipped: {type(exc).__name__}: {exc}")

    _page._load_page_data = _hot_load_page_data

    retry_thread = threading.Thread(
        target=_bootstrap_retry_loop,
        name="order-share-hot-cache-bootstrap",
        daemon=True,
    )
    retry_thread.start()

    sweep_thread = threading.Thread(
        target=_sweep_loop,
        name="order-share-hot-cache",
        daemon=True,
    )
    sweep_thread.start()


install()
