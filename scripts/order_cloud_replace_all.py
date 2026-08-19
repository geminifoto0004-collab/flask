#!/usr/bin/env python3
"""Fast one-request rebuild of the customer-safe ORDER TiDB mirror.

Use for first initialization or an explicit repair/rebuild. It reads local ORDER
SQLite in query-only mode, builds the same safe payload as the incremental sync,
and sends one atomic replace request to Render. Images/PDF/Access are never read.

Normal daily/startup sync should continue using order_cloud_sync_all.py, which sends
only changed orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys

import requests

import order_cloud_sync_all as inc
import order_cloud_sync_real_order as one


def _post_replace(payloads: list[dict]) -> dict:
    url = one.BASE_URL + "/api/order-cloud/sync/order"
    try:
        response = requests.post(
            url,
            headers=one._headers(),
            json={"_replace_all": True, "orders": payloads},
            timeout=(5, 180),
        )
    except requests.RequestException as exc:
        raise one.SyncError(f"Cloud unavailable during bulk replace: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:300]}
    if not response.ok or not body.get("ok"):
        raise one.SyncError(
            f"bulk replace failed HTTP {response.status_code}: "
            + json.dumps(body, ensure_ascii=False)[:800]
        )
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="explicit local tracking.db path")
    ap.add_argument("--state", help="explicit local fingerprint state path")
    args = ap.parse_args()

    health = one._request_json("GET", "/api/order-cloud/health")
    if not health.get("ok"):
        raise one.SyncError("Render ORDER cloud gateway is not ready")

    db = one._discover_db(args.db)
    conn = one._open_read_only(db)
    try:
        numbers = inc._order_numbers(conn)
        users = inc._load_order_users(conn)
        payloads = []
        fingerprints = {}
        skipped_no_customer = 0
        failed = 0

        for order_number in numbers:
            try:
                payload = one._load_order_payload(conn, order_number)
                payloads.append(payload)
                fingerprints[order_number] = inc._payload_hash(payload)
            except one.SyncError as exc:
                if "has no customer_name" in str(exc):
                    skipped_no_customer += 1
                    continue
                failed += 1
                print(f"PREPARE FAILED: {order_number}: {exc}")

        if failed:
            raise one.SyncError(f"refusing replace because {failed} local payloads failed to prepare")

        # Native ORDER login mirror: one small request, plaintext passwords never exist here.
        users_body = one._request_json("POST", "/api/order-cloud/sync/users", json={"users": users})
        if not users_body.get("ok"):
            raise one.SyncError("ORDER login-user sync failed")

        raw_size = len(json.dumps(payloads, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
        print(f"ORDER SQLite: {db}")
        print(f"Orders scanned: {len(numbers)}")
        print(f"Cloud-safe orders: {len(payloads)} | no_customer={skipped_no_customer}")
        print(f"ORDER login users: {len(users)}")
        print(f"Bulk JSON: {raw_size / 1024 / 1024:.2f} MB")
        print("Images/PDF/Access: NOT READ / NOT SENT")
        print("TiDB mirror: atomic DELETE rows + bulk INSERT in ONE transaction")

        body = _post_replace(payloads)
        result = body.get("result") or {}
        print(
            "BULK REPLACE OK: "
            f"orders={result.get('orders')} workflows={result.get('workflows')} "
            f"timeline={result.get('timeline_items')} customers={result.get('customers')}"
        )

        # Seed the incremental state so the next normal startup does not re-send all rows.
        state_path = inc._state_path(args.state)
        state = inc._load_state(state_path)
        now = datetime.now(timezone.utc).isoformat()
        state["fingerprints"] = fingerprints
        state["users_hash"] = inc._payload_hash(users)
        state["last_attempt_at"] = now
        state["last_success_at"] = now
        state["last_db"] = str(db)
        state["last_order_count"] = len(numbers)
        state["last_skipped_no_customer"] = skipped_no_customer
        inc._save_state(state_path, state)
        print("Incremental hash state seeded: OK")
        print("ORDER CLOUD FAST INITIALIZATION PASSED")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except one.SyncError as exc:
        print(f"ORDER CLOUD REPLACE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
