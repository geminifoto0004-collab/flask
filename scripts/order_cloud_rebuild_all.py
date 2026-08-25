#!/usr/bin/env python3
"""Clean and rebuild all ORDER customer cloud images from the current local SQLite.

Use this only for an intentional global cleanup (for example after legacy B2-1/B2-2
cross-backend duplicates or cancelled-order images were uploaded). It is deliberately
preview-first and requires one explicit REBUILD-ALL confirmation.

Safety properties:
- local tracking.db and local attachment files are read-only;
- every known customer is preflighted before the first deletion;
- a failed/incomplete B2 scan blocks the destructive phase;
- local customers are rebuilt from current SQLite and keep existing share tokens;
- cloud-only customers absent from SQLite are purged and their derived TiDB order rows
  are reconciled to empty;
- no image bytes ever pass through Render during normal direct-B2 republish.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Dict, List, Tuple

import order_cloud_customer_storage_admin as storage_admin
import order_cloud_publish_customer as customer_publish
import order_cloud_sync_real_images as image_scan
import order_cloud_sync_real_order as order_sync
import order_cloud_sync_customer as customer_sync

CONFIRM_TEXT = "REBUILD-ALL"


def _local_customers() -> Tuple[Dict[str, str], str]:
    _config, db_path, _upload_folder = image_scan._load_order_config()
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        rows = conn.execute(
            "SELECT DISTINCT customer_name FROM orders "
            "WHERE customer_name IS NOT NULL AND TRIM(customer_name)<>'' "
            "ORDER BY customer_name"
        ).fetchall()
    finally:
        conn.close()

    result: Dict[str, str] = {}
    for row in rows:
        name = str(row[0] or "").strip()
        key = customer_sync._norm_customer(name)
        if key and key not in result:
            result[key] = name
    return result, str(db_path)


def _cloud_customers() -> Dict[str, dict]:
    result = order_sync._request_json(
        "POST", "/api/order-cloud/storage/customers", json={}
    ).get("result") or {}
    items = result.get("customers") or []
    cloud = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("customer_key") or "").strip()
        if key:
            cloud[key] = dict(item)
    return cloud


def _preflight(keys: List[str]) -> Dict[str, dict]:
    previews = {}
    total = len(keys)
    for index, key in enumerate(keys, 1):
        print(f"PREVIEW {index}/{total}: {key}")
        preview = storage_admin._call(
            "/api/order-cloud/storage/customer/purge", key, execute=False
        )
        previews[key] = preview
        errors = preview.get("scan_errors") or {}
        if errors:
            raise RuntimeError(f"B2 scan incomplete for {key}: {errors}")
        print(
            "  backend=" + str(preview.get("assigned_backend") or "?")
            + " metadata=" + str(preview.get("metadata_rows") or 0)
            + " b2=" + str(preview.get("prefix_objects") or {})
        )
    return previews


def _confirm(supplied: str | None) -> None:
    if supplied:
        if supplied != CONFIRM_TEXT:
            raise RuntimeError(f"--confirm must be exactly {CONFIRM_TEXT}")
        return
    if not sys.stdin.isatty():
        raise RuntimeError(f"interactive confirmation unavailable; pass --confirm {CONFIRM_TEXT}")
    print("\nALL customer B2 previews completed successfully.")
    print("This will delete customer cloud image objects and rebuild from current SQLite.")
    print("Local tracking.db and local image files will NOT be modified.")
    typed = input(f"Type {CONFIRM_TEXT} to continue: ").strip()
    if typed != CONFIRM_TEXT:
        raise RuntimeError("global rebuild cancelled")


def _purge_one(key: str, reset_assignment: bool = False) -> dict:
    return storage_admin._call(
        "/api/order-cloud/storage/customer/purge",
        key,
        execute=True,
        confirm=f"PURGE:{key}",
        reset_assignment=bool(reset_assignment),
    )


def _remove_cloud_only_customer(key: str) -> dict:
    result = order_sync._request_json(
        "POST",
        "/api/order-cloud/customer/reconcile-orders",
        json={"customer_key": key, "order_numbers": [], "confirm_empty": True},
    ).get("result") or {}
    # Snapshot can legitimately be absent after its final local-derived order is removed.
    order_sync._request_json(
        "POST", "/api/order-cloud/share/refresh", json={"customer_key": key}
    )
    return result


def rebuild_all(preview_only: bool, confirm: str | None) -> int:
    local, db_path = _local_customers()
    cloud = _cloud_customers()
    keys = sorted(set(local) | set(cloud))

    print(f"ORDER SQLite: {db_path}")
    print(f"Local customers: {len(local)} | cloud-known customers: {len(cloud)} | union: {len(keys)}")
    print("Cancelled/skipped/unlocked order images will not be republished.")
    print("Existing share tokens/URLs are preserved for local customers.")

    if not keys:
        print("Nothing to rebuild.")
        return 0

    _preflight(keys)
    if preview_only:
        print("GLOBAL REBUILD PREVIEW PASSED; no cloud data was deleted.")
        return 0

    _confirm(confirm)

    completed = 0
    total = len(keys)
    for key in keys:
        completed += 1
        print(f"\n=== REBUILD {completed}/{total}: {key} ===")
        if key in local:
            # Keep the established customer B2 assignment. Purge removes old duplicates
            # from both B2s; publish then writes only the customer's assigned backend.
            purge = _purge_one(key, reset_assignment=False)
            if not purge.get("purged"):
                raise RuntimeError(f"purge did not complete for {key}")
            customer_publish.publish_customer(local[key], None, dry_run=False)
        else:
            # Cloud-only means current SQLite no longer contains this customer at all.
            # Delete its physical customer images and derived cloud projection. The old
            # share token may remain as a revoked/empty historical record, but no ORDER
            # data/image survives as an active projection.
            purge = _purge_one(key, reset_assignment=True)
            if not purge.get("purged"):
                raise RuntimeError(f"purge did not complete for cloud-only {key}")
            reconcile = _remove_cloud_only_customer(key)
            print(
                "CLOUD-ONLY REMOVED: "
                f"stale_orders={int(reconcile.get('stale_orders_removed') or 0)}"
            )

    print(f"\nORDER CLOUD GLOBAL REBUILD PASSED: {completed}/{total} customers")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or rebuild all ORDER customer B2/TiDB projections")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="scan every customer only; delete nothing")
    mode.add_argument("--execute", action="store_true", help="preflight all customers, then rebuild")
    parser.add_argument("--confirm", help=f"non-interactive execute confirmation: {CONFIRM_TEXT}")
    args = parser.parse_args()

    try:
        return rebuild_all(preview_only=bool(args.preview), confirm=args.confirm)
    except KeyboardInterrupt:
        print("GLOBAL REBUILD CANCELLED", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"GLOBAL REBUILD ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
