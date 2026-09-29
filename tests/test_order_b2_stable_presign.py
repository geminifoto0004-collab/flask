"""Regression: TiDB metadata loss must rediscover the customer's existing B2 key."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'services/order_cloud_direct_multi_b2.py'


class StablePresignTests(unittest.TestCase):
    def _run(self, physical=None, *, file_size=500000, b2_found=True):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_direct_presign_result')
        scope = {
            '_validate_sha256': lambda value: value,
            '_validate_content_type': lambda value: value,
            '_resolve_owner': lambda order, workflow, conn=None: (order, 'customer-a', workflow),
            '_existing_asset': lambda *args, **kwargs: None,
            '_scoped_object_key': lambda *args: 'old-scoped-key',
            '_object_key': lambda *args: 'legacy-key',
            '_b2_existing_object': (lambda *_: self.fail('B2 HEAD is unnecessary for registered customer SHA')) if physical else
                                   (lambda keys, size=0: ('b2_primary', keys[0], size) if b2_found else None),
            '_upsert_registered_asset': lambda *args, **kwargs: {'asset_key': 'repaired-key'},
            '_thumb_object_key': lambda sha: 'thumb/' + sha,
            '_NEW_IMAGE_MAX_BYTES': 1_000_000,
            '_LEGACY_MAX_BYTES': 15 * 1024 * 1024,
            'PRIMARY': 'b2_primary',
            'SECONDARY': 'b2_secondary',
            '_ALLOWED_BACKENDS': {'b2_primary', 'b2_secondary'},
            'backend_ready': lambda _backend: True,
        }
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, str(SOURCE), 'exec'), scope)
        customer_module = types.ModuleType('services.order_cloud_customer_storage')
        customer_module.stable_object_key = lambda *_: 'stable-customer-sha-key'
        customer_module.find_customer_sha_asset = lambda *_: physical
        with patch.dict(sys.modules, {'services': types.ModuleType('services'),
                                      'services.order_cloud_customer_storage': customer_module}):
            result = scope['_direct_presign_result']({
                'order_number': '1007874', 'workflow_key': '1007874-1',
                'sha256': 'a' * 64, 'content_type': 'image/jpeg', 'file_size': file_size,
            }, conn=object(), selected_backend='b2_primary')
        return result

    def test_existing_customer_object_rebuilds_metadata_without_upload(self):
        result = self._run()
        self.assertTrue(result['exists'])
        self.assertEqual(result['object_key'], 'stable-customer-sha-key')
        self.assertEqual(result['asset_key'], 'repaired-key')
        self.assertNotIn('upload_url', result)

    def test_same_customer_registered_sha_relinks_without_b2_head(self):
        result = self._run({'object_key': 'other-order-object', 'file_size': 500000,
                            'content_type': 'image/jpeg', 'storage_backend': 'b2_primary'})
        self.assertEqual(result['object_key'], 'other-order-object')
        self.assertEqual(result['upload_mode'], 'customer_sha_relinked_without_upload')

    def test_legacy_oversized_b2_object_rebuilds_tidb_without_reupload(self):
        result = self._run(file_size=1_500_000)
        self.assertTrue(result['exists'])
        self.assertEqual(result['file_size'], 1_500_000)
        self.assertNotIn('upload_url', result)

    def test_missing_oversized_object_cannot_receive_upload_url(self):
        with self.assertRaisesRegex(ValueError, 'optimized image exceeds'):
            self._run(file_size=1_500_000, b2_found=False)


if __name__ == '__main__':
    unittest.main()
