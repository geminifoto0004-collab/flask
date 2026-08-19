"""Private B2 asset storage for ORDER customer sharing.

Security/design rules:
- B2 credentials exist only on Render.
- Original client filenames are never stored; they may contain phone/private data.
- Images are addressed by SHA-256 so identical bytes reuse the same B2 object.
- TiDB stores only safe relationship metadata needed to render a customer space.
- Public reads are still gated by the customer share token in the Flask route.
"""

import hashlib
import os
import re

import boto3
from botocore.exceptions import ClientError

from database import get_cursor, get_db_connection, get_row_dict


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def _b2_config():
    cfg = {
        "key_id": (os.environ.get("B2_KEY_ID") or "").strip(),
        "application_key": (os.environ.get("B2_APPLICATION_KEY") or "").strip(),
        "bucket_name": (os.environ.get("B2_BUCKET_NAME") or "").strip(),
        "endpoint": (os.environ.get("B2_ENDPOINT") or "").strip().rstrip("/"),
    }
    missing = [
        env_name
        for env_name, value in (
            ("B2_KEY_ID", cfg["key_id"]),
            ("B2_APPLICATION_KEY", cfg["application_key"]),
            ("B2_BUCKET_NAME", cfg["bucket_name"]),
            ("B2_ENDPOINT", cfg["endpoint"]),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing B2 configuration: " + ", ".join(missing))
    return cfg


def _b2_client(cfg=None):
    cfg = cfg or _b2_config()
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["application_key"],
    )


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


def init_order_cloud_asset_table():
    """Create the isolated safe asset metadata table."""
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


def _asset_key(order_number, workflow_key, sha256_hex):
    material = f"IMAGE\0{order_number}\0{workflow_key or ''}\0{sha256_hex}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _upsert_asset_metadata(order_number, workflow_key, sha256_hex, object_key, content_type, file_size, source_site=None):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        order_number, customer_key, workflow_key = _resolve_order_and_workflow(cur, order_number, workflow_key)
        asset_key = _asset_key(order_number, workflow_key, sha256_hex)
        display_name = f"Imagen {order_number}"
        source_site = str(source_site or "").strip().upper()[:16] or None

        cur.execute("SELECT asset_key FROM cloud_assets WHERE asset_key=?", (asset_key,))
        values = (
            customer_key,
            order_number,
            workflow_key,
            sha256_hex,
            object_key,
            content_type,
            int(file_size),
            display_name,
            source_site,
            asset_key,
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_assets
                   SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                       sha256=?, object_key=?, content_type=?, file_size=?, display_name=?,
                       source_site=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                   WHERE asset_key=?""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO cloud_assets
                   (customer_key, order_number, workflow_key, asset_type, sha256,
                    object_key, content_type, file_size, display_name, source_site, asset_key)
                   VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?)""",
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


def check_image_hash(sha256_hex, content_type):
    """Preflight check used by clients to avoid uploading bytes already present in B2."""
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _object_key(sha256_hex, content_type)
    cfg = _b2_config()
    try:
        info = _b2_client(cfg).head_object(Bucket=cfg["bucket_name"], Key=object_key)
        return {"exists": True, "sha256": sha256_hex, "content_type": content_type, "file_size": int(info.get("ContentLength") or 0)}
    except ClientError as exc:
        if _is_not_found(exc):
            return {"exists": False, "sha256": sha256_hex, "content_type": content_type, "file_size": None}
        raise


def register_existing_image(order_number, workflow_key, sha256_hex, content_type, source_site=None):
    """Attach an already-present content-addressed B2 image to an ORDER row."""
    sha256_hex = _validate_sha256(sha256_hex)
    content_type = _validate_content_type(content_type)
    object_key = _object_key(sha256_hex, content_type)
    cfg = _b2_config()
    try:
        info = _b2_client(cfg).head_object(Bucket=cfg["bucket_name"], Key=object_key)
    except ClientError as exc:
        if _is_not_found(exc):
            raise ValueError("image hash is not present in B2")
        raise
    result = _upsert_asset_metadata(
        order_number,
        workflow_key,
        sha256_hex,
        object_key,
        content_type,
        int(info.get("ContentLength") or 0),
        source_site=source_site,
    )
    result["deduplicated"] = True
    result["uploaded_to_b2"] = False
    return result


def upload_image(order_number, workflow_key, data, content_type, source_site=None, expected_sha256=None):
    """Hash, deduplicate, upload if needed, then attach an image to an ORDER row."""
    content_type = _validate_content_type(content_type)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 15 MB limit")

    sha256_hex = hashlib.sha256(bytes(data)).hexdigest()
    if expected_sha256:
        expected = _validate_sha256(expected_sha256)
        if expected != sha256_hex:
            raise ValueError("client sha256 does not match uploaded bytes")

    object_key = _object_key(sha256_hex, content_type)
    cfg = _b2_config()
    s3 = _b2_client(cfg)
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
            Bucket=cfg["bucket_name"],
            Key=object_key,
            Body=bytes(data),
            ContentType=content_type,
            Metadata={"sha256": sha256_hex},
        )
        uploaded_to_b2 = True

    result = _upsert_asset_metadata(
        order_number,
        workflow_key,
        sha256_hex,
        object_key,
        content_type,
        len(data),
        source_site=source_site,
    )
    result["deduplicated"] = not uploaded_to_b2
    result["uploaded_to_b2"] = uploaded_to_b2
    return result


def list_customer_assets(customer_key):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, content_type, file_size, display_name, source_site, updated_at
               FROM cloud_assets
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        return [_safe_row(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def attach_assets_to_space(space):
    """Add safe asset metadata to the already-safe customer-space structure."""
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
                      sha256, object_key, content_type, file_size, display_name, source_site
               FROM cloud_assets WHERE asset_key=? AND active=TRUE""",
            (asset_key,),
        )
        return _safe_row(cur.fetchone(), cur)
    finally:
        conn.close()


def read_private_asset(asset):
    """Read a private B2 object after the caller has already authorized the token."""
    if not asset or not asset.get("object_key"):
        raise ValueError("asset not found")
    object_key = str(asset["object_key"])
    if not object_key.startswith("order-cloud/images/"):
        raise ValueError("invalid asset object key")
    cfg = _b2_config()
    try:
        obj = _b2_client(cfg).get_object(Bucket=cfg["bucket_name"], Key=object_key)
        return obj["Body"].read(), (obj.get("ContentType") or asset.get("content_type") or "application/octet-stream")
    except ClientError as exc:
        if _is_not_found(exc):
            raise FileNotFoundError("asset object not found")
        raise
