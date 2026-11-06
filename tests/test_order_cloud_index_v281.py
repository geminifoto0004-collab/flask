import unittest

from services.order_cloud_index_v281 import (
    _asset_customer_visible,
    _clean_customer_keys,
    _next_cursor,
    _order_customer_visible,
    _parse_cursor,
)


class OrderCloudIndexV281Tests(unittest.TestCase):
    def test_customer_keys_are_deduplicated_and_bounded(self):
        self.assertEqual(_clean_customer_keys([" A  B ", "a b"]), ["A  B "])
        with self.assertRaises(ValueError):
            _clean_customer_keys([" "])

    def test_cursor_is_entity_specific(self):
        self.assertEqual(
            _parse_cursor({"customer_key": "A", "order_number": "1001"}, "orders"),
            ("A", "1001"),
        )
        self.assertEqual(
            _parse_cursor({"customer_key": "A", "asset_key": "a" * 64}, "assets"),
            ("A", "a" * 64),
        )
        with self.assertRaises(ValueError):
            _parse_cursor({"customer_key": "A"}, "assets")

    def test_next_cursor_uses_last_returned_row(self):
        row = {"customer_key": "A", "order_number": "1001", "asset_key": "b" * 64}
        self.assertEqual(_next_cursor(row, "orders"), {"customer_key": "A", "order_number": "1001"})
        self.assertEqual(_next_cursor(row, "assets"), {"customer_key": "A", "asset_key": "b" * 64})

    def test_order_visibility_matches_public_filter(self):
        token = {"token_hash": "t1"}
        visible = {"active": True, "order_status": "ACTIVE", "order_number": "1001"}
        hidden = {"active": True, "order_status": "CANCELLED", "order_number": "1001"}
        self.assertTrue(_order_customer_visible(visible, [token], {}))
        self.assertFalse(_order_customer_visible(hidden, [token], {}))
        self.assertFalse(_order_customer_visible(visible, [token], {"t1": {"1001": {"show_order": False}}}))

    def test_asset_visibility_is_not_b2_existence_check(self):
        token = {"token_hash": "t1", "show_images": True, "show_workflow_images": True, "show_pdf_pages": True}
        asset = {"active": True, "order_number": "1001", "workflow_key": ""}
        order = {"active": True, "order_status": "ACTIVE", "order_number": "1001"}
        self.assertTrue(_asset_customer_visible(asset, order, [token], {}))
        self.assertFalse(_asset_customer_visible(asset, order, [token], {"t1": {"1001": {"show_order": False}}}))


if __name__ == "__main__":
    unittest.main()
