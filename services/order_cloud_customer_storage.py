"""Customer-pinned B2 storage policy for ORDER share images.

New uploads are pinned by customer. Existing TiDB metadata always wins, so a timeout or
temporary unreadable backend never causes the same image to be uploaded to the other B2.
New physical keys are stable per customer+sha256 and do not encode order/workflow paths.
"""
from __future__ import annotations

import hashlib
import threading

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services.order_cloud_asset_service import ALLOWED_IMAGE_TYPES, _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, backend_ready

_TABLE = "cloud_customer_storage_assignment"
_ALLOWED = {PRIMARY, SECONDARY}
_LOCK = threading.RLock()
_CACHE = {}


def customer_namespace(customer_key):
    value = str(customer_key or "").strip()
    if not value:
        raise ValueError("customer_key is required")
    return "c_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def stable_object_key(customer_key, sha256_hex, content_type):
    content_type = _validate_content_type(content_type)
    sha256_hex = _validate_sha256(sha256_hex)
    return (
        f"customers/{customer_namespace(customer_key)}/assets/"
        f"{sha256_hex}{ALLOWED_IMAGE_TYPES[content_type]}"
    )


def _ensure_table():
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
                customer_key VARCHAR(191) PRIMARY KEY,
                storage_backend VARCHAR(32) NOT NULL,
                assignment_reason VARCHAR(64) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_order_customer_storage_backend (storage_backend)
            )"""
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash_backend(customer_key):
    return PRIMARY if int(hashlib.sha256(str(customer_key).encode("utf-8")).hexdigest()[0], 16) < 8 else SECONDARY


def existing_distribution(customer_key):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT storage_backend, COUNT(*) AS n, COALESCE(SUM(file_size),0) AS bytes
               FROM cloud_assets
               WHERE customer_key=? AND active=TRUE
               GROUP BY storage_backend""",
            (customer_key,),
        )
        result = {}
        for row in cur.fetchall() or []:
            data = get_row_dict(row, cur) or {}
            backend = str(data.get("storage_backend") or PRIMARY).strip().lower()
            if backend in _ALLOWED:
                result[backend] = {
                    "count": int(data.get("n") or 0),
                    "bytes": int(data.get("bytes") or 0),
                }
        return result
    finally:
        conn.close()


def _derive_assignment(customer_key):
    dist = existing_distribution(customer_key)
    if dist:
        preferred = _hash_backend(customer_key)
        ranked = sorted(
            dist.items(),
            key=lambda item: (
                int((item[1] or {}).get("bytes") or 0),
                int((item[1] or {}).get("count") or 0),
                1 if item[0] == preferred else 0,
            ),
            reverse=True,
        )
        return ranked[0][0], "existing_majority"

    selected = _hash_backend(customer_key)
    if backend_ready(selected):
        return selected, "customer_hash_50_50"
    alternate = SECONDARY if selected == PRIMARY else PRIMARY
    if backend_ready(alternate):
        return alternate, "customer_hash_config_fallback"
    return selected, "customer_hash_unconfigured"


def assigned_backend(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        raise ValueError("customer_key is required")
    with _LOCK:
        cached = _CACHE.get(customer_key)
        if cached in _ALLOWED:
            return cached

    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(f"SELECT storage_backend FROM {_TABLE} WHERE customer_key=? LIMIT 1", (customer_key,))
        row = cur.fetchone()
        data = get_row_dict(row, cur) if row else {}
        backend = str((data or {}).get("storage_backend") or "").strip().lower()
        if backend not in _ALLOWED:
            backend, reason = _derive_assignment(customer_key)
            cur.execute(
                f"""INSERT INTO {_TABLE} (customer_key, storage_backend, assignment_reason)
                    VALUES (?, ?, ?)
                    ON DUPLICATE KEY UPDATE customer_key=VALUES(customer_key)""",
                (customer_key, backend, reason),
            )
            conn.commit()
            cur.execute(f"SELECT storage_backend FROM {_TABLE} WHERE customer_key=? LIMIT 1", (customer_key,))
            row = cur.fetchone()
            data = get_row_dict(row, cur) if row else {}
            backend = str((data or {}).get("storage_backend") or backend).strip().lower()
        if backend not in _ALLOWED:
            raise RuntimeError("customer storage assignment is invalid")
    finally:
        conn.close()

    with _LOCK:
        _CACHE[customer_key] = backend
    return backend


def clear_assignment_cache(customer_key=None):
    with _LOCK:
        if customer_key:
            _CACHE.pop(str(customer_key).strip(), None)
        else:
            _CACHE.clear()


def find_customer_sha_asset(customer_key, sha256_hex):
    sha256_hex = _validate_sha256(sha256_hex)
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                      object_key, content_type, file_size, storage_backend
               FROM cloud_assets
               WHERE customer_key=? AND sha256=? AND active=TRUE
                 AND object_key IS NOT NULL AND object_key<>''
               ORDER BY updated_at DESC, created_at DESC LIMIT 1""",
            (str(customer_key or "").strip(), sha256_hex),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        conn.close()


@b2_test_bp.before_app_request
def _customer_pinned_direct_upload():
    path = request.path or ""
    if request.method != "POST" or path not in {
        "/api/order-cloud/assets/direct-presign",
        "/api/order-cloud/assets/direct-register",
    }:
        return None

    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        from services import order_cloud_direct_multi_b2 as direct

        if path.endswith("/direct-presign"):
            variant = str(payload.get("variant") or "image").strip().lower()
            order_number = str(payload.get("order_number") or "").strip()
            if variant != "image" or not order_number:
                return None

            sha256_hex = _validate_sha256(payload.get("sha256"))
            content_type = _validate_content_type(payload.get("content_type"))
            workflow_key = str(payload.get("workflow_key") or "").strip() or None
            try:
                file_size = int(payload.get("file_size") or 0)
            except Exception:
                file_size = 0
            if file_size and file_size > direct._NEW_IMAGE_MAX_BYTES:
                raise ValueError("optimized image exceeds 1,000,000-byte policy")

            order_number, customer_key, workflow_key = direct._resolve_owner(order_number, workflow_key)
            customer_backend = assigned_backend(customer_key)

            exact = direct._existing_asset(order_number, workflow_key, sha256_hex)
            if exact and exact.get("object_key"):
                backend = str(exact.get("storage_backend") or PRIMARY).strip().lower()
                if backend not in _ALLOWED:
                    return jsonify({"ok": False, "error": "existing asset storage_backend is invalid"}), 409
                return jsonify({"ok": True, "result": {
                    "exists": True, "reused": True, "variant": "image",
                    "sha256": sha256_hex, "asset_sha256": sha256_hex,
                    "content_type": exact.get("content_type") or content_type,
                    "file_size": int(exact.get("file_size") or 0),
                    "object_key": exact.get("object_key"), "storage_backend": backend,
                    "asset_key": exact.get("asset_key"),
                    "upload_mode": "tidb_existing_asset_pinned_no_failover",
                    "render_receives_image_bytes": False, "b2_head_calls_per_image": 0,
                    "backend_selection": {
                        "selected": backend, "customer_assignment": customer_backend,
                        "cross_backend_retry_allowed": False,
                    },
                }})

            physical = find_customer_sha_asset(customer_key, sha256_hex)
            if physical and physical.get("object_key"):
                backend = str(physical.get("storage_backend") or PRIMARY).strip().lower()
                if backend not in _ALLOWED:
                    return jsonify({"ok": False, "error": "existing physical image storage_backend is invalid"}), 409
                linked = direct._upsert_registered_asset(
                    order_number, customer_key, workflow_key, sha256_hex,
                    physical.get("object_key"), physical.get("content_type") or content_type,
                    int(physical.get("file_size") or file_size or 0), source_site, backend,
                )
                return jsonify({"ok": True, "result": {
                    "exists": True, "reused": True, "reused_physical_object": True,
                    "variant": "image", "sha256": sha256_hex, "asset_sha256": sha256_hex,
                    "content_type": linked.get("content_type") or content_type,
                    "file_size": int(linked.get("file_size") or 0),
                    "object_key": linked.get("object_key"), "storage_backend": backend,
                    "asset_key": linked.get("asset_key"),
                    "upload_mode": "customer_sha_relinked_without_upload",
                    "render_receives_image_bytes": False, "b2_head_calls_per_image": 0,
                    "backend_selection": {
                        "selected": backend, "customer_assignment": customer_backend,
                        "cross_backend_retry_allowed": False,
                    },
                }})

            if not backend_ready(customer_backend):
                return jsonify({
                    "ok": False,
                    "error": "assigned customer B2 backend is unavailable; retry later without switching backend",
                    "storage_backend": customer_backend,
                    "cross_backend_retry_allowed": False,
                }), 503

            object_key = stable_object_key(customer_key, sha256_hex, content_type)
            upload_url = direct._presigned_put(customer_backend, object_key, content_type, seconds=600)
            return jsonify({"ok": True, "result": {
                "exists": False, "reused": False, "variant": "image",
                "sha256": sha256_hex, "asset_sha256": sha256_hex,
                "content_type": content_type, "object_key": object_key,
                "storage_backend": customer_backend, "upload_url": upload_url,
                "expires_seconds": 600,
                "upload_mode": "customer_pinned_direct_b2_single_object",
                "render_receives_image_bytes": False, "b2_head_calls_per_image": 0,
                "customer_namespace": customer_namespace(customer_key),
                "backend_selection": {
                    "selected": customer_backend,
                    "customer_assignment": customer_backend,
                    "cross_backend_retry_allowed": False,
                    "avoid_backend_ignored": str(payload.get("avoid_backend") or "").strip().lower() or None,
                },
            }})

        order_number = str(payload.get("order_number") or "").strip()
        if not order_number:
            return None
        workflow_key = str(payload.get("workflow_key") or "").strip() or None
        sha256_hex = _validate_sha256(payload.get("sha256"))
        content_type = _validate_content_type(payload.get("content_type"))
        backend = str(payload.get("storage_backend") or "").strip().lower()
        if backend not in _ALLOWED or not backend_ready(backend):
            raise ValueError("storage_backend is invalid or not configured")
        try:
            file_size = int(payload.get("file_size") or 0)
        except Exception:
            raise ValueError("file_size must be an integer")
        if file_size <= 0 or file_size > direct._LEGACY_MAX_BYTES:
            raise ValueError("file_size is outside the allowed range")

        order_number, customer_key, workflow_key = direct._resolve_owner(order_number, workflow_key)
        stable_key = stable_object_key(customer_key, sha256_hex, content_type)
        old_scoped_key = direct._scoped_object_key(customer_key, order_number, workflow_key, sha256_hex, content_type)
        legacy_key = asset_service._object_key(sha256_hex, content_type)
        object_key = str(payload.get("object_key") or "").strip() or stable_key
        if object_key not in {stable_key, old_scoped_key, legacy_key}:
            raise ValueError("object_key does not match accepted canonical/legacy paths")
        if object_key == stable_key:
            pinned = assigned_backend(customer_key)
            if backend != pinned:
                raise ValueError("new canonical object must use the customer's assigned B2 backend")
            if file_size > direct._NEW_IMAGE_MAX_BYTES:
                raise ValueError("optimized image exceeds 1,000,000-byte policy")

        result = direct._upsert_registered_asset(
            order_number, customer_key, workflow_key, sha256_hex, object_key,
            content_type, file_size, source_site, backend,
        )
        result["upload_mode"] = (
            "customer_pinned_direct_b2_registered"
            if object_key == stable_key else "legacy_path_registered_without_move"
        )
        result["render_received_image_bytes"] = False
        result["b2_head_calls"] = 0
        result["customer_assignment"] = assigned_backend(customer_key)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 500
