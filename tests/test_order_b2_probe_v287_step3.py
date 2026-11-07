"""V287 step 3: bounded B2 Class-B probe regressions, entirely offline.

The production probe is extracted as AST so importing this test cannot import
Flask, configure B2 credentials, or call the actual network.
"""
import ast
import importlib.util
from pathlib import Path
import types
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
METRICS_FILE = ROOT / "services" / "order_b2_metrics.py"
PROBE_FILE = ROOT / "services" / "order_b2_classb_probe.py"
spec = importlib.util.spec_from_file_location("metrics_under_test_v287_3", METRICS_FILE)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


class ClientError(Exception):
    def __init__(self, status, code, message):
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status, "RequestId": "simulated-request"},
            "Error": {"Code": code, "Message": message},
        }
        super().__init__(message)


class FakeEvents:
    def __init__(self):
        self.callbacks = {}

    def register(self, event, handler, unique_id=None):
        self.callbacks.setdefault(event, []).append(handler)

    def emit(self, event):
        for callback in self.callbacks.get(event, ()):
            callback(request=object())


class FakeClient:
    def __init__(self, exception):
        self.meta = types.SimpleNamespace(events=FakeEvents())
        self.exception = exception
        self.calls = 0

    def head_object(self, *, Bucket, Key):
        self.calls += 1
        assert Bucket == "test-private-bucket"
        assert Key.startswith("order-cloud/images/__classb_probe__/")
        self.meta.events.emit("before-send.s3.HeadObject")
        raise self.exception


def load_probe(fake_client):
    """Compile only the production probe function with substituted dependencies."""
    source = ast.parse(PROBE_FILE.read_text(encoding="utf-8"))
    node = next(n for n in source.body
                if isinstance(n, ast.FunctionDef) and n.name == "_probe_backend")
    module = ast.Module(body=[node], type_ignores=[])
    scope = {
        "backend_ready": lambda name: name in {"b2_primary", "b2_secondary"},
        "config_for_backend": lambda name, required=True: {
            "bucket_name": "test-private-bucket", "endpoint": "https://example.invalid",
            "key_id": "FAKE1234", "backend": name,
        },
        "client_for_backend": lambda backend: fake_client,
        "ClientError": ClientError,
        "uuid": uuid,
    }
    exec(compile(module, str(PROBE_FILE), "exec"), scope)
    return scope["_probe_backend"]


class B2ClassBProbeOfflineTests(unittest.TestCase):
    def setUp(self):
        metrics.snapshot(drain=True)

    def invoke(self, status, code, message, backend="b2_primary"):
        fake = FakeClient(ClientError(status, code, message))
        metrics.instrument_client(fake, backend=backend, component="multi_b2")
        result = load_probe(fake)(backend)
        counted = metrics.snapshot(drain=True)
        self.assertEqual(fake.calls, 1, "each backend probe should use exactly one HEAD")
        self.assertEqual(counted["totals"], {"HEAD": 1, "GET": 0, "PUT": 0, "LIST": 0})
        self.assertEqual(counted["details"][0]["backend"], backend)
        return result

    def test_404_missing_probe_object_means_b2_access_is_healthy(self):
        result = self.invoke(404, "NoSuchKey", "The specified key does not exist")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["class_b_ok"])

    def test_actual_class_b_cap_message_is_detected(self):
        result = self.invoke(
            403, "AccessDenied",
            "download bandwidth or transaction (Class B) cap exceeded",
        )
        self.assertEqual(result["status"], "cap_exceeded")
        self.assertFalse(result["class_b_ok"])
        self.assertEqual(result["http_status"], 403)

    def test_general_permission_403_is_not_mislabeled_as_cap(self):
        result = self.invoke(403, "AccessDenied", "Access denied")
        self.assertEqual(result["status"], "forbidden_or_error")
        self.assertFalse(result["class_b_ok"])

    def test_probes_can_count_primary_and_secondary_separately(self):
        first = self.invoke(404, "NoSuchKey", "Missing", backend="b2_primary")
        second = self.invoke(403, "AccessDenied", "transaction cap exceeded",
                             backend="b2_secondary")
        self.assertEqual((first["status"], second["status"]), ("ok", "cap_exceeded"))

    def test_test_suite_uses_only_fake_clients(self):
        code = PROBE_FILE.read_text(encoding="utf-8")
        self.assertIn("def _probe_backend(", code)
        self.assertIn("(client_factory or client_for_backend)(backend).head_object(", code)


if __name__ == "__main__":
    unittest.main()
