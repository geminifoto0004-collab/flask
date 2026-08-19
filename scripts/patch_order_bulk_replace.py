#!/usr/bin/env python3
"""Install atomic bulk-replace support into ORDER cloud service.

Used once by CI. It patches only the Render repository service; local ORDER SQLite
is never opened or modified.
"""
from pathlib import Path
import py_compile

MARKER = "def _replace_all_orders_atomic(payloads, source_site=None):"

HELPER = r'''
def _replace_all_orders_atomic(payloads, source_site=None):
    """Atomically replace the cloud ORDER mirror using one TiDB transaction.

    Share tokens and B2 asset metadata are intentionally preserved. Only the four
    text mirror tables are replaced. If any insert fails, rollback keeps the old
    mirror intact.
    """
    if not isinstance(payloads, list):
        raise ValueError("orders must be a list")
    if len(payloads) > 10000:
        raise ValueError("too many orders in one replace request")

    source_site = (str(source_site or "").strip().upper()[:16] or None)
    customers = {}
    orders = {}
    workflows = {}
    history = {}

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
                wf.get("workflow_key") or workflow_number or wf.get("id") or f"{order_number}:{pos}"
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

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        from database import executemany_sql

        # One transaction: readers keep the old committed mirror until commit.
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

        conn.commit()
        return {
            "replace_all": True,
            "customers": len(customers),
            "orders": len(orders),
            "workflows": len(workflows),
            "timeline_items": len(history),
            "source_site": source_site,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


'''


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / "services" / "order_cloud_service.py"
    text = path.read_text("utf-8")
    changed = False

    if MARKER not in text:
        anchor = "\ndef sync_order(payload, source_site=None):\n"
        if anchor not in text:
            raise RuntimeError("sync_order anchor not found")
        text = text.replace(anchor, "\n" + HELPER + "def sync_order(payload, source_site=None):\n", 1)
        changed = True

    branch = '''    if bool(payload.get("_replace_all")):\n        return _replace_all_orders_atomic(payload.get("orders") or [], source_site=source_site)\n\n'''
    if branch not in text:
        anchor = '    order_number = str(payload.get("order_number") or "").strip()\n'
        if anchor not in text:
            raise RuntimeError("sync_order body anchor not found")
        text = text.replace(anchor, branch + anchor, 1)
        changed = True

    if changed:
        path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)
    print("bulk replace patch", "applied" if changed else "already present")


if __name__ == "__main__":
    main()
