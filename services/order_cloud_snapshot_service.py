"""Fast whole-snapshot ORDER text mirror for Render/TiDB.

This service replaces only the four customer-safe ORDER text mirror tables.
Share tokens, B2 asset metadata/files, and cloud ORDER login users are preserved.
"""
from __future__ import annotations

import hashlib
import json

from database import executemany_sql, get_cursor, get_db_connection, get_row_dict
from services.order_cloud_service import init_order_cloud_tables

SNAPSHOT_KEY = "order_text_v1"
MAX_ORDERS = 10000


def _canonical_hash(orders: list[dict]) -> str:
    raw = json.dumps(
        orders,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_source_site(source_site) -> str | None:
    value = str(source_site or "").strip().upper()[:16]
    return value or None


def _normalize_watermark(value) -> str | None:
    value = str(value or "").strip()
    return value[:64] or None


def init_snapshot_state_table() -> None:
    init_order_cloud_tables()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_order_snapshot_state (
                snapshot_key VARCHAR(64) PRIMARY KEY,
                snapshot_hash VARCHAR(64) NULL,
                source_watermark VARCHAR(64) NULL,
                source_site VARCHAR(16) NULL,
                order_count INT NOT NULL DEFAULT 0,
                workflow_count INT NOT NULL DEFAULT 0,
                history_count INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_snapshot_state() -> dict:
    init_snapshot_state_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT snapshot_hash, source_watermark, source_site,
                      order_count, workflow_count, history_count, updated_at
               FROM cloud_order_snapshot_state
               WHERE snapshot_key=?""",
            (SNAPSHOT_KEY,),
        )
        row = cur.fetchone()
        data = get_row_dict(row, cur) if row else {}
        return data or {}
    finally:
        conn.close()


def _build_rows(payloads: list[dict], source_site: str | None):
    customers: dict[str, tuple] = {}
    orders: dict[str, tuple] = {}
    workflows: dict[str, tuple] = {}
    history: dict[str, tuple] = {}

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        order_number = str(payload.get("order_number") or "").strip()
        customer_name = str(payload.get("customer_name") or "").strip()
        customer_key = str(payload.get("customer_key") or customer_name).strip()
        if not order_number or not customer_name or not customer_key:
            continue

        customers[customer_key] = (customer_key, customer_name, True, source_site)
        orders[order_number] = (
            order_number,
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
            True,
            source_site,
        )

        for pos, wf in enumerate(payload.get("workflows") or []):
            if not isinstance(wf, dict):
                continue
            workflow_number = str(wf.get("workflow_number") or "").strip()
            workflow_key = str(
                wf.get("workflow_key")
                or workflow_number
                or wf.get("id")
                or f"{order_number}:{pos}"
            ).strip()
            if not workflow_key:
                continue
            workflows[workflow_key] = (
                workflow_key,
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
                True,
            )

            timeline = wf.get("timeline") or wf.get("history") or []
            if not isinstance(timeline, list):
                continue
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
                history[history_key] = (
                    history_key,
                    workflow_key,
                    order_number,
                    item.get("status") or item.get("to_status"),
                    item.get("action_date"),
                    int(item.get("sort_order", hpos) or 0),
                    True,
                )

    return customers, orders, workflows, history


def replace_snapshot(
    payloads: list[dict],
    snapshot_hash: str,
    source_watermark=None,
    source_site=None,
    force: bool = False,
) -> dict:
    """Replace the ORDER text mirror in one TiDB transaction.

    Hash equality is checked before any DELETE. A strictly older source watermark is
    rejected unless force=True, preventing an older CL/CN SQLite copy from replacing
    a newer cloud snapshot.
    """
    if not isinstance(payloads, list):
        raise ValueError("orders must be a list")
    if len(payloads) > MAX_ORDERS:
        raise ValueError(f"too many orders in one snapshot (max {MAX_ORDERS})")

    snapshot_hash = str(snapshot_hash or "").strip().lower()
    if len(snapshot_hash) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_hash):
        raise ValueError("snapshot_hash must be a SHA-256 hex digest")

    calculated = _canonical_hash(payloads)
    if calculated != snapshot_hash:
        raise ValueError("snapshot_hash does not match received ORDER payload")

    source_site = _normalize_source_site(source_site)
    source_watermark = _normalize_watermark(source_watermark)
    init_snapshot_state_table()

    current = get_snapshot_state()
    if current.get("snapshot_hash") == snapshot_hash and not force:
        return {
            "changed": False,
            "reason": "same_hash",
            "snapshot_hash": snapshot_hash,
            "source_watermark": current.get("source_watermark"),
            "source_site": current.get("source_site"),
            "orders": int(current.get("order_count") or 0),
            "workflows": int(current.get("workflow_count") or 0),
            "timeline_items": int(current.get("history_count") or 0),
        }

    current_watermark = _normalize_watermark(current.get("source_watermark"))
    if (
        not force
        and source_watermark
        and current_watermark
        and source_watermark < current_watermark
    ):
        return {
            "changed": False,
            "reason": "stale_source",
            "stale": True,
            "snapshot_hash": snapshot_hash,
            "source_watermark": source_watermark,
            "cloud_watermark": current_watermark,
            "cloud_source_site": current.get("source_site"),
        }

    customers, orders, workflows, history = _build_rows(payloads, source_site)
    if len(orders) != len(payloads):
        raise ValueError("one or more ORDER payloads are invalid or duplicated")

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        # One transaction. If an INSERT fails, rollback restores the previous mirror.
        cur.execute("DELETE FROM cloud_workflow_history")
        cur.execute("DELETE FROM cloud_workflows")
        cur.execute("DELETE FROM cloud_orders")
        cur.execute("DELETE FROM cloud_customers")

        if customers:
            executemany_sql(
                cur,
                """INSERT INTO cloud_customers
                   (customer_key, customer_name, active, source_site)
                   VALUES (?, ?, ?, ?)""",
                list(customers.values()),
            )
        if orders:
            executemany_sql(
                cur,
                """INSERT INTO cloud_orders
                   (order_number, customer_key, customer_name, order_status, order_date,
                    expected_delivery_date, production_type, product_name, product_code,
                    pattern_code, quantity, active, source_site)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                list(orders.values()),
            )
        if workflows:
            executemany_sql(
                cur,
                """INSERT INTO cloud_workflows
                   (workflow_key, order_number, workflow_number, workflow_type, status,
                    production_type, product_name, product_code, quantity,
                    expected_delivery_date, last_status_change_date, draft_date,
                    sort_order, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                list(workflows.values()),
            )
        if history:
            executemany_sql(
                cur,
                """INSERT INTO cloud_workflow_history
                   (history_key, workflow_key, order_number, status, action_date,
                    sort_order, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                list(history.values()),
            )

        cur.execute("DELETE FROM cloud_order_snapshot_state WHERE snapshot_key=?", (SNAPSHOT_KEY,))
        cur.execute(
            """INSERT INTO cloud_order_snapshot_state
               (snapshot_key, snapshot_hash, source_watermark, source_site,
                order_count, workflow_count, history_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                SNAPSHOT_KEY,
                snapshot_hash,
                source_watermark,
                source_site,
                len(orders),
                len(workflows),
                len(history),
            ),
        )
        conn.commit()
        return {
            "changed": True,
            "reason": "replaced",
            "snapshot_hash": snapshot_hash,
            "source_watermark": source_watermark,
            "source_site": source_site,
            "customers": len(customers),
            "orders": len(orders),
            "workflows": len(workflows),
            "timeline_items": len(history),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
