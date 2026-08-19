"""Publish one real ORDER from local SQLite to the Render customer-share API.

This script is deliberately read-only toward ORDER SQLite and uses an explicit
customer-safe whitelist. It does NOT read/upload phone, deposit/payment data,
internal notes, handler/factory details, or arbitrary metadata.

Typical Windows CMD usage from the Render-Flask clone:

    git pull
    python scripts\order_cloud_sync_real_order.py --latest

The API key is read from ORDER_SYNC_API_KEY (same environment variable used by
order_cloud_roundtrip_test.py). Override the SQLite path with ORDER_TRACKING_DB
when needed. The default discovery includes E:\\upload_xingwang\\tracking.db.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, Iterable, List, Optional

import requests


BASE_URL = (os.environ.get("ORDER_CLOUD_BASE_URL") or "https://flask-393d.onrender.com").rstrip("/")
API_KEY = (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()


SAFE_ORDER_COLUMNS = {
    "order_number",
    "customer_name",
    "order_date",
    "status",
    "current_status",
    "production_type",
    "product_name",
    "product_code",
    "pattern_code",
    "quantity",
    "expected_delivery_date",
}
SAFE_WORKFLOW_COLUMNS = {
    "workflow_number",
    "order_number",
    "current_status",
    "production_type",
    "product_name",
    "product_code",
    "quantity",
    "expected_delivery_date",
    "status_updated_at",
}
SAFE_HISTORY_COLUMNS = {
    "id",
    "workflow_number",
    "to_status",
    "action_date",
    "created_at",
}


class SyncError(RuntimeError):
    pass


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _safe_select_list(existing: set[str], allowed: Iterable[str]) -> str:
    names = [name for name in allowed if name in existing]
    if not names:
        raise SyncError("No compatible safe columns were found")
    return ", ".join(f'"{name}"' for name in names)


def _discover_db(explicit: Optional[str]) -> Path:
    candidates: List[Path] = []
    for value in (
        explicit,
        os.environ.get("ORDER_TRACKING_DB"),
        os.environ.get("TRACKING_DB_PATH"),
    ):
        if value:
            candidates.append(Path(value).expanduser())

    candidates.extend(
        [
            Path(r"E:\upload_xingwang\tracking.db"),
            Path.cwd().parent / "order_tracking" / "data" / "tracking.db",
            Path.cwd().parent / "order_tracking" / "tracking.db",
            Path.cwd() / "order_tracking" / "data" / "tracking.db",
        ]
    )

    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.resolve()

    checked = "\n  - ".join(str(p) for p in candidates)
    raise SyncError(
        "tracking.db not found. Set ORDER_TRACKING_DB to the real SQLite file.\n"
        f"Checked:\n  - {checked}"
    )


def _open_read_only(path: Path) -> sqlite3.Connection:
    # PRAGMA query_only prevents accidental writes even if SQLite opened the file normally.
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _pick_latest_order_number(conn: sqlite3.Connection) -> str:
    order_cols = _columns(conn, "orders")
    if "order_number" not in order_cols:
        raise SyncError("orders.order_number is missing")

    order_by = []
    if "order_date" in order_cols:
        order_by.append("o.order_date DESC")
    if "updated_at" in order_cols:
        order_by.append("o.updated_at DESC")
    if "created_at" in order_cols:
        order_by.append("o.created_at DESC")
    order_by.append("o.order_number DESC")
    order_clause = ", ".join(order_by)

    # Prefer a real order that already has at least one workflow, so the first
    # verification exercises the timeline/customer page rather than an empty shell.
    if _table_exists(conn, "workflows"):
        wf_cols = _columns(conn, "workflows")
        if "order_number" in wf_cols:
            row = conn.execute(
                f"""
                SELECT o.order_number
                FROM orders o
                WHERE EXISTS (
                    SELECT 1 FROM workflows w WHERE w.order_number=o.order_number
                )
                ORDER BY {order_clause}
                LIMIT 1
                """
            ).fetchone()
            if row and row[0]:
                return str(row[0])

    row = conn.execute(
        f"SELECT o.order_number FROM orders o ORDER BY {order_clause} LIMIT 1"
    ).fetchone()
    if not row or not row[0]:
        raise SyncError("No orders were found in tracking.db")
    return str(row[0])


def _load_history(conn: sqlite3.Connection, workflow_number: str) -> List[Dict[str, Any]]:
    if not _table_exists(conn, "workflow_status_history"):
        return []
    cols = _columns(conn, "workflow_status_history")
    required = {"workflow_number", "to_status", "action_date"}
    if not required.issubset(cols):
        return []

    selected = [name for name in SAFE_HISTORY_COLUMNS if name in cols]
    order_parts = []
    if "action_date" in cols:
        order_parts.append("action_date ASC")
    if "created_at" in cols:
        order_parts.append("created_at ASC")
    if "id" in cols:
        order_parts.append("id ASC")
    order_sql = ", ".join(order_parts) or "rowid ASC"

    rows = conn.execute(
        f"SELECT {', '.join(selected)} FROM workflow_status_history "
        f"WHERE workflow_number=? ORDER BY {order_sql}",
        (workflow_number,),
    ).fetchall()

    result: List[Dict[str, Any]] = []
    for pos, row in enumerate(rows):
        item = dict(row)
        status = _clean(item.get("to_status"))
        action_date = _clean(item.get("action_date"))
        if not status and not action_date:
            continue
        raw_id = item.get("id")
        history_key = f"{workflow_number}:{raw_id if raw_id is not None else pos}"
        result.append(
            {
                "history_key": history_key,
                "status": status,
                "action_date": action_date,
                "sort_order": pos,
            }
        )
    return result


def _load_order_payload(conn: sqlite3.Connection, order_number: str) -> Dict[str, Any]:
    order_cols = _columns(conn, "orders")
    required = {"order_number", "customer_name"}
    if not required.issubset(order_cols):
        raise SyncError("orders table must contain order_number and customer_name")

    order_select = _safe_select_list(order_cols, SAFE_ORDER_COLUMNS)
    row = conn.execute(
        f"SELECT {order_select} FROM orders WHERE order_number=? LIMIT 1",
        (order_number,),
    ).fetchone()
    if not row:
        raise SyncError(f"ORDER not found: {order_number}")
    order = {k: _clean(v) for k, v in dict(row).items()}

    customer_name = str(order.get("customer_name") or "").strip()
    if not customer_name:
        raise SyncError(f"ORDER {order_number} has no customer_name")

    # ORDER uses the customer name as its current customer grouping. Uppercasing the
    # key keeps CN/CL copies stable across display-case differences without exposing
    # any extra local customer metadata.
    customer_key = " ".join(customer_name.upper().split())

    lifecycle_status = str(order.get("status") or "").strip().upper()
    if lifecycle_status == "CANCELLED":
        order_status = "CANCELLED"
    else:
        order_status = order.get("current_status") or order.get("status")

    payload: Dict[str, Any] = {
        "order_number": str(order_number),
        "customer_key": customer_key,
        "customer_name": customer_name,
        "order_status": order_status,
        "order_date": order.get("order_date"),
        "expected_delivery_date": order.get("expected_delivery_date"),
        "production_type": order.get("production_type"),
        "product_name": order.get("product_name"),
        "product_code": order.get("product_code"),
        "pattern_code": order.get("pattern_code"),
        "quantity": order.get("quantity"),
        "workflows": [],
    }

    if _table_exists(conn, "workflows"):
        wf_cols = _columns(conn, "workflows")
        if {"workflow_number", "order_number"}.issubset(wf_cols):
            wf_select = _safe_select_list(wf_cols, SAFE_WORKFLOW_COLUMNS)
            rows = conn.execute(
                f"SELECT {wf_select} FROM workflows WHERE order_number=? ORDER BY workflow_number ASC",
                (order_number,),
            ).fetchall()
            for pos, wf_row in enumerate(rows):
                wf = {k: _clean(v) for k, v in dict(wf_row).items()}
                workflow_number = str(wf.get("workflow_number") or "").strip()
                if not workflow_number:
                    continue
                timeline = _load_history(conn, workflow_number)
                last_history_date = next(
                    (item.get("action_date") for item in reversed(timeline) if item.get("action_date")),
                    None,
                )
                draft_date = next(
                    (
                        item.get("action_date")
                        for item in timeline
                        if str(item.get("status") or "").upper() == "DRAFT_CONFIRMING"
                    ),
                    None,
                )
                payload["workflows"].append(
                    {
                        "workflow_key": workflow_number,
                        "workflow_number": workflow_number,
                        "status": wf.get("current_status"),
                        "production_type": wf.get("production_type"),
                        "product_name": wf.get("product_name"),
                        "product_code": wf.get("product_code"),
                        "quantity": wf.get("quantity"),
                        "expected_delivery_date": wf.get("expected_delivery_date"),
                        "last_status_change_date": last_history_date or wf.get("status_updated_at"),
                        "draft_date": draft_date,
                        "sort_order": pos,
                        "timeline": timeline,
                    }
                )

    # Remove None only; keep zero/empty-list semantics. This is also a last local
    # whitelist boundary: only keys explicitly constructed above can leave the PC.
    return {k: v for k, v in payload.items() if v is not None}


def _headers() -> Dict[str, str]:
    if not API_KEY:
        raise SyncError(
            "ORDER_SYNC_API_KEY is not set in this CMD/PowerShell session. "
            "Set it to the Render ORDER sync key first."
        )
    return {"X-Order-Sync-Key": API_KEY}


def _request_json(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    url = BASE_URL + path
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_headers())
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=(5, 25),
            **kwargs,
        )
    except requests.RequestException as exc:
        raise SyncError(f"Cloud unavailable: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:1000]}
    if not response.ok or not body.get("ok"):
        raise SyncError(f"{method} {path} failed ({response.status_code}): {json.dumps(body, ensure_ascii=False)}")
    return body


def _safe_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order_number": payload.get("order_number"),
        "customer_name": payload.get("customer_name"),
        "order_status": payload.get("order_status"),
        "order_date": payload.get("order_date"),
        "workflow_count": len(payload.get("workflows") or []),
        "timeline_count": sum(len(wf.get("timeline") or []) for wf in payload.get("workflows") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one real ORDER SQLite record safely to Render/TiDB")
    parser.add_argument("order_number", nargs="?", help="ORDER number to publish")
    parser.add_argument("--latest", action="store_true", help="Publish the latest ORDER that has a workflow")
    parser.add_argument("--db", help="Explicit tracking.db path (or use ORDER_TRACKING_DB)")
    parser.add_argument("--dry-run", action="store_true", help="Read/build payload only; do not call Render")
    parser.add_argument("--share", action="store_true", help="Also create a new 24-hour customer share URL")
    args = parser.parse_args()

    if args.order_number and args.latest:
        raise SyncError("Use either an order number or --latest, not both")
    if not args.order_number and not args.latest:
        raise SyncError("Provide an order number, or use --latest")

    db_path = _discover_db(args.db)
    conn = _open_read_only(db_path)
    try:
        order_number = _pick_latest_order_number(conn) if args.latest else str(args.order_number).strip()
        payload = _load_order_payload(conn, order_number)
    finally:
        conn.close()

    print(f"ORDER SQLite: {db_path}")
    print("Safe payload:")
    print(json.dumps(_safe_preview(payload), ensure_ascii=False, indent=2))
    print("Sensitive local fields: NOT READ / NOT SENT")

    if args.dry_run:
        print("DRY RUN OK")
        return 0

    health = _request_json("GET", "/api/order-cloud/health")
    print(f"Render health: phase {health.get('phase')}")

    sync = _request_json("POST", "/api/order-cloud/sync/order", json=payload)
    result = sync.get("result") or {}
    print(
        "REAL ORDER SYNC OK: "
        f"{result.get('order_number')} | workflows={result.get('workflows')} | "
        f"timeline={result.get('timeline_items')} | source={result.get('source_site')}"
    )

    verify = _request_json("GET", f"/api/order-cloud/debug/order/{requests.utils.quote(str(payload['order_number']), safe='')}")
    cloud_order = verify.get("order") or {}
    if str(cloud_order.get("customer_name") or "") != str(payload.get("customer_name") or ""):
        raise SyncError("Cloud verification customer_name does not match local safe payload")
    if len(cloud_order.get("workflows") or []) != len(payload.get("workflows") or []):
        raise SyncError("Cloud verification workflow count does not match local safe payload")
    print("TiDB verification OK")

    if args.share:
        share = _request_json(
            "POST",
            "/api/order-cloud/share/create",
            json={"customer_key": payload["customer_key"], "expires_hours": 24},
        )
        url = (share.get("result") or {}).get("share_url")
        print(f"SHARE_URL: {url}")

    print("REAL ORDER CLOUD SYNC PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
