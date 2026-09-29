"""Focused failover regression checks without TiDB/B2 credentials."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).with_name('services').joinpath('order_cloud_direct_multi_b2.py')
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))


def load_function(name, namespace):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace[name]


class FailoverReuseTests(unittest.TestCase):
    def test_existing_b2_bytes_only_repair_tidb(self):
        ns = {
            '_validate_sha256': lambda x: x,
            '_validate_content_type': lambda x: x,
            '_resolve_owner': lambda *a, **kw: ('10001', 'customer', None),
            '_existing_asset': lambda *a, **kw: None,
            '_scoped_object_key': lambda *a: 'customers/c/orders/10001/images/web.jpg',
            '_object_key': lambda *a: 'order-cloud/images/old.jpg',
            '_thumb_object_key': lambda *a: 'order-cloud/thumbs/web.jpg',
            '_b2_existing_object': Mock(side_effect=[
                ('b2_primary', 'customers/c/orders/10001/images/web.jpg', 123), None,
            ]),
            '_upsert_registered_asset': Mock(return_value={'asset_key': 'asset1'}),
            '_NEW_IMAGE_MAX_BYTES': 1_000_000,
        }
        fn = load_function('_direct_presign_result', ns)
        result = fn({'order_number': '10001', 'sha256': 'a' * 64,
                     'content_type': 'image/jpeg', 'file_size': 123}, conn=object())
        self.assertTrue(result['exists'])
        self.assertEqual(result['upload_mode'], 'b2_existing_object_tidb_metadata_repair')
        self.assertNotIn('upload_url', result)
        ns['_upsert_registered_asset'].assert_called_once()
        self.assertEqual(ns['_upsert_registered_asset'].call_args.args[4], result['object_key'])

    def test_size_mismatch_never_reuses_wrong_object(self):
        # A failover repair must check B2's actual size against the cached image.
        # The HEAD helper owns the check, so exercise its result via a fake client.
        class FakeClientError(Exception):
            response = {'Error': {'Code': '404'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}

        import sys
        import types
        fake = types.ModuleType('botocore')
        exceptions = types.ModuleType('botocore.exceptions')
        exceptions.ClientError = FakeClientError
        old = sys.modules.get('botocore.exceptions')
        sys.modules['botocore.exceptions'] = exceptions
        try:
            ns = {'PRIMARY': 'b2_primary', 'SECONDARY': 'b2_secondary',
                  'backend_ready': lambda b: b == 'b2_primary',
                  'config_for_backend': lambda *a, **kw: {'bucket_name': 'images'},
                  '_client_for_backend': lambda b: Mock(head_object=lambda **kw: {'ContentLength': 124})}
            fn = load_function('_b2_existing_object', ns)
            with self.assertRaisesRegex(RuntimeError, 'unexpected size'):
                fn(('web.jpg',), expected_size=123)
        finally:
            if old is None:
                sys.modules.pop('botocore.exceptions', None)
            else:
                sys.modules['botocore.exceptions'] = old


if __name__ == '__main__':
    unittest.main()
