"""Customer-pinned B2 storage policy for ORDER share images.

Rules enforced here:
- one customer is pinned to one B2 for all NEW images;
- existing TiDB pointers always win and are never moved just because a backend is slow;
- timeout/403 never triggers a cross-B2 retry;
- physical object keys are stable per customer+image SHA, independent of order/workflow;
- a retry after an uncertain PUT checks the SAME B2 object before another PUT, avoiding
  duplicate B2 versions when the first upload actually succeeded but register/response failed.
"""
from __future__ import annotations

import hashlib
import threading

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services.order_cloud_asset_service import ALLOWED_IMAGE_TYPES, _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    client_for_backend,
    config_for_backend,
)

_TABLE = "cloud_customer_storage_assignment"
_INTENT_TABLE = "cloud_asset_upload_intent"
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
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {_INTENT_TABLE} (
                asset_key VARCHAR(64) PRIMARY KEY,
                customer_key VARCHAR(191) NOT NULL,
                order_number VARCHAR(191) NOT NULL,
                workflow_key VARCHAR(191) NULL,
                sha256 VARCHAR(64) NOT NULL,
                object_key VARCHAR(768) NOT NULL,
                storage_backend VARCHAR(32) NOT NULL,
                content_type VARCHAR(128) NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_order_upload_intent_customer_sha (customer_key, sha256),
                INDEX idx_order_upload_intent_updated (updated_at)
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
        # This fallback is only used while the customer has NO assignment and NO assets.
        # Once persisted, the assignment is immutable unless an administrator resets it.
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


def _intent_get(asset_key):
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(f"SELECT * FROM {_INTENT_TABLE} WHERE asset_key=? LIMIT 1", (asset_key,))
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        conn.close()


def _intent_put(asset_key, customer_key, order_number, workflow_key, sha256_hex,
                object_key, backend, content_type, file_size):
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            f"""INSERT INTO {_INTENT_TABLE}
                (asset_key, customer_key, order_number, workflow_key, sha256,
                 object_key, storage_backend, content_type, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE asset_key=VALUES(asset_key)""",
            (
                asset_key, customer_key, order_number, workflow_key, sha256_hex,
                object_key, backend, content_type, int(file_size or 0),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _intent_get(asset_key)


def _intent_delete(asset_key):
    if not asset_key:
        return
    _ensure_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(f"DELETE FROM {_INTENT_TABLE} WHERE asset_key=?", (asset_key,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _same_b2_object_state(backend, object_key, expected_size=0):
    """Return (exists, size). 404 is absence; auth/network errors are UNKNOWN and raise.

    This is deliberately used only when an upload intent already exists, i.e. a retry
    after an uncertain first PUT. Normal first uploads still consume zero B2 HEAD calls.
    """
    cfg = config_for_backend(backend, required=True)
    client = client_for_backend(backend)
    try:
        response = client.head_object(Bucket=cfg["bucket_name"], Key=object_key)
    except Exception as exc:
        response = getattr(exc, "response", None) or {}
        error = response.get("Error") or {}
        code = str(error.get("Code") or "").strip().lower()
        status = int((response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
        if status == 404 or code in {"404", "nosuchkey", "notfound"}:
            return False, 0
        raise RuntimeError(
            f"cannot verify pending object on {backend}; refusing another PUT: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    actual_size = int(response.get("ContentLength") or 0)
    expected_size = int(expected_size or 0)
    if expected_size > 0 and actual_size != expected_size:
        raise RuntimeError(
            f"pending object exists on {backend} but size differs "
            f"({actual_size} != {expected_size}); refusing overwrite"
        )
    return True, actual_size


def _existing_result(row, customer_backend, upload_mode, extra=None):
    backend = str((row or {}).get("storage_backend") or PRIMARY).strip().lower()
    result = {
        "exists": True,
        "reused": True,
        "variant": "image",
        "sha256": row.get("sha256"),
        "asset_sha256": row.get("sha256"),
        "content_type": row.get("content_type"),
        "file_size": int(row.get("file_size") or 0),
        "object_key": row.get("object_key"),
        "storage_backend": backend,
        "asset_key": row.get("asset_key"),
        "upload_mode": upload_mode,
        "render_receives_image_bytes": False,
        "b2_head_calls_per_image": 0,
        "backend_selection": {
            "selected": backend,
            "customer_assignment": customer_backend,
            "cross_backend_retry_allowed": False,
        },
    }
    if extra:
        result.update(extra)
    return result


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
        _ensure_table()
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
            if file_size <= 0:
                raise ValueError("file_size is required for direct image upload")
            if file_size > direct._NEW_IMAGE_MAX_BYTES:
                raise ValueError("optimized image exceeds 1,000,000-byte policy")

            order_number, customer_key, workflow_key = direct._resolve_owner(order_number, workflow_key)
            customer_backend = assigned_backend(customer_key)
            asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)

            exact = direct._existing_asset(order_number, workflow_key, sha256_hex)
            if exact and exact.get("object_key"):
                backend = str(exact.get("storage_backend") or PRIMARY).strip().lower()
                if backend not in _ALLOWED:
                    return jsonify({"ok": False, "error": "existing asset storage_backend is invalid"}), 409
                _intent_delete(asset_key)
                return jsonify({"ok": True, "result": _existing_result(
                    exact, customer_backend, "tidb_existing_asset_pinned_no_failover"
                )})

            physical = find_customer_sha_asset(customer_key, sha256_hex)
            if physical and physical.get("object_key"):
                backend = str(physical.get("storage_backend") or PRIMARY).strip().lower()
                if backend not in _ALLOWED:
                    return jsonify({"ok": False, "error": "existing physical image storage_backend is invalid"}), 409
                linked = direct._upsert_registered_asset(
                    order_number, customer_key, workflow_key, sha256_hex,
                    physical.get("object_key"), physical.get("content_type") or content_type,
                    int(physical.get("file_size") or file_size), source_site, backend,
                )
                _intent_delete(asset_key)
                return jsonify({"ok": True, "result": _existing_result(
                    linked,
                    customer_backend,
                    "customer_sha_relinked_without_upload",
                    {"reused_physical_object": True},
                )})

            # If this asset was already presigned once but never registered, this is a
            # retry/uncertain PUT. Check the SAME backend/object before issuing another
            # PUT. This costs one HEAD only on retry, not on normal uploads.
            intent = _intent_get(asset_key)
            if intent:
                intent_backend = str(intent.get("storage_backend") or "").strip().lower()
                intent_object_key = str(intent.get("object_key") or "").strip()
                if intent_backend not in _ALLOWED or not intent_object_key:
                    return jsonify({"ok": False, "error": "stored upload intent is invalid"}), 409
                if not backend_ready(intent_backend):
                    return jsonify({
                        "ok": False,
                        "error": "pending image belongs to an unavailable B2; retry later without switching backend",
                        "storage_backend": intent_backend,
                        "cross_backend_retry_allowed": False,
                    }), 503
                try:
                    exists, actual_size = _same_b2_object_state(
                        intent_backend,
                        intent_object_key,
                        int(intent.get("file_size") or file_size),
                    )
                except RuntimeError as exc:
                    return jsonify({
                        "ok": False,
                        "error": str(exc),
                        "storage_backend": intent_backend,
                        "cross_backend_retry_allowed": False,
                        "b2_head_calls_per_image": 1,
                    }), 503
                if exists:
                    linked = direct._upsert_registered_asset(
                        order_number,
                        customer_key,
                        workflow_key,
                        sha256_hex,
                        intent_object_key,
                        str(intent.get("content_type") or content_type),
                        int(actual_size or intent.get("file_size") or file_size),
                        source_site,
                        intent_backend,
                    )
                    _intent_delete(asset_key)
                    result = _existing_result(
                        linked,
                        customer_backend,
                        "retry_found_same_b2_object_registered_without_upload",
                        {"recovered_uncertain_put": True},
                    )
                    result["b2_head_calls_per_image"] = 1
                    return jsonify({"ok": True, "result": result})

                upload_url = direct._presigned_put(
                    intent_backend, intent_object_key,
                    str(intent.get("content_type") or content_type), seconds=600,
                )
                return jsonify({"ok": True, "result": {
                    "exists": False, "reused": False, "variant": "image",
                    "sha256": sha256_hex, "asset_sha256": sha256_hex,
                    "content_type": str(intent.get("content_type") or content_type),
                    "file_size": int(intent.get("file_size") or file_size),
                    "object_key": intent_object_key,
                    "storage_backend": intent_backend,
                    "upload_url": upload_url,
                    "expires_seconds": 600,
                    "upload_mode": "retry_same_b2_after_confirmed_missing",
                    "render_receives_image_bytes": False,
                    "b2_head_calls_per_image": 1,
                    "customer_namespace": customer_namespace(customer_key),
                    "backend_selection": {
                        "selected": intent_backend,
                        "customer_assignment": customer_backend,
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
            intent = _intent_put(
                asset_key,
                customer_key,
                order_number,
                workflow_key,
                sha256_hex,
                object_key,
                customer_backend,
                content_type,
                file_size,
            )
            intent_backend = str((intent or {}).get("storage_backend") or customer_backend).strip().lower()
            intent_object_key = str((intent or {}).get("object_key") or object_key).strip()
            if intent_backend != customer_backend or intent_object_key != object_key:
                return jsonify({
                    "ok": False,
                    "error": "concurrent upload intent conflicts with customer storage assignment; no PUT issued",
                    "cross_backend_retry_allowed": False,
                }), 409

            upload_url = direct._presigned_put(customer_backend, object_key, content_type, seconds=600)
            return jsonify({"ok": True, "result": {
                "exists": False, "reused": False, "variant": "image",
                "sha256": sha256_hex, "asset_sha256": sha256_hex,
                "content_type": content_type, "file_size": file_size,
                "object_key": object_key,
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
        asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
        stable_key = stable_object_key(customer_key, sha256_hex, content_type)
        old_scoped_key = direct._scoped_object_key(customer_key, order_number, workflow_key, sha256_hex, content_type)
        legacy_key = asset_service._object_key(sha256_hex, content_type)
        supplied_object_key = str(payload.get("object_key") or "").strip()
        object_key = supplied_object_key or stable_key
        if object_key not in {stable_key, old_scoped_key, legacy_key}:
            raise ValueError("object_key does not match accepted canonical/legacy paths")
        if object_key == stable_key:
            pinned = assigned_backend(customer_key)
            if backend != pinned:
                raise ValueError("new canonical object must use the customer's assigned B2 backend")
            if file_size > direct._NEW_IMAGE_MAX_BYTES:
                raise ValueError("optimized image exceeds 1,000,000-byte policy")
            intent = _intent_get(asset_key)
            if intent:
                if str(intent.get("object_key") or "").strip() != object_key:
                    raise ValueError("direct-register object_key does not match pending upload intent")
                if str(intent.get("storage_backend") or "").strip().lower() != backend:
                    raise ValueError("direct-register backend does not match pending upload intent")

        result = direct._upsert_registered_asset(
            order_number, customer_key, workflow_key, sha256_hex, object_key,
            content_type, file_size, source_site, backend,
        )
        _intent_delete(asset_key)
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
