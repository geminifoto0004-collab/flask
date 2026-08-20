#!/usr/bin/env python3
"""Make Render ORDER drawer read the same operational text shape as LAN.

Keeps LAN SQLite paths untouched. The cloud mirror still excludes media, local paths,
phone/payment/deposit data. Operational ORDER text used by the authenticated drawer
(notes/factory/handler/history notes) is carried in cloud_orders.render_payload.
"""
from pathlib import Path
import py_compile
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


def patch_sync_script():
    path = ROOT / "scripts" / "order_cloud_sync_real_order.py"
    text = path.read_text("utf-8")

    text = re.sub(
        r"SAFE_ORDER_COLUMNS = \{.*?\}\nSAFE_WORKFLOW_COLUMNS = \{",
        '''SAFE_ORDER_COLUMNS = {\n    "order_number", "customer_name", "order_date", "status", "current_status",\n    "visibility", "is_locked", "notes", "created_by", "updated_by", "updated_at",\n    "production_type", "product_name", "product_code", "pattern_code", "quantity",\n    "expected_delivery_date",\n}\nSAFE_WORKFLOW_COLUMNS = {''',
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"SAFE_WORKFLOW_COLUMNS = \{.*?\}\nSAFE_HISTORY_COLUMNS = \{",
        '''SAFE_WORKFLOW_COLUMNS = {\n    "workflow_number", "order_number", "current_status", "production_type",\n    "product_name", "product_code", "quantity", "factory",\n    "expected_delivery_date", "status_updated_at", "status_days",\n    "created_by_id", "handler_id", "notes", "created_at", "updated_at",\n}\nSAFE_HISTORY_COLUMNS = {''',
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"SAFE_HISTORY_COLUMNS = \{.*?\}\n\n\nclass SyncError",
        '''SAFE_HISTORY_COLUMNS = {\n    "id", "workflow_number", "from_status", "to_status", "action_date",\n    "operator_id", "notes", "created_at",\n}\n\n\nclass SyncError''',
        text,
        count=1,
        flags=re.S,
    )

    old_hist = '''            {\n                "history_key": history_key,\n                "status": status,\n                "action_date": action_date,\n                "sort_order": pos,\n            }'''
    new_hist = '''            {\n                "history_key": history_key,\n                "status": status,\n                "from_status": _clean(item.get("from_status")),\n                "action_date": action_date,\n                "operator_id": item.get("operator_id"),\n                "notes": _clean(item.get("notes")),\n                "created_at": _clean(item.get("created_at")),\n                "sort_order": pos,\n            }'''
    text = replace_once(text, old_hist, new_hist, "history payload")

    old_order = '''        "order_date": order.get("order_date"),\n        "expected_delivery_date": order.get("expected_delivery_date"),'''
    new_order = '''        "order_date": order.get("order_date"),\n        "visibility": order.get("visibility"),\n        "is_locked": order.get("is_locked"),\n        "notes": order.get("notes"),\n        "created_by": order.get("created_by"),\n        "updated_by": order.get("updated_by"),\n        "updated_at": order.get("updated_at"),\n        "expected_delivery_date": order.get("expected_delivery_date"),'''
    text = replace_once(text, old_order, new_order, "order operational fields")

    old_wf = '''                        "quantity": wf.get("quantity"),\n                        "expected_delivery_date": wf.get("expected_delivery_date"),\n                        "last_status_change_date": last_history_date or wf.get("status_updated_at"),'''
    new_wf = '''                        "quantity": wf.get("quantity"),\n                        "factory": wf.get("factory"),\n                        "expected_delivery_date": wf.get("expected_delivery_date"),\n                        "status_days": wf.get("status_days"),\n                        "created_by_id": wf.get("created_by_id"),\n                        "handler_id": wf.get("handler_id"),\n                        "notes": wf.get("notes"),\n                        "created_at": wf.get("created_at"),\n                        "updated_at": wf.get("updated_at"),\n                        "last_status_change_date": last_history_date or wf.get("status_updated_at"),'''
    text = replace_once(text, old_wf, new_wf, "workflow operational fields")

    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_cloud_service():
    path = ROOT / "services" / "order_cloud_service.py"
    text = path.read_text("utf-8")
    if "import json\n" not in text:
        text = text.replace("from datetime import datetime, timedelta\n", "from datetime import datetime, timedelta\nimport json\n", 1)

    anchor = '''        for name, definition in (\n            ("production_type", "VARCHAR(191) NULL"),'''
    if '"render_payload", "LONGTEXT NULL"' not in text:
        insert = '''        _ensure_column(cur, "cloud_orders", "render_payload", "LONGTEXT NULL")\n\n'''
        if anchor not in text:
            raise RuntimeError("cloud_orders migration anchor not found")
        text = text.replace(anchor, insert + anchor, 1)

    if "SET render_payload=? WHERE order_number=?" not in text:
        anchor2 = "        seen_workflows = []\n"
        block = '''        # Authenticated Render ORDER may need the LAN drawer's operational text.\n        # This JSON deliberately comes from the local whitelist; it contains no media,\n        # local paths, phone, payment or deposit data. Public customer-share routes do\n        # not return this column.\n        cur.execute(\n            "UPDATE cloud_orders SET render_payload=? WHERE order_number=?",\n            (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), order_number),\n        )\n\n'''
        if anchor2 not in text:
            raise RuntimeError("sync_order seen_workflows anchor not found")
        text = text.replace(anchor2, block + anchor2, 1)

    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_snapshot_service():
    path = ROOT / "services" / "order_cloud_snapshot_service.py"
    text = path.read_text("utf-8")
    if "render_payload_rows = [" not in text:
        anchor = "        if workflows:\n"
        block = '''        render_payload_rows = [\n            (\n                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),\n                str(payload.get("order_number") or "").strip(),\n            )\n            for payload in payloads\n            if isinstance(payload, dict) and str(payload.get("order_number") or "").strip()\n        ]\n        if render_payload_rows:\n            executemany_sql(\n                cur,\n                "UPDATE cloud_orders SET render_payload=? WHERE order_number=?",\n                render_payload_rows,\n            )\n\n'''
        if anchor not in text:
            raise RuntimeError("snapshot workflows anchor not found")
        text = text.replace(anchor, block + anchor, 1)
    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_provider_interface():
    path = ROOT / "order_tracking" / "data_provider.py"
    text = path.read_text("utf-8")
    if "def get_workflows_for_order(" not in text:
        anchor = "    def get_order_detail(self, order_number: str):"
        block = '''    def get_workflows_for_order(self, order_number: str, role: str = 'viewer',\n                                user_id: Any = None):  # pragma: no cover - interface only\n        raise NotImplementedError\n\n'''
        if anchor not in text:
            raise RuntimeError("provider interface anchor not found")
        text = text.replace(anchor, block + anchor, 1)
    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_render_provider():
    path = ROOT / "services" / "order_tracking_render_provider.py"
    text = path.read_text("utf-8")
    if "import json\n" not in text:
        text = text.replace("from datetime import date, datetime\n", "from datetime import date, datetime\nimport json\n", 1)

    marker = "    # Enhanced LAN-compatible drawer readers use render_payload."
    if marker not in text:
        anchor = "    def get_last_synced_at(self):\n"
        if anchor not in text:
            raise RuntimeError("render provider get_last_synced_at anchor not found")
        block = r'''    # Enhanced LAN-compatible drawer readers use render_payload.  Defining these
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

'''
        text = text.replace(anchor, block + anchor, 1)

    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_shared_routes():
    path = ROOT / "order_tracking" / "__init__.py"
    text = path.read_text("utf-8")
    marker = "_cloud_provider_call('get_workflows_for_order', order_number"
    if marker not in text:
        anchor = '''    if not order_number:\n        return jsonify({'success': False, 'error': '缺少訂單號參數'}), 400\n    \n    conn = get_db()\n'''
        block = '''    if not order_number:\n        return jsonify({'success': False, 'error': '缺少訂單號參數'}), 400\n\n    if cloud_mode_enabled():\n        current_ctx = get_current_user_context()\n        try:\n            workflows = _cloud_provider_call(\n                'get_workflows_for_order', order_number,\n                current_ctx.get('role', 'viewer'), current_ctx.get('id')\n            ) or []\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端流程列表載入失敗: {exc}'}), 503\n        return jsonify({\n            'success': True,\n            'data': {'order_number': order_number, 'workflows': list(workflows)}\n        })\n    \n    conn = get_db()\n'''
        if anchor not in text:
            raise RuntimeError("api_list_workflows anchor not found")
        # Restrict replacement to the GET route, not unrelated functions with same fragment.
        start = text.index("def api_list_workflows():")
        pos = text.find(anchor, start)
        if pos < 0:
            raise RuntimeError("api_list_workflows local DB anchor not found")
        text = text[:pos] + block + text[pos + len(anchor):]

    path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)


def main():
    patch_sync_script()
    patch_cloud_service()
    patch_snapshot_service()
    patch_provider_interface()
    patch_render_provider()
    patch_shared_routes()

    checks = {
        ROOT / "services" / "order_cloud_service.py": "render_payload",
        ROOT / "services" / "order_cloud_snapshot_service.py": "render_payload_rows",
        ROOT / "services" / "order_tracking_render_provider.py": "get_workflows_for_order",
        ROOT / "order_tracking" / "__init__.py": "get_workflows_for_order",
        ROOT / "scripts" / "order_cloud_sync_real_order.py": '"handler_id"',
    }
    for path, needle in checks.items():
        if needle not in path.read_text("utf-8"):
            raise RuntimeError(f"validation failed: {path.name} missing {needle}")
    print("ORDER drawer cloud compatibility applied")


if __name__ == "__main__":
    main()
