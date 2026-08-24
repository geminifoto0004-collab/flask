"""Customer-level TiDB reconciliation against the local SQLite manifest.

This endpoint removes stale LOGICAL rows only. It never deletes B2 bytes. The caller is
expected to upload/relink current images first, then reconcile image metadata, then call
this endpoint with the customer's current SQLite order-number set.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_customer_storage import _INTENT_TABLE


@b2_test_bp.before_app_request
def _reconcile_customer_orders():
    if request.method != "POST" or request.path != "/api/order-cloud/customer/reconcile-orders":
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        customer_key = str(payload.get("customer_key") or "").strip()
        raw_orders = payload.get("order_numbers")
        if not customer_key:
            return jsonify({"ok": False, "error": "customer_key is required"}), 400
        if not isinstance(raw_orders, list):
            return jsonify({"ok": False, "error": "order_numbers must be a list"}), 400
        if len(raw_orders) > 50000:
            return jsonify({"ok": False, "error": "too many order_numbers"}), 400

        expected = {
            str(value or "").strip()
            for value in raw_orders
            if str(value or "").strip()
        }
        if not expected and not bool(payload.get("confirm_empty", False)):
            return jsonify({"ok": False, "error": "empty order manifest requires confirm_empty=true"}), 400

        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                "SELECT order_number FROM cloud_orders WHERE customer_key=?",
                (customer_key,),
            )
            current = {
                str((get_row_dict(row, cur) or {}).get("order_number") or "").strip()
                for row in cur.fetchall() or []
            }
            stale = sorted(value for value in current if value and value not in expected)

            # Child rows first; no FK cascade is assumed. B2 objects are deliberately
            # untouched. cloud_assets is logical metadata and follows SQLite ownership.
            for order_number in stale:
                cur.execute("DELETE FROM cloud_workflow_history WHERE order_number=?", (order_number,))
                cur.execute("DELETE FROM cloud_workflows WHERE order_number=?", (order_number,))
                cur.execute(
                    "DELETE FROM cloud_assets WHERE customer_key=? AND order_number=?",
                    (customer_key, order_number),
                )
                cur.execute(
                    f"DELETE FROM {_INTENT_TABLE} WHERE customer_key=? AND order_number=?",
                    (customer_key, order_number),
                )
                cur.execute(
                    "DELETE FROM cloud_orders WHERE customer_key=? AND order_number=?",
                    (customer_key, order_number),
                )

            cur.execute("SELECT COUNT(*) AS n FROM cloud_orders WHERE customer_key=?", (customer_key,))
            row = cur.fetchone()
            count_data = get_row_dict(row, cur) if row else {}
            remaining = int((count_data or {}).get("n") or 0)
            if remaining == 0:
                cur.execute("DELETE FROM cloud_customers WHERE customer_key=?", (customer_key,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        # Rebuild/invalidate the same existing share snapshots immediately. If the
        # customer was removed because SQLite has no orders, rebuild_snapshot returns None.
        from services import order_customer_share_snapshot as snapshot
        bundle = snapshot.rebuild_snapshot(customer_key)
        return jsonify({"ok": True, "result": {
            "customer_key": customer_key,
            "expected_orders": len(expected),
            "stale_orders_removed": len(stale),
            "remaining_orders": remaining,
            "physical_objects_deleted": 0,
            "snapshot_present": bool(bundle),
        }})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 500
