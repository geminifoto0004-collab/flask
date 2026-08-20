"""Read-only ORDER provider for the Render-hosted ORDER UI.

The vendored ORDER HTML/JS/routes are shared with LAN. This provider only changes
where read data comes from: LAN keeps SQLite, while Render reads the customer-safe
TiDB cloud_* mirror. No local files, Access data, phone/payment/deposit data,
internal notes or local paths are exposed here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import json
from threading import Lock

from database import get_cursor, get_db_connection, get_row_dict


class RenderOrderDataProvider:
    """Supply the existing ORDER read APIs with TiDB-backed rows."""

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
    def _date_only(value):
        if not value:
            return None
        try:
            return datetime.strptime(str(value).strip().split()[0], "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _months_ago(months: int) -> date:
        today = date.today()
        year = today.year
        month = today.month - int(months)
        while month <= 0:
            year -= 1
            month += 12
        for day in range(today.day, 27, -1):
            try:
                return date(year, month, day)
            except ValueError:
                pass
        return date(year, month, min(today.day, 28))

    @staticmethod
    def _safe_status_light(row: dict) -> tuple[str, str]:
        try:
            from order_tracking.models import calculate_status_light, get_status_light_hint
            obj = {
                "order_number": row.get("order_number"),
                "order_date": row.get("order_date"),
                "expected_delivery_date": row.get("expected_delivery_date"),
                "status_updated_at": row.get("last_status_change_date") or row.get("status_updated_at"),
                "current_status": row.get("current_status"),
                "last_status_change_date": row.get("last_status_change_date") or row.get("status_updated_at"),
            }
            return calculate_status_light(obj), get_status_light_hint(obj)
        except Exception:
            return "grey", ""

    def _history_map(self, cur, workflow_keys=None):
        params = []
        where = "WHERE active=TRUE"
        if workflow_keys:
            placeholders = ",".join(["?"] * len(workflow_keys))
            where += f" AND workflow_key IN ({placeholders})"
            params.extend(workflow_keys)
        cur.execute(
            f"""SELECT history_key, workflow_key, order_number, status, action_date,
                       sort_order, updated_at
                FROM cloud_workflow_history
                {where}
                ORDER BY workflow_key, sort_order, action_date, history_key""",
            params,
        )
        history = defaultdict(list)
        for raw in cur.fetchall():
            item = get_row_dict(raw, cur) or {}
            history[str(item.get("workflow_key") or "")].append(item)
        return history

    def _load_joined_rows(self, customer_name=None):
        self._ensure()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            where = "WHERE o.active=TRUE"
            params = []
            if customer_name:
                where += " AND LOWER(o.customer_name)=LOWER(?)"
                params.append(str(customer_name).strip())
            cur.execute(
                f"""
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
                  ON w.order_number=o.order_number AND w.active=TRUE
                {where}
                ORDER BY o.order_date DESC, o.order_number DESC, w.sort_order, w.workflow_key
                """,
                params,
            )
            raw_rows = [get_row_dict(r, cur) or {} for r in cur.fetchall()]
            keys = [str(r.get("workflow_key") or "") for r in raw_rows if r.get("workflow_key")]
            history = self._history_map(cur, keys) if keys else {}
            return raw_rows, history
        finally:
            conn.close()

    def _home_row(self, source: dict, timeline: list[dict]) -> dict:
        workflow_key = str(source.get("workflow_key") or "")
        last_event = timeline[-1] if timeline else {}
        last_change = (
            source.get("last_status_change_date")
            or last_event.get("action_date")
            or source.get("workflow_updated_at")
            or source.get("order_updated_at")
            or ""
        )
        if not workflow_key:
            return {
                "order_number": source.get("order_number"), "workflow_number": "",
                "customer_name": source.get("customer_name") or "", "order_date": source.get("order_date") or "",
                "order_status": source.get("order_status") or "ACTIVE", "visibility": "all_sales",
                "current_status": "", "status_light": "grey", "status_light_hint": "",
                "handler_name": "", "handler_id": None, "created_by_id": None,
                "product_name": source.get("order_product_name") or "",
                "product_code": source.get("order_product_code") or "", "pattern_code": source.get("pattern_code") or "",
                "quantity": source.get("order_quantity") or "", "factory": "",
                "production_type": source.get("order_production_type") or "",
                "expected_delivery_date": source.get("order_expected_delivery_date") or "",
                "status_days": 0, "is_locked": 1, "can_edit_notes": False, "no_workflow": True,
                "last_history_id": None, "last_status_change_date": "", "draft_date": None,
                "last_shipping_date": "", "last_shipping_status": "", "partial_ship_count": 0, "notes": "",
            }

        shipping_events = [
            h for h in timeline
            if str(h.get("status") or "").upper() in {"PARTIAL_SHIPPED", "ALL_SHIPPED", "SHIPPED", "COMPLETED"}
        ]
        last_shipping = shipping_events[-1] if shipping_events else {}
        partial_count = sum(1 for h in timeline if str(h.get("status") or "").upper() == "PARTIAL_SHIPPED")
        row = {
            "order_number": source.get("order_number"),
            "workflow_number": source.get("workflow_number") or workflow_key,
            "customer_name": source.get("customer_name") or "", "order_date": source.get("order_date") or "",
            "order_status": source.get("order_status") or "ACTIVE", "visibility": "all_sales",
            "current_status": source.get("current_status") or "", "status_updated_at": last_change,
            "handler_name": "", "handler_id": None, "created_by_id": None,
            "product_name": source.get("product_name") or source.get("order_product_name") or "",
            "product_code": source.get("product_code") or source.get("order_product_code") or "",
            "pattern_code": source.get("pattern_code") or "",
            "quantity": source.get("quantity") or source.get("order_quantity") or "", "factory": "",
            "production_type": source.get("production_type") or source.get("workflow_type") or source.get("order_production_type") or "",
            "expected_delivery_date": source.get("expected_delivery_date") or source.get("order_expected_delivery_date") or "",
            "status_days": self._days_since(last_change), "is_locked": 1, "can_edit_notes": False, "no_workflow": False,
            "last_history_id": None, "last_status_change_date": last_change, "draft_date": source.get("draft_date"),
            "last_shipping_date": last_shipping.get("action_date") or "",
            "last_shipping_status": last_shipping.get("status") or "", "partial_ship_count": partial_count, "notes": "",
        }
        row["status_light"], row["status_light_hint"] = self._safe_status_light(row)
        return row

    def load_home_orders(self, role: str, user_id):
        raw_rows, history = self._load_joined_rows()
        return [self._home_row(row, history.get(str(row.get("workflow_key") or ""), [])) for row in raw_rows]

    def get_order_detail(self, order_number: str):
        self._ensure()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT order_number, customer_name, order_status, order_date,
                          expected_delivery_date, production_type, product_name, product_code,
                          pattern_code, quantity, source_site, updated_at
                   FROM cloud_orders WHERE order_number=? AND active=TRUE""",
                (str(order_number).strip(),),
            )
            data = get_row_dict(cur.fetchone(), cur) or None
            if not data:
                return None
            data.update({
                "status": data.get("order_status") or "ACTIVE",
                "visibility": "all_sales", "is_locked": 1, "notes": "", "history": [],
            })
            return data
        finally:
            conn.close()

    def get_workflow_detail(self, workflow_number: str):
        self._ensure()
        key = str(workflow_number or "").strip()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT w.workflow_key, w.workflow_number, w.order_number, w.workflow_type,
                          w.status AS current_status, w.production_type, w.product_name,
                          w.product_code, w.quantity, w.expected_delivery_date,
                          w.last_status_change_date, w.draft_date, w.sort_order, w.updated_at,
                          o.customer_name, o.order_date, o.order_status, o.pattern_code
                   FROM cloud_workflows w
                   INNER JOIN cloud_orders o ON o.order_number=w.order_number AND o.active=TRUE
                   WHERE w.active=TRUE AND (w.workflow_number=? OR w.workflow_key=?)
                   LIMIT 1""",
                (key, key),
            )
            workflow = get_row_dict(cur.fetchone(), cur) or None
            if not workflow:
                return None
            workflow_key = str(workflow.get("workflow_key") or key)
            timeline = self._history_map(cur, [workflow_key]).get(workflow_key, [])
        finally:
            conn.close()

        history = []
        previous = ""
        for item in timeline:
            status = item.get("status") or ""
            history.append({
                "id": None,
                "history_key": item.get("history_key"),
                "workflow_number": workflow.get("workflow_number") or workflow_key,
                "order_number": workflow.get("order_number"),
                "from_status": previous,
                "to_status": status,
                "status": status,
                "action_date": item.get("action_date") or "",
                "created_at": item.get("updated_at") or item.get("action_date") or "",
                "notes": "",
                "operator_name": "",
                "operator": "",
            })
            previous = status

        last_change = workflow.get("last_status_change_date") or (history[-1].get("action_date") if history else "")
        result = {
            **workflow,
            "workflow_number": workflow.get("workflow_number") or workflow_key,
            "workflow_type": workflow.get("workflow_type") or workflow.get("production_type") or "",
            "status_updated_at": last_change,
            "status_days": self._days_since(last_change),
            "visibility": "all_sales", "handler_name": "", "handler_id": None, "created_by_id": None,
            "factory": "", "folder_path": "", "notes": "", "workflow_notes": "", "order_notes": "",
            "is_locked": 1, "can_edit_notes": False,
            "history": history, "last_history_id": None,
        }
        result["status_light"], result["status_light_hint"] = self._safe_status_light(result)
        return result

    def search_customers(self, query: str, limit: int = 10):
        self._ensure()
        needle = str(query or "").strip()
        if not needle:
            return []
        limit = max(1, min(int(limit or 10), 50))
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT DISTINCT customer_name
                   FROM cloud_customers
                   WHERE active=TRUE AND customer_name LIKE ?
                   ORDER BY customer_name
                   LIMIT ?""",
                (f"%{needle}%", limit),
            )
            result = []
            for row in cur.fetchall():
                data = get_row_dict(row, cur) or {}
                name = str(data.get("customer_name") or "").strip()
                if name:
                    result.append(name.upper())
            return result
        finally:
            conn.close()

    def get_customer_history(self, customer_name: str, history_scope: str = "current",
                             include_cancelled: bool = False, role: str = "viewer", user_id=None):
        raw_rows, history = self._load_joined_rows(customer_name)
        rows = [self._home_row(row, history.get(str(row.get("workflow_key") or ""), [])) for row in raw_rows]
        if not rows:
            return {"customer_name": str(customer_name or "").strip(), "data": []}
        exact_name = rows[0].get("customer_name") or str(customer_name or "").strip()

        scope = str(history_scope or "current").strip().lower()
        months = {"current": 3, "6m": 6, "12m": 12, "all": None}.get(scope, 3)
        cutoff = self._months_ago(months) if months is not None else None
        try:
            from order_tracking.status_definitions import STATUS_KEYS
            completed = STATUS_KEYS["COMPLETED"]
            cancelled = STATUS_KEYS["CANCELLED"]
        except Exception:
            completed, cancelled = "COMPLETED", "CANCELLED"

        filtered = []
        for row in rows:
            status = str(row.get("current_status") or "")
            if not row.get("workflow_number"):
                filtered.append(row)
                continue
            if status == cancelled and not include_cancelled:
                continue
            if cutoff is None:
                filtered.append(row)
                continue
            if status not in {completed, cancelled}:
                filtered.append(row)
                continue
            changed = self._date_only(row.get("last_status_change_date") or row.get("status_updated_at"))
            if changed and changed >= cutoff:
                filtered.append(row)
        return {"customer_name": exact_name, "data": filtered}

    # Enhanced LAN-compatible drawer readers use render_payload.  Defining these
    # later in the class intentionally replaces the earlier minimal methods.
    def _render_user_name(self, cur, user_id):
        if user_id in (None, ""):
            return ""
        cur.execute(
            """SELECT COALESCE(NULLIF(real_name,''), NULLIF(display_name,''), username) AS name
               FROM cloud_order_users WHERE local_user_id=? LIMIT 1""",
            (user_id,),
        )
        row = get_row_dict(cur.fetchone(), cur) or {}
        return str(row.get("name") or "")

    @staticmethod
    def _decode_render_payload(raw):
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            value = json.loads(str(raw))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def get_workflows_for_order(self, order_number: str, role: str = "viewer", user_id=None):
        self._ensure()
        order_number = str(order_number or "").strip()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                "SELECT render_payload FROM cloud_orders WHERE order_number=? AND active=TRUE LIMIT 1",
                (order_number,),
            )
            row = get_row_dict(cur.fetchone(), cur) or {}
            payload = self._decode_render_payload(row.get("render_payload"))
            result = []
            for wf in payload.get("workflows") or []:
                if not isinstance(wf, dict):
                    continue
                handler_id = wf.get("handler_id")
                result.append({
                    "workflow_number": wf.get("workflow_number") or wf.get("workflow_key") or "",
                    "order_number": order_number,
                    "handler_id": handler_id,
                    "handler_name": self._render_user_name(cur, handler_id),
                    "current_status": wf.get("status") or wf.get("current_status") or "",
                    "status_days": wf.get("status_days") or self._days_since(wf.get("last_status_change_date")),
                })
            if result:
                return result

            cur.execute(
                """SELECT workflow_number, workflow_key, status AS current_status, last_status_change_date
                   FROM cloud_workflows
                   WHERE order_number=? AND active=TRUE
                   ORDER BY sort_order, workflow_number, workflow_key""",
                (order_number,),
            )
            return [
                {
                    "workflow_number": (get_row_dict(r, cur) or {}).get("workflow_number")
                                       or (get_row_dict(r, cur) or {}).get("workflow_key") or "",
                    "order_number": order_number,
                    "handler_id": None,
                    "handler_name": "",
                    "current_status": (get_row_dict(r, cur) or {}).get("current_status") or "",
                    "status_days": self._days_since((get_row_dict(r, cur) or {}).get("last_status_change_date")),
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def get_order_detail(self, order_number: str):
        self._ensure()
        order_number = str(order_number or "").strip()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT order_number, customer_name, order_status, order_date,
                          expected_delivery_date, production_type, product_name, product_code,
                          pattern_code, quantity, source_site, updated_at, render_payload
                   FROM cloud_orders WHERE order_number=? AND active=TRUE LIMIT 1""",
                (order_number,),
            )
            data = get_row_dict(cur.fetchone(), cur) or None
            if not data:
                return None
            payload = self._decode_render_payload(data.pop("render_payload", None))
            for name in ("visibility", "is_locked", "notes", "created_by", "updated_by"):
                if name in payload:
                    data[name] = payload.get(name)
            data.update({
                "status": data.get("order_status") or payload.get("order_status") or "ACTIVE",
                "visibility": data.get("visibility") or "all_sales",
                "is_locked": int(bool(data.get("is_locked"))) if data.get("is_locked") is not None else 1,
                "notes": data.get("notes") or "",
                "history": [],
            })
            return data
        finally:
            conn.close()

    def get_workflow_detail(self, workflow_number: str):
        self._ensure()
        key = str(workflow_number or "").strip()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """SELECT w.workflow_key, w.workflow_number, w.order_number, w.workflow_type,
                          w.status AS current_status, w.production_type, w.product_name,
                          w.product_code, w.quantity, w.expected_delivery_date,
                          w.last_status_change_date, w.draft_date, w.sort_order, w.updated_at,
                          o.customer_name, o.order_date, o.order_status, o.pattern_code,
                          o.render_payload
                   FROM cloud_workflows w
                   INNER JOIN cloud_orders o ON o.order_number=w.order_number AND o.active=TRUE
                   WHERE w.active=TRUE AND (w.workflow_number=? OR w.workflow_key=?)
                   LIMIT 1""",
                (key, key),
            )
            base = get_row_dict(cur.fetchone(), cur) or None
            if not base:
                return None
            payload = self._decode_render_payload(base.pop("render_payload", None))
            source_wf = None
            for wf in payload.get("workflows") or []:
                if not isinstance(wf, dict):
                    continue
                wf_key = str(wf.get("workflow_number") or wf.get("workflow_key") or "").strip()
                if wf_key == key or wf_key == str(base.get("workflow_number") or base.get("workflow_key") or ""):
                    source_wf = wf
                    break
            source_wf = source_wf or {}
            timeline = source_wf.get("timeline") or []
            if not isinstance(timeline, list) or not timeline:
                workflow_key = str(base.get("workflow_key") or key)
                timeline = self._history_map(cur, [workflow_key]).get(workflow_key, [])

            handler_id = source_wf.get("handler_id")
            handler_name = self._render_user_name(cur, handler_id)
            user_ids = {item.get("operator_id") for item in timeline if isinstance(item, dict) and item.get("operator_id") not in (None, "")}
            user_names = {uid: self._render_user_name(cur, uid) for uid in user_ids}
        finally:
            conn.close()

        history = []
        previous = ""
        for pos, item in enumerate(timeline):
            if not isinstance(item, dict):
                continue
            status = item.get("status") or item.get("to_status") or ""
            from_status = item.get("from_status") or previous
            operator_id = item.get("operator_id")
            history.append({
                "id": item.get("id") or item.get("history_key") or pos,
                "history_key": item.get("history_key"),
                "workflow_number": base.get("workflow_number") or base.get("workflow_key") or key,
                "order_number": base.get("order_number"),
                "from_status": from_status,
                "to_status": status,
                "status": status,
                "action_date": item.get("action_date") or "",
                "created_at": item.get("created_at") or item.get("updated_at") or item.get("action_date") or "",
                "notes": item.get("notes") or "",
                "operator_id": operator_id,
                "operator_name": user_names.get(operator_id, ""),
                "operator": user_names.get(operator_id, ""),
            })
            previous = status

        last_change = source_wf.get("last_status_change_date") or base.get("last_status_change_date") or (history[-1].get("action_date") if history else "")
        result = {
            **base,
            "workflow_number": source_wf.get("workflow_number") or base.get("workflow_number") or base.get("workflow_key") or key,
            "workflow_type": source_wf.get("workflow_type") or source_wf.get("production_type") or base.get("workflow_type") or base.get("production_type") or "",
            "current_status": source_wf.get("status") or source_wf.get("current_status") or base.get("current_status") or "",
            "production_type": source_wf.get("production_type") or base.get("production_type") or "",
            "product_name": source_wf.get("product_name") or base.get("product_name") or "",
            "product_code": source_wf.get("product_code") or base.get("product_code") or "",
            "quantity": source_wf.get("quantity") if source_wf.get("quantity") is not None else (base.get("quantity") or ""),
            "factory": source_wf.get("factory") or "",
            "expected_delivery_date": source_wf.get("expected_delivery_date") or base.get("expected_delivery_date") or "",
            "status_updated_at": last_change,
            "status_days": source_wf.get("status_days") or self._days_since(last_change),
            "visibility": payload.get("visibility") or "all_sales",
            "handler_name": handler_name,
            "handler_id": handler_id,
            "created_by_id": source_wf.get("created_by_id"),
            "folder_path": "",
            "notes": source_wf.get("notes") or "",
            "workflow_notes": source_wf.get("notes") or "",
            "order_notes": payload.get("notes") or "",
            "is_locked": int(bool(payload.get("is_locked"))) if payload.get("is_locked") is not None else 1,
            "can_edit_notes": False,
            "history": history,
            "last_history_id": history[-1].get("id") if history else None,
        }
        result["status_light"], result["status_light_hint"] = self._safe_status_light(result)
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
