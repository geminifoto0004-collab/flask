"""Private B2 asset storage for ORDER customer sharing.

Supports both legacy Render-proxy uploads and direct PC -> B2 presigned PUT uploads.
Metadata remains in TiDB and public reads stay protected by the share-token route.
"""

import hashlib
import json
import os
import re
from urllib.parse import quote

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from database import check_column_exists, get_cursor, get_db_connection, get_row_dict


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 15 * 1024 * 1024
BACKENDS = ("b2_primary", "b2_secondary")


def _backend_config(name="b2_primary", required=False):
    name = str(name or "b2_primary").strip().lower()
    if name not in BACKENDS:
        raise ValueError("invalid storage_backend")
    prefix = "B2" if name == "b2_primary" else "B2_SECONDARY"
    cfg = {
        "name": name,
        "key_id": (os.environ.get(prefix + "_KEY_ID") or "").strip(),
        "application_key": (os.environ.get(prefix + "_APPLICATION_KEY") or "").strip(),
        "bucket_name": (os.environ.get(prefix + "_BUCKET_NAME") or "").strip(),
        "endpoint": (os.environ.get(prefix + "_ENDPOINT") or "").strip().rstrip("/"),
    }
    missing = [
        key for key, value in (
            (prefix + "_KEY_ID", cfg["key_id"]),
            (prefix + "_APPLICATION_KEY", cfg["application_key"]),
            (prefix + "_BUCKET_NAME", cfg["bucket_name"]),
            (prefix + "_ENDPOINT", cfg["endpoint"]),
        ) if not value
    ]
    cfg["configured"] = not bool(missing)
    cfg["missing"] = missing
    if required and missing:
        raise RuntimeError("Missing B2 configuration: " + ", ".join(missing))
    return cfg


def _b2_config():
    return _backend_config("b2_primary", required=True)


def _b2_client(cfg=None):
    cfg = cfg or _b2_config()
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["application_key"],
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=8,
            retries={"max_attempts": 1, "mode": "standard"},
            signature_version="s3v4",
        ),
    )


def _backend_client(name):
    cfg = _backend_config(name, required=True)
    return _b2_client(cfg), cfg


def _is_not_found(exc):
    if not isinstance(exc, ClientError):
        return False
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = exc.response.get("Error", {}).get("Code")
    return status == 404 or code in ("404", "NoSuchKey", "NotFound")


def _validate_content_type(content_type):
    content_type = str(content_type or "").strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Only JPEG, PNG and WEBP customer images are allowed")
    return content_type


def _validate_sha256(value):
    value = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("sha256 must be a 64-character hexadecimal value")
    return value


def _object_key(sha256_hex, content_type):
    extension = ALLOWED_IMAGE_TYPES[_validate_content_type(content_type)]
    sha256_hex = _validate_sha256(sha256_hex)
    return f"order-cloud/images/{sha256_hex[:2]}/{sha256_hex}{extension}"


def _validate_object_key(object_key, sha256_hex, content_type):
    expected = _object_key(sha256_hex, content_type)
    if str(object_key or "").strip() != expected:
        raise ValueError("object_key does not match sha256/content_type")
    return expected


def init_order_cloud_asset_table():
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_assets (
                asset_key VARCHAR(64) PRIMARY KEY,
                customer_key VARCHAR(191) NOT NULL,
                order_number VARCHAR(191) NOT NULL,
                workflow_key VARCHAR(191) NULL,
                asset_type VARCHAR(16) NOT NULL DEFAULT 'IMAGE',
                sha256 VARCHAR(64) NOT NULL,
                object_key VARCHAR(512) NOT NULL,
                storage_backend VARCHAR(32) NOT NULL DEFAULT 'b2_primary',
                content_type VARCHAR(127) NOT NULL,
                file_size BIGINT NOT NULL,
                display_name VARCHAR(255) NULL,
                source_site VARCHAR(16) NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_cloud_assets_customer (customer_key),
                INDEX idx_cloud_assets_order (order_number),
                INDEX idx_cloud_assets_sha (sha256)
            )
            """
        )
        if not check_column_exists(cur, "cloud_assets", "storage_backend"):
            cur.execute(
                "ALTER TABLE cloud_assets ADD COLUMN storage_backend VARCHAR(32) NOT NULL DEFAULT 'b2_primary'"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_row(row, cur):
    return get_row_dict(row, cur) if row else None


def _resolve_order_and_workflow(cur, order_number, workflow_key=None):
    order_number = str(order_number or "").strip()
    workflow_key = str(workflow_key or "").strip() or None
    if not order_number:
        raise ValueError("order_number is required")

    cur.execute(
        "SELECT order_number, customer_key FROM cloud_orders WHERE order_number=? AND active=TRUE",
        (order_number,),
    )
    order = _safe_row(cur.fetchone(), cur)
    if not order:
        raise ValueError("order not found; sync the order before publishing images")

    if workflow_key:
        cur.execute(
            "SELECT workflow_key FROM cloud_workflows WHERE workflow_key=? AND order_number=? AND active=TRUE",
            (workflow_key, order_number),
        )
        if not cur.fetchone():
            raise ValueError("workflow_key does not belong to this active order")
    return order_number, order.get("customer_key"), workflow_key


def ensure_order_owners_batch(orders, source_site=None):
    """Batch-upsert complete safe ORDER trees in one TiDB transaction.

    V92.3 originally used this endpoint only to create image-presign owners and
    intentionally skipped workflow history. Public shipping badges are derived from
    cloud_workflow_history, so historical orders could have images/status but lose the
    actual shipped date. V93.0 keeps the fast batch transport while mirroring the same
    order/workflow/timeline shape as sync_order().
    """
    if not isinstance(orders, list):
        raise ValueError("orders must be a list")
    if not orders:
        return {"count": 0, "orders": [], "customer_keys": [], "timeline_items": 0}
    if len(orders) > 100:
        raise ValueError("owners batch limit is 100")

    from services.order_cloud_service import _upsert_customer

    source_site = (str(source_site or "").strip().upper()[:16] or None)
    conn = get_db_connection()
    cur = get_cursor(conn)
    synced = []
    customers = set()
    total_history = 0
    try:
        for payload in orders:
            if not isinstance(payload, dict):
                raise ValueError("each order must be an object")
            order_number = str(payload.get("order_number") or "").strip()
            customer_name = str(payload.get("customer_name") or "").strip()
            customer_key = str(payload.get("customer_key") or customer_name).strip()
            if not order_number:
                raise ValueError("order_number is required")
            if not customer_name or not customer_key:
                raise ValueError(f"customer_name is required for {order_number}")

            workflows = payload.get("workflows") or []
            if not isinstance(workflows, list):
                raise ValueError(f"workflows must be a list for {order_number}")

            _upsert_customer(cur, customer_key, customer_name, source_site)
            customers.add(customer_key)

            cur.execute("SELECT order_number, render_payload FROM cloud_orders WHERE order_number=?", (order_number,))
            existing_row = cur.fetchone()
            existing_data = get_row_dict(existing_row, cur) if existing_row else {}
            from services.order_cloud_service import _preserve_existing_logistics
            payload = _preserve_existing_logistics(payload, (existing_data or {}).get("render_payload"))

            order_values = (
                customer_key,
                customer_name,
                payload.get("order_status") or payload.get("current_status"),
                payload.get("order_date"),
                payload.get("expected_delivery_date") or payload.get("delivery_date"),
                payload.get("production_type"),
                payload.get("product_name"),
                payload.get("product_code"),
                payload.get("pattern_code"),
                str(payload.get("quantity")) if payload.get("quantity") is not None else None,
                source_site,
                order_number,
            )
            if existing_row:
                cur.execute(
                    """UPDATE cloud_orders
                       SET customer_key=?, customer_name=?, order_status=?, order_date=?,
                           expected_delivery_date=?, production_type=?, product_name=?,
                           product_code=?, pattern_code=?, quantity=?, active=TRUE,
                           source_site=?, updated_at=CURRENT_TIMESTAMP
                       WHERE order_number=?""",
                    order_values,
                )
            else:
                cur.execute(
                    """INSERT INTO cloud_orders
                       (customer_key, customer_name, order_status, order_date,
                        expected_delivery_date, production_type, product_name,
                        product_code, pattern_code, quantity, source_site, order_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    order_values,
                )

            # Keep manifest/hash diagnostics equivalent to the single-order sync path.
            try:
                cur.execute(
                    "UPDATE cloud_orders SET render_payload=? WHERE order_number=?",
                    (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), order_number),
                )
            except Exception:
                # render_payload is additive on old deployments; order ownership must
                # still succeed if a rolling schema has not added it yet.
                pass

            seen_workflows = []
            seen_history = []
            for pos, wf in enumerate(workflows):
                if not isinstance(wf, dict):
                    continue
                workflow_number = str(wf.get("workflow_number") or "").strip()
                workflow_key = str(
                    wf.get("workflow_key") or workflow_number or wf.get("id") or f"{order_number}:{pos}"
                ).strip()
                if not workflow_key:
                    continue
                seen_workflows.append(workflow_key)
                wf_values = (
                    order_number,
                    workflow_number or workflow_key,
                    wf.get("workflow_type") or wf.get("production_type") or wf.get("type"),
                    wf.get("status") or wf.get("current_status"),
                    wf.get("production_type"),
                    wf.get("product_name"),
                    wf.get("product_code"),
                    str(wf.get("quantity")) if wf.get("quantity") is not None else None,
                    wf.get("expected_delivery_date"),
                    wf.get("last_status_change_date"),
                    wf.get("draft_date"),
                    int(wf.get("sort_order", pos) or 0),
                    workflow_key,
                )
                cur.execute("SELECT workflow_key FROM cloud_workflows WHERE workflow_key=?", (workflow_key,))
                if cur.fetchone():
                    cur.execute(
                        """UPDATE cloud_workflows
                           SET order_number=?, workflow_number=?, workflow_type=?, status=?,
                               production_type=?, product_name=?, product_code=?, quantity=?,
                               expected_delivery_date=?, last_status_change_date=?, draft_date=?,
                               sort_order=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                           WHERE workflow_key=?""",
                        wf_values,
                    )
                else:
                    cur.execute(
                        """INSERT INTO cloud_workflows
                           (order_number, workflow_number, workflow_type, status,
                            production_type, product_name, product_code, quantity,
                            expected_delivery_date, last_status_change_date, draft_date,
                            sort_order, workflow_key)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        wf_values,
                    )

                timeline_present = "timeline" in wf or "history" in wf
                timeline = wf.get("timeline") if "timeline" in wf else wf.get("history")
                if timeline is None:
                    timeline = []
                if timeline_present and not isinstance(timeline, list):
                    raise ValueError(f"timeline must be a list for {workflow_key}")
                if not timeline_present:
                    continue

                workflow_history_keys = []
                for hpos, item in enumerate(timeline):
                    if not isinstance(item, dict):
                        continue
                    history_key = str(
                        item.get("history_key")
                        or item.get("id")
                        or f"{workflow_key}:{hpos}:{item.get('status') or item.get('to_status') or ''}:{item.get('action_date') or ''}"
                    ).strip()
                    if not history_key:
                        continue
                    workflow_history_keys.append(history_key)
                    seen_history.append(history_key)
                    history_values = (
                        workflow_key,
                        order_number,
                        item.get("status") or item.get("to_status"),
                        item.get("action_date"),
                        int(item.get("sort_order", hpos) or 0),
                        history_key,
                    )
                    cur.execute("SELECT history_key FROM cloud_workflow_history WHERE history_key=?", (history_key,))
                    if cur.fetchone():
                        cur.execute(
                            """UPDATE cloud_workflow_history
                               SET workflow_key=?, order_number=?, status=?, action_date=?,
                                   sort_order=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                               WHERE history_key=?""",
                            history_values,
                        )
                    else:
                        cur.execute(
                            """INSERT INTO cloud_workflow_history
                               (workflow_key, order_number, status, action_date, sort_order, history_key)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            history_values,
                        )
                    total_history += 1

                # Exact mirror only when the caller explicitly supplied timeline/history.
                cur.execute(
                    "SELECT history_key FROM cloud_workflow_history WHERE workflow_key=?",
                    (workflow_key,),
                )
                for row in cur.fetchall():
                    data = get_row_dict(row, cur) or {}
                    key = str(data.get("history_key") or "")
                    if key and key not in workflow_history_keys:
                        cur.execute("DELETE FROM cloud_workflow_history WHERE history_key=?", (key,))

            # Full safe payloads explicitly carry the workflow list, so remove stale
            # cloud children to match the local order exactly.
            cur.execute("SELECT workflow_key FROM cloud_workflows WHERE order_number=?", (order_number,))
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                key = str(data.get("workflow_key") or "")
                if key and key not in seen_workflows:
                    cur.execute("DELETE FROM cloud_workflow_history WHERE workflow_key=?", (key,))
                    cur.execute("DELETE FROM cloud_workflows WHERE workflow_key=?", (key,))

            synced.append(order_number)

        conn.commit()
        return {
            "count": len(synced),
            "orders": synced,
            "customer_keys": sorted(customers),
            "timeline_items": total_history,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validate_order_target(order_number, workflow_key=None):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        return _resolve_order_and_workflow(cur, order_number, workflow_key)
    finally:
        conn.close()


def _asset_key(order_number, workflow_key, sha256_hex):
    material = f"IMAGE\0{order_number}\0{workflow_key or ''}\0{sha256_hex}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _upsert_asset_metadata(order_number, workflow_key, sha256_hex, object_key, content_type,
                           file_size, source_site=None, storage_backend="b2_primary"):
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _validate_object_key(object_key, sha256_hex, content_type)
    storage_backend = str(storage_backend or "b2_primary").strip().lower()
    if storage_backend not in BACKENDS:
        raise ValueError("invalid storage_backend")

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        order_number, customer_key, workflow_key = _resolve_order_and_workflow(cur, order_number, workflow_key)
        asset_key = _asset_key(order_number, workflow_key, sha256_hex)
        display_name = f"Imagen {order_number}"
        source_site = str(source_site or "").strip().upper()[:16] or None

        cur.execute("SELECT asset_key FROM cloud_assets WHERE asset_key=?", (asset_key,))
        values = (
            customer_key, order_number, workflow_key, sha256_hex, object_key,
            storage_backend, content_type, int(file_size), display_name, source_site, asset_key,
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_assets
                   SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                       sha256=?, object_key=?, storage_backend=?, content_type=?, file_size=?,
                       display_name=?, source_site=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                   WHERE asset_key=?""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO cloud_assets
                   (customer_key, order_number, workflow_key, asset_type, sha256, object_key,
                    storage_backend, content_type, file_size, display_name, source_site, asset_key)
                   VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        conn.commit()
        return {
            "asset_key": asset_key,
            "customer_key": customer_key,
            "order_number": order_number,
            "workflow_key": workflow_key,
            "asset_type": "IMAGE",
            "sha256": sha256_hex,
            "object_key": object_key,
            "storage_backend": storage_backend,
            "content_type": content_type,
            "file_size": int(file_size),
            "display_name": display_name,
            "source_site": source_site,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _head_backend_object(backend, object_key):
    s3, cfg = _backend_client(backend)
    try:
        return s3.head_object(Bucket=cfg["bucket_name"], Key=object_key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise


def _health_one(backend):
    cfg = _backend_config(backend, required=False)
    if not cfg["configured"]:
        return {"status": "not_configured", "missing": cfg["missing"]}
    try:
        s3 = _b2_client(cfg)
        s3.list_objects_v2(Bucket=cfg["bucket_name"], MaxKeys=1)
        return {"status": "ok", "bucket": cfg["bucket_name"]}
    except Exception as exc:
        result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:400]}
        if isinstance(exc, ClientError):
            result["http_status"] = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            result["error_code"] = exc.response.get("Error", {}).get("Code")
        return result


def backend_health(force=False):
    primary = _health_one("b2_primary")
    secondary = _health_one("b2_secondary")
    selected = ""
    if primary.get("status") == "ok":
        selected = "b2_primary"
    elif secondary.get("status") == "ok":
        selected = "b2_secondary"
    return {
        "selected": selected,
        "primary": primary,
        "secondary": secondary,
    }


def _select_backend(avoid_backend=""):
    avoid_backend = str(avoid_backend or "").strip().lower()
    health = backend_health(force=True)
    candidates = ["b2_primary", "b2_secondary"]
    if avoid_backend in BACKENDS:
        candidates = [x for x in candidates if x != avoid_backend] + [avoid_backend]
    for backend in candidates:
        item = health["primary"] if backend == "b2_primary" else health["secondary"]
        if item.get("status") == "ok":
            return backend, health
    raise RuntimeError("Primary / Secondary B2 are unavailable")


def direct_presign(order_number, workflow_key, sha256_hex, content_type, file_size,
                   source_site=None, avoid_backend=None):
    """Return a short-lived B2 PUT URL or reuse an already-present object."""
    _validate_order_target(order_number, workflow_key)
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    file_size = int(file_size or 0)
    if file_size < 1 or file_size > MAX_IMAGE_BYTES:
        raise ValueError("file_size is invalid")
    object_key = _object_key(sha256_hex, content_type)

    # Reuse an object from either readable backend before creating a new upload.
    health = backend_health(force=True)
    ordered = ["b2_primary", "b2_secondary"]
    if str(avoid_backend or "").strip().lower() in BACKENDS:
        avoided = str(avoid_backend).strip().lower()
        ordered = [x for x in ordered if x != avoided] + [avoided]
    for backend in ordered:
        h = health["primary"] if backend == "b2_primary" else health["secondary"]
        if h.get("status") != "ok":
            continue
        info = _head_backend_object(backend, object_key)
        if info is not None:
            actual_size = int(info.get("ContentLength") or 0)
            return {
                "exists": True,
                "sha256": sha256_hex,
                "content_type": content_type,
                "file_size": actual_size or file_size,
                "object_key": object_key,
                "storage_backend": backend,
                "upload_url": "",
                "backend_selection": {
                    "primary_status": health["primary"].get("status"),
                    "secondary_status": health["secondary"].get("status"),
                },
            }

    backend, health = _select_backend(avoid_backend=avoid_backend)
    s3, cfg = _backend_client(backend)
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": cfg["bucket_name"], "Key": object_key, "ContentType": content_type},
        ExpiresIn=300,
        HttpMethod="PUT",
    )
    return {
        "exists": False,
        "sha256": sha256_hex,
        "content_type": content_type,
        "file_size": file_size,
        "object_key": object_key,
        "storage_backend": backend,
        "upload_url": upload_url,
        "backend_selection": {
            "primary_status": health["primary"].get("status"),
            "secondary_status": health["secondary"].get("status"),
        },
    }


def direct_register(order_number, workflow_key, sha256_hex, content_type, file_size,
                    object_key, storage_backend, source_site=None):
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _validate_object_key(object_key, sha256_hex, content_type)
    storage_backend = str(storage_backend or "b2_primary").strip().lower()
    if storage_backend not in BACKENDS:
        raise ValueError("invalid storage_backend")
    info = _head_backend_object(storage_backend, object_key)
    if info is None:
        raise ValueError("image is not present in selected B2")
    actual_size = int(info.get("ContentLength") or 0)
    expected_size = int(file_size or 0)
    if expected_size and actual_size and expected_size != actual_size:
        raise ValueError("uploaded image size does not match")
    result = _upsert_asset_metadata(
        order_number, workflow_key, sha256_hex, object_key, content_type,
        actual_size or expected_size, source_site=source_site, storage_backend=storage_backend,
    )
    result["deduplicated"] = False
    result["uploaded_to_b2"] = True
    result["direct_upload"] = True
    return result


def check_image_hash(sha256_hex, content_type):
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _object_key(sha256_hex, content_type)
    health = backend_health(force=True)
    for backend in BACKENDS:
        h = health["primary"] if backend == "b2_primary" else health["secondary"]
        if h.get("status") != "ok":
            continue
        info = _head_backend_object(backend, object_key)
        if info is not None:
            return {
                "exists": True, "sha256": sha256_hex, "content_type": content_type,
                "file_size": int(info.get("ContentLength") or 0), "storage_backend": backend,
            }
    return {"exists": False, "sha256": sha256_hex, "content_type": content_type, "file_size": None}


def register_existing_image(order_number, workflow_key, sha256_hex, content_type, source_site=None):
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _object_key(sha256_hex, content_type)
    health = backend_health(force=True)
    for backend in BACKENDS:
        h = health["primary"] if backend == "b2_primary" else health["secondary"]
        if h.get("status") != "ok":
            continue
        info = _head_backend_object(backend, object_key)
        if info is None:
            continue
        result = _upsert_asset_metadata(
            order_number, workflow_key, sha256_hex, object_key, content_type,
            int(info.get("ContentLength") or 0), source_site=source_site, storage_backend=backend,
        )
        result["deduplicated"] = True
        result["uploaded_to_b2"] = False
        return result
    raise ValueError("image hash is not present in B2")


def upload_image(order_number, workflow_key, data, content_type, source_site=None, expected_sha256=None):
    """Render-proxy fallback. Try Primary then Secondary B2."""
    content_type = _validate_content_type(content_type)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 15 MB limit")

    sha256_hex = hashlib.sha256(bytes(data)).hexdigest()
    if expected_sha256 and _validate_sha256(expected_sha256) != sha256_hex:
        raise ValueError("client sha256 does not match uploaded bytes")
    object_key = _object_key(sha256_hex, content_type)
    _validate_order_target(order_number, workflow_key)

    health = backend_health(force=True)
    errors = []
    for backend in BACKENDS:
        h = health["primary"] if backend == "b2_primary" else health["secondary"]
        if h.get("status") != "ok":
            continue
        try:
            s3, cfg = _backend_client(backend)
            uploaded_to_b2 = False
            try:
                info = s3.head_object(Bucket=cfg["bucket_name"], Key=object_key)
                existing_size = int(info.get("ContentLength") or 0)
                if existing_size and existing_size != len(data):
                    raise RuntimeError("B2 object size mismatch for existing SHA-256 key")
            except ClientError as exc:
                if not _is_not_found(exc):
                    raise
                s3.put_object(
                    Bucket=cfg["bucket_name"], Key=object_key, Body=bytes(data),
                    ContentType=content_type,
                )
                uploaded_to_b2 = True
            result = _upsert_asset_metadata(
                order_number, workflow_key, sha256_hex, object_key, content_type, len(data),
                source_site=source_site, storage_backend=backend,
            )
            result["deduplicated"] = not uploaded_to_b2
            result["uploaded_to_b2"] = uploaded_to_b2
            result["proxy_fallback"] = True
            return result
        except Exception as exc:
            errors.append(f"{backend}: {type(exc).__name__}: {exc}")
    raise RuntimeError("proxy upload failed on all B2 backends: " + " | ".join(errors[-4:]))


def list_customer_assets(customer_key):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, storage_backend, content_type, file_size, display_name,
                      source_site, updated_at
               FROM cloud_assets
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        return [_safe_row(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def attach_assets_to_space(space):
    if not space or not isinstance(space, dict):
        return space
    customer = space.get("customer") or {}
    customer_key = customer.get("customer_key")
    if not customer_key:
        return space
    by_order = {}
    for asset in list_customer_assets(customer_key):
        by_order.setdefault(asset.get("order_number"), []).append(asset)
    for order in space.get("orders") or []:
        order["assets"] = by_order.get(order.get("order_number"), [])
    return space


def get_asset(asset_key):
    asset_key = str(asset_key or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", asset_key):
        return None
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, storage_backend, content_type, file_size,
                      display_name, source_site, active
               FROM cloud_assets WHERE asset_key=? AND active=TRUE""",
            (asset_key,),
        )
        return _safe_row(cur.fetchone(), cur)
    finally:
        conn.close()


def _asset_backend(asset):
    backend = str((asset or {}).get("storage_backend") or "b2_primary").strip().lower()
    return backend if backend in BACKENDS else "b2_primary"


def read_private_asset(asset):
    if not asset or not asset.get("object_key"):
        raise ValueError("asset not found")
    object_key = str(asset["object_key"])
    if not object_key.startswith("order-cloud/images/"):
        raise ValueError("invalid asset object key")
    backend = _asset_backend(asset)
    s3, cfg = _backend_client(backend)
    try:
        obj = s3.get_object(Bucket=cfg["bucket_name"], Key=object_key)
        return obj["Body"].read(), (obj.get("ContentType") or asset.get("content_type") or "application/octet-stream")
    except ClientError as exc:
        if _is_not_found(exc):
            raise FileNotFoundError("asset object not found")
        raise


def _cdn_asset_url(asset):
    """Return the Cloudflare URL for primary-B2 images and saved thumbnails."""
    if not asset or not asset.get("object_key"):
        return None
    if _asset_backend(asset) != "b2_primary":
        return None

    base_url = (os.environ.get("ORDER_CDN_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return None

    object_key = str(asset["object_key"]).strip()
    is_image_key = object_key.startswith(("order-cloud/images/", "order-cloud/thumbs/"))
    # Existing customer WEB images predate the order-cloud/images layout.
    is_legacy_key = re.match(r"^customers/c_[0-9a-f]{24}/", object_key) is not None
    if not (is_image_key or is_legacy_key):
        return None
    return f"{base_url}/{quote(object_key, safe='/')}"


def presign_private_asset_read(asset, expires_seconds=300):
    if not asset or not asset.get("object_key"):
        raise ValueError("asset not found")
    object_key = str(asset["object_key"])
    if not object_key.startswith("order-cloud/images/"):
        raise ValueError("invalid asset object key")

    # Prefer Cloudflare for primary B2 when configured.
    cdn_url = _cdn_asset_url(asset)
    if cdn_url:
        return cdn_url

    # Safe fallback for secondary-backend assets or when CDN is not configured.
    backend = _asset_backend(asset)
    s3, cfg = _backend_client(backend)
    expires_seconds = max(60, min(int(expires_seconds or 300), 1800))
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg["bucket_name"], "Key": object_key},
        ExpiresIn=expires_seconds,
        HttpMethod="GET",
    )

def wan_storage_summary(customer_keys):
    keys = []
    for raw in customer_keys or []:
        key = str(raw or "").strip()
        if key and key not in keys:
            keys.append(key)
    health = backend_health(force=True)
    customers = {}
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        for key in keys:
            cur.execute(
                """SELECT storage_backend, COUNT(*) AS qty FROM cloud_assets
                   WHERE customer_key=? AND active=TRUE GROUP BY storage_backend""",
                (key,),
            )
            counts = {"b2_primary": 0, "b2_secondary": 0}
            for row in cur.fetchall():
                item = _safe_row(row, cur) or {}
                backend = str(item.get("storage_backend") or "b2_primary").lower()
                if backend not in counts:
                    backend = "b2_primary"
                counts[backend] += int(item.get("qty") or 0)
            customers[key] = {"total": sum(counts.values()), **counts}
    finally:
        conn.close()
    return {"customers": customers, "health": health}


def wan_repair_plan(customer_key):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        raise ValueError("customer_key is required")
    health = backend_health(force=True)
    readable = {
        "b2_primary": health["primary"].get("status") == "ok",
        "b2_secondary": health["secondary"].get("status") == "ok",
    }
    conn = get_db_connection()
    cur = get_cursor(conn)
    items = []
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                      object_key, storage_backend, content_type, file_size
               FROM cloud_assets WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        for row in cur.fetchall():
            item = _safe_row(row, cur) or {}
            backend = str(item.get("storage_backend") or "b2_primary").lower()
            if not readable.get(backend, False):
                items.append(item)
    finally:
        conn.close()
    return {
        "customer_key": customer_key,
        "selected_readable": health.get("selected") or "",
        "repair_needed": len(items),
        "items": items,
        "health": health,
    }


def direct_repair_register(asset_key, sha256_hex, content_type, file_size, object_key,
                           storage_backend, source_site=None):
    old = get_asset(asset_key)
    if not old:
        raise ValueError("asset not found")
    result = direct_register(
        old.get("order_number"), old.get("workflow_key"), sha256_hex, content_type,
        file_size, object_key, storage_backend, source_site=source_site,
    )
    if result.get("asset_key") != old.get("asset_key"):
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                "UPDATE cloud_assets SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE asset_key=?",
                (old.get("asset_key"),),
            )
            conn.commit()
        finally:
            conn.close()
    result["replaced_asset_key"] = old.get("asset_key")
    return result
