"""Customer-level TiDB reconciliation against the local SQLite manifest.

This endpoint removes stale LOGICAL rows only. It never deletes B2 bytes. The caller is
expected to upload/relink current images first, then reconcile image metadata, then call
this endpoint with the customer's current SQLite order-number set.
"""
from __future__ import annotations

import hashlib
import json

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_customer_storage import _INTENT_TABLE


def _delete_stale_order_numbers(cur, customer_key, stale):
    """Delete stale logical rows in bounded SQL batches, never one order at a time."""
    removed = 0
    for offset in range(0, len(stale), 500):
        batch = stale[offset:offset + 500]
        marks = ",".join("?" for _ in batch)
        values = tuple(batch)
        cur.execute(f"DELETE FROM cloud_workflow_history WHERE order_number IN ({marks})", values)
        cur.execute(f"DELETE FROM cloud_workflows WHERE order_number IN ({marks})", values)
        # Keep the metadata row as an inactive tombstone. The retention audit
        # needs its object_key/backend so it can remove the B2 bytes after grace.
        cur.execute(
            f"UPDATE cloud_assets SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE customer_key=? AND order_number IN ({marks})",
            (customer_key, *values),
        )
        cur.execute(
            f"DELETE FROM {_INTENT_TABLE} WHERE customer_key=? AND order_number IN ({marks})",
            (customer_key, *values),
        )
        cur.execute(
            f"DELETE FROM cloud_orders WHERE customer_key=? AND order_number IN ({marks})",
            (customer_key, *values),
        )
        removed += len(batch)
    return removed


def _snapshot_manifest(raw):
    """Certify the persisted bundle, never substitute current SQL rows for it."""
    try:
        snap = json.loads(raw or "{}")
        space = snap.get("space") or {}
        orders = space.get("orders") or []
        if not isinstance(orders, list):
            raise ValueError("invalid snapshot orders")
        numbers, cards = set(), set()
        for order in orders:
            if not isinstance(order, dict):
                raise ValueError("invalid snapshot order")
            number = str(order.get("order_number") or "").strip()
            if number:
                numbers.add(number)
            workflows = [w for w in (order.get("workflows") or []) if isinstance(w, dict)]
            if workflows:
                cards.update(str(w.get("workflow_number") or w.get("workflow_key") or "").strip()
                             for w in workflows)
            elif number:
                cards.add(number)
        hashes = snap.get("source_payload_hashes")
        return sorted(numbers), sorted(cards - {""}), hashes if isinstance(hashes, dict) else None
    except (TypeError, ValueError, AttributeError):
        return None, None, None


def _order_manifest_error(numbers, metadata):
    """Reject empty, malformed or explicitly incomplete local order manifests."""
    if not isinstance(numbers, list):
        return "INCOMPLETE_ORDER_MANIFEST", "order_numbers must be a list"
    if not numbers:
        return "EMPTY_ORDER_MANIFEST", "empty order manifest cannot remove any order"
    if len(numbers) > 50000 or any(not isinstance(x, str) or not x.strip() for x in numbers):
        return "INCOMPLETE_ORDER_MANIFEST", "invalid or incomplete order manifest"
    expected = {x.strip() for x in numbers}
    if (len(expected) != len(numbers)
            or metadata.get("manifest_complete") is False
            or metadata.get("scan_complete") is False
            or metadata.get("logistics_ready") is False
            or metadata.get("skipped_orders")
            or metadata.get("scan_errors")
            or (metadata.get("expected_order_count") is not None
                and str(metadata["expected_order_count"]) != str(len(expected)))):
        return "INCOMPLETE_ORDER_MANIFEST", "local order manifest is incomplete"
    return None


@b2_test_bp.before_app_request
def _reconcile_customer_orders():
    if request.method != "POST" or request.path not in {
        "/api/order-cloud/customer/manifest",
        "/api/order-cloud/customer/reconcile-orders",
        "/api/order-cloud/customer/reconcile-orders-batch",
        "/api/order-cloud/customer/snapshot",
    }:
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        customer_key = str(payload.get("customer_key") or "").strip()
        workflow_numbers = payload.get("workflow_order_numbers", None)
        if workflow_numbers is not None:
            if (not isinstance(workflow_numbers, list) or len(workflow_numbers) > 20 or
                    any(not isinstance(x, str) or not x.strip() or len(x) > 191 for x in workflow_numbers)):
                raise ValueError("workflow_order_numbers must contain at most 20 order IDs")
        raw_orders = payload.get("order_numbers")
        if not customer_key and not request.path.endswith("/reconcile-orders-batch"):
            return jsonify({"ok": False, "error": "customer_key is required"}), 400

        if request.path.endswith("/manifest"):
            conn = get_db_connection()
            cur = get_cursor(conn)
            try:
                cur.execute(
                    "SELECT order_number, render_payload, active, order_status, customer_key FROM cloud_orders "
                    "WHERE customer_key=? ORDER BY order_number",
                    (customer_key,),
                )
                items = []
                for row in cur.fetchall() or []:
                    data = get_row_dict(row, cur) or {}
                    order_number = str(data.get("order_number") or "").strip()
                    payload_hash = None
                    try:
                        decoded = json.loads(data.get("render_payload") or "")
                        canonical = json.dumps(
                            decoded,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ).encode("utf-8")
                        payload_hash = hashlib.sha256(canonical).hexdigest()
                    except Exception:
                        pass
                    if order_number:
                        items.append({
                            "order_number": order_number,
                            "payload_sha256": payload_hash,
                            "active": bool(data.get("active")),
                            "order_status": str(data.get("order_status") or "ACTIVE").strip().upper(),
                            "customer_key": str(data.get("customer_key") or "").strip(),
                        })
                # Read-only verification: a successful logical ORDER upsert does
                # not imply the customer-facing persisted snapshot is refreshed.
                # Opt-in bounded SQL proof, independent of the persisted snapshot.
                # B never treats the snapshot as proof that cloud_workflows exists.
                workflow_keys = None
                workflow_target = None
                if workflow_numbers is not None:
                    parents = sorted(set(workflow_numbers))
                    workflow_keys = {parent: [] for parent in parents}
                    workflow_target = getattr(conn, "active_target", "")
                    if parents:
                        placeholders = ",".join(["?"] * len(parents))
                        cur.execute("SELECT w.order_number,w.workflow_number,w.workflow_key "
                                    "FROM cloud_workflows w JOIN cloud_orders o "
                                    "ON o.order_number=w.order_number "
                                    "WHERE o.customer_key=? AND o.active=TRUE AND w.active=TRUE "
                                    "AND w.order_number IN (" + placeholders + ")",
                                    (customer_key, *parents))
                        for raw in cur.fetchall():
                            wf = get_row_dict(raw, cur) or {}
                            workflow_keys[wf['order_number']].append(
                                str(wf.get('workflow_number') or wf.get('workflow_key') or '').strip())
                cur.execute("SELECT payload, updated_at FROM cloud_customer_share_snapshot "
                            "WHERE customer_key=? LIMIT 1", (customer_key,))
                snapshot_row = cur.fetchone()
                snapshot_obj = get_row_dict(snapshot_row, cur) if snapshot_row else {}
                snapshot_numbers, snapshot_cards, snapshot_hashes = _snapshot_manifest(
                    (snapshot_obj or {}).get("payload"))
                try:
                    snapshot_meta = json.loads((snapshot_obj or {}).get('payload') or '{}')
                    snapshot_mode = snapshot_meta.get('data_mode')
                except (ValueError, TypeError, AttributeError):
                    snapshot_mode = 'invalid'
            finally:
                conn.close()
            from services import order_customer_share_snapshot as snapshot_runtime
            return jsonify({"ok": True, "result": {
                "customer_key": customer_key,
                "orders": items,
                "order_count": len(items),
                "snapshot_order_numbers": snapshot_numbers,
                "snapshot_card_keys": snapshot_cards,
                "snapshot_payload_hashes": snapshot_hashes,
                "tidb_workflow_keys": workflow_keys,
                "tidb_workflow_target": workflow_target,
                "manifest_version": 141,
                "snapshot_data_mode": snapshot_mode,
                "snapshot_updated_at": str((snapshot_obj or {}).get('updated_at') or ''),
                "snapshot_refresh": dict(snapshot_runtime._BUILD_PROGRESS.get(customer_key) or {}),
                "snapshot_refresh_slots_available": getattr(snapshot_runtime._BUILD_SLOTS, '_value', None),
            }})

        if request.path.endswith("/snapshot"):
            raw_payloads = payload.get("orders")
            if not isinstance(raw_payloads, list):
                return jsonify({"ok": False, "error": "orders must be a list"}), 400
            if not raw_payloads:
                return jsonify({"ok": False, "code": "EMPTY_ORDER_SNAPSHOT",
                                "error": "empty snapshot cannot replace remote orders"}), 400
            if (payload.get("manifest_complete") is not True
                    or payload.get("scan_complete") is False
                    or payload.get("logistics_ready") is False
                    or payload.get("skipped_orders") or payload.get("scan_errors")
                    or (payload.get("expected_order_count") is not None
                        and str(payload["expected_order_count"]) != str(len(raw_payloads)))):
                return jsonify({"ok": False, "code": "INCOMPLETE_ORDER_SNAPSHOT",
                                "error": "complete local snapshot is required before replace"}), 400
            from services.order_cloud_snapshot_service import replace_customer_snapshot
            result = replace_customer_snapshot(
                customer_key,
                raw_payloads,
                source_site=_source_site,
            )
            from services import order_customer_share_snapshot as snapshot
            bundle = snapshot.rebuild_snapshot(customer_key)
            result["snapshot_present"] = bool(bundle)
            return jsonify({"ok": True, "result": result})

        if request.path.endswith("/reconcile-orders-batch"):
            raw_customers = payload.get("customers")
            if not isinstance(raw_customers, list) or not 1 <= len(raw_customers) <= 100:
                return jsonify({"ok": False, "error": "customers must contain 1..100 entries"}), 400
            conn = get_db_connection()
            cur = get_cursor(conn)
            results = []
            try:
                for raw_customer in raw_customers:
                    if not isinstance(raw_customer, dict):
                        results.append({"customer_key": "", "ok": False, "error": "customer entry must be an object"})
                        continue
                    item = dict(raw_customer)
                    customer = str(item.get("customer_key") or "").strip()
                    numbers = item.get("order_numbers")
                    error = _order_manifest_error(numbers, item)
                    if not customer or error:
                        code, reason = error or ("INCOMPLETE_ORDER_MANIFEST", "customer_key is required")
                        results.append({"customer_key": customer, "ok": False,
                                        "code": code, "error": reason})
                        continue
                    expected = {value.strip() for value in numbers}
                    try:
                        cur.execute(
                            "SELECT order_number FROM cloud_orders WHERE customer_key=?",
                            (customer,),
                        )
                        current = {
                            str((get_row_dict(row, cur) or {}).get("order_number") or "").strip()
                            for row in cur.fetchall() or []
                        }
                        stale = sorted(value for value in current if value and value not in expected)
                        if stale and item.get("manifest_complete") is not True:
                            results.append({"customer_key": customer, "ok": False,
                                            "code": "INCOMPLETE_ORDER_MANIFEST",
                                            "error": "deleting stale orders requires a complete local manifest"})
                            continue
                        _delete_stale_order_numbers(cur, customer, stale)
                        cur.execute("SELECT COUNT(*) AS n FROM cloud_orders WHERE customer_key=?", (customer,))
                        count_row = cur.fetchone()
                        count_data = get_row_dict(count_row, cur) if count_row else {}
                        remaining = int((count_data or {}).get("n") or 0)
                        # A non-empty expected manifest must never erase an empty
                        # customer row when upstream order writes are missing.
                        conn.commit()
                        results.append({"customer_key": customer, "ok": True, "result": {
                            "customer_key": customer,
                            "expected_orders": len(expected),
                            "stale_orders_removed": len(stale),
                            "remaining_orders": remaining,
                            "physical_objects_deleted": 0,
                        }})
                    except Exception as exc:
                        conn.rollback()
                        results.append({"customer_key": customer, "ok": False,
                                        "error": str(exc), "error_type": type(exc).__name__})
            finally:
                conn.close()
            from services import order_customer_share_snapshot as snapshot
            for row in results:
                if row.get("ok") is True:
                    customer = str(row.get("customer_key") or "")
                    try:
                        snapshot.queue_snapshot_refresh(customer, delay=0.05)
                        row.setdefault("result", {})["snapshot_refresh_queued"] = True
                    except Exception as exc:
                        row.setdefault("result", {})["snapshot_refresh_queued"] = False
                        row["warning"] = f"snapshot refresh queue failed: {type(exc).__name__}"
            return jsonify({"ok": True, "result": {
                "items": results,
                "reconciled": sum(1 for row in results if row.get("ok") is True),
                "failed": sum(1 for row in results if row.get("ok") is not True),
            }})

        error = _order_manifest_error(raw_orders, payload)
        if error:
            code, reason = error
            return jsonify({"ok": False, "code": code, "error": reason}), 400
        expected = {value.strip() for value in raw_orders}

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
            if stale and payload.get("manifest_complete") is not True:
                return jsonify({"ok": False, "code": "INCOMPLETE_ORDER_MANIFEST",
                                "error": "deleting stale orders requires a complete local manifest"}), 400

            # Child rows first; no FK cascade is assumed. B2 objects are deliberately
            # untouched. cloud_assets is logical metadata and follows SQLite ownership.
            _delete_stale_order_numbers(cur, customer_key, stale)

            cur.execute("SELECT COUNT(*) AS n FROM cloud_orders WHERE customer_key=?", (customer_key,))
            row = cur.fetchone()
            count_data = get_row_dict(row, cur) if row else {}
            remaining = int((count_data or {}).get("n") or 0)
            # Never delete a customer row for a non-empty manifest: upstream
            # order upload may still be missing when the remote count is zero.
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        # Rebuilding here can enumerate every B2 object for this customer. Large
        # customers would time out this control-plane POST (502), even though the
        # SQL changes were already committed. Invalidate now and rebuild off-request.
        from services import order_customer_share_snapshot as snapshot
        snapshot.queue_snapshot_refresh(customer_key, delay=0.05)
        return jsonify({"ok": True, "result": {
            "customer_key": customer_key,
            "expected_orders": len(expected),
            "stale_orders_removed": len(stale),
            "remaining_orders": remaining,
            "physical_objects_deleted": 0,
            "snapshot_refresh_queued": True,
        }})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 500
