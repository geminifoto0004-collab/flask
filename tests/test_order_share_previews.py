"""Public covers use small cached previews while preserving full/detail reads."""
import ast
from pathlib import Path
import threading
import time
import types
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / 'services/order_share_thumb_render_patch.py'
FUNCTIONS = {'_native_images', '_cached_signed_thumb_get',
             '_cached_signed_preview_get', '_safe_route_markers'}
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
module = ast.fix_missing_locations(ast.Module(
    body=[node for node in tree.body
          if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS],
    type_ignores=[],
))


class SharePreviewTests(unittest.TestCase):
    def setUp(self):
        self.thumb_sign = Mock(return_value=('https://storage.example/small.jpg', 'b2_primary'))
        self.full_sign = Mock(return_value=('https://storage.example/web.jpg', 'b2_primary', False, 0.0))
        self.scope = {
            '_direct': types.SimpleNamespace(_LOCK=threading.RLock(), _URL_CACHE={}),
            'signed_thumb_get': self.thumb_sign,
            '_ORIGINAL_DIRECT_CACHED_GET': self.full_sign,
            'PRIMARY': 'b2_primary', 'time': time,
        }
        exec(compile(module, str(SOURCE), 'exec'), self.scope)
        self.asset = {'asset_key': 'a' * 64, 'customer_key': 'customer',
                      'storage_backend': 'b2_primary', 'object_key': 'web.jpg',
                      'thumb_object_key': 'order-cloud/thumbs/small.jpg'}

    def test_direct_cover_uses_thumbnail_and_reuses_signature(self):
        first = self.scope['_cached_signed_preview_get'](self.asset)
        second = self.scope['_cached_signed_preview_get'](self.asset)
        self.assertEqual(first[0], 'https://storage.example/small.jpg')
        self.assertEqual(second[0], first[0])
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.thumb_sign.assert_called_once_with(self.asset, seconds=600)
        self.full_sign.assert_not_called()

    def test_old_image_without_thumbnail_stays_visible(self):
        self.asset.pop('thumb_object_key')
        result = self.scope['_cached_signed_preview_get'](self.asset)
        self.assertEqual(result[0], 'https://storage.example/web.jpg')
        self.full_sign.assert_called_once_with(self.asset)
        self.thumb_sign.assert_not_called()

    def test_card_preview_does_not_change_opened_image_or_pdf(self):
        full = '/share/token/image/' + 'a' * 64
        self.scope['_ORIGINAL_NATIVE_IMAGES'] = Mock(return_value=[
            {'media_type': 'image', 'url': full, 'preview_url': full},
            {'media_type': 'pdf_page', 'url': '/pdf', 'preview_url': '/pdf-preview'},
        ])
        images = self.scope['_native_images']({}, {}, 'token')
        self.assertEqual(images[0]['preview_url'], full.replace('/image/', '/thumb/'))
        self.assertEqual(images[0]['url'], full)
        self.assertEqual(images[1]['preview_url'], '/pdf-preview')

    def test_cover_optimizer_leaves_full_image_attribute_untouched(self):
        self.assertEqual(list(self.scope['_safe_route_markers']('token', 'a' * 64, 'data-full')), [])


if __name__ == '__main__':
    unittest.main()
