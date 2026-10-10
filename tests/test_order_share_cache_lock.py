"""Keep background TiDB work away from the public HTML read lock."""
import ast
import hashlib
import io
from pathlib import Path
import threading
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest

from flask import Flask, Response, g, request


ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, scope):
    source = ast.parse((ROOT / path).read_text())
    nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), path, 'exec'), scope)
    return scope


def cache_scope():
    from test_order_share_links import links
    share_token_hash = links.share_token_hash
    scope = dict(hashlib=hashlib, share_token_hash=share_token_hash, time=time, _LOCK=threading.RLock(),
                 _HTML={}, _HTML_CUSTOMERS={}, _HTML_CHECKED_AT={}, _TOKEN_HTML={},
                 _TEMPLATE_HASH='test-template', _TABLE='existing_html_cache',
                 _ensure_table=lambda: None, _ORIGINAL_CACHE_SPACE=lambda *args: None,
                 _build_variant=lambda *args, **kwargs: True,
                 get_row_dict=lambda row, cursor: row)
    return load_functions('services/order_share_render_cache.py', {
        '_token_hash', '_share_variant', '_variant_key', '_memory_put',
        '_drop_customer', '_cache_space_and_prerender', '_load_all_persisted',
        '_load_one_persisted',
    }, scope)


def fake_database(scope, rows):
    cursor = SimpleNamespace(execute=lambda *args: None, fetchall=lambda: rows,
                             fetchone=lambda: rows[0] if rows else None)
    connection = SimpleNamespace(close=lambda: None)
    scope.update(get_db_connection=lambda: connection, get_cursor=lambda conn: cursor)


class HtmlCacheLockTests(unittest.TestCase):
    def test_background_database_wait_does_not_block_another_public_wall(self):
        scope = cache_scope()
        target = {'customer_key': 'updated-customer'}
        visitor = {'customer_key': 'other-customer'}
        scope['_memory_put'](target, 'updated HTML')
        scope['_memory_put'](visitor, 'other HTML')
        waiting = threading.Event()
        release = threading.Event()
        reader_done = threading.Event()
        results = []

        def database_scan():
            waiting.set()
            release.wait(2)
            return []

        scope['_active_shares'] = database_scan
        wall = load_functions('services/order_share_first_paint_patch.py', {'_html_is_hot'}, {
            '_render': SimpleNamespace(**scope),
        })

        def visitor_request():
            results.append(wall['_html_is_hot']('test-token', visitor))
            reader_done.set()

        writer = threading.Thread(target=scope['_cache_space_and_prerender'], args=('updated-customer', {}))
        reader = threading.Thread(target=visitor_request)
        writer.start()
        try:
            self.assertTrue(waiting.wait(1), 'Writer did not reach the simulated TiDB wait')
            reader.start()
            self.assertTrue(reader_done.wait(.25), 'Public HTML read waited for background TiDB')
            self.assertEqual(results, [True])
        finally:
            release.set()
            writer.join(2)
            if reader.ident is not None:
                reader.join(2)

    def test_invalidation_removes_all_target_variants_without_database_scan(self):
        scope = cache_scope()
        variants = [{'customer_key': 'target', 'history_scope': 'current'},
                    {'customer_key': 'target', 'history_scope': 'all', 'show_images': False}]
        keys = [scope['_memory_put'](share, 'HTML') for share in variants]
        other_key = scope['_memory_put']({'customer_key': 'other'}, 'other HTML')
        scope['_TOKEN_HTML']['old-token-hash'] = {'customer_key': 'target', 'variant_key': keys[0]}
        scope['_active_shares'] = lambda: self.fail('Invalidation performed a database scan')
        scope['_drop_customer']('target')
        for key in keys:
            self.assertNotIn(key, scope['_HTML'])
            self.assertNotIn(key, scope['_HTML_CUSTOMERS'])
            self.assertNotIn(key, scope['_HTML_CHECKED_AT'])
        self.assertNotIn('old-token-hash', scope['_TOKEN_HTML'])
        self.assertEqual(scope['_HTML'], {other_key: 'other HTML'})

    def test_startup_persisted_html_is_indexed_before_its_first_visitor(self):
        scope = cache_scope()
        fake_database(scope, [{'cache_key': 'persisted-key', 'customer_key': 'target', 'html': 'HTML'}])
        self.assertEqual(scope['_load_all_persisted'](), 1)
        scope['_drop_customer']('target')
        self.assertEqual(scope['_HTML'], {})
        self.assertEqual(scope['_HTML_CUSTOMERS'], {})

    def test_cold_persisted_read_is_also_indexed_for_invalidation(self):
        scope = cache_scope()
        share = {'customer_key': 'target'}
        fake_database(scope, [{'html': 'HTML'}])
        self.assertEqual(scope['_load_one_persisted'](share), 'HTML')
        scope['_drop_customer']('target')
        self.assertEqual(scope['_HTML'], {})
        self.assertEqual(scope['_HTML_CUSTOMERS'], {})

    def test_performance_log_contains_timings_but_no_raw_share_token(self):
        scope = load_functions('services/order_share_server_timing.py', {'_add_order_share_server_timing'}, {
            'g': g, 'request': request, 'time': time, 'hashlib': hashlib,
            '_sweep_state': lambda: (False, 0, 0),
        })
        token = 'do-not-log-this-secret-token'
        app = Flask('timing-log-test')
        output = io.StringIO()
        with app.test_request_context('/share/' + token), redirect_stdout(output):
            g._order_request_started = time.perf_counter() - .1
            g._order_load_ms = 10
            g._order_render_ms = 20
            g._order_load_path = 'html-memory-zero-bundle'
            response = Response('HTML')
            response.headers['X-Order-Cache'] = 'HIT'
            scope['_add_order_share_server_timing'](response)
        log = output.getvalue()
        self.assertNotIn(token, log)
        self.assertIn('share_id=' + hashlib.sha256(token.encode()).hexdigest()[:12], log)
        self.assertIn('load_ms=10.0', log)
        self.assertIn('render_ms=20.0', log)
        self.assertIn('cache=HIT load_path=html-memory-zero-bundle', log)


if __name__ == '__main__':
    unittest.main()
