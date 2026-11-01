"""Isolated regression tests for safe 512-MiB Render share caches.

Extract only pure cache functions so no Flask startup, TiDB connection or
customer data is needed to run these tests.
"""
import ast
import os
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def isolate_function(path, func_name, namespace):
    module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == func_name
    ]
    assert len(nodes) == 1, (path, func_name)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


class TestShareMemoryBounds(unittest.TestCase):
    def test_space_and_token_lru(self):
        ns = dict(
            os=os,
            time=time,
            _cache_lock=threading.RLock(),
            _space_cache={},
            _token_cache={},
        )
        file = "services/order_public_share_multi_b2_page.py"
        for name in ("_cache_limit", "_cache_put", "_cache_get"):
            isolate_function(file, name, ns)
        put = ns["_cache_put"]
        get = ns["_cache_get"]
        for i in range(30):
            put(ns["_space_cache"], f"customer_{i}", {"orders": []}, 86400)
        self.assertLessEqual(len(ns["_space_cache"]), 12)
        self.assertIsNone(get(ns["_space_cache"], "customer_0"))
        self.assertIsNotNone(get(ns["_space_cache"], "customer_29"))
        for i in range(300):
            put(ns["_token_cache"], f"token_{i}", {"id": i}, 86400)
        self.assertLessEqual(len(ns["_token_cache"]), 256)
        self.assertIsNotNone(get(ns["_token_cache"], "token_299"))
        put(ns["_token_cache"], "already_expired", "bad", -1)
        self.assertIsNone(get(ns["_token_cache"], "already_expired"))

    def test_html_cache_bytes_and_variants(self):
        ns = dict(
            sys=sys,
            time=time,
            _LOCK=threading.RLock(),
            _HTML={},
            _HTML_CUSTOMERS={},
            _HTML_CHECKED_AT={},
            _TOKEN_HTML={},
            _MAX_HTML_ENTRIES=12,
            _MAX_HTML_BYTES=32 * 1024 * 1024,
            _MAX_SINGLE_HTML_BYTES=8 * 1024 * 1024,
        )
        isolate_function("services/order_share_render_cache.py", "_memory_store", ns)
        store = ns["_memory_store"]
        payload = "x" * (1024 * 1024)
        for i in range(30):
            self.assertTrue(store(f"variant-{i}", f"customer-{i}", payload))
        self.assertLessEqual(len(ns["_HTML"]), 12)
        self.assertEqual(set(ns["_HTML"]), set(ns["_HTML_CUSTOMERS"]))
        self.assertEqual(set(ns["_HTML"]), set(ns["_HTML_CHECKED_AT"]))
        self.assertFalse(store("oversized", "customer", "z" * (9 * 1024 * 1024)))
        self.assertNotIn("oversized", ns["_HTML"])

    def test_mirror_repair_uses_streaming_cursor(self):
        source = (ROOT / "services/order_tidb_cloud_reconcile.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SSDictCursor", source)
        self.assertIn("reader.fetchmany(100)", source)
        self.assertIn("TIDB_MIRROR_AUDIT_KEYS", source)
        self.assertIn("TIDB_MIRROR_REPAIR_MIN_SECONDS", source)


if __name__ == "__main__":
    unittest.main()
