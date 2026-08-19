"""Read-only ORDER provider for the Render-hosted ORDER UI.

This module intentionally reads only the customer-safe cloud_* tables already
populated by the local ORDER sync. It never reads Access data, phone numbers,
payments, deposits, internal notes, local file paths, or original filenames.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from threading import Lock

from database import get_cursor, get_db_connection, get_row_dict


class RenderOrderDataProvider:
    """Supply the existing ORDER homepage with TiDB-backed read-only rows."""

    def __init__(self):
        self._ready = False
        self._lock = Lock()

    def _ensure(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            from services.order_cloud_service import init_order_cloud_tables
            init_order_cloud_tables()
            self._ready = True

    @staticmethod
    def _days_since(value) -> int:
        if not value:
            return 0
        try:
            raw = str(value).strip().split()[0]
            return max(0, (date.today() - datetime.strptime(raw, "%Y-%m-%d").date()).days)
        except Exception:
            return 0

    @staticmethod
    def _safe_status_light(row: dict) -> tuple[str, str]:
        try:
            from order_tracking.models import calculate_status_light, get_status_light_hint
            obj = {
                "order_number": row.get("order_number"),
                "order_date": row.get("order_date"),
                "expected_delivery_date": row.get("expected_delivery_date"),
                "status_updated_at": row.get("last_status_change_date"),
                "current_status": row.get("current_status"),
                "last_status_change_date": row.get("last_status_change_date"),
            }
            return calculate_status_light(obj), get_status_light_hint(obj)
        except Exception:
            return "grey", ""

    def load_home_orders(self, role: str, user_id):
        """Return rows shaped like the local ORDER homepage dataset.

        Cloud phase is intentionally view-only. Because customer-safe TiDB does
        not contain internal salesperson/handler ownership, authenticated Render
        users see the shared cloud order set rather than a fake ownership filter.
        """
        self._ensure()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute("""
                SELECT
                    o.order_number,
                    o.customer_name,
                    o.order_status,
                    o.order_date,
                    o.expected_delivery_date AS order_expected_delivery_date,
                    o.production_type AS order_production_type,
                    o.product_name AS order_product_name,
                    o.product_code AS order_product_code,
                    o.pattern_code,
                    o.quantity AS order_quantity,
                    o.updated_at AS order_updated_at,
                    w.workflow_key,
                    w.workflow_number,
                    w.workflow_type,
                    w.status AS current_status,
                    w.production_type,
                    w.product_name,
                    w.product_code,
                    w.quantity,
                    w.expected_delivery_date,
                    w.last_status_change_date,
                    w.draft_date,
                    w.sort_order,
                    w.updated_at AS workflow_updated_at
                FROM cloud_orders o
                LEFT JOIN cloud_workflows w
                  ON w.order_number = o.order_number AND w.active = TRUE
                WHERE o.active = TRUE
                ORDER BY o.order_date DESC, o.order_number DESC, w.sort_order, w.workflow_key
            """)
            raw_rows = [get_row_dict(r, cur) or {} for r in cur.fetchall()]

            cur.execute("""
                SELECT workflow_key, status, action_date, sort_order
                FROM cloud_workflow_history
                WHERE active = TRUE
                ORDER BY workflow_key, sort_order, action_date, history_key
            """)
            history = defaultdict(list)
            for raw in cur.fetchall():
                item = get_row_dict(raw, cur) or {}
                history[str(item.get("workflow_key") or "")].append(item)
        finally:
            conn.close()

        result = []
        for source in raw_rows:
            workflow_key = str(source.get("workflow_key") or "")
            timeline = history.get(workflow_key, [])
            last_event = timeline[-1] if timeline else {}
            last_change = (
                source.get("last_status_change_date")
                or last_event.get("action_date")
                or source.get("workflow_updated_at")
                or source.get("order_updated_at")
                or ""
            )

            if not workflow_key:
                row = {
                    "order_number": source.get("order_number"),
                    "workflow_number": "",
                    "customer_name": source.get("customer_name") or "",
                    "order_date": source.get("order_date") or "",
                    "order_status": source.get("order_status") or "ACTIVE",
                    "visibility": "all_sales",
                    "current_status": "",
                    "status_light": "grey",
                    "status_light_hint": "",
                    "handler_name": "",
                    "handler_id": None,
                    "created_by_id": None,
                    "product_name": source.get("order_product_name") or "",
                    "product_code": source.get("order_product_code") or "",
                    "pattern_code": source.get("pattern_code") or "",
                    "quantity": source.get("order_quantity") or "",
                    "factory": "",
                    "production_type": source.get("order_production_type") or "",
                    "expected_delivery_date": source.get("order_expected_delivery_date") or "",
                    "status_days": 0,
                    "is_locked": 1,
                    "can_edit_notes": False,
                    "no_workflow": True,
                    "last_history_id": None,
                    "last_status_change_date": "",
                    "draft_date": None,
                    "last_shipping_date": "",
                    "last_shipping_status": "",
                    "partial_ship_count": 0,
                    "notes": "",
                }
                result.append(row)
                continue

            shipping_events = [
                h for h in timeline
                if str(h.get("status") or "").upper() in {
                    "PARTIAL_SHIPPED", "ALL_SHIPPED", "SHIPPED", "COMPLETED"
                }
            ]
            last_shipping = shipping_events[-1] if shipping_events else {}
            partial_count = sum(
                1 for h in timeline
                if str(h.get("status") or "").upper() == "PARTIAL_SHIPPED"
            )

            row = {
                "order_number": source.get("order_number"),
                "workflow_number": source.get("workflow_number") or workflow_key,
                "customer_name": source.get("customer_name") or "",
                "order_date": source.get("order_date") or "",
                "order_status": source.get("order_status") or "ACTIVE",
                "visibility": "all_sales",
                "current_status": source.get("current_status") or "",
                "status_updated_at": last_change,
                "handler_name": "",
                "handler_id": None,
                "created_by_id": None,
                "product_name": source.get("product_name") or source.get("order_product_name") or "",
                "product_code": source.get("product_code") or source.get("order_product_code") or "",
                "pattern_code": source.get("pattern_code") or "",
                "quantity": source.get("quantity") or source.get("order_quantity") or "",
                "factory": "",
                "production_type": source.get("production_type") or source.get("workflow_type") or source.get("order_production_type") or "",
                "expected_delivery_date": source.get("expected_delivery_date") or source.get("order_expected_delivery_date") or "",
                "status_days": self._days_since(last_change),
                "is_locked": 1,
                "can_edit_notes": False,
                "no_workflow": False,
                "last_history_id": None,
                "last_status_change_date": last_change,
                "draft_date": source.get("draft_date"),
                "last_shipping_date": last_shipping.get("action_date") or "",
                "last_shipping_status": last_shipping.get("status") or "",
                "partial_ship_count": partial_count,
                "notes": "",
            }
            row["status_light"], row["status_light_hint"] = self._safe_status_light(row)
            result.append(row)

        return result

    def get_last_synced_at(self):
        self._ensure()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute("SELECT MAX(updated_at) AS last_synced_at FROM cloud_orders WHERE active=TRUE")
            data = get_row_dict(cur.fetchone(), cur) or {}
            value = data.get("last_synced_at")
            return None if value is None else str(value)
        finally:
            conn.close()
