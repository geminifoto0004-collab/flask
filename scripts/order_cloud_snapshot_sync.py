#!/usr/bin/env python3
"""Fast SQLite -> Render/TiDB ORDER text snapshot sync.

Reads local tracking.db in query-only mode, builds the existing customer-safe ORDER
text payload, compares one whole-snapshot SHA-256, and sends at most one bulk POST.
Images, PDFs, Access data, local paths, phone/payment/deposit/internal notes are not
read or uploaded by this script.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from typing import Any

import requests

import order_cloud_sync_real_order as one

BASE_URL = (os.environ.get("ORDER_CLOUD_BASE_URL") or "https://flask-393d.onrender.com").rstrip("/")
API_KEY = (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise one.SyncError("ORDER_SYNC_API_KEY is not configured")
    return {"X-Order-Sync-Key": API_KEY}


def _request_json(session: requests.Session, method: str, path: str, **kwargs: Any) -> dict:
    response = session.request(
        method,
        BASE_URL + path,
        headers={**_headers(), **(kwargs.pop("headers", {}) or {})},
        timeout=(5, 180),
        **kwargs,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:1000]}
    if not response.ok or not body.get("ok"):
        raise one.SyncError(
            f"{method} {path} failed ({response.status_code}): "
            + json.dumps(body, ensure_ascii=False)
        )
    return body


def _canonical_hash(orders: list[dict]) -> str:
    raw = json.dumps(
        orders,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source_watermark(conn) -> str | None:
    candidates: list[str] = []
    specs = (
        ("orders", ("updated_at", "created_at", "order_date")),
        ("workflows", ("updated_at", "status_updated_at", "created_at")),
        ("workflow_status_history", ("created_at", "action_date")),
    )
    for table, names in specs:
        cols = one._columns(conn, table)
        for name in names:
            if name not in cols:
                continue
            row = conn.execute(
                f'SELECT MAX(CAST("{name}" AS TEXT)) FROM "{table}" WHERE "{name}" IS NOT NULL'
            ).fetchone()
            if row and row[0] is not None:
                value = str(row[0]).strip()
                if value:
                    candidates.append(value)
    return max(candidates) if candidates else None


def _load_orders(conn):
    rows = conn.execute(
        "SELECT order_number FROM orders WHERE order_number IS NOT NULL ORDER BY order_number"
    ).fetchall()
    orders = []
    no_customer = []
    for row in rows:
        order_number = str(row[0] or "").strip()
        if not order_number:
            continue
        try:
            orders.append(one._load_order_payload(conn, order_number))
        except one.SyncError as exc:
            if "has no customer_name" in str(exc):
                no_customer.append(order_number)
                continue
            raise
    orders.sort(key=lambda item: str(item.get("order_number") or ""))
    return orders, no_customer


def _load_users(conn) -> list[dict]:
    if not one._table_exists(conn, "users"):
        return []
    cols = one._columns(conn, "users")
    if not {"username", "password_hash"}.issubset(cols):
        return []
    allowed = [
        "id", "username", "password_hash", "display_name", "real_name",
        "role", "status", "needs_password_reset",
    ]
    selected = [name for name in allowed if name in cols]
    rows = conn.execute(
        "SELECT " + ", ".join(f'\"{name}\"' for name in selected) + " FROM users ORDER BY username"
    ).fetchall()
    users = []
    for row in rows:
        data = dict(row)
        username = str(data.get("username") or "").strip()
        password_hash = str(data.get("password_hash") or "").strip()
        if not username or not password_hash:
            continue
        users.append({
            "id": data.get("id"),
            "username": username,
            "password_hash": password_hash,
            "display_name": data.get("display_name") or username,
            "real_name": data.get("real_name"),
            "role": data.get("role") or "viewer",
            "status": data.get("status") or "active",
            "needs_password_reset": bool(data.get("needs_password_reset") or False),
        })
    return users


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast whole ORDER text snapshot sync to Render/TiDB")
    ap.add_argument("--db", help="explicit local tracking.db path")
    ap.add_argument("--force", action="store_true", help="replace even when hash/watermark guard would skip")
    ap.add_argument("--dry-run", action="store_true", help="build snapshot/hash only; do not call Render")
    args = ap.parse_args()

    db = one._discover_db(args.db)
    conn = one._open_read_only(db)
    try:
        orders, no_customer = _load_orders(conn)
        users = _load_users(conn)
        watermark = _source_watermark(conn)
    finally:
        conn.close()

    snapshot_hash = _canonical_hash(orders)
    payload_bytes = len(json.dumps(orders, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))

    print(f"ORDER SQLite: {db}")
    print(f"Cloud-safe orders: {len(orders)} | no_customer skipped: {len(no_customer)}")
    print(f"ORDER login users: {len(users)}")
    print(f"Text payload: {payload_bytes / 1024 / 1024:.2f} MB")
    print(f"Snapshot HASH: {snapshot_hash}")
    print(f"Source watermark: {watermark or '(none)'}")
    print("Images/PDF/Access/phone/payment/deposit/internal notes: NOT READ / NOT SENT")

    if args.dry_run:
        print("DRY RUN OK")
        return 0

    with requests.Session() as session:
        # Small auth mirror; this preserves the native ORDER login on Render.
        users_body = _request_json(session, "POST", "/api/order-cloud/sync/users", json={"users": users})
        users_result = users_body.get("result") or {}
        print(f"ORDER login users synced: {users_result.get('users', 0)}")

        state_body = _request_json(session, "GET", "/api/order-cloud/sync/snapshot-state")
        state = state_body.get("result") or {}
        cloud_hash = str(state.get("snapshot_hash") or "")
        if cloud_hash == snapshot_hash and not args.force:
            print("TiDB ORDER text mirror: SAME HASH -> no DELETE / no INSERT")
            return 0

        body = _request_json(
            session,
            "POST",
            "/api/order-cloud/sync/snapshot",
            json={
                "snapshot_hash": snapshot_hash,
                "source_watermark": watermark,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "force": bool(args.force),
                "orders": orders,
            },
        )
        result = body.get("result") or {}
        if result.get("stale"):
            print(
                "TiDB ORDER text mirror: NOT UPDATED (this SQLite snapshot is older than cloud).\n"
                f"Local watermark: {result.get('source_watermark')}\n"
                f"Cloud watermark: {result.get('cloud_watermark')}"
            )
            return 3

        if not result.get("changed"):
            print(f"TiDB ORDER text mirror: skipped ({result.get('reason') or 'no change'})")
            return 0

        print(
            "TIDB BULK REPLACE OK: "
            f"orders={result.get('orders')} workflows={result.get('workflows')} "
            f"timeline={result.get('timeline_items')} customers={result.get('customers')}"
        )
        print("Share tokens / B2 assets / PDFs: PRESERVED")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("ORDER snapshot sync cancelled", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ORDER SNAPSHOT SYNC ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
