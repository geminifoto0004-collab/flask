"""Manual maintenance and refresh endpoints for customer-pinned ORDER B2 storage."""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services.order_cloud_asset_service import _validate_sha256
from services.order_cloud_customer_storage import (
    PRIMARY,
    SECONDARY,
    _TABLE,
    _INTENT_TABLE,
    assigned_backend,
    backend_ready,
    clear_assignment_cache,
    customer_namespace,
    existing_distribution,
)
from services.order_cloud_multi_b2 import client_for_backend, config_for_backend


def _customer_asset_rows(customer_key):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, order_number, workflow_key, sha256, object_key,
                      content_type, file_size, storage_backend
               FROM cloud_assets WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, asset_key""",
            (customer_key,),
        )
        return [get_row_dict(row, cur) for row in cur.fetchall() or []]
    finally:
        conn.close()


def _shared_object_keys(customer_key, object_keys):
    """Return keys still referenced by another active customer.

    Older builds used SHA-only global object keys. A customer purge must never remove one
    of those physical objects while another customer still points at it.
    """
    keys = [str(value or "").strip() for value in (object_keys or []) if str(value or "").strip()]
    if not keys:
        return set()
    shared = set()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        for start in range(0, len(keys), 200):
            batch = keys[start:start + 200]
            placeholders = ",".join(["?"] * len(batch))
            cur.execute(
                f"""SELECT DISTINCT object_key
                    FROM cloud_assets
                    WHERE active=TRUE AND customer_key<>?
                      AND object_key IN ({placeholders})""",
                [customer_key, *batch],
            )
            for row in cur.fetchall() or []:
                data = get_row_dict(row, cur) or {}
                key = str(data.get("object_key") or "").strip()
                if key:
                    shared.add(key)
        return shared
    finally:
        conn.close()


def _prefix_keys(backend, prefix):
    if not backend_ready(backend):
        raise RuntimeError(f"{backend} is not readable/configured")
    cfg = config_for_backend(backend, required=True)
    client = client_for_backend(backend)
    result = []
    token = None
    while True:
        kwargs = {"Bucket": cfg["bucket_name"], "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        result.extend(
            str(item.get("Key") or "")
            for item in (page.get("Contents") or [])
            if item.get("Key")
        )
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            break
    return result


def _version_listing_unsupported(exc):
    response = getattr(exc, "response", None) or {}
    error = response.get("Error") or {}
    code = str(error.get("Code") or "").strip().lower()
    status = int((response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
    return status in {400, 405, 501} and code in {
        "", "invalidrequest", "methodnotallowed", "notimplemented", "unsupportedoperation"
    }


def _delete_exact_all_versions(backend, object_key):
    if not object_key:
        return 0
    if not backend_ready(backend):
        raise RuntimeError(f"{backend} became unavailable during purge")
    cfg = config_for_backend(backend, required=True)
    client = client_for_backend(backend)
    deleted = 0
    try:
        key_marker = None
        version_marker = None
        while True:
            kwargs = {"Bucket": cfg["bucket_name"], "Prefix": object_key, "MaxKeys": 1000}
            if key_marker:
                kwargs["KeyMarker"] = key_marker
            if version_marker:
                kwargs["VersionIdMarker"] = version_marker
            page = client.list_object_versions(**kwargs)
            objects = []
            for item in list(page.get("Versions") or []) + list(page.get("DeleteMarkers") or []):
                if str(item.get("Key") or "") == object_key and item.get("VersionId") is not None:
                    objects.append({"Key": object_key, "VersionId": str(item.get("VersionId"))})
            if objects:
                client.delete_objects(
                    Bucket=cfg["bucket_name"],
                    Delete={"Objects": objects, "Quiet": True},
                )
                deleted += len(objects)
            if not page.get("IsTruncated"):
                break
            key_marker = page.get("NextKeyMarker")
            version_marker = page.get("NextVersionIdMarker")
            if not key_marker and not version_marker:
                break
        if deleted:
            return deleted
    except Exception as exc:
        # Fail closed on auth/network errors. Only an explicit "version listing is not
        # supported" response may fall back to deleting the current key.
        if not _version_listing_unsupported(exc):
            raise
    client.delete_object(Bucket=cfg["bucket_name"], Key=object_key)
    return 1


def _refresh(customer_key):
    from services import order_customer_share_snapshot as snapshot

    bundle = snapshot.rebuild_snapshot(customer_key)
    return {
        "orders": len((((bundle or {}).get("space") or {}).get("orders") or [])),
        "assets": int((bundle or {}).get("asset_count") or 0),
    }


@b2_test_bp.before_app_request
def _customer_storage_admin():
    path = request.path or ""
    if request.method != "POST" or path not in {
        "/api/order-cloud/storage/customer/status",
        "/api/order-cloud/storage/customer/purge",
        "/api/order-cloud/assets/reconcile",
        "/api/order-cloud/share/refresh",
    }:
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        customer_key = str(payload.get("customer_key") or "").strip()
        if not customer_key:
            return jsonify({"ok": False, "error": "customer_key is required"}), 400

        if path.endswith("/status"):
            backend = assigned_backend(customer_key)
            return jsonify({"ok": True, "result": {
                "customer_key": customer_key,
                "customer_namespace": customer_namespace(customer_key),
                "assigned_backend": backend,
                "backend_ready": bool(backend_ready(backend)),
                "existing_distribution": existing_distribution(customer_key),
                "policy": "one_customer_one_backend_new_uploads",
            }})

        if path.endswith("/refresh"):
            refreshed = _refresh(customer_key)
            return jsonify({"ok": True, "result": {
                "customer_key": customer_key,
                "share_tokens_changed": False,
                "snapshot_refreshed": True,
                **refreshed,
            }})

        if path.endswith("/reconcile"):
            items = payload.get("items")
            if not isinstance(items, list):
                return jsonify({"ok": False, "error": "items must be a list"}), 400
            if len(items) > 20000:
                return jsonify({"ok": False, "error": "too many asset items"}), 400
            if not items and not bool(payload.get("confirm_empty", False)):
                return jsonify({"ok": False, "error": "empty manifest requires confirm_empty=true"}), 400

            expected = set()
            for item in items:
                if not isinstance(item, dict):
                    continue
                order_number = str(item.get("order_number") or "").strip()
                workflow_key = str(item.get("workflow_key") or "").strip() or None
                sha256_hex = _validate_sha256(item.get("sha256"))
                if not order_number:
                    raise ValueError("order_number is required for every asset item")
                expected.add(asset_service._asset_key(order_number, workflow_key, sha256_hex))

            conn = get_db_connection()
            cur = get_cursor(conn)
            try:
                cur.execute(
                    "SELECT asset_key FROM cloud_assets WHERE customer_key=? AND active=TRUE",
                    (customer_key,),
                )
                current = {
                    str((get_row_dict(row, cur) or {}).get("asset_key") or "").strip()
                    for row in cur.fetchall() or []
                }
                stale = sorted(key for key in current if key and key not in expected)
                for asset_key in stale:
                    cur.execute(
                        "DELETE FROM cloud_assets WHERE customer_key=? AND asset_key=?",
                        (customer_key, asset_key),
                    )
                    cur.execute(
                        f"DELETE FROM {_INTENT_TABLE} WHERE customer_key=? AND asset_key=?",
                        (customer_key, asset_key),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

            refreshed = _refresh(customer_key)
            return jsonify({"ok": True, "result": {
                "customer_key": customer_key,
                "expected_assets": len(expected),
                "stale_metadata_removed": len(stale),
                "physical_objects_deleted": 0,
                **refreshed,
            }})

        execute = bool(payload.get("execute", False))
        required = f"PURGE:{customer_key}"
        rows = _customer_asset_rows(customer_key)
        prefix = f"customers/{customer_namespace(customer_key)}/"
        prefix_keys = {}
        scan_errors = {}
        backend_state = {}
        for backend in (PRIMARY, SECONDARY):
            backend_state[backend] = bool(backend_ready(backend))
            try:
                prefix_keys[backend] = _prefix_keys(backend, prefix)
            except Exception as exc:
                prefix_keys[backend] = []
                scan_errors[backend] = f"{type(exc).__name__}: {exc}"
        metadata_keys = sorted({
            str(row.get("object_key") or "").strip()
            for row in rows if row.get("object_key")
        })
        protected_shared_keys = sorted(_shared_object_keys(customer_key, metadata_keys))
        preview = {
            "customer_key": customer_key,
            "assigned_backend": assigned_backend(customer_key),
            "metadata_rows": len(rows),
            "metadata_object_keys": len(metadata_keys),
            "customer_prefix": prefix,
            "prefix_objects": {key: len(value) for key, value in prefix_keys.items()},
            "backend_ready": backend_state,
            "protected_shared_object_keys": len(protected_shared_keys),
            "scan_errors": scan_errors,
            "execute": execute,
            "confirmation_required": required,
        }
        if not execute:
            return jsonify({"ok": True, "result": preview})
        if str(payload.get("confirm") or "") != required:
            return jsonify({"ok": False, "error": f"confirm must equal {required}"}), 400
        if scan_errors:
            return jsonify({
                "ok": False,
                "error": "B2 scan incomplete; nothing was deleted",
                "result": preview,
            }), 503

        deleted = {PRIMARY: 0, SECONDARY: 0}
        errors = []
        protected = set(protected_shared_keys)
        for backend in (PRIMARY, SECONDARY):
            try:
                keys = set(prefix_keys.get(backend) or [])
                # Known legacy object keys may live outside the new customer prefix and
                # may have been duplicated across B2s by old retry logic. Delete exact
                # known keys from both backends, EXCEPT a global legacy key that another
                # customer still actively references.
                keys.update(metadata_keys)
                for object_key in sorted(key for key in keys if key not in protected):
                    deleted[backend] += _delete_exact_all_versions(backend, object_key)
            except Exception as exc:
                errors.append(f"{backend}: {type(exc).__name__}: {exc}")

        if errors:
            return jsonify({
                "ok": False,
                "error": "B2 purge incomplete; TiDB metadata was preserved",
                "errors": errors,
                "result": {**preview, "deleted_versions": deleted},
            }), 500

        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute("DELETE FROM cloud_assets WHERE customer_key=?", (customer_key,))
            cur.execute(f"DELETE FROM {_INTENT_TABLE} WHERE customer_key=?", (customer_key,))
            if bool(payload.get("reset_assignment", False)):
                cur.execute(f"DELETE FROM {_TABLE} WHERE customer_key=?", (customer_key,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        if bool(payload.get("reset_assignment", False)):
            clear_assignment_cache(customer_key)
        refreshed = _refresh(customer_key)
        return jsonify({"ok": True, "result": {
            **preview,
            "purged": True,
            "deleted_versions": deleted,
            "metadata_rows_deleted": len(rows),
            "assignment_preserved": not bool(payload.get("reset_assignment", False)),
            **refreshed,
        }})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 500
