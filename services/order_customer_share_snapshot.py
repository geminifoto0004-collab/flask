"""Persistent TiDB snapshot for fast ORDER public-share pages.

A public /share GET should not rebuild hundreds of ORDER/asset rows.  Keep one safe
JSON bundle per customer in TiDB and patch the existing page loader so a cache miss
needs one indexed token+snapshot row lookup.

The snapshot contains only cloud-safe render_payload fields and cloud_assets metadata.
It never contains image bytes, storage credentials, local paths, phone/payment/deposit
data, or the raw share token.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time

from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as _asset_service
from services import order_cloud_service as _cloud_service
from services import order_public_share_multi_b2_page as _page

_TABLE = "cloud_customer_share_snapshot"
_INIT_LOCK = threading.Lock()
_INITIALIZED = False
_TIMER_LOCK = threading.Lock()
_REFRESH_TIMERS = {}

_ORIGINAL_LOAD_PAGE_DATA = _page._load_page_data
_ORIGINAL_SYNC_ORDER = _cloud_service.sync_order
_ORIGINAL_CREATE_LIVE_SHARE = _cloud_service.create_live_share


def _ensure_table():
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    customer_key VARCHAR(191) PRIMARY KEY,
                    payload LONGTEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_order_share_snapshot_updated (updated_at)
                )
                """
            )
            conn.commit()
            _INITIALIZED = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _json_dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decode_snapshot(raw):
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _load_build_rows(customer_key):
    """Background/update path only: two indexed reads to build one persisted bundle."""
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT order_number, customer_key AS row_customer_key, customer_name,
                      order_status, order_date, expected_delivery_date, production_type,
                      product_name, product_code, pattern_code, quantity,
                      source_site AS row_source_site, updated_at AS row_updated_at,
                      render_payload
               FROM cloud_orders
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_date DESC, order_number DESC""",
            (customer_key,),
        )
        order_rows = [get_row_dict(row, cur) for row in cur.fetchall()]

        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, content_type, file_size, display_name,
                      source_site, storage_backend, updated_at, created_at
               FROM cloud_assets
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        assets = [get_row_dict(row, cur) for row in cur.fetchall()]
        return order_rows, assets
    finally:
        conn.close()


def _build_bundle(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return None

    order_rows, assets = _load_build_rows(customer_key)
    if not order_rows:
        return None

    orders = []
    for db_row in order_rows:
        payload = _page._decode_payload(db_row.get("render_payload"))
        if payload is None:
            legacy = _page._legacy_bundle(customer_key, assets)
            if legacy:
                legacy["data_mode"] = "persistent-snapshot-legacy-source"
                legacy.pop("cache_state", None)
            return legacy
        orders.append(_page._normalize_order_payload(payload, db_row))

    orders.sort(
        key=lambda item: (
            str(item.get("order_date") or ""),
            str(item.get("order_number") or ""),
        ),
        reverse=True,
    )
    by_order = {str(order.get("order_number") or ""): order for order in orders}
    for asset in assets:
        parent = by_order.get(str(asset.get("order_number") or ""))
        if parent is not None:
            parent["assets"].append(asset)

    first = order_rows[0]
    customer = {
        "customer_key": customer_key,
        "customer_name": str(first.get("customer_name") or "").strip(),
        "updated_at": first.get("row_updated_at"),
    }
    return {
        "space": {"customer": customer, "orders": orders},
        "asset_count": len(assets),
        "asset_order_count": len(
            {str(asset.get("order_number") or "") for asset in assets if asset.get("order_number")}
        ),
        "data_mode": "persistent-snapshot",
    }


def _persist_snapshot(customer_key, bundle):
    _ensure_table()
    customer_key = str(customer_key or "").strip()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        if not bundle:
            cur.execute(f"DELETE FROM {_TABLE} WHERE customer_key=?", (customer_key,))
        else:
            payload = _json_dump(bundle)
            cur.execute(f"SELECT customer_key FROM {_TABLE} WHERE customer_key=?", (customer_key,))
            if cur.fetchone():
                cur.execute(
                    f"UPDATE {_TABLE} SET payload=?, updated_at=CURRENT_TIMESTAMP WHERE customer_key=?",
                    (payload, customer_key),
                )
            else:
                cur.execute(
                    f"INSERT INTO {_TABLE} (customer_key, payload) VALUES (?, ?)",
                    (customer_key, payload),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _invalidate_local_cache(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return
    try:
        with _page._cache_lock:
            _page._space_cache.pop(customer_key, None)
            stale_tokens = []
            for token, item in list(_page._token_cache.items()):
                try:
                    share = item[1]
                except Exception:
                    continue
                if str((share or {}).get("customer_key") or "").strip() == customer_key:
                    stale_tokens.append(token)
            for token in stale_tokens:
                _page._token_cache.pop(token, None)
    except Exception:
        pass


def rebuild_snapshot(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return None
    bundle = _build_bundle(customer_key)
    _persist_snapshot(customer_key, bundle)
    _invalidate_local_cache(customer_key)
    return bundle


def _refresh_worker(customer_key):
    try:
        rebuild_snapshot(customer_key)
    except Exception as exc:
        print(
            f"[WARN] ORDER share snapshot refresh failed for {customer_key}: "
            f"{type(exc).__name__}: {exc}"
        )
    finally:
        with _TIMER_LOCK:
            _REFRESH_TIMERS.pop(customer_key, None)


def queue_snapshot_refresh(customer_key, delay=1.5):
    """Debounce batch ORDER/image writes so hundreds of image registers rebuild once."""
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        return
    _invalidate_local_cache(customer_key)
    with _TIMER_LOCK:
        previous = _REFRESH_TIMERS.pop(customer_key, None)
        if previous is not None:
            try:
                previous.cancel()
            except Exception:
                pass
        timer = threading.Timer(float(delay), _refresh_worker, args=(customer_key,))
        timer.daemon = True
        _REFRESH_TIMERS[customer_key] = timer
        timer.start()


def _snapshot_load_page_data(token):
    """Public hot/cold path: in-process HIT or one token+snapshot TiDB row."""
    token = str(token or "").strip()
    if not token:
        return None, None, _page.Response(
            "Enlace no encontrado.", 404, mimetype="text/plain"
        )

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

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                f"""SELECT s.token_hash, s.customer_key, s.mode, s.status, s.source_site,
                           s.created_at, s.expires_at, s.history_scope, s.include_cancelled,
                           p.payload AS snapshot_payload
                    FROM cloud_share_tokens s
                    LEFT JOIN {_TABLE} p ON p.customer_key=s.customer_key
                    WHERE s.token_hash=? LIMIT 1""",
                (token_hash,),
            )
            row = cur.fetchone()
            data = get_row_dict(row, cur) if row else None
        finally:
            conn.close()
    except Exception as exc:
        print(f"[WARN] ORDER share snapshot read fallback: {type(exc).__name__}: {exc}")
        return _ORIGINAL_LOAD_PAGE_DATA(token)

    share, error = _page._validate_share(data)
    if error:
        return share, None, error

    customer_key = str((share or {}).get("customer_key") or "").strip()
    bundle = _decode_snapshot((data or {}).get("snapshot_payload"))
    if not bundle:
        # Existing data may predate this table. Serve correctly now, then backfill.
        share, bundle, error = _ORIGINAL_LOAD_PAGE_DATA(token)
        if error:
            return share, bundle, error
        if bundle:
            queue_snapshot_refresh(customer_key, delay=0.05)
            bundle = copy.deepcopy(bundle)
            bundle["data_mode"] = "snapshot-bootstrap-fallback"
            bundle["cache_state"] = "MISS"
        return share, bundle, None

    bundle = copy.deepcopy(bundle)
    bundle["data_mode"] = "persistent-snapshot-one-row"
    bundle["cache_state"] = "MISS"
    _page._cache_put(_page._token_cache, token, dict(share), _page._TOKEN_TTL)
    hot_bundle = copy.deepcopy(bundle)
    hot_bundle["cache_state"] = "HIT"
    _page._cache_put(_page._space_cache, customer_key, hot_bundle, _page._SPACE_TTL)
    return share, bundle, None


def _lookup_deleted_customer(payload):
    customer_key = str((payload or {}).get("customer_key") or "").strip()
    if customer_key:
        return customer_key
    order_number = str((payload or {}).get("order_number") or "").strip()
    if not order_number:
        return ""
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            "SELECT customer_key FROM cloud_orders WHERE order_number=? LIMIT 1",
            (order_number,),
        )
        row = cur.fetchone()
        data = get_row_dict(row, cur) if row else {}
        return str((data or {}).get("customer_key") or "").strip()
    finally:
        conn.close()


def _sync_order_with_snapshot(payload, source_site=None):
    payload = payload or {}
    old_customer_key = (
        _lookup_deleted_customer(payload) if payload.get("_deleted") else ""
    )
    result = _ORIGINAL_SYNC_ORDER(payload, source_site=source_site)
    customer_key = str(
        (result or {}).get("customer_key")
        or old_customer_key
        or payload.get("customer_key")
        or payload.get("customer_name")
        or ""
    ).strip()
    queue_snapshot_refresh(customer_key)
    return result


def _create_live_share_with_snapshot(
    customer_key, source_site=None, expires_hours=24, permanent=False
):
    result = _ORIGINAL_CREATE_LIVE_SHARE(
        customer_key,
        source_site=source_site,
        expires_hours=expires_hours,
        permanent=permanent,
    )
    # Move the expensive assembly to link creation instead of the customer's first GET.
    try:
        rebuild_snapshot(customer_key)
    except Exception as exc:
        print(
            f"[WARN] ORDER share snapshot create warmup failed: "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _patch_asset_writers():
    original = getattr(_asset_service, "_upsert_asset_metadata", None)
    if callable(original) and not getattr(original, "_order_snapshot_wrapped", False):
        def wrapped_asset_upsert(*args, **kwargs):
            result = original(*args, **kwargs)
            queue_snapshot_refresh((result or {}).get("customer_key"))
            return result

        wrapped_asset_upsert._order_snapshot_wrapped = True
        _asset_service._upsert_asset_metadata = wrapped_asset_upsert

    try:
        from services import order_cloud_direct_multi_b2 as direct_multi
    except Exception:
        direct_multi = None
    if direct_multi is not None:
        direct_original = getattr(direct_multi, "_upsert_registered_asset", None)
        if callable(direct_original) and not getattr(
            direct_original, "_order_snapshot_wrapped", False
        ):
            def wrapped_direct_upsert(*args, **kwargs):
                result = direct_original(*args, **kwargs)
                queue_snapshot_refresh((result or {}).get("customer_key"))
                return result

            wrapped_direct_upsert._order_snapshot_wrapped = True
            direct_multi._upsert_registered_asset = wrapped_direct_upsert


def _backfill_active_shares():
    # Let normal Flask imports finish, then prebuild only customers with live links.
    time.sleep(0.75)
    try:
        _ensure_table()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT DISTINCT customer_key
                   FROM cloud_share_tokens
                   WHERE status='active' AND customer_key IS NOT NULL"""
            )
            keys = []
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                key = str(data.get("customer_key") or "").strip()
                if key:
                    keys.append(key)
        finally:
            conn.close()

        for key in keys:
            try:
                rebuild_snapshot(key)
            except Exception as exc:
                print(
                    f"[WARN] ORDER share snapshot backfill failed for {key}: "
                    f"{type(exc).__name__}: {exc}"
                )
    except Exception as exc:
        print(f"[WARN] ORDER share snapshot startup skipped: {type(exc).__name__}: {exc}")


def install():
    _page._load_page_data = _snapshot_load_page_data
    _cloud_service.sync_order = _sync_order_with_snapshot
    _cloud_service.create_live_share = _create_live_share_with_snapshot
    _patch_asset_writers()
    thread = threading.Thread(
        target=_backfill_active_shares,
        name="order-share-snapshot-backfill",
        daemon=True,
    )
    thread.start()


install()
