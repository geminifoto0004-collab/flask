"""Protected cloud-storage inventory for SQLite-authoritative ORDER rebuilds.

This endpoint exposes only customer keys and row counts to the authenticated office sync
client. It never returns B2 credentials, bucket names, object keys, signed URLs or image
bytes. The inventory lets a deliberate full rebuild also find cloud-only customers that
no longer exist in the current local SQLite database.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_customer_storage import _TABLE, _ensure_table


def _group_counts(cur, table_name, column="customer_key"):
    try:
        cur.execute(
            f"SELECT {column} AS customer_key, COUNT(*) AS n "
            f"FROM {table_name} WHERE {column} IS NOT NULL AND {column}<>'' "
            f"GROUP BY {column}"
        )
    except Exception:
        return {}
    result = {}
    for row in cur.fetchall() or []:
        data = get_row_dict(row, cur) or {}
        key = str(data.get("customer_key") or "").strip()
        if key:
            result[key] = int(data.get("n") or 0)
    return result


@b2_test_bp.before_app_request
def _order_cloud_storage_inventory():
    if request.method != "POST" or request.path != "/api/order-cloud/storage/customers":
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        _ensure_table()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            orders = _group_counts(cur, "cloud_orders")
            assets = _group_counts(cur, "cloud_assets")
            shares = _group_counts(cur, "cloud_share_tokens")
            customers = _group_counts(cur, "cloud_customers")

            assignments = {}
            try:
                cur.execute(
                    f"SELECT customer_key, storage_backend FROM {_TABLE} "
                    "WHERE customer_key IS NOT NULL AND customer_key<>''"
                )
                for row in cur.fetchall() or []:
                    data = get_row_dict(row, cur) or {}
                    key = str(data.get("customer_key") or "").strip()
                    backend = str(data.get("storage_backend") or "").strip().lower()
                    if key:
                        assignments[key] = backend or None
            except Exception:
                assignments = {}
        finally:
            conn.close()

        keys = sorted(set(orders) | set(assets) | set(shares) | set(customers) | set(assignments))
        items = [
            {
                "customer_key": key,
                "orders": int(orders.get(key) or 0),
                "assets": int(assets.get(key) or 0),
                "shares": int(shares.get(key) or 0),
                "customer_rows": int(customers.get(key) or 0),
                "assigned_backend": assignments.get(key),
            }
            for key in keys
        ]
        return jsonify({
            "ok": True,
            "result": {
                "customers": items,
                "customer_count": len(items),
                "exposes_object_keys": False,
                "exposes_credentials": False,
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 500
