#!/usr/bin/env python3
"""Make one customer's Render/TiDB/B2 view match current local ORDER SQLite.

This is the explicit customer-share update/rebuild path. It is read-only toward the
local ORDER SQLite and never sends local filenames or paths to Render.

For the selected customer it:
1. syncs current cloud-safe ORDER/workflow/history rows from SQLite;
2. optimizes current local images only for ACTIVE orders (cancelled/skipped/unlocked
   order rows are never uploaded as customer-share media);
3. asks Render for customer-pinned direct-B2 PUTs (Render never receives image bytes);
4. reuses/relinks an existing customer+SHA physical object when order/workflow paths changed;
5. reconciles TiDB cloud_assets so its logical image rows equal the current ACTIVE SQLite rows;
6. rebuilds the existing public-share snapshot without creating/changing share tokens.

Typical Windows CMD:
    python scripts\order_cloud_sync_customer.py --from-order G26001
    python scripts\order_cloud_sync_customer.py --customer "CLIENTE ABC"

A full cloud purge is intentionally NOT performed here. Use
scripts/order_cloud_customer_storage_admin.py for the separate preview+confirm purge.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, Iterable, List, Tuple

import requests

import order_cloud_sync_real_order as order_sync
import order_cloud_sync_real_images as image_scan

MAX_CLOUD_IMAGE_BYTES = 1_000_000
MAX_EDGE = 1920


class CustomerSyncError(RuntimeError):
    pass


def _norm_customer(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _customer_identity(conn: sqlite3.Connection, customer: str | None, from_order: str | None) -> Tuple[str, str]:
    if from_order:
        row = conn.execute(
            "SELECT customer_name FROM orders WHERE order_number=? LIMIT 1",
            (str(from_order).strip(),),
        ).fetchone()
        if not row or not str(row[0] or "").strip():
            raise CustomerSyncError(f"ORDER {from_order} has no customer_name")
        name = str(row[0]).strip()
        return name, _norm_customer(name)

    wanted = _norm_customer(customer)
    if not wanted:
        raise CustomerSyncError("customer name is required")
    rows = conn.execute(
        "SELECT DISTINCT customer_name FROM orders WHERE customer_name IS NOT NULL AND customer_name<>''"
    ).fetchall()
    matches = [str(row[0]).strip() for row in rows if _norm_customer(row[0]) == wanted]
    if not matches:
        raise CustomerSyncError(f"customer not found in local SQLite: {customer}")
    return matches[0], wanted


def _customer_orders(conn: sqlite3.Connection, customer_key: str) -> List[str]:
    rows = conn.execute(
        "SELECT order_number, customer_name FROM orders WHERE order_number IS NOT NULL ORDER BY order_number"
    ).fetchall()
    result: List[str] = []
    seen = set()
    for row in rows:
        if _norm_customer(row[1]) != customer_key:
            continue
        number = str(row[0] or "").strip()
        if number and number not in seen:
            seen.add(number)
            result.append(number)
    return result


def _customer_media_orders(conn: sqlite3.Connection, customer_key: str) -> List[str]:
    """Return only local orders eligible to publish image bytes.

    ORDER lifecycle status is authoritative here. ACTIVE (and blank legacy status) may
    publish media. CANCELLED, SKIPPED, UNLOCKED and any other non-active pool/lifecycle
    states remain mirrored as metadata when applicable, but their image bytes are not
    uploaded to B2 and are omitted from the cloud_assets reconciliation manifest.
    """
    cols = image_scan._columns(conn, "orders")
    status_select = ", status" if "status" in cols else ", NULL AS status"
    rows = conn.execute(
        "SELECT order_number, customer_name" + status_select
        + " FROM orders WHERE order_number IS NOT NULL ORDER BY order_number"
    ).fetchall()
    result: List[str] = []
    seen = set()
    for row in rows:
        if _norm_customer(row[1]) != customer_key:
            continue
        lifecycle = str(row[2] or "").strip().upper()
        if lifecycle and lifecycle != "ACTIVE":
            continue
        number = str(row[0] or "").strip()
        if number and number not in seen:
            seen.add(number)
            result.append(number)
    return result


def _flatten_rgb(image):
    from PIL import Image
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_jpeg(image, quality: int) -> bytes:
    buf = BytesIO()
    image.save(
        buf,
        format="JPEG",
        quality=int(quality),
        optimize=True,
        progressive=True,
        subsampling="4:2:0",
    )
    return buf.getvalue()


def _optimized_image(path: Path, declared_type: str, cache: dict) -> Tuple[bytes, str, str]:
    stat = path.stat()
    cache_key = (str(path.resolve()).lower(), int(stat.st_size), int(stat.st_mtime_ns))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from PIL import Image, ImageOps

    raw = path.read_bytes()
    declared_type = str(declared_type or "").split(";", 1)[0].strip().lower()
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened)
        width, height = image.size
        if (
            0 < len(raw) <= MAX_CLOUD_IMAGE_BYTES
            and max(width, height) <= MAX_EDGE
            and declared_type in {"image/jpeg", "image/png", "image/webp"}
        ):
            digest = hashlib.sha256(raw).hexdigest()
            result = (raw, declared_type, digest)
            cache[cache_key] = result
            return result

        image = _flatten_rgb(image)
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        original = image.copy()
        original.thumbnail((MAX_EDGE, MAX_EDGE), resampling)

        # Keep quality high first, then reduce dimensions only if a very detailed photo
        # cannot fit below the hard 1 MB cloud policy.
        edges = [MAX_EDGE, 1728, 1536, 1365, 1200, 1024]
        qualities = [92, 90, 88, 85, 82, 78, 74, 70, 65, 60]
        best = None
        for edge in edges:
            candidate = original.copy()
            candidate.thumbnail((edge, edge), resampling)
            for quality in qualities:
                data = _encode_jpeg(candidate, quality)
                best = data
                if len(data) <= MAX_CLOUD_IMAGE_BYTES:
                    digest = hashlib.sha256(data).hexdigest()
                    result = (data, "image/jpeg", digest)
                    cache[cache_key] = result
                    return result

    raise CustomerSyncError(
        f"could not optimize image below {MAX_CLOUD_IMAGE_BYTES} bytes: {path} "
        f"(last={len(best or b'')} bytes)"
    )


def _put_direct(upload_url: str, data: bytes, content_type: str) -> None:
    try:
        response = requests.put(
            upload_url,
            data=data,
            headers={"Content-Type": content_type},
            timeout=(8, 90),
        )
    except requests.RequestException as exc:
        # Do NOT try another backend here. The next presign call will verify the same
        # B2/object intent first and only retry there if it is confirmed missing.
        raise CustomerSyncError(f"direct B2 PUT uncertain/failed: {exc}") from exc
    if not (200 <= response.status_code < 300):
        raise CustomerSyncError(f"direct B2 PUT failed HTTP {response.status_code}: {response.text[:300]}")


def _publish_blob(order_number: str, workflow_key: str | None, data: bytes,
                  content_type: str, digest: str) -> Dict[str, Any]:
    presign = order_sync._request_json(
        "POST",
        "/api/order-cloud/assets/direct-presign",
        json={
            "variant": "image",
            "order_number": order_number,
            "workflow_key": workflow_key,
            "sha256": digest,
            "content_type": content_type,
            "file_size": len(data),
        },
    )
    result = presign.get("result") or {}
    if result.get("exists"):
        return {"mode": "reused", "result": result}

    upload_url = str(result.get("upload_url") or "").strip()
    backend = str(result.get("storage_backend") or "").strip()
    object_key = str(result.get("object_key") or "").strip()
    if not upload_url or not backend or not object_key:
        raise CustomerSyncError(f"presign result is incomplete: {result}")

    _put_direct(upload_url, data, content_type)

    registered = order_sync._request_json(
        "POST",
        "/api/order-cloud/assets/direct-register",
        json={
            "order_number": order_number,
            "workflow_key": workflow_key,
            "sha256": digest,
            "content_type": content_type,
            "file_size": len(data),
            "storage_backend": backend,
            "object_key": object_key,
        },
    ).get("result") or {}
    return {"mode": "uploaded", "result": registered}


def _local_customer_media(conn: sqlite3.Connection, upload_folder: Path,
                          order_numbers: Iterable[str], optimize_cache: dict) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for order_number in order_numbers:
        for item in image_scan._image_rows(conn, upload_folder, order_number):
            path = item.get("path")
            if not isinstance(path, Path) or not path.is_file():
                continue
            data, content_type, digest = _optimized_image(path, item.get("content_type") or "", optimize_cache)
            key = (str(order_number), str(item.get("workflow_key") or ""), digest)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "order_number": str(order_number),
                "workflow_key": str(item.get("workflow_key") or "").strip() or None,
                "sha256": digest,
                "content_type": content_type,
                "data": data,
                "source": item.get("source"),
                "source_id": item.get("source_id"),
            })
    return result


def sync_customer(customer: str | None, from_order: str | None, dry_run: bool = False) -> Dict[str, Any]:
    config_path, db_path, upload_folder = image_scan._load_order_config()
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    optimize_cache: dict = {}
    try:
        customer_name, customer_key = _customer_identity(conn, customer, from_order)
        order_numbers = _customer_orders(conn, customer_key)
        media_order_numbers = _customer_media_orders(conn, customer_key)
        if not order_numbers:
            raise CustomerSyncError(f"customer has no local orders: {customer_name}")

        order_payloads = []
        for number in order_numbers:
            try:
                payload = order_sync._load_order_payload(conn, number)
            except order_sync.SyncError as exc:
                # Placeholder rows with no compatible cloud customer are not part of this
                # exact customer's usable share set.
                if "has no customer_name" in str(exc):
                    continue
                raise
            if str(payload.get("customer_key") or "") == customer_key:
                order_payloads.append(payload)

        media = _local_customer_media(conn, upload_folder, media_order_numbers, optimize_cache)
    finally:
        conn.close()

    print(f"ORDER config: {config_path}")
    print(f"ORDER SQLite: {db_path}")
    print(f"Customer: {customer_name} | key={customer_key}")
    print(
        f"Orders mirrored: {len(order_payloads)} | media-active orders: {len(media_order_numbers)} "
        f"| current local images to publish: {len(media)}"
    )
    print("Cancelled/skipped/unlocked order images: NOT UPLOADED")
    print("Local filenames/paths: NOT SENT")

    if dry_run:
        by_size = sum(len(item["data"]) for item in media)
        return {
            "customer_key": customer_key,
            "orders": len(order_payloads),
            "media_orders": len(media_order_numbers),
            "images": len(media),
            "optimized_bytes": by_size,
            "dry_run": True,
        }

    health = order_sync._request_json("GET", "/api/order-cloud/health")
    if not health.get("ok"):
        raise CustomerSyncError("Render ORDER cloud gateway is not ready")

    # ORDER/workflow/history first, so direct-presign can validate canonical ownership.
    for index, payload in enumerate(order_payloads, 1):
        order_sync._request_json("POST", "/api/order-cloud/sync/order", json=payload)
        print(f"ORDER {index}/{len(order_payloads)} synced: {payload.get('order_number')}")

    status = order_sync._request_json(
        "POST",
        "/api/order-cloud/storage/customer/status",
        json={"customer_key": customer_key},
    ).get("result") or {}
    print(
        "Customer B2: " + str(status.get("assigned_backend") or "?")
        + " | existing=" + str(status.get("existing_distribution") or {})
    )

    uploaded = reused = 0
    manifest: List[Dict[str, Any]] = []
    for index, item in enumerate(media, 1):
        out = _publish_blob(
            item["order_number"], item.get("workflow_key"), item["data"],
            item["content_type"], item["sha256"],
        )
        if out["mode"] == "uploaded":
            uploaded += 1
        else:
            reused += 1
        manifest.append({
            "order_number": item["order_number"],
            "workflow_key": item.get("workflow_key"),
            "sha256": item["sha256"],
        })
        mode = str((out.get("result") or {}).get("upload_mode") or out["mode"])
        backend = str((out.get("result") or {}).get("storage_backend") or "?")
        print(f"IMAGE {index}/{len(media)} OK: {mode} -> {backend}")

    # Only reconcile after every current local image has been successfully linked/uploaded.
    # This is the point where TiDB logical image membership becomes exactly the image
    # manifest from ACTIVE local ORDER rows. Cancelled/non-active image metadata is removed.
    reconciled = order_sync._request_json(
        "POST",
        "/api/order-cloud/assets/reconcile",
        json={
            "customer_key": customer_key,
            "items": manifest,
            "confirm_empty": not bool(manifest),
        },
    ).get("result") or {}

    refreshed = order_sync._request_json(
        "POST",
        "/api/order-cloud/share/refresh",
        json={"customer_key": customer_key},
    ).get("result") or {}

    print(
        f"MEDIA ALIGN OK: uploaded={uploaded} reused/relinked={reused} "
        f"stale_tidb_removed={int(reconciled.get('stale_metadata_removed') or 0)}"
    )
    print(
        "EXISTING SHARES REFRESHED: token unchanged | "
        f"orders={refreshed.get('orders')} assets={refreshed.get('assets')}"
    )
    return {
        "customer_key": customer_key,
        "orders": len(order_payloads),
        "media_orders": len(media_order_numbers),
        "images": len(media),
        "uploaded": uploaded,
        "reused": reused,
        "reconcile": reconciled,
        "refresh": refreshed,
        "dry_run": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Align one customer's ORDER SQLite -> TiDB/B2/share")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--customer", help="exact customer name from local ORDER")
    group.add_argument("--from-order", help="pick the customer from this local ORDER number")
    parser.add_argument("--dry-run", action="store_true", help="read/hash/optimize only; do not write cloud data")
    args = parser.parse_args()

    try:
        sync_customer(args.customer, args.from_order, dry_run=bool(args.dry_run))
        return 0
    except (CustomerSyncError, order_sync.SyncError, image_scan.ImageSyncError) as exc:
        print(f"CUSTOMER CLOUD SYNC ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("CUSTOMER CLOUD SYNC CANCELLED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
