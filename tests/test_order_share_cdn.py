"""Exercise the real public-media functions without starting the snapshot workers."""
import ast
import copy
import os
from pathlib import Path
import re
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

from flask import Flask, Response, has_request_context, redirect, request


ROOT = Path(__file__).resolve().parents[1]
CDN = 'https://images.example.test'
FULL_KEY = 'c_' + '1' * 24 + '/1008474/large.jpg'
THUMB_KEY = 'order-cloud/thumbs/aa/small.jpg'


def load_functions(relative_path, names, scope):
    source = ROOT / relative_path
    tree = ast.parse(source.read_text(encoding='utf-8'))
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            body.append(node)
    assert len(body) == len(names), 'Missing source function'
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, str(source), 'exec'), scope)
    return scope


class ShareCDNTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ORDER_CDN_BASE_URL': CDN + '/'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = Flask(__name__)
        self.helper = load_functions('services/order_cloud_asset_service.py',
            {'_asset_backend', '_cdn_asset_url'},
            {'os': os, 're': re, 'quote': quote,
             'BACKENDS': ('b2_primary', 'b2_secondary')})['_cdn_asset_url']
        self.client = Mock()
        self.client.generate_presigned_url.return_value = (
            'https://storage.example.test/image.jpg?X-Amz-Algorithm=AWS4-HMAC-SHA256')
        self.client_get = Mock(return_value=(self.client, {'bucket_name': 'private'}))
        self.media_scope = load_functions('services/order_cloud_multi_b2_public.py',
            {'_signed_get', '_timing_headers', '_multi_b2_public_media_interceptor'},
            {'PRIMARY': 'b2_primary', '_ALLOWED_BACKENDS': {'b2_primary', 'b2_secondary'},
             '_cdn_asset_url': self.helper, '_cached_client': self.client_get,
             'time': time, 'request': request, 'redirect': redirect, 'Response': Response})
        self.full = self.media_scope['_signed_get']
        self.media = types.SimpleNamespace(_ALLOWED_BACKENDS={'b2_primary', 'b2_secondary'},
            _cdn_asset_url=self.helper, _cached_client=self.client_get)
        self.thumb_scope = load_functions('services/order_share_thumb_metadata_patch.py',
            {'signed_thumb_get', '_is_thumb_request', '_signed_get_router'},
            {'PRIMARY': 'b2_primary', '_media': self.media, '_ORIGINAL_SIGNED_GET': self.full,
             'has_request_context': has_request_context, 'request': request})
        self.thumb = self.thumb_scope['signed_thumb_get']
        self.asset = {'asset_key': 'a' * 64, 'customer_key': 'customer',
            'asset_type': 'IMAGE', 'object_key': FULL_KEY,
            'thumb_object_key': THUMB_KEY, 'storage_backend': 'b2_primary'}

    def test_legacy_large_and_real_thumbnail_use_distinct_cdn_objects(self):
        self.assertEqual(self.full(self.asset), (CDN + '/' + FULL_KEY, 'b2_primary'))
        self.assertEqual(self.thumb(self.asset), (CDN + '/' + THUMB_KEY, 'b2_primary'))
        self.client_get.assert_not_called()

    def test_new_large_images_also_use_cdn(self):
        self.asset['object_key'] = 'order-cloud/images/aa/large.webp'
        self.assertEqual(self.full(self.asset)[0], CDN + '/' + self.asset['object_key'])
        self.client_get.assert_not_called()

    def test_full_image_is_not_replaced_by_thumbnail_in_request_context(self):
        with self.app.test_request_context('/share/token/image/' + 'a' * 64):
            self.assertEqual(self.thumb_scope['_signed_get_router'](self.asset)[0],
                             CDN + '/' + FULL_KEY)
        with self.app.test_request_context('/share/token/thumb/' + 'a' * 64):
            self.assertEqual(self.thumb_scope['_signed_get_router'](self.asset)[0],
                             CDN + '/' + THUMB_KEY)
        self.client_get.assert_not_called()

    def test_existing_cover_cache_stores_cdn_thumbnail(self):
        scope = load_functions('services/order_share_thumb_render_patch.py',
            {'_cached_signed_thumb_get', '_cached_signed_preview_get'},
            {'PRIMARY': 'b2_primary', 'time': time, 'signed_thumb_get': self.thumb,
             '_direct': types.SimpleNamespace(_LOCK=threading.RLock(), _URL_CACHE={}),
             '_ORIGINAL_DIRECT_CACHED_GET': Mock(side_effect=AssertionError('Full image requested'))})
        first = scope['_cached_signed_preview_get'](self.asset)
        second = scope['_cached_signed_preview_get'](self.asset)
        self.assertEqual(first[0], CDN + '/' + THUMB_KEY)
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.client_get.assert_not_called()

    def test_legacy_thumbnail_fallback_still_uses_cdn_web_image(self):
        self.asset.pop('thumb_object_key')
        scope = load_functions('services/order_share_thumb_legacy_fallback.py',
            {'_is_thumb_request', '_has_thumb', '_signed_get_compat'},
            {'has_request_context': has_request_context, 'request': request,
             '_thumb': types.SimpleNamespace(_ORIGINAL_SIGNED_GET=self.full),
             '_PREVIOUS_ROUTER': self.thumb_scope['_signed_get_router']})
        with self.app.test_request_context('/share/token/thumb/' + 'a' * 64):
            self.assertEqual(scope['_signed_get_compat'](self.asset)[0], CDN + '/' + FULL_KEY)
        self.client_get.assert_not_called()

    def test_secondary_backend_remains_on_its_correct_bucket(self):
        self.asset['storage_backend'] = 'b2_secondary'
        self.full(self.asset)
        self.thumb(self.asset)
        self.assertEqual(self.client_get.call_count, 2)
        for call in self.client_get.call_args_list:
            self.assertEqual(call.args[0], 'b2_secondary')
        self.assertEqual(self.client.generate_presigned_url.call_args_list[0].kwargs['Params']['Key'], FULL_KEY)
        self.assertEqual(self.client.generate_presigned_url.call_args_list[1].kwargs['Params']['Key'], THUMB_KEY)

    def test_unconfigured_cdn_keeps_both_signed_b2_fallbacks(self):
        with patch.dict(os.environ, {'ORDER_CDN_BASE_URL': ''}):
            self.assertIn('X-Amz-Algorithm', self.full(self.asset)[0])
            self.assertIn('X-Amz-Algorithm', self.thumb(self.asset)[0])
        self.assertEqual(self.client_get.call_count, 2)

    def test_unknown_backend_is_normalized_before_cdn_selection(self):
        self.asset['storage_backend'] = 'invalid'
        self.assertEqual(self.full(self.asset)[1], 'b2_primary')
        self.assertEqual(self.thumb(self.asset)[1], 'b2_primary')
        self.client_get.assert_not_called()

    def test_cdn_url_encodes_object_names_without_changing_folder_structure(self):
        self.asset['object_key'] = 'order-cloud/images/花型 1/#red?.jpg'
        self.assertEqual(self.full(self.asset)[0],
            CDN + '/order-cloud/images/%E8%8A%B1%E5%9E%8B%201/%23red%3F.jpg')

    def test_unrelated_object_keys_are_not_mapped_to_image_cdn(self):
        self.assertIsNone(self.helper({'object_key': 'private-backups/database.sqlite'}))

    def test_bad_thumbnail_metadata_is_rejected_before_cdn_or_storage_access(self):
        self.asset['thumb_object_key'] = 'private-backups/database.sqlite'
        with self.assertRaises(ValueError):
            self.thumb(self.asset)
        self.client_get.assert_not_called()

    def test_media_authorization_still_happens_before_generating_cdn_url(self):
        error = Response('Forbidden', 403)
        signer = Mock(side_effect=self.full)
        self.media_scope['_signed_get'] = signer
        self.media_scope['_authorized_asset'] = Mock(return_value=(None, error, 'memory-prewarmed'))
        with self.app.test_request_context('/share/token/image/' + 'a' * 64):
            result = self.media_scope['_multi_b2_public_media_interceptor']()
        self.assertIs(result, error)
        self.assertEqual(result.status_code, 403)
        signer.assert_not_called()

    def test_authorized_image_redirects_to_cdn_with_correct_delivery_header(self):
        self.media_scope['_authorized_asset'] = Mock(return_value=(self.asset, None, 'memory-prewarmed'))
        with self.app.test_request_context('/share/token/image/' + 'a' * 64):
            result = self.media_scope['_multi_b2_public_media_interceptor']()
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.headers['Location'], CDN + '/' + FULL_KEY)
        self.assertEqual(result.headers['X-Order-Media-Mode'], 'cloudflare-cdn-redirect-memory-first')
        self.client_get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
