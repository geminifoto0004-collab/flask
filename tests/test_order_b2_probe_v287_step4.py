"""V287 step 4: offline checks for fail-closed, bounded owner-only B2 diagnostics.

Compile the real production functions with dependency stubs. Tests never import
boto3 or Flask and never access B2, TiDB or the network.
"""
import ast
from contextlib import nullcontext
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import uuid

SOURCE = Path(__file__).resolve().parents[1] / "services" / "order_b2_classb_probe.py"
IMPORTS = Path(__file__).resolve().parents[1] / "services" / "__init__.py"
SRC_TEXT = SOURCE.read_text(encoding="utf-8")


class Response(dict):
    def __init__(self, value):
        super().__init__(value)
        self.headers = {}


def isolated_functions():
    tree = ast.parse(SRC_TEXT)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    for node in functions:
        node.decorator_list = []
    return compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec")


CODE = isolated_functions()


class OneShotProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.secret = "a" * 48
        self.request = types.SimpleNamespace(headers={})
        self.scope = {
            "hmac": hmac, "json": json, "os": os, "time": time,
            "uuid": uuid, "request": self.request,
            "jsonify": Response, "PRIMARY": "b2_primary",
            "SECONDARY": "b2_secondary",
            "_DIAG_PATH": str(Path(self.temp.name) / "one-shot.json"),
            "_TOKEN_HEADER": "X-ORDER-B2-Diag-Token",
            "activity_context": lambda name: nullcontext(),
            "snapshot": lambda drain=False: {
                "details": [], "totals": {"HEAD": 0, "GET": 0, "PUT": 0, "LIST": 0},
            },
        }
        exec(CODE, self.scope)
        self.calls = []
        self.counts = {"b2_primary": 0, "b2_secondary": 0}

        def fake_probe(backend, client_factory=None):
            self.calls.append(backend)
            self.counts[backend] += 1
            return {"configured": True, "backend": backend,
                    "class_b_ok": True, "status": "ok", "http_status": 404}

        self.scope["_probe_backend"] = fake_probe
        self.scope["_diagnostic_attempts"] = lambda: dict(self.counts)

    def post(self):
        return self.scope["order_cloud_b2_class_b_probe"]()

    def get(self):
        return self.scope["order_cloud_b2_diagnostic_status"]()

    def test_default_disabled_even_when_order_switch_on(self):
        with patch.dict(os.environ, {"ORDER": "1", "ORDER_B2_DIAG_TOKEN": self.secret},
                        clear=True):
            self.request.headers["X-ORDER-B2-Diag-Token"] = self.secret
            response, status = self.post()
        self.assertEqual(status, 404)
        self.assertEqual(response["code"], "DIAGNOSTIC_DISABLED")
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(self.scope["_DIAG_PATH"]))

    def test_switch_without_separate_secret_cannot_run(self):
        with patch.dict(os.environ, {"ORDER": "1", "ORDER_B2_DIAG_ENABLED": "1"},
                        clear=True):
            response, status = self.post()
        self.assertEqual(status, 403)
        self.assertEqual(response["code"], "DIAGNOSTIC_FORBIDDEN")
        self.assertEqual(self.calls, [])

    def test_short_or_incorrect_token_cannot_run(self):
        for secret, supplied in (("short", "short"), (self.secret, "bad"),
                                 (self.secret, "")):
            with self.subTest(secret_length=len(secret), supplied=supplied):
                with patch.dict(os.environ, {
                    "ORDER_B2_DIAG_ENABLED": "1", "ORDER_B2_DIAG_TOKEN": secret,
                }, clear=True):
                    self.request.headers["X-ORDER-B2-Diag-Token"] = supplied
                    _, status = self.post()
                    self.assertEqual(status, 403)
                    self.assertEqual(self.calls, [])

    def test_once_only_two_backends_and_status_read_does_no_head(self):
        with patch.dict(os.environ, {
            "ORDER_B2_DIAG_ENABLED": "1", "ORDER_B2_DIAG_TOKEN": self.secret,
        }, clear=True):
            self.request.headers["X-ORDER-B2-Diag-Token"] = self.secret
            first, status = self.post()
            self.assertEqual(status, 200)
            self.assertEqual(self.calls, ["b2_primary", "b2_secondary"])
            self.assertEqual(first["total_head_http_send_attempts"], 2)
            self.assertEqual(first["head_http_send_attempts"],
                             {"b2_primary": 1, "b2_secondary": 1})
            self.assertEqual(first["scope"], "one_run_per_render_instance_no_sdk_retries")
            self.assertEqual(first.headers["Cache-Control"], "no-store, max-age=0")
            self.assertNotIn(self.secret, str(first))
            self.assertNotIn("bucket_name", str(first))

            status_response, status_code = self.get()
            self.assertEqual(status_code, 200)
            self.assertEqual(status_response["last_run"]["state"], "completed")
            self.assertEqual(len(self.calls), 2, "status GET must not call B2")

            second, status_code = self.post()
            self.assertEqual(status_code, 409)
            self.assertEqual(second["code"], "DIAGNOSTIC_ALREADY_USED")
            self.assertEqual(len(self.calls), 2, "second POST must not call B2")

    def test_guard_failure_denies_without_network(self):
        with patch.dict(os.environ, {
            "ORDER_B2_DIAG_ENABLED": "1", "ORDER_B2_DIAG_TOKEN": self.secret,
        }, clear=True):
            self.request.headers["X-ORDER-B2-Diag-Token"] = self.secret
            self.scope["_reserve_once"] = lambda: (_ for _ in ()).throw(OSError("readonly"))
            response, status = self.post()
        self.assertEqual(status, 503)
        self.assertEqual(response["code"], "DIAGNOSTIC_GUARD_UNAVAILABLE")
        self.assertEqual(self.calls, [])

    def test_no_retry_client_is_explicitly_bounded(self):
        seen = {}
        class FakeBoto:
            @staticmethod
            def client(service, **kwargs):
                seen["service"] = service
                seen.update(kwargs)
                return object()
        self.scope["boto3"] = FakeBoto()
        self.scope["BotoConfig"] = lambda **kwargs: kwargs
        self.scope["config_for_backend"] = lambda name, required=True: {
            "endpoint": "https://b2.invalid", "key_id": "KEY", "application_key": "SECRET",
        }
        self.scope["instrument_client"] = lambda client, **kwargs: kwargs
        result = self.scope["_single_attempt_client"]("b2_primary")
        self.assertEqual(result["component"], "classb_probe")
        self.assertEqual(seen["service"], "s3")
        self.assertEqual(seen["config"]["retries"]["total_max_attempts"], 1)
        self.assertEqual(seen["config"]["connect_timeout"], 5)

    def test_route_registration_is_only_post_and_status_get(self):
        tree = ast.parse(SRC_TEXT)
        routes = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", "") == "route":
                    routes[ast.literal_eval(decorator.args[0])] = ast.literal_eval(
                        next(k.value for k in decorator.keywords if k.arg == "methods"))
        self.assertEqual(routes["/api/order-cloud/b2/class-b"], ["POST"])
        self.assertEqual(routes["/api/order-cloud/b2/class-b/status"], ["GET"])
        self.assertIn("import order_b2_classb_probe", IMPORTS.read_text(encoding="utf-8"))

    def test_sensitive_exception_messages_are_not_returned(self):
        # The existing simulation tests cover HTTP 404 and Class-B-vs-access-denied.
        self.assertNotIn('"aws_message": message', SRC_TEXT)
        self.assertNotIn('"error": str(exc)', SRC_TEXT)
        self.assertIn("os.O_CREAT | os.O_EXCL", SRC_TEXT)


if __name__ == "__main__":
    unittest.main()
