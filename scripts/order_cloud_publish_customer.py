#!/usr/bin/env python3
"""Publish one ORDER customer so Render/TiDB/B2 exactly follows current local SQLite.

This is the normal high-level customer publish command. It reuses the existing safe image
sync, then reconciles cloud order membership against the exact current SQLite customer
order set, and finally refreshes all existing share snapshots without changing tokens.

Local tracking.db and local attachment files are read-only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any, Dict

import order_cloud_sync_real_images as image_scan
import order_cloud_sync_real_order as order_sync
import order_cloud_sync_customer as customer_sync


class CustomerPublishError(RuntimeError):
    pass


def _local_manifest(customer: str | None, from_order: str | None) -> Dict[str, Any]:
    _config_path, db_path, _upload_folder = image_scan._load_order_config()
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        customer_name, customer_key = customer_sync._customer_identity(conn, customer, from_order)
        order_numbers = customer_sync._customer_orders(conn, customer_key)
        if not order_numbers:
            raise CustomerPublishError(f"customer has no local orders: {customer_name}")
        return {
            "customer_name": customer_name,
            "customer_key": customer_key,
            "order_numbers": list(order_numbers),
            "db_path": str(db_path),
        }
    finally:
        conn.close()


def publish_customer(customer: str | None, from_order: str | None, dry_run: bool = False) -> Dict[str, Any]:
    manifest = _local_manifest(customer, from_order)
    print(
        "SQLITE AUTHORITATIVE CUSTOMER: "
        f"{manifest['customer_name']} | orders={len(manifest['order_numbers'])}"
    )

    synced = customer_sync.sync_customer(customer, from_order, dry_run=dry_run)
    if dry_run:
        return {
            **synced,
            "order_numbers": manifest["order_numbers"],
            "order_reconcile": None,
        }

    # This is deliberately after all current order/image writes succeed. Cloud rows that
    # are no longer in SQLite are removed only when the new snapshot is already usable.
    order_reconcile = order_sync._request_json(
        "POST",
        "/api/order-cloud/customer/reconcile-orders",
        json={
            "customer_key": manifest["customer_key"],
            "order_numbers": manifest["order_numbers"],
            "confirm_empty": False,
        },
    ).get("result") or {}

    # Customer sync already refreshes once. Refresh again after order reconciliation so
    # an existing share sees the final exact SQLite projection, with the same token/URL.
    refreshed = order_sync._request_json(
        "POST",
        "/api/order-cloud/share/refresh",
        json={"customer_key": manifest["customer_key"]},
    ).get("result") or {}

    print(
        "ORDER ALIGN OK: "
        f"expected={len(manifest['order_numbers'])} "
        f"stale_cloud_removed={int(order_reconcile.get('stale_orders_removed') or 0)}"
    )
    print(
        "SHARE FINAL REFRESH OK: token unchanged | "
        f"orders={refreshed.get('orders')} assets={refreshed.get('assets')}"
    )
    return {
        **synced,
        "order_numbers": manifest["order_numbers"],
        "order_reconcile": order_reconcile,
        "final_refresh": refreshed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish one customer: SQLite -> TiDB/B2 -> existing Render shares"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--customer", help="exact customer name from local ORDER")
    group.add_argument("--from-order", help="derive customer from this local ORDER number")
    parser.add_argument("--dry-run", action="store_true", help="read/hash/optimize only; no cloud writes")
    args = parser.parse_args()

    try:
        publish_customer(args.customer, args.from_order, dry_run=bool(args.dry_run))
        print("CUSTOMER PUBLISH PASSED")
        return 0
    except (CustomerPublishError, customer_sync.CustomerSyncError, order_sync.SyncError, image_scan.ImageSyncError) as exc:
        print(f"CUSTOMER PUBLISH ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("CUSTOMER PUBLISH CANCELLED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
