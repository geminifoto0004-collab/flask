import ast
from pathlib import Path
import unittest


def load_pure_helpers():
    source = Path("services/order_cloud_index_v281.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_clean_customer_keys",
        "_parse_cursor",
        "_next_cursor",
        "_order_customer_visible",
        "_asset_customer_visible",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "order_cloud_index_v281.py", "exec"), scope)
    return scope


HELPERS = load_pure_helpers()


class OrderCloudIndexV281Tests(unittest.TestCase):
    def test_customer_keys_are_deduplicated_and_bounded(self):
        self.assertEqual(HELPERS["_clean_customer_keys"]([" A  B ", "a b"]), ["A  B"])
        with self.assertRaises(ValueError):
            HELPERS["_clean_customer_keys"]([" "])
        with self.assertRaises(ValueError):
            HELPERS["_clean_customer_keys(["x"] * 201)

    def test_cursor_is_entity_specific(self):
        self.assertEqual(
            HELPERS["_parse_cursor"]({"customer_key": "A", "order_number": "1001"}, "orders"),
            ("A", "1001"),
        )
        self.assertEqual(
            HELPERS["_parse_cursor"]({"customer_key": "A", "asset_key": "a" * 64}, "assets"),
            ("A", "a" * 64),
        )
        with self.assertRaises(ValueError):
            HELPERS["_parse_cursor"]({"customer_key": "A"}, "assets")

    def test_next_cursor_uses_last_returned_row(self):
        row = {"customer_key": "A", "order_number": "1001", "asset_key": "b" * 64}
        self.assertEqual(HELPERS["_next_cursor"](row, "orders"), {"customer_key": "A", "order_number": "1001"})
        self.assertEqual(HELPERS["_next_cursor"](row, "assets"), {"customer_key": "A", "asset_key": "b" * 64})

    def test_order_visibility_matches_public_filter(self):
        token = {"token_hash": "t1"}
        visible = {"active": True, "order_status": "ACTIVE", "order_number": "1001"}
        hidden = {"active": True, "order_status": "CANCELLED", "order_number": "1001"}
        self.assertTrue(HELPERS["_order_customer_visible"](visible, [token], {}))
        self.assertFalse(HELPERS["_order_customer_visible"](hidden, [token], {}))
        self.assertFalse(HELPERS["_order_customer_visible"](
            visible, [token], {"t1": {"1001": {"show_order": False}}}
        ))

    def test_asset_visibility_is_separate_from_b2_existence(self):
        token = {"token_hash": "t1", "show_images": True, "show_workflow_images": True, "show_pdf_pages": True}
        asset = {"active": True, "order_number": "1001", "workflow_key": ""}
        order = {"active": True, "order_status": "ACTIVE", "order_number": "1001"}
        self.assertTrue(HELPERS["_asset_customer_visible"](asset, order, [token], {}))
        self.assertFalse(HELPERS["_asset_customer_visible"](
            asset, order, [token], {"t1": {"1001": {"show_order": False}}}
        ))


if __name__ == "__main__":
    unittest.main()
