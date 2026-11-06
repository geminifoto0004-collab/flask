"""Regression tests for cloud audit checkpoints and background share snapshots."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OrderAuditProgressRegressionTests(unittest.TestCase):
    def test_all_checkpoint_kinds_pass_the_shared_normalizer(self):
        path = ROOT / "services/order_cloud_sync_ledger.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        kinds = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_KINDS"
                    for target in node.targets)
        )
        checker = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_check"
        )
        scope = {}
        exec(compile(ast.Module(body=[kinds, checker], type_ignores=[]),
                     str(path), "exec"), scope)
        for value in ("media", "audit", "scope", "status"):
            with self.subTest(kind=value):
                self.assertEqual(scope["_check"](value, scope["_KINDS"], "kind"), value.upper())
        self.assertEqual(scope["_check"]("GLOBAL", ("TIDB1", "TIDB2", "GLOBAL"), "target"), "GLOBAL")

    def test_native_background_snapshot_uses_request_context(self):
        path = ROOT / "services/order_share_native_order_ui.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(
            item for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "_native_skeleton"
        )
        source = ast.get_source_segment(path.read_text(encoding="utf-8"), node)
        self.assertIn("app.test_request_context(", source)
        self.assertIn('base_url="https://flask-393d.onrender.com"', source)
        self.assertLess(source.index("app.test_request_context("), source.index("_customer_context("))


if __name__ == "__main__":
    unittest.main()
