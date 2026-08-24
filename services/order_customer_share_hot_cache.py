"""Keep active ORDER share snapshots hot before customers arrive.

The public share path is intentionally kept away from TiDB on normal customer GETs.
Startup preloads active token hashes + persisted customer snapshots, snapshot rebuilds
immediately repopulate the same process cache, and cache entries live for one day so
Gunicorn pre-fork workers do not fall back to TiDB merely because a background thread
was lost after fork.

No image bytes, B2 credentials, raw share tokens, LAN SQLite data, phone/payment or
other private fields are cached here.
"""
from __future__ import annotations

import copy
import hashlib
import time

from blueprints.b2_test_bp import b2_test_bp
from database import get_cursor, get_db_connection, get_row_dict, init_database
from services import order_cloud_service as _cloud_service
from services import order_customer_share_snapshot as _snapshot
from services import order_public_share_multi_b2_page as _page

# Render/Gunicorn may preload the app and then fork workers. Daemon refresh threads
# started before fork are not reliable in the child process. Keep the preload cache
# alive for a full day instead; ORDER/image writers already rebuild+rewarm snapshots,
# expiry is validated locally on every request, and explicit revoke clears this cache.
_HASH_TTL = 86400.0
_SPACE_TTL = 86400.0
_HASH_TOKEN_CACHE = {}
_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data
_ORIGINAL_REBUILD_SNAPSHOT = _snapshot.rebuild_snapshot
_ORIGINAL_REVOKE_LIVE_SHARE = getattr(_cloud_service, "revoke_live_share", None)
_LAST_ACTIVE_HASHES = set()
_LAST_WARM_ERROR = "not-run"
_LAST_WARM_AT = 0.0
_STARTUP_DB_READY = False
_STARTUP_TEMPLATE_READY = False
_FIRST_REQUEST_INIT_BYPASS_DONE = False


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
    """Load active token hashes + persisted snapshots in one TiDB query."""
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
    """Serve from process memory; one-row TiDB read remains the safe fallback."""
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


def _revoke_live_share_and_drop_cache(raw_token):
    changed = _ORIGINAL_REVOKE_LIVE_SHARE(raw_token)
    if changed:
        token = str(raw_token or "").strip()
        token_hash = _token_hash(token)
        with _page._cache_lock:
            _HASH_TOKEN_CACHE.pop(token_hash, None)
            _page._token_cache.pop(token, None)
    return changed


@b2_test_bp.record_once
def _order_share_startup_warm(state):
    """Pay DB init + Jinja compile during Flask startup, not on the first visitor."""
    global _STARTUP_DB_READY, _STARTUP_TEMPLATE_READY
    app = state.app

    try:
        init_database()
        _STARTUP_DB_READY = True
        app.config["ORDER_SHARE_STARTUP_DB_READY"] = True
        print("[ORDER] startup database initialization complete")
    except Exception as exc:
        print(f"[WARN] ORDER startup database initialization skipped: {type(exc).__name__}: {exc}")

    try:
        with app.app_context():
            app.jinja_env.get_template("customer_share_live_fast.html")
        _STARTUP_TEMPLATE_READY = True
        app.config["ORDER_SHARE_TEMPLATE_READY"] = True
        print("[ORDER] customer share template precompiled")
    except Exception as exc:
        print(f"[WARN] ORDER share template precompile skipped: {type(exc).__name__}: {exc}")


@b2_test_bp.before_app_request
def _skip_duplicate_first_request_database_init():
    """app.py already has a first-request init hook; skip it only after startup succeeded."""
    global _FIRST_REQUEST_INIT_BYPASS_DONE
    if _FIRST_REQUEST_INIT_BYPASS_DONE or not _STARTUP_DB_READY:
        return None
    try:
        from flask import current_app

        for func in current_app.before_request_funcs.get(None, ()):  # app-wide hooks
            if getattr(func, "__name__", "") == "initialize_database":
                func.__globals__["_database_initialized"] = True
                break
        _FIRST_REQUEST_INIT_BYPASS_DONE = True
    except Exception:
        pass
    return None


def install():
    _page._SPACE_TTL = _SPACE_TTL
    _snapshot.rebuild_snapshot = _rebuild_snapshot_and_rewarm
    if callable(_ORIGINAL_REVOKE_LIVE_SHARE):
        _cloud_service.revoke_live_share = _revoke_live_share_and_drop_cache

    # Synchronous preload is deliberate: it survives Gunicorn preload/fork as memory
    # state, whereas a daemon sweep thread created before fork may disappear in workers.
    try:
        _warm_once()
    except Exception as exc:
        _mark_warm_error(exc)
        print(f"[WARN] ORDER share startup prewarm skipped: {type(exc).__name__}: {exc}")

    _page._load_page_data = _hot_load_page_data


install()
