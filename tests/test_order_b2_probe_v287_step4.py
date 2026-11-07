"""Offline security/cooldown tests for protected B2 Class-B probe."""
import ast
from pathlib import Path
import math
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "services" / "order_b2_classb_probe.py"


def extract(name, scope):
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    mod = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(mod, str(PATH), "exec"), scope)
    return scope[name]


class FakeClientError(Exception):
    def __init__(self, code, aws, message):
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": code},
            "Error": {"Code": aws, "Message": message},
        }


class ProbeTests(unittest.TestCase):
    def run_case(self, exception):
        calls = []
        class Client:
            def head_object(self, **kwargs):
                calls.append(kwargs)
                raise exception
        scope = {
            "backend_ready": lambda backend: True,
            "config_for_backend": lambda backend, required=True: {"bucket_name": "fake-bucket"},
            "_one_shot_client": lambda backend, cfg: Client(),
            "ClientError": FakeClientError,
            "uuid": types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex="test123")),
        }
        result = extract("_probe_backend", scope)("b2_primary")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["Bucket"], "fake-bucket")
        self.assertNotIn("bucket_name", result)
        return result

    def test_missing_key_is_healthy(self):
        self.assertEqual(self.run_case(FakeClientError(404, "NoSuchKey", "missing"))["status"], "ok")

    def test_cap_exceeded_403(self):
        result = self.run_case(FakeClientError(
            403, "AccessDenied", "download bandwidth or transaction (Class B) cap exceeded"))
        self.assertEqual(result["status"], "cap_exceeded")

    def test_permission_denied_403(self):
        self.assertEqual(self.run_case(FakeClientError(
            403, "AccessDenied", "Access denied"))["status"], "access_denied")

    def test_timeout_not_notfound(self):
        self.assertEqual(self.run_case(TimeoutError("timed out"))["status"], "network_error")

    def test_cooldown_prevents_repeat_calls(self):
        sent = []
        def fake_probe(backend):
            sent.append(backend)
            return {"backend": backend, "configured": True, "status": "ok", "head_requests": 1}
        scope = {
            "_PROBE_LOCK": threading.Lock(),
            "_LAST_PROBE_AT": 0,
            "_LAST_RESULT": None,
            "_COOLDOWN_SECONDS": 900,
            "PRIMARY": "b2_primary",
            "SECONDARY": "b2_secondary",
            "_probe_backend": fake_probe,
            "math": math,
            "time": types.SimpleNamespace(monotonic=lambda: 100.0),
        }
        run = extract("_read_or_run_probe", scope)
        first = run(now=100)
        self.assertEqual(first["head_requests_this_call"], 2)
        second = run(now=101)
        self.assertTrue(second["cached"])
        self.assertEqual(second["head_requests_this_call"], 0)
        self.assertEqual(len(sent), 2)
        third = run(now=1000)
        self.assertEqual(third["head_requests_this_call"], 2)
        self.assertEqual(len(sent), 4)

    def test_no_grant_no_probe(self):
        fake = types.ModuleType("services.order_desktop_grant")
        fake.authorized = lambda scope: False
        sent = []
        scope = {
            "_order_cloud_auth_source": lambda: ("ORDER", None),
            "request": types.SimpleNamespace(get_json=lambda silent=True: {"action": "probe"}),
            "jsonify": lambda **kwargs: kwargs,
            "_read_or_run_probe": lambda: sent.append("head"),
        }
        route = extract("order_cloud_b2_class_b_probe", scope)
        with patch.dict(sys.modules, {"services.order_desktop_grant": fake}):
            response, status = route()
        self.assertEqual(status, 401)
        self.assertEqual(sent, [])

    def test_safety_configuration(self):
        code = PATH.read_text(encoding="utf-8")
        self.assertIn('"total_max_attempts": 1', code)
        self.assertIn("_COOLDOWN_SECONDS = 900", code)
        self.assertIn('authorized("replicas:verify-repair")', code)
        self.assertIn('methods=["POST"]', code)
        self.assertIn("instrument_client(client,", code)


if __name__ == "__main__":
    unittest.main()
