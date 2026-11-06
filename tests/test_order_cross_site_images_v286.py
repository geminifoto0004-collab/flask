"""V286 regression: a HOME-only source manifest must not hide COMPANY photos."""
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "services/order_share_image_policy.py"
spec = importlib.util.spec_from_file_location("order_share_image_policy_under_test", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class CrossPCImageManifestTests(unittest.TestCase):
    def setUp(self):
        self.company_photo = {
            "asset_key": "a" * 64, "order_number": "G26158",
            "workflow_key": "G26158-1", "sha256": "b" * 64,
            "asset_type": "IMAGE", "content_type": "image/jpeg",
            "source_site": "ORDER", "customer_visible": True,
        }
        # Both PCs are identified as ORDER by the current Render gate.
        self.home_order = {
            "order_number": "G26158", "source_site": "ORDER",
            "image_sources_authoritative": True, "image_sources": [],
            "assets": [dict(self.company_photo)],
        }

    def test_home_empty_manifest_cannot_hide_registered_company_photo(self):
        self.assertIsNone(policy.source_match(self.company_photo, self.home_order))
        policy.filter_assets_in_space({"orders": [self.home_order]}, {"show_images": True, "show_workflow_images": True})
        self.assertEqual(len(self.home_order["assets"]), 1)

    def test_company_upload_time_still_used_when_manifest_matches(self):
        self.home_order["image_sources"] = [{
            "workflow_key": "G26158-1", "sha256": "b" * 64,
            "uploaded_at_epoch": 123456789,
        }]
        item = policy.source_match(self.company_photo, self.home_order)
        self.assertEqual(item["uploaded_at_epoch"], 123456789)

    def test_cloud_customer_visible_false_remains_hidden(self):
        photo = dict(self.company_photo, customer_visible=False)
        order = dict(self.home_order, assets=[photo])
        policy.filter_assets_in_space({"orders": [order]}, {"show_workflow_images": True})
        self.assertEqual(order["assets"], [])

    def test_share_disables_workflow_images(self):
        order = dict(self.home_order, assets=[dict(self.company_photo)])
        policy.filter_assets_in_space({"orders": [order]}, {"show_workflow_images": False})
        self.assertEqual(order["assets"], [])

    def test_share_disables_order_photos(self):
        photo = dict(self.company_photo, workflow_key="")
        order = dict(self.home_order, assets=[photo])
        policy.filter_assets_in_space({"orders": [order]}, {"show_images": False})
        self.assertEqual(order["assets"], [])

    def test_hidden_order_visibility_still_hides_image(self):
        order = dict(self.home_order, assets=[dict(self.company_photo)])
        policy.filter_assets_in_space({"orders": [order]}, {
            "show_workflow_images": True,
            "order_visibility": {"G26158": {"show_order": False}},
        })
        self.assertEqual(order["assets"], [])

    def test_no_authority_manifest_remains_advisory(self):
        order = dict(self.home_order, image_sources_authoritative=False)
        self.assertIsNone(policy.source_match(self.company_photo, order))

    def test_asset_in_no_manifest_does_not_invent_blob(self):
        order = dict(self.home_order, assets=[])
        policy.filter_assets_in_space({"orders": [order]}, {"show_workflow_images": True})
        self.assertEqual(order["assets"], [])


if __name__ == "__main__":
    unittest.main()
