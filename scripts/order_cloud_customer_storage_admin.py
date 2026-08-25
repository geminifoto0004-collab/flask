#!/usr/bin/env python3
"""Manual ORDER customer B2 maintenance with preview-first destructive controls.

Commands use the same protected Render sync key as the normal local ORDER cloud sync.
No B2 credentials are stored on the PC.

Examples (Windows CMD):
    python scripts\order_cloud_customer_storage_admin.py status "CLIENTE ABC"
    python scripts\order_cloud_customer_storage_admin.py refresh "CLIENTE ABC"
    python scripts\order_cloud_customer_storage_admin.py purge-preview "CLIENTE ABC"
    python scripts\order_cloud_customer_storage_admin.py rebuild "CLIENTE ABC"

`rebuild` always shows the purge preview and requires typing the exact confirmation
before deleting cloud image objects. Local SQLite/images are never deleted or modified.
After purge it republishes the exact current SQLite customer projection and refreshes the
same share links without changing their tokens.
"""
from __future__ import annotations

import argparse
import json
import sys

import order_cloud_sync_real_order as order_sync


def _key(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _call(path: str, customer_key: str, **extra):
    payload = {"customer_key": customer_key}
    payload.update(extra)
    return (order_sync._request_json("POST", path, json=payload).get("result") or {})


def _print(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _preview(customer_key: str):
    result = _call(
        "/api/order-cloud/storage/customer/purge",
        customer_key,
        execute=False,
    )
    _print(result)
    return result


def _confirm(customer_key: str, supplied: str | None) -> str:
    required = f"PURGE:{customer_key}"
    if supplied:
        if supplied != required:
            raise RuntimeError(f"--confirm must be exactly: {required}")
        return supplied
    if not sys.stdin.isatty():
        raise RuntimeError(f"interactive confirmation unavailable; pass --confirm \"{required}\"")
    print("\nThis deletes ONLY this customer's cloud image objects/metadata.")
    print("Local tracking.db and local files are untouched.")
    typed = input(f"Type {required} to continue: ").strip()
    if typed != required:
        raise RuntimeError("purge cancelled: confirmation did not match")
    return typed


def _purge(customer_key: str, confirm: str | None, reset_assignment: bool):
    preview = _preview(customer_key)
    if preview.get("scan_errors"):
        raise RuntimeError("B2 preview is incomplete; purge is blocked")
    token = _confirm(customer_key, confirm)
    result = _call(
        "/api/order-cloud/storage/customer/purge",
        customer_key,
        execute=True,
        confirm=token,
        reset_assignment=bool(reset_assignment),
    )
    print("\nPURGE RESULT")
    _print(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="ORDER customer B2 status / refresh / purge / rebuild")
    parser.add_argument("command", choices=["status", "refresh", "purge-preview", "purge", "rebuild"])
    parser.add_argument("customer", help="customer name/key; normalized like ORDER customer_key")
    parser.add_argument("--confirm", help="exact PURGE:<CUSTOMER_KEY> confirmation for non-interactive use")
    parser.add_argument(
        "--reset-assignment",
        action="store_true",
        help="also forget the customer's B2 assignment; default keeps the same assigned B2",
    )
    args = parser.parse_args()

    customer_key = _key(args.customer)
    if not customer_key:
        print("ERROR: customer is required", file=sys.stderr)
        return 2

    try:
        if args.command == "status":
            _print(_call("/api/order-cloud/storage/customer/status", customer_key))
            return 0
        if args.command == "refresh":
            _print(_call("/api/order-cloud/share/refresh", customer_key))
            return 0
        if args.command == "purge-preview":
            _preview(customer_key)
            return 0
        if args.command == "purge":
            _purge(customer_key, args.confirm, args.reset_assignment)
            return 0

        # rebuild = explicit full clean cloud image reset, then publish the exact current
        # SQLite customer projection. Existing B2 assignment is preserved by default.
        _purge(customer_key, args.confirm, args.reset_assignment)
        import order_cloud_publish_customer as customer_publish
        print("\nREBUILDING FROM CURRENT LOCAL SQLITE...")
        customer_publish.publish_customer(args.customer, None, dry_run=False)
        print("\nCUSTOMER CLOUD REBUILD PASSED")
        return 0
    except KeyboardInterrupt:
        print("CANCELLED", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
