"""Offline regressions for public share HTML and both media authorization paths.

Load real service modules without the production package's DB startup hooks;
only external database/storage dependencies are replaced.
"""
import copy
import hashlib
import importlib.util
import itertools
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask, Response, render_template
from PIL import Image, ImageOps  # Preload once before each isolated module registry.

ROOT = Path(__file__).resolve().parent


class ShareImageVisibilityTests(unittest.TestCase):
    def load(self, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        parent, _, leaf = name.rpartition('.')
        if parent in sys.modules:
            setattr(sys.modules[parent], leaf, module)
        return module

    def stub(self, name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module
        return module

    def service(self, name):
        return self.load('services.' + name, ROOT / 'services' / (name + '.py'))

    def setUp(self):
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        self.stub('services', __path__=[str(ROOT / 'services')])
        self.stub('order_tracking', __path__=[str(ROOT / 'order_tracking')])
        self.load('order_tracking.share_common', ROOT / 'order_tracking/share_common.py')
        self.stub('blueprints', __path__=[])
        decorators = types.SimpleNamespace(**{
            name: lambda fn: fn for name in ('before_app_request', 'after_app_request', 'record_once')
        })
        self.stub('blueprints.b2_test_bp', b2_test_bp=decorators,
                  _ensure_order_cloud_tables=Mock(), _order_cloud_auth_source=lambda: ('test', None))
        self.conn = Mock()
        self.cur = Mock()
        self.stub('database', get_cursor=lambda conn: self.cur,
                  get_db_connection=lambda: self.conn, get_row_dict=lambda row, cur: row,
                  check_column_exists=lambda *args: True)
        self.stub('services.order_cloud_service')
        self.stub('services.order_cloud_multi_b2', PRIMARY='primary', SECONDARY='secondary',
                  config_for_backend=Mock())
        self.stub('services.order_share_direct_cover_cache')
        self.stub('services.order_customer_share_snapshot')
        self.hot = self.stub('services.order_customer_share_hot_cache',
                             _cache_space=Mock(), _HASH_TOKEN_CACHE={})
        # Block an optional older patch even if a deployment copy contains it.
        self.stub('services.order_share_visibility_live_patch')
        self.stub('boto3', client=Mock())
        self.stub('botocore', __path__=[])
        self.stub('botocore.config', Config=Mock())
        self.policy = self.service('order_share_image_policy')
        self.fast = self.service('order_public_share_fast')
        self.share = {'customer_key': 'customer', 'status': 'active', 'history_scope': 'all',
                      'show_images': False, 'show_workflow_images': True}
        self.supervisor = {'asset_key': 'a' * 64, 'workflow_key': '', 'order_number': '100',
                           'customer_key': 'customer', 'asset_type': 'IMAGE',
                           'content_type': 'image/jpeg', 'object_key': 'supervisor.jpg'}
        self.sales = dict(self.supervisor, asset_key='b' * 64, workflow_key='100-1', object_key='sales.jpg')
        self.space = {'customer': {'customer_name': 'TEST'}, 'orders': [{
            'order_number': '100', 'order_status': 'ACTIVE',
            'assets': [self.supervisor, self.sales],
            'workflows': [{'workflow_key': '100-1', 'workflow_number': '100-1', 'status': 'COMPLETED'}],
        }]}
        self.page = self.stub('services.order_public_share_multi_b2_page',
                              _load_page_data=lambda token: (dict(self.share), {'space': self.space}, None),
                              _validate_share=lambda share: (dict(share), None),
                              _cache_get=self.fast._cache_get, _cache_put=self.fast._cache_put,
                              _cache_lock=threading.RLock(), _token_cache={}, _space_cache={},
                              render_template=render_template)
        self.render = self.service('order_share_render_cache')
        self.native = self.service('order_share_native_order_ui')
        self.sources = self.service('order_share_image_source_patch')
        self.media = self.service('order_cloud_multi_b2_public')
        self.sources._settings = Mock(side_effect=lambda token: dict(self.share))
        self.sources._ensure_columns = Mock()
        self.sources._BASE_RESOLVE = lambda token: (dict(self.share), 'active')
        self.app = Flask(__name__, template_folder=str(ROOT / 'order_tracking/templates'))
        self.app.before_request(self.native._native_detail)
        self.app.before_request(self.media._multi_b2_public_media_interceptor)
        self.media._signed_get = Mock(return_value=('https://storage.example/image', 'primary'))
        self.render._TEMPLATE_HASH = 'test-template'
        self.warm()

    def warm(self):
        self.page._cache_put(self.page._token_cache, 'token', dict(self.share), 86400)
        self.page._cache_put(self.page._space_cache, 'customer', {'space': self.space}, 86400)
        for asset in (self.supervisor, self.sales):
            self.fast._cache_put(self.fast._asset_cache, asset['asset_key'], dict(asset), 120)

    def test_all_source_combinations_in_html_detail_and_media(self):
        original = copy.deepcopy(self.space)
        for supervisor, sales in itertools.product((False, True), repeat=2):
            with self.subTest(supervisor=supervisor, sales=sales):
                self.share.update(show_images=supervisor, show_workflow_images=sales)
                # Deliberately leave the token cache with the old flags.
                context = self.native._customer_context(self.space, self.share, 'token')
                self.assertEqual(len(context['orders'][0]['images']), int(supervisor) + int(sales))
                html = self.native._native_skeleton(self.app, self.share, {'space': self.space})
                detail = self.app.test_client().get('/share/token/order/100-1')
                self.assertEqual(detail.status_code, 200)
                for asset, allowed in ((self.supervisor, supervisor), (self.sales, sales)):
                    key = asset['asset_key']
                    self.assertEqual(key in html, allowed)
                    self.assertEqual(key in detail.get_data(as_text=True), allowed)
                    for route in ('image', 'thumb', 'asset'):
                        response = self.app.test_client().get(f'/share/token/{route}/{key}')
                        self.assertEqual(response.status_code, 302 if allowed else 404)
                    _, result, error = self.fast._asset_for_share('token', key)
                    self.assertEqual(error is None, allowed)
                    self.assertEqual(result is not None, allowed)
        self.assertEqual(self.space, original, 'share-specific filtering must not mutate a shared snapshot')

    def test_tidb_fallback_checks_each_source_and_keeps_ownership_join(self):
        self.page._token_cache.clear()
        for supervisor, sales in itertools.product((False, True), repeat=2):
            for asset, allowed in ((self.supervisor, supervisor), (self.sales, sales)):
                with self.subTest(supervisor=supervisor, sales=sales, workflow=asset['workflow_key']):
                    self.cur.fetchone.return_value = dict(asset, share_status='active',
                        share_show_images=int(supervisor), share_show_workflow_images=int(sales))
                    result, error, mode = self.media._authorized_asset('token', asset['asset_key'])
                    self.assertEqual(mode, 'tidb-one-query')
                    self.assertEqual(error is None, allowed)
                    self.assertEqual(result is not None, allowed)
                    sql = self.cur.execute.call_args.args[0]
                    self.assertIn('o.customer_key=s.customer_key', sql)
                    self.assertIn('s.show_workflow_images', sql)

    def test_missing_or_revoked_assets_stay_blocked(self):
        for row, code in ((None, 404), (dict(self.sales, share_status='revoked'), 410)):
            self.cur.fetchone.return_value = row
            asset, error = self.media._authorized_asset_from_tidb('token', self.sales['asset_key'])
            self.assertIsNone(asset)
            self.assertEqual(error.status_code, code)

    def test_filtered_renderer_bypasses_old_supervisor_cover_html(self):
        self.render._ORIGINAL_RENDER_TEMPLATE = Mock(return_value='filtered')
        self.sources._BASE_RENDER = Mock(return_value='stale supervisor cover')
        result = self.sources._render_template('customer_share_live_fast.html',
            space=self.space, share=self.share, share_token='token')
        self.assertEqual(result, 'filtered')
        self.sources._BASE_RENDER.assert_not_called()
        passed = self.render._ORIGINAL_RENDER_TEMPLATE.call_args.kwargs['space']
        self.assertEqual(passed['orders'][0]['assets'], [self.sales])
        self.assertEqual(len(self.space['orders'][0]['assets']), 2)

    def test_html_cache_distinguishes_all_four_source_combinations(self):
        keys = {self.render._variant_key(dict(self.share, show_images=a, show_workflow_images=b))
                for a, b in itertools.product((False, True), repeat=2)}
        self.assertEqual(len(keys), 4)

    def test_old_links_default_sales_images_to_visible_and_parse_false_values(self):
        for value in (False, 0, '0', 'false', 'off'):
            self.assertFalse(self.policy.asset_allowed(self.supervisor, {'show_images': value}))
            self.assertTrue(self.policy.asset_allowed(self.sales, {'show_images': value}))
            self.assertFalse(self.policy.asset_allowed(self.sales, {'show_workflow_images': value}))

    def test_pdf_page_toggle_cannot_override_source_toggle(self):
        pdf = dict(self.supervisor, asset_kind='PDF_PAGE')
        self.assertFalse(self.policy.asset_allowed(pdf, self.share))
        self.assertFalse(self.policy.asset_allowed(dict(pdf, workflow_key='100-1'),
                                                   dict(self.share, show_pdf_pages=False)))

    def test_settings_failure_does_not_render_unfiltered_snapshot(self):
        self.sources._settings.side_effect = RuntimeError('database unavailable')
        _, bundle, error = self.sources._load_page('token')
        self.assertIsNone(bundle)
        self.assertEqual(error.status_code, 503)
        _, _, available = self.media._authorized_asset_from_memory('token', self.sales['asset_key'])
        self.assertFalse(available)

    def test_save_settings_invalidates_token_and_html_caches(self):
        token_hash = hashlib.sha256(b'token').hexdigest()
        self.hot._HASH_TOKEN_CACHE[token_hash] = (float('inf'), dict(self.share))
        self.render._TOKEN_HTML[token_hash] = {'html': 'old'}
        self.sources._CACHE[token_hash] = (float('inf'), dict(self.share))
        self.cur.fetchone.return_value = {'customer_key': 'customer'}
        with self.app.test_request_context('/api/order-cloud/share/update', method='POST',
                json={'token': 'token', 'show_images': False, 'show_workflow_images': True}):
            response = self.sources._update_share_settings()
        self.assertTrue(response.get_json()['ok'])
        self.assertFalse(response.get_json()['result']['show_images'])
        self.assertTrue(response.get_json()['result']['show_workflow_images'])
        self.assertTrue(self.conn.commit.called)
        self.assertIn('UPDATE cloud_share_tokens', self.cur.execute.call_args.args[0])
        self.assertNotIn('token', self.page._token_cache)
        self.assertNotIn(token_hash, self.hot._HASH_TOKEN_CACHE)
        self.assertNotIn(token_hash, self.render._TOKEN_HTML)
        self.assertNotIn(token_hash, self.sources._CACHE)


if __name__ == '__main__':
    unittest.main()
