"""Offline checks for V281 metadata-only visibility, no TiDB/B2 credentials."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "services/order_cloud_asset_service.py").read_text(encoding="utf-8")
BLUEPRINT = (ROOT / "blueprints/b2_test_bp.py").read_text(encoding="utf-8")
THUMBS = (ROOT / "services/order_share_thumb_metadata_patch.py").read_text(encoding="utf-8")
SNAPSHOT = (ROOT / "services/order_customer_share_snapshot.py").read_text(encoding="utf-8")


class FakeCursor:
    def __init__(self, share_exists=True, found_keys=None):
        self.share_exists = share_exists
        self.found_keys = found_keys
        self.statements = []
        self.current = None
        self.params = ()
    def execute(self, sql, params=()):
        self.current = str(sql)
        self.params = tuple(params)
        self.statements.append((self.current, self.params))
    def fetchone(self):
        if "FROM cloud_share_tokens" in (self.current or ""):
            return {"token_hash": "valid"} if self.share_exists else None
        return None
    def fetchall(self):
        if "SELECT asset_key FROM cloud_assets" not in (self.current or ""):
            return []
        requested = self.params[1:]
        return [{"asset_key": k} for k in requested
                if self.found_keys is None or k in self.found_keys]


class FakeConnection:
    def __init__(self, target="TIDB1", share_exists=True, found_keys=None):
        self.active_target = target
        self.cursor = FakeCursor(share_exists, found_keys)
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        self.closed += 1


def visible_function(conn):
    tree = ast.parse(SERVICE)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "set_asset_visibility_batch")
    scope = {
        "re": re,
        "get_db_connection": lambda: conn,
        "get_cursor": lambda c: c.cursor,
        "get_row_dict": lambda row, cur: dict(row),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "asset_service.py", "exec"), scope)
    return scope[node.name]


class V281VisibilityTests(unittest.TestCase):
    KEY_A = "a" * 64
    KEY_B = "b" * 64

    def test_flag_only_update_no_b2_and_no_delete(self):
        conn = FakeConnection()
        run = visible_function(conn)
        out = run("CLIENT A", [
            {"asset_key": self.KEY_A, "customer_visible": False},
            {"asset_key": self.KEY_B, "customer_visible": True},
        ], "TIDB1")
        self.assertEqual(out["updated"], 2)
        self.assertFalse(out["b2_touched"])
        self.assertEqual(out["deleted"], 0)
        self.assertEqual(conn.commits, 1)
        updates = [(q, args) for q, args in conn.cursor.statements
                   if q.startswith("UPDATE cloud_assets")]
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0][1], (False, "CLIENT A", self.KEY_A))
        self.assertEqual(updates[1][1], (True, "CLIENT A", self.KEY_B))
        self.assertTrue(all("object_key" not in q and "DELETE" not in q for q, _ in conn.cursor.statements))

    def test_no_active_web_share_does_not_write(self):
        conn = FakeConnection(share_exists=False)
        with self.assertRaisesRegex(ValueError, "no active WEB share"):
            visible_function(conn)("CLIENT A", [{"asset_key": self.KEY_A, "customer_visible": False}], "TIDB1")
        self.assertEqual(conn.commits, 0)
        self.assertFalse(any(q.startswith("UPDATE") for q, _ in conn.cursor.statements))

    def test_wrong_target_fails_before_db_queries(self):
        conn = FakeConnection(target="TIDB2")
        with self.assertRaisesRegex(ValueError, "target changed"):
            visible_function(conn)("CLIENT A", [{"asset_key": self.KEY_A, "customer_visible": False}], "TIDB1")
        self.assertEqual(conn.cursor.statements, [])
        self.assertEqual(conn.commits, 0)

    def test_foreign_customer_assets_cannot_be_changed(self):
        conn = FakeConnection(found_keys=set())
        with self.assertRaisesRegex(ValueError, "foreign customer assets"):
            visible_function(conn)("CLIENT A", [{"asset_key": self.KEY_A, "customer_visible": False}], "TIDB1")
        self.assertFalse(any(q.startswith("UPDATE") for q, _ in conn.cursor.statements))
        self.assertEqual(conn.commits, 0)

    def test_duplicate_and_invalid_keys_rejected(self):
        conn = FakeConnection()
        run = visible_function(conn)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            run("CLIENT A", [
                {"asset_key": self.KEY_A, "customer_visible": False},
                {"asset_key": self.KEY_A, "customer_visible": True}
            ], "TIDB1")
        with self.assertRaisesRegex(ValueError, "invalid asset_key"):
            run("CLIENT A", [{"asset_key": "BAD", "customer_visible": True}], "TIDB1")
        self.assertEqual(conn.cursor.statements, [])

    def test_protected_endpoint_and_cache_refresh(self):
        route = BLUEPRINT.split('def order_cloud_asset_visibility_batch():', 1)[1].split(
            '@b2_test_bp.route(', 1)[0]
        self.assertIn('authorized("replicas:verify-repair")', route)
        self.assertIn('X-Order-Checkpoint-Key', route)
        self.assertIn('hmac.compare_digest', route)
        self.assertIn('queue_snapshot_refresh(', route)
        self.assertIn('invalidate_customer_html_cache(', route)
        self.assertIn('invalidate_asset_cache(', route)

    def test_public_paths_respect_per_asset_visibility(self):
        self.assertIn('FROM cloud_assets WHERE asset_key=? AND active=TRUE AND customer_visible=TRUE', SERVICE)
        self.assertIn('FROM cloud_assets WHERE asset_key=? AND active=TRUE AND customer_visible=TRUE', THUMBS)
        self.assertIn('a.active=TRUE AND a.customer_visible=TRUE', THUMBS)
        self.assertIn('a.active=TRUE AND a.customer_visible=TRUE', SNAPSHOT)
        self.assertIn('a.asset_key=? AND a.active=TRUE AND a.customer_visible=TRUE', THUMBS)

    def test_reregister_does_not_unhide_existing_image(self):
        self.assertIn('effective_visible = (bool(existing.get("customer_visible", True))', SERVICE)
        self.assertIn('customer_visible=None):', SERVICE)
        self.assertIn('effective_visible, asset_key', SERVICE)


if __name__ == "__main__":
    unittest.main()
