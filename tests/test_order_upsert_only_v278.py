"""V278 non-destructive endpoint structural regression checks (stdlib only)."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UpsertOnlyContracts(unittest.TestCase):
    def test_all_stale_deletions_are_guarded(self):
        tree = ast.parse((ROOT / "services/order_cloud_asset_service.py").read_text("utf-8"))
        writer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_write_order_rows")
        guarded = []
        unguarded = []

        def traverse(node, under_guard=False):
            for child in ast.iter_child_nodes(node):
                is_guard = (
                    isinstance(child, ast.If) and
                    isinstance(child.test, ast.UnaryOp) and
                    isinstance(child.test.op, ast.Not) and
                    isinstance(child.test.operand, ast.Name) and
                    child.test.operand.id == "upsert_only"
                )
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_delete_keys":
                    (guarded if under_guard else unguarded).append(child)
                traverse(child, under_guard or is_guard)
        traverse(writer)
        self.assertEqual(len(guarded), 3)
        self.assertEqual(unguarded, [])

    def test_old_delta_preserved_new_non_destructive_route(self):
        text = (ROOT / "blueprints/b2_test_bp.py").read_text("utf-8")
        self.assertIn('"/api/order-cloud/sync/orders-delta"', text)
        self.assertIn('"/api/order-cloud/sync/orders-upsert-only"', text)
        route = text.split("def order_cloud_sync_orders_upsert_only():", 1)[1].split(
            '@b2_test_bp.route("/api/order-cloud/sync/orders-fast-batch"', 1)[0]
        self.assertIn("upsert_only=True", route)
        self.assertIn("include_new=True", route)


if __name__ == "__main__":
    unittest.main()
