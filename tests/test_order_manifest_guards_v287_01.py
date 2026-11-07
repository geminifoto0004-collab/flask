"""V287-01 fail-closed manifests: real handler AST, fake SQL, no network or B2."""
import ast
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def extract(path, name, scope):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), scope)
    return scope[name]


class Request:
    def __init__(self, path, data):
        self.path, self.data, self.method = path, data, "POST"

    def get_json(self, silent=False):
        return self.data


class DB:
    def __init__(self, orders=("OLD", "KEEP")):
        self.orders = list(orders)
        self.sql = []
        self.writes = []
        self.queries = 0
        self.commits = 0
        self.rollbacks = 0
        self.cur = self
        self.rows = []

    def execute(self, sql, params=()):
        self.sql.append((sql, tuple(params)))
        low = sql.strip().lower()
        if low.startswith(("delete ", "update ", "insert ")):
            self.writes.append((sql, tuple(params)))
            self.rowcount = 1
            self.rows = []
        elif "count(*)" in low:
            self.rows = [{"n": len(self.orders)}]
        elif "from cloud_orders" in low:
            self.rows = [{"order_number": n} for n in self.orders]
        else:
            self.rows = []
        return self

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class ManifestGuards(unittest.TestCase):
    def make(self, path, payload, orders=("OLD", "KEEP")):
        db = DB(orders)
        req = Request(path, payload)
        created = []
        def connection():
            created.append(True)
            return db

        scope = {
            "request": req, "jsonify": lambda obj: obj,
            "_order_cloud_auth_source": lambda: ("COMPANY", None),
            "_ensure_order_cloud_tables": lambda: None,
            "_ensure_share_columns": lambda: None,
            "get_db_connection": connection,
            "get_cursor": lambda conn: conn,
            "get_row_dict": lambda row, cur: row,
            "_scope": lambda val: str(val or "current"),
            "_SCOPE_RANK": {"current": 0, "6m": 1, "12m": 2, "all": 3},
            "_cache_lock": threading.Lock(), "_space_cache": {},
            "_validate_sha256": lambda value: value if len(value) == 64 else (_ for _ in ()).throw(ValueError("bad sha")),
            "_INTENT_TABLE": "cloud_asset_upload_intent",
        }
        srv = types.ModuleType("services")
        srv.__path__ = []
        snap = types.ModuleType("services.order_customer_share_snapshot")
        snap.queue_snapshot_refresh = lambda *a, **k: None
        srv.order_customer_share_snapshot = snap

        if "/customer/reconcile-orders" in path:
            file = "services/order_cloud_customer_reconcile.py"
            extract(file, "_order_manifest_error", scope)
            extract(file, "_delete_stale_order_numbers", scope)
            fn = extract(file, "_reconcile_customer_orders", scope)
        elif "/assets/prune" in path:
            fn = extract("services/order_cloud_direct_b2.py", "order_cloud_asset_prune", scope)
        else:
            fn = extract("services/order_public_share_fast.py", "_prune_customer_scope", scope)
        with patch.dict(sys.modules, {
            "services": srv, "services.order_customer_share_snapshot": snap,
        }):
            response = fn()
        return response, db, created

    def assert_rejected_unchanged(self, path, payload, code):
        (body, status), db, created = self.make(path, payload)
        self.assertEqual(status, 400)
        self.assertEqual(body.get("code"), code)
        self.assertFalse(db.writes, db.writes)
        self.assertFalse(db.commits)
        self.assertFalse(created, "invalid manifest opened a DB connection")

    def test_customer_scope_empty_has_zero_sql_delete(self):
        self.assert_rejected_unchanged("/api/order-cloud/sync/customer-scope",
            {"customer_key": "A", "order_numbers": []}, "EMPTY_ORDER_SCOPE")

    def test_customer_scope_empty_confirm_true_still_rejected(self):
        self.assert_rejected_unchanged("/api/order-cloud/sync/customer-scope",
            {"customer_key": "A", "order_numbers": [], "confirm_empty": True}, "EMPTY_ORDER_SCOPE")

    def test_customer_scope_explicit_partial_has_zero_mutations(self):
        self.assert_rejected_unchanged("/api/order-cloud/sync/customer-scope",
            {"customer_key": "A", "order_numbers": ["KEEP"],
             "scan_complete": False, "manifest_complete": True}, "INCOMPLETE_ORDER_SCOPE")

    def test_asset_prune_empty_never_calls_b2_or_sql_delete(self):
        self.assert_rejected_unchanged("/api/order-cloud/assets/prune",
            {"order_number": "O1", "allowed_sha256": []}, "EMPTY_ASSET_MANIFEST")

    def test_asset_prune_nonempty_without_scan_proof_denied(self):
        self.assert_rejected_unchanged("/api/order-cloud/assets/prune",
            {"order_number": "O1", "allowed_sha256": ["a" * 64]}, "INCOMPLETE_ASSET_MANIFEST")

    def test_single_reconcile_empty_even_confirm_true(self):
        self.assert_rejected_unchanged("/api/order-cloud/customer/reconcile-orders",
            {"customer_key": "A", "order_numbers": [], "confirm_empty": True}, "EMPTY_ORDER_MANIFEST")

    def test_single_reconcile_blank_only_never_deletes(self):
        self.assert_rejected_unchanged("/api/order-cloud/customer/reconcile-orders",
            {"customer_key": "A", "order_numbers": ["  "],
             "confirm_empty": True}, "INCOMPLETE_ORDER_MANIFEST")

    def test_batch_mixed_empty_skipped_other_customer_reconciles(self):
        body, db, created = self.make("/api/order-cloud/customer/reconcile-orders-batch",
            {"customers": [
                {"customer_key": "EMPTY", "order_numbers": [], "confirm_empty": True},
                {"customer_key": "GOOD", "order_numbers": ["KEEP"],
                 "manifest_complete": True, "expected_order_count": 1},
            ]})
        self.assertTrue(body["ok"])
        items = body["result"]["items"]
        self.assertEqual(items[0]["code"], "EMPTY_ORDER_MANIFEST")
        self.assertFalse(items[0]["ok"])
        self.assertTrue(items[1]["ok"])
        self.assertEqual(body["result"]["reconciled"], 1)
        self.assertTrue(db.writes, "nonempty client must still reconcile")
        self.assertFalse(any("EMPTY" in str(params) for _, params in db.writes))

    def test_nonempty_customer_scope_prune_preserves_normal_behavior(self):
        body, db, _ = self.make("/api/order-cloud/sync/customer-scope",
            {"customer_key": "A", "order_numbers": ["KEEP"],
             "manifest_complete": True, "expected_order_count": 1})
        self.assertTrue(body["ok"])
        self.assertEqual(body["deleted_orders"], 1)
        self.assertEqual(len([sql for sql, _ in db.writes if sql.strip().lower().startswith("delete ")]), 4)

    def test_nonempty_asset_prune_preserves_normal_behavior(self):
        body, db, _ = self.make("/api/order-cloud/assets/prune",
            {"order_number": "O1", "allowed_sha256": ["a" * 64],
             "manifest_complete": True})
        self.assertTrue(body["ok"])
        self.assertEqual(len(db.writes), 1)
        self.assertTrue(db.writes[0][0].startswith("DELETE FROM cloud_assets"))

    def test_nonempty_single_reconcile_keeps_tombstone(self):
        body, db, _ = self.make("/api/order-cloud/customer/reconcile-orders",
            {"customer_key": "A", "order_numbers": ["KEEP"],
             "manifest_complete": True, "expected_order_count": 1})
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["stale_orders_removed"], 1)
        self.assertTrue(any("UPDATE cloud_assets SET active=FALSE" in sql for sql, _ in db.writes))
        self.assertFalse(any("DELETE FROM cloud_assets" in sql for sql, _ in db.writes))

    def test_partial_nonempty_without_certificate_cannot_prune(self):
        response, db, _ = self.make("/api/order-cloud/customer/reconcile-orders",
            {"customer_key": "A", "order_numbers": ["KEEP"]})
        body, status = response
        self.assertEqual((status, body["code"]), (400, "INCOMPLETE_ORDER_MANIFEST"))
        self.assertEqual(db.writes, [])
        self.assertEqual(db.commits, 0)

    def test_mismatched_expected_order_count_blocks_before_sql(self):
        self.assert_rejected_unchanged("/api/order-cloud/customer/reconcile-orders",
            {"customer_key": "A", "order_numbers": ["KEEP"],
             "expected_order_count": 2, "manifest_complete": True}, "INCOMPLETE_ORDER_MANIFEST")

    def test_cloud_only_rebuild_never_calls_purge_or_reconcile(self):
        script = "scripts/order_cloud_rebuild_all.py"
        source = (ROOT / script).read_text(encoding="utf-8")
        self.assertNotIn("confirm_empty", source)
        self.assertNotIn("_purge_one(key, reset_assignment=True)", source)
        fn = extract(script, "_remove_cloud_only_customer", {})
        self.assertTrue(fn("Missing Customer")["skipped_empty"])

    def test_maintenance_scripts_never_auto_confirm_empty(self):
        publish = (ROOT / "scripts/order_cloud_publish_customer.py").read_text(encoding="utf-8")
        sync = (ROOT / "scripts/order_cloud_sync_customer.py").read_text(encoding="utf-8")
        self.assertNotIn("confirm_empty", publish)
        self.assertNotIn("confirm_empty", sync)
        self.assertIn('"manifest_complete": True', publish)
        self.assertIn("if manifest:", sync)


if __name__ == "__main__":
    unittest.main()
