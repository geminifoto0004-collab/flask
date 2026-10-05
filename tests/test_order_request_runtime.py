"""Exercise startup and request timing under concurrent guest/sync requests."""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
from pathlib import Path
import threading
import time
import unittest

from flask import Flask, g, request


def runtime(init_database):
    source = Path(__file__).resolve().parents[1].joinpath('app.py').read_text()
    tree = ast.parse(source)
    names = {'_begin_order_request_timing', '_finish_order_request_timing',
             'initialize_database', 'render_keepalive_ping'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    app = Flask(__name__)
    namespace = {'app': app, 'g': g, 'request': request, 'time': time,
                 '_database_initialized': False, '_database_initialize_lock': threading.Lock(),
                 'init_database': init_database}
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'app-runtime', 'exec'), namespace)

    @app.route('/share/test-customer')
    def share():
        return 'orders'

    return app, namespace


class OrderRequestRuntimeTests(unittest.TestCase):
    def test_concurrent_first_requests_initialize_once_and_ping_does_not_wait(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def initialize():
            calls.append(1)
            started.set()
            if not release.wait(3):
                raise RuntimeError('test release was not signaled')

        app, state = runtime(initialize)
        def fetch(path):
            with app.test_client() as client:
                return client.get(path)

        with redirect_stdout(io.StringIO()), ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(fetch, '/share/test-customer')
            self.assertTrue(started.wait(2))
            second = pool.submit(fetch, '/share/test-customer')
            ping = pool.submit(fetch, '/ping')
            try:
                self.assertEqual(ping.result(timeout=1).data, b'OK')
                self.assertFalse(first.done())
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2).status_code, 200)
            self.assertEqual(second.result(timeout=2).status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertTrue(state['_database_initialized'])

    def test_failed_bootstrap_is_attempted_once(self):
        calls = []
        def initialize():
            calls.append(1)
            raise RuntimeError('unavailable DB')
        app, state = runtime(initialize)
        with redirect_stdout(io.StringIO()), app.test_client() as client:
            self.assertEqual(client.get('/share/test-customer').status_code, 200)
            self.assertEqual(client.get('/share/test-customer').status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertTrue(state['_database_initialized'])

    def test_timer_includes_bootstrap_before_the_page_loader(self):
        app, _ = runtime(lambda: time.sleep(0.02))
        with redirect_stdout(io.StringIO()), app.test_client() as client:
            response = client.get('/share/test-customer')
        self.assertGreaterEqual(float(response.headers['X-Order-Request-MS']), 20)


if __name__ == '__main__':
    unittest.main()
