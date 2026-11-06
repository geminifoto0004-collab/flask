"""Private B2 asset storage for ORDER customer sharing.

Supports both legacy Render-proxy uploads and direct PC -> B2 presigned PUT uploads.
Metadata remains in TiDB and public reads stay protected by the share-token route.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
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


def _head_backend_object(backend, object_key, client_cfg=None):
    s3, cfg = client_cfg or _backend_client(backend)
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


def check_image_hash_batch(items, max_workers=12):
    """Check up to 500 B2 image hashes with one backend-health probe per batch."""
    if not isinstance(items, list) or not 1 <= len(items) <= 500:
        raise ValueError("check-batch expects 1..500 items")
    unique = {}
    seen_ids = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("each check item must be an object")
        client_id = str(raw.get("client_id") or "").strip()
        if not client_id or len(client_id) > 64 or client_id in seen_ids:
            raise ValueError("client_id must be unique and 1..64 characters")
        seen_ids.add(client_id)
        sha256_hex = _validate_sha256(raw.get("sha256"))
        content_type = _validate_content_type(raw.get("content_type"))
        object_key = _object_key(sha256_hex, content_type)
        key = (sha256_hex, content_type)
        row = unique.setdefault(key, {
            "sha256": sha256_hex, "content_type": content_type,
            "object_key": object_key, "client_ids": [],
        })
        row["client_ids"].append(client_id)

    # Health checks are expensive (one S3 list request per configured bucket).
    # Do them once for the batch, not once for every image.
    health = backend_health(force=True)
    readable = []
    unavailable = []
    for backend in BACKENDS:
        health_row = (health.get("primary") if backend == "b2_primary" else health.get("secondary")) or {}
        status = health_row.get("status")
        if status == "ok":
            readable.append(backend)
        elif status == "error":
            unavailable.append(backend)
    if not readable:
        raise RuntimeError("no readable B2 backend is available for batch verification")
    # Reuse one boto3 client per backend across all worker threads in this batch.
    backend_clients = {backend: _backend_client(backend) for backend in readable}

    def inspect(item):
        errors = []
        for backend in readable:
            try:
                info = _head_backend_object(backend, item["object_key"], client_cfg=backend_clients[backend])
            except Exception as exc:
                errors.append(f"{backend}: {type(exc).__name__}: {exc}")
                continue
            if info is not None:
                return {"ok": True, "result": {
                    "exists": True, "sha256": item["sha256"],
                    "content_type": item["content_type"],
                    "file_size": int(info.get("ContentLength") or 0),
                    "storage_backend": backend,
                }}
        if unavailable or errors:
            return {"ok": False, "error": (errors or ["a configured B2 backend is unavailable; absence cannot be confirmed"])[0][:300]}
        return {"ok": True, "result": {
            "exists": False, "sha256": item["sha256"],
            "content_type": item["content_type"], "file_size": None,
        }}

    rows = list(unique.values())
    workers = max(1, min(int(max_workers or 12), 16, len(rows)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        inspected = list(pool.map(inspect, rows))

    results = []
    for item, outcome in zip(rows, inspected):
        for client_id in item["client_ids"]:
            results.append({"client_id": client_id, **outcome})
    return {
        "items": results,
        "unique_count": len(rows),
        "checked_count": len(rows),
        "backend_health": health,
    }


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


_DELTA_MAX_ORDERS = 2000
_SQL_ORDER_CHUNK = 500


def _order_json(payload, *, sort_keys=True):
    return json.dumps(payload, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"), default=str)


def _sql_chunks(keys):
    for offset in range(0, len(keys), _SQL_ORDER_CHUNK):
        yield tuple(keys[offset:offset + _SQL_ORDER_CHUNK])


def _delete_keys(cur, table, column, keys):
    for part in _sql_chunks(keys):
        cur.execute(f"DELETE FROM {table} WHERE {column} IN (" + ",".join(["?"] * len(part)) + ")", part)


def probe_order_deltas(fingerprints, *, include_new=False):
    """Read indexed order digests from the current TiDB without fetching payloads."""
    if not isinstance(fingerprints, dict) or not 1 <= len(fingerprints) <= _DELTA_MAX_ORDERS:
        raise ValueError("fingerprints must contain 1..2000 orders")
    numbers = {}
    for number, digest in fingerprints.items():
        if not isinstance(number, str) or not number or number != number.strip() or len(number) > 191:
            raise ValueError("invalid order_number")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid order fingerprint")
        numbers[number.casefold()] = number
    if len(numbers) != len(fingerprints):
        raise ValueError("duplicate order_number in fingerprints")
    changed = dict.fromkeys(fingerprints, "")
    found = set()
    conn = get_db_connection()
    try:
        target = getattr(conn, "active_target", "")
        cur = get_cursor(conn)
        cur.execute(
            "SELECT order_number, active, SHA2(render_payload, 256) AS digest "
            "FROM cloud_orders WHERE order_number IN (" + ",".join(["?"] * len(fingerprints)) + ")",
            tuple(fingerprints),
        )
        for raw in cur.fetchall():
            row = get_row_dict(raw, cur)
            number = numbers.get(row["order_number"].casefold())
            if number is not None:
                found.add(number)
            if number is None:
                continue
            if row["active"] and row["digest"] == fingerprints[number]:
                del changed[number]
    finally:
        conn.close()
    result = {"changed": changed, "target": target}
    if include_new:
        result["new"] = [key for key in fingerprints if key not in found]
    return result


def _validate_order_batch(orders, limit):
    if not isinstance(orders, list) or not 1 <= len(orders) <= limit:
        raise ValueError(f"expected 1..{limit} orders")
    seen_numbers = set()
    for payload in orders:
        if not isinstance(payload, dict):
            raise ValueError("each order must be an object")
        number = str(payload.get("order_number") or "").strip()
        name = str(payload.get("customer_name") or "").strip()
        if not number or not name:
            raise ValueError("order_number and customer_name are required")
        if number.casefold() in seen_numbers:
            raise ValueError("duplicate order_number in batch")
        seen_numbers.add(number.casefold())
        if not isinstance(payload.get("workflows") or [], list):
            raise ValueError("workflows must be a list")


def _write_order_rows(cur, part, source_site, *, changed_only, upsert_only=False):
    numbers = tuple(str(row["order_number"]).strip() for row in part)
    written = []
    all_customers = set()
    total_timeline = 0
    customers = {}
    order_rows = []
    workflow_rows = []
    history_rows = []
    workflow_by_order = {}
    history_by_workflow = {}
    existing_orders = {}
    cur.execute(
        "SELECT order_number, customer_key, active, render_payload FROM cloud_orders "
        "WHERE order_number IN (" + ",".join(["?"] * len(numbers)) + ")" +
        (" FOR UPDATE" if changed_only else ""), numbers,
    )
    for raw in cur.fetchall():
        row = get_row_dict(raw, cur)
        existing_orders[row["order_number"].casefold()] = row
    from services.order_cloud_service import _preserve_existing_logistics
    for original in part:
        number = str(original["order_number"]).strip()
        name = str(original["customer_name"]).strip()
        key = str(original.get("customer_key") or name).strip()
        if not key:
            raise ValueError("customer_key is required")
        existing = existing_orders.get(number.casefold(), {})
        prior = existing.get("render_payload")
        p = _preserve_existing_logistics(original, prior)
        encoded = _order_json(p, sort_keys=changed_only)
        same_order = changed_only and existing.get("active") and existing.get("customer_key") == key
        if same_order and prior == encoded:
            continue
        written.append(number)
        all_customers.add(key)
        if changed_only and existing.get("customer_key"):
            all_customers.add(existing["customer_key"])
        previous = {}
        if same_order and prior:
            try:
                previous = json.loads(prior)
            except ValueError:
                pass
        if not isinstance(previous, dict) or previous.get("customer_name") != p.get("customer_name"):
            customers[key] = name
        order_rows.append((
            number, key, name,
            p.get("order_status") or p.get("current_status"),
            p.get("order_date"),
            p.get("expected_delivery_date") or p.get("delivery_date"),
            p.get("production_type"), p.get("product_name"),
            p.get("product_code"), p.get("pattern_code"),
            str(p["quantity"]) if p.get("quantity") is not None else None,
            source_site,
            encoded,
        ))
        if same_order and isinstance(previous, dict) and previous.get("workflows") == p.get("workflows"):
            continue
        wf_keys = set()
        for pos, wf in enumerate(p.get("workflows") or []):
            if not isinstance(wf, dict):
                continue
            wf_number = str(wf.get("workflow_number") or "").strip()
            wf_key = str(wf.get("workflow_key") or wf_number or wf.get("id") or (number + ":" + str(pos))).strip()
            if not wf_key:
                continue
            wf_keys.add(wf_key.casefold())
            workflow_rows.append((
                wf_key, number, wf_number or wf_key,
                wf.get("workflow_type") or wf.get("production_type") or wf.get("type"),
                wf.get("status") or wf.get("current_status"),
                wf.get("production_type"), wf.get("product_name"), wf.get("product_code"),
                str(wf["quantity"]) if wf.get("quantity") is not None else None,
                wf.get("expected_delivery_date"), wf.get("last_status_change_date"),
                wf.get("draft_date"), int(wf.get("sort_order", pos) or 0),
            ))
            timeline_present = "timeline" in wf or "history" in wf
            if not timeline_present:
                continue
            timeline = wf.get("timeline") if "timeline" in wf else wf.get("history")
            timeline = [] if timeline is None else timeline
            if not isinstance(timeline, list):
                raise ValueError("timeline must be a list")
            hist_keys = set()
            for hpos, item in enumerate(timeline):
                if not isinstance(item, dict):
                    continue
                hist_key = str(item.get("history_key") or item.get("id") or
                               (wf_key + ":" + str(hpos) + ":" + str(item.get("status") or item.get("to_status") or "") +
                                ":" + str(item.get("action_date") or ""))).strip()
                if not hist_key:
                    continue
                hist_keys.add(hist_key.casefold())
                history_rows.append((
                    hist_key, wf_key, number, item.get("status") or item.get("to_status"),
                    item.get("action_date"), int(item.get("sort_order", hpos) or 0)
                ))
                total_timeline += 1
            history_by_workflow[wf_key] = hist_keys
        workflow_by_order[number] = wf_keys
    if not written:
        return written, all_customers, 0
    if customers:
        cur.executemany(
            "INSERT INTO cloud_customers (customer_key,customer_name,source_site) VALUES (?,?,?) "
            "ON DUPLICATE KEY UPDATE customer_name=VALUES(customer_name),active=TRUE,"
            "source_site=VALUES(source_site),updated_at=CURRENT_TIMESTAMP",
            [(key, name, source_site) for key, name in customers.items()],
        )
    cur.executemany(
        "INSERT INTO cloud_orders "
        "(order_number,customer_key,customer_name,order_status,order_date,expected_delivery_date,"
        "production_type,product_name,product_code,pattern_code,quantity,source_site,render_payload) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE "
        "customer_key=VALUES(customer_key),customer_name=VALUES(customer_name),"
        "order_status=VALUES(order_status),order_date=VALUES(order_date),"
        "expected_delivery_date=VALUES(expected_delivery_date),"
        "production_type=VALUES(production_type),product_name=VALUES(product_name),"
        "product_code=VALUES(product_code),pattern_code=VALUES(pattern_code),"
        "quantity=VALUES(quantity),source_site=VALUES(source_site),"
        "render_payload=VALUES(render_payload),active=TRUE,updated_at=CURRENT_TIMESTAMP",
        order_rows)
    if workflow_rows:
        cur.executemany(
            "INSERT INTO cloud_workflows "
            "(workflow_key,order_number,workflow_number,workflow_type,status,production_type,"
            "product_name,product_code,quantity,expected_delivery_date,last_status_change_date,"
            "draft_date,sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON DUPLICATE KEY UPDATE order_number=VALUES(order_number),"
            "workflow_number=VALUES(workflow_number),workflow_type=VALUES(workflow_type),"
            "status=VALUES(status),production_type=VALUES(production_type),"
            "product_name=VALUES(product_name),product_code=VALUES(product_code),"
            "quantity=VALUES(quantity),expected_delivery_date=VALUES(expected_delivery_date),"
            "last_status_change_date=VALUES(last_status_change_date),draft_date=VALUES(draft_date),"
            "sort_order=VALUES(sort_order),active=TRUE,updated_at=CURRENT_TIMESTAMP",
            workflow_rows)
    if history_rows:
        cur.executemany(
            "INSERT INTO cloud_workflow_history "
            "(history_key,workflow_key,order_number,status,action_date,sort_order) "
            "VALUES (?,?,?,?,?,?) ON DUPLICATE KEY UPDATE "
            "workflow_key=VALUES(workflow_key),order_number=VALUES(order_number),"
            "status=VALUES(status),action_date=VALUES(action_date),"
            "sort_order=VALUES(sort_order),active=TRUE,updated_at=CURRENT_TIMESTAMP",
            history_rows)
    # B-mode is strictly non-destructive: never delete workflow/history rows.
    # Other callers retain their previous authoritative replacement semantics.
    if not upsert_only:
        # Only reconcile orders whose workflow snapshot is being written.
        stale_workflows = []
        if workflow_by_order:
            keys = tuple(workflow_by_order)
            normalized = {key.casefold(): values for key, values in workflow_by_order.items()}
            cur.execute(
                "SELECT workflow_key,order_number FROM cloud_workflows WHERE order_number IN ("
                + ",".join(["?"] * len(keys)) + ")", keys,
            )
            for raw in cur.fetchall():
                row = get_row_dict(raw, cur)
                if row["workflow_key"].casefold() not in normalized.get(row["order_number"].casefold(), ()):
                    stale_workflows.append(row["workflow_key"])
        stale_history = []
        normalized = {key.casefold(): values for key, values in history_by_workflow.items()}
        for keys in _sql_chunks(tuple(history_by_workflow)):
            cur.execute(
                "SELECT workflow_key,history_key FROM cloud_workflow_history WHERE workflow_key IN ("
                + ",".join(["?"] * len(keys)) + ")", keys,
            )
            for raw in cur.fetchall():
                row = get_row_dict(raw, cur)
                if row["history_key"].casefold() not in normalized.get(row["workflow_key"].casefold(), ()):
                    stale_history.append(row["history_key"])
        _delete_keys(cur, "cloud_workflow_history", "history_key", stale_history)
        _delete_keys(cur, "cloud_workflow_history", "workflow_key", stale_workflows)
        _delete_keys(cur, "cloud_workflows", "workflow_key", stale_workflows)
    
    return written, all_customers, total_timeline


def ensure_order_owners_fast_batch(orders, source_site=None, *, expected_target=None, upsert_only=False):
    """Apply ORDER, workflow and history rows in grouped SQL operations."""
    changed_only = expected_target is not None
    limit = _DELTA_MAX_ORDERS if changed_only else 200
    _validate_order_batch(orders, limit)
    source_site = str(source_site or "").strip().upper()[:16] or None
    if changed_only and any(not isinstance(row.get("workflows"), list) or
                            not isinstance(row.get("logistics"), list) for row in orders):
        raise ValueError("delta orders require workflows and logistics lists")
    written, customers, total_timeline = [], set(), 0
    conn = get_db_connection()
    try:
        if changed_only and getattr(conn, "active_target", "") != expected_target:
            raise ValueError("TiDB target changed after comparison; run sync again")
        cur = get_cursor(conn)
        if changed_only:
            orders = sorted(orders, key=lambda row: str(row["order_number"]).strip())
        size = _SQL_ORDER_CHUNK if changed_only else 100
        for offset in range(0, len(orders), size):
            numbers, keys, count = _write_order_rows(
                cur, orders[offset:offset + size], source_site, changed_only=changed_only,
                upsert_only=upsert_only,
            )
            written.extend(numbers)
            customers.update(keys)
            total_timeline += count
            if not changed_only:
                conn.commit()
        if changed_only and written:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    confirmed = [str(row["order_number"]).strip() for row in orders]
    return {"count": len(confirmed), "orders": confirmed, "customer_keys": sorted(customers),
            "timeline_items": total_timeline, "fast": True, "written": written}


_FAST_REFRESH_LOCK = __import__("threading").Lock()
_FAST_REFRESH_QUEUED = set()
_FAST_REFRESH_THREAD = None

def fast_refresh_shared_customers(customer_keys):
    """Refresh only actively shared customers, serially, *after* fast import."""
    import threading
    global _FAST_REFRESH_THREAD
    keys = sorted(set(str(x or "").strip() for x in customer_keys if str(x or "").strip()))
    if not keys:
        return {"queued":0}
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        active = set()
        for part in _sql_chunks(keys):
            cur.execute("SELECT DISTINCT customer_key FROM cloud_share_tokens WHERE status='active' "
                        "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
                        "AND customer_key IN (" + ",".join(["?"]*len(part)) + ")", tuple(part))
            active.update(str((get_row_dict(r,cur) or {}).get("customer_key") or "") for r in cur.fetchall())
    finally:
        conn.close()
    with _FAST_REFRESH_LOCK:
        _FAST_REFRESH_QUEUED.update(active)
        if _FAST_REFRESH_THREAD is None or not _FAST_REFRESH_THREAD.is_alive():
            def worker():
                global _FAST_REFRESH_THREAD
                from services.order_customer_share_snapshot import rebuild_snapshot
                from services.order_public_share_fast import invalidate_customer_space_cache
                while True:
                    with _FAST_REFRESH_LOCK:
                        if not _FAST_REFRESH_QUEUED:
                            _FAST_REFRESH_THREAD = None
                            return
                        customer = _FAST_REFRESH_QUEUED.pop()
                    try:
                        rebuild_snapshot(customer)
                        invalidate_customer_space_cache(customer)
                    except Exception as exc:
                        print("[ORDER Fast Restore] snapshot refresh deferred: " + type(exc).__name__, flush=True)
                        from services.order_customer_share_snapshot import queue_snapshot_refresh
                        queue_snapshot_refresh(customer, delay=30)
            _FAST_REFRESH_THREAD = threading.Thread(target=worker, name="order-fast-refresh", daemon=True)
            _FAST_REFRESH_THREAD.start()
        return {"queued":len(active)}
