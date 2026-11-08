"""Offline regression checks for the published ORDER wall after a text-only upsert."""

import ast
import copy
import gzip
import io
import json
import sys
import threading
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "fixture-token"
ORDER = "1008632"
WORKFLOW = "1008632-1"
CUSTOMER = "QA CLIENT"


def load_functions(relative_path, names, namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text("utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == set(names)
    for node in functions:
        node.decorator_list = []
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class OrderShareRefreshTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.written = []
        self.queued = []
        self.rebuild_pending = []
        self.order = {"order_number": ORDER, "order_status": "ACTIVE", "workflows": []}
        self.bundle = self._snapshot()
        service = types.ModuleType("services.order_cloud_asset_service")
        service.ensure_order_owners_fast_batch = self._write
        service.fast_refresh_shared_customers = self._queue
        service.probe_order_deltas = lambda fps, include_new: {"new": list(fps) if include_new else []}
        self.service = service
        route = "order_cloud_sync_orders_upsert_only"
        namespace = load_functions(
            "blueprints/b2_test_bp.py", [route],
            {"request": request, "jsonify": jsonify, "json": json, "gzip": gzip, "io": io, "zlib": zlib,
             "_order_cloud_auth_source": lambda: ("HOME", None), "_ensure_order_cloud_tables": lambda: None},
        )
        self.path = "/api/order-cloud/sync/orders-upsert-only"
        self.app.add_url_rule(self.path, view_func=namespace[route], methods=["POST"])
        self.client = self.app.test_client()

    def _snapshot(self):
        order = copy.deepcopy(self.order)
        # Represents an already-registered parent attachment. The upsert and
        # the refresh never need an image upload or a B2 verification request.
        if order["workflows"]:
            order["assets"] = [{
                "asset_key": "a" * 64, "sha256": "b" * 64, "order_number": ORDER,
                "asset_type": "IMAGE", "workflow_key": "", "customer_visible": True,
            }]
        return {"orders": [order], "customer": {"customer_name": CUSTOMER}}

    def _write(self, orders, source_site, *, expected_target, upsert_only):
        assert source_site == "HOME" and expected_target == "TIDB1" and upsert_only
        number = orders[0]["order_number"]
        if self.order == orders[0]:
            return {"orders": [number], "customer_keys": [], "written": []}
        self.order = copy.deepcopy(orders[0])
        self.written.append(number)
        return {"orders": [number], "customer_keys": [CUSTOMER], "written": [number]}

    def _queue(self, customer_keys):
        assert self.written == [ORDER]  # after the committed write
        self.queued.append(customer_keys)
        self.rebuild_pending.append(self._snapshot)
        return {"queued": len(customer_keys)}

    def _submit(self, body):
        modules = {"services.order_cloud_asset_service": self.service}
        with patch.dict(sys.modules, modules):
            return self.client.post(self.path, json=body)

    def _change(self):
        return {"orders": [{"order_number": ORDER, "order_status": "ACTIVE", "customer_name": CUSTOMER,
                            "workflows": [{"workflow_number": WORKFLOW, "status": "NEW_ORDER"}],
                            "logistics": []}], "target": "TIDB1"}

    def test_text_only_upsert_rebuilds_wall_with_current_key_and_permitted_cover(self):
        policy = load_functions(
            "services/order_share_image_policy.py",
            ["source_match", "bool_default", "_order_override", "asset_allowed", "filter_assets_in_space"], {},
        )
        native = load_functions(
            "services/order_share_native_order_ui.py",
            ["_key", "_is_image", "_route", "_images", "_pick", "_logistics_filter_key",
             "_fully_retired", "_logistics_filter_keys", "_card", "_cards", "_history", "_stages",
             "_expiry", "_order_context"],
            {**policy, "copy": copy, "quote": quote, "_label": lambda status, lang: status,
             "_stage": lambda status: "order", "_fingerprint": lambda: "fixture",
             "apply_shipping_summary": lambda *_: None, "derive_shipping_summary": lambda _: {}},
        )
        stale = native["_cards"](self.bundle, TOKEN)[0]
        self.assertEqual(stale["detail_url"], f"/share/{TOKEN}/order/{ORDER}")
        self.assertEqual(stale["images"], [])
        reply = self._submit(self._change())
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json["result"]["snapshot_refresh"], {"queued": 1})
        self.assertEqual(self.queued, [[CUSTOMER]])
        self.bundle = self.rebuild_pending.pop()()
        self.assertIsNone(native["_order_context"](self.bundle, {}, TOKEN, ORDER))
        current = native["_cards"](self.bundle, TOKEN)[0]
        self.assertEqual(current["detail_url"], f"/share/{TOKEN}/order/{WORKFLOW}")
        self.assertEqual(current["images"][0]["_source_kind"], "order")
        self.assertEqual(native["_order_context"](self.bundle, {}, TOKEN, WORKFLOW)["order"]["images"],
                         current["images"])
        self.assertEqual(native["_order_context"](self.bundle, {"show_images": False}, TOKEN, WORKFLOW)
                         ["order"]["images"], [])
        self.bundle["orders"][0]["assets"][0]["customer_visible"] = False
        self.assertEqual(native["_order_context"](self.bundle, {}, TOKEN, WORKFLOW)["order"]["images"], [])

    def test_read_only_probe_and_unchanged_write_do_not_queue(self):
        self.assertEqual(self._submit({"fingerprints": {ORDER: "a" * 64}}).status_code, 200)
        self.order = self._change()["orders"][0]
        result = self._submit(self._change()).json["result"]
        self.assertEqual(result["written"], [])
        self.assertEqual(self.queued, [])

    def test_enqueue_failure_does_not_discard_committed_receipt(self):
        def unavailable(_):
            raise TimeoutError("fixture")

        self.service.fast_refresh_shared_customers = unavailable
        reply = self._submit(self._change())
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json["result"]["written"], [ORDER])
        self.assertEqual(reply.json["result"]["snapshot_refresh"], {"queued": 0, "deferred": True})

    def test_frequent_visits_recheck_and_do_not_restore_evicted_html(self):
        old = "OLD /share/PLACEHOLDER/order/1008632"
        new = "NEW /share/PLACEHOLDER/order/1008632-1"
        now = types.SimpleNamespace(monotonic=lambda: 1.0)
        rechecks = []
        html_cache = {"variant": old}
        token_cache = {}
        checked_at = {"variant": 0.0}

        def refresh(share):
            rechecks.append(share)
            html_cache["variant"] = new
            checked_at["variant"] = now.monotonic()
            token_cache.clear()

        env = load_functions(
            "services/order_share_render_cache.py", ["_cached_render_template"],
            {"_TEMPLATE": "wall", "_LOCK": threading.RLock(), "_TOKEN_PLACEHOLDER": "PLACEHOLDER",
             "_token_hash": lambda token: token, "_variant_key": lambda _: "variant",
             "_HTML": html_cache, "_HTML_CHECKED_AT": checked_at, "_TOKEN_HTML": token_cache,
             "time": now, "_PERSISTED_RECHECK_SECONDS": 3.0, "_queue_persisted_recheck": refresh,
             "_load_one_persisted": lambda _: None, "_ORIGINAL_RENDER_TEMPLATE": lambda *_a, **_kw: "",
             "_inject_direct_cover_urls": lambda html, *_: html},
        )
        share = {"customer_key": CUSTOMER}

        def visit():
            return env["_cached_render_template"](
                "wall", share_token=TOKEN, share=share, space={"orders": [self.order]})

        for tick in (1.0, 2.0, 3.0):
            now.monotonic = lambda: tick
            self.assertEqual(visit(), old.replace("PLACEHOLDER", TOKEN))
        self.assertEqual(rechecks, [])
        now.monotonic = lambda: 4.0
        self.assertEqual(visit(), old.replace("PLACEHOLDER", TOKEN))
        self.assertEqual(rechecks, [share])
        self.assertEqual(token_cache, {})
        self.assertEqual(visit(), new.replace("PLACEHOLDER", TOKEN))
