"""Offline regression tests for V287 Class-B HEAD circuit breaker.

Tests compile the actual canonical functions with fake dependencies. No network,
B2 account, TiDB tables or Flask application are loaded.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
import re
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "services" / "order_cloud_asset_service.py"
DIRECT = ROOT / "services" / "order_cloud_direct_multi_b2.py"


class ClientError(Exception):
    def __init__(self, status, code, message):
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code, "Message": message},
        }
        super().__init__(message)


def _function(path, name, globals_dict):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    # The production import is equivalent to this fake dependency in offline tests.
    if name == "_b2_existing_object":
        node.body = [
            n for n in node.body
            if not (isinstance(n, ast.ImportFrom) and n.module == "botocore.exceptions")
        ]
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), globals_dict)
    return globals_dict[name]


def cap_checker():
    scope = {"ClientError": ClientError}
    return _function(ASSET, "_is_class_b_cap_exceeded", scope)


class ClassBCapClassifierTests(unittest.TestCase):
    def test_precise_classb_error_does_not_confuse_access_denied(self):
        check = cap_checker()
        self.assertTrue(check(ClientError(
            403, "AccessDenied", "download bandwidth or transaction (Class B) cap exceeded")))
        self.assertTrue(check(ClientError(403, "AccessDenied", "transaction cap exceeded")))
        self.assertFalse(check(ClientError(403, "AccessDenied", "Access denied")))
        self.assertFalse(check(ClientError(404, "NoSuchKey", "Object missing")))
        self.assertFalse(check(ClientError(500, "InternalError", "Class B cap exceeded")))
        self.assertFalse(check(RuntimeError("network unavailable")))


class BatchCircuitBreakerTests(unittest.TestCase):
    def run_batch(self, primary_results, secondary_results, count=3):
        calls = []
        counters = {"b2_primary": 0, "b2_secondary": 0}
        responses = {"b2_primary": primary_results, "b2_secondary": secondary_results}

        def head(backend, object_key, client_cfg=None):
            calls.append(backend)
            pos = counters[backend]
            counters[backend] += 1
            seq = responses[backend]
            result = seq[min(pos, len(seq) - 1)]
            if isinstance(result, Exception):
                raise result
            return result

        scope = {
            "ClientError": ClientError,
            "threading": threading,
            "ThreadPoolExecutor": ThreadPoolExecutor,
            "activity_context": lambda name: nullcontext(),
            "BACKENDS": ("b2_primary", "b2_secondary"),
            "_validate_sha256": lambda value: value,
            "_validate_content_type": lambda value: value,
            "_object_key": lambda sha, content_type: "sha/" + sha,
            "backend_health": lambda force=False: {
                "primary": {"status": "ok"}, "secondary": {"status": "ok"}},
            "_backend_client": lambda backend: (object(), {"bucket_name": "private"}),
            "_head_backend_object": head,
        }
        scope["_is_class_b_cap_exceeded"] = cap_checker()
        fn = _function(ASSET, "check_image_hash_batch", scope)
        items = [
            {"client_id": f"i{index}", "sha256": ("%064x" % (index + 1)),
             "content_type": "image/jpeg"}
            for index in range(count)
        ]
        result = fn(items, max_workers=1)
        return result, calls, counters

    def test_cap_blocks_later_head_without_claiming_missing(self):
        cap = ClientError(403, "AccessDenied", "transaction (Class B) cap exceeded")
        result, calls, counts = self.run_batch([cap], [None], count=5)
        self.assertEqual(counts, {"b2_primary": 1, "b2_secondary": 5})
        self.assertEqual(result["checked_count"], 5)
        self.assertTrue(all(not x["ok"] for x in result["items"]))
        self.assertTrue(all("cap exceeded" in x["error"] for x in result["items"]))

    def test_other_backend_can_still_confirm_existing_image(self):
        cap = ClientError(403, "AccessDenied", "transaction cap exceeded")
        result, _, counts = self.run_batch([cap], [{"ContentLength": 256}], count=4)
        self.assertEqual(counts, {"b2_primary": 1, "b2_secondary": 4})
        self.assertTrue(all(x["ok"] and x["result"]["exists"] for x in result["items"]))
        self.assertTrue(all(x["result"]["storage_backend"] == "b2_secondary"
                            for x in result["items"]))

    def test_plain_access_denied_does_not_trip_global_cap_breaker(self):
        forbidden = ClientError(403, "AccessDenied", "This prefix is not accessible")
        result, _, counts = self.run_batch([forbidden], [None], count=4)
        self.assertEqual(counts, {"b2_primary": 4, "b2_secondary": 4})
        self.assertTrue(all(not x["ok"] for x in result["items"]))

    def test_all_404s_are_absent_only_when_both_checked(self):
        result, _, counts = self.run_batch([None], [None], count=3)
        self.assertEqual(counts, {"b2_primary": 3, "b2_secondary": 3})
        self.assertTrue(all(x["ok"] and not x["result"]["exists"]
                            for x in result["items"]))


class ExistingObjectProbeTests(unittest.TestCase):
    def run_probe(self, responses, names=("a", "b", "c")):
        calls = []
        def client_for(backend):
            class FakeClient:
                def head_object(self, *, Bucket, Key):
                    calls.append((backend, Key))
                    item = responses.get((backend, Key), None)
                    if isinstance(item, Exception):
                        raise item
                    return item or {"ContentLength": 12}
            return FakeClient()

        scope = {
            "ClientError": ClientError,
            "PRIMARY": "b2_primary", "SECONDARY": "b2_secondary",
            "backend_ready": lambda backend: True,
            "config_for_backend": lambda backend, required=True: {"bucket_name": "private"},
            "_client_for_backend": client_for,
            "asset_service": types.SimpleNamespace(
                _is_class_b_cap_exceeded=cap_checker()),
        }
        probe = _function(DIRECT, "_b2_existing_object", scope)
        try:
            return probe(names, expected_size=12), calls, None
        except RuntimeError as exc:
            return None, calls, exc

    def test_cap_skips_rest_of_capped_backend_and_recovers_secondary(self):
        cap = ClientError(403, "AccessDenied", "Class B cap exceeded")
        missing = ClientError(404, "NoSuchKey", "missing")
        result, calls, err = self.run_probe({
            ("b2_primary", "a"): cap,
            ("b2_secondary", "a"): missing,
            ("b2_secondary", "b"): {"ContentLength": 12},
        })
        self.assertIsNone(err)
        self.assertEqual(result, ("b2_secondary", "b", 12))
        self.assertEqual(calls, [
            ("b2_primary", "a"), ("b2_secondary", "a"), ("b2_secondary", "b")])

    def test_all_capped_backends_return_unknown_not_false_missing(self):
        cap = ClientError(403, "AccessDenied", "transaction cap exceeded")
        result, calls, err = self.run_probe({
            ("b2_primary", "a"): cap, ("b2_secondary", "a"): cap})
        self.assertIsNone(result)
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(calls, [("b2_primary", "a"), ("b2_secondary", "a")])

    def test_object_specific_403_still_tries_legacy_key(self):
        forbidden = ClientError(403, "AccessDenied", "This key is forbidden")
        missing = ClientError(404, "NoSuchKey", "missing")
        result, calls, err = self.run_probe({
            ("b2_primary", "a"): forbidden,
            ("b2_primary", "b"): missing,
            ("b2_primary", "c"): {"ContentLength": 12},
        })
        self.assertIsNone(err)
        self.assertEqual(result, ("b2_primary", "c", 12))
        self.assertEqual(calls, [
            ("b2_primary", "a"), ("b2_primary", "b"), ("b2_primary", "c")])



class CapFailClosedSignerTests(unittest.TestCase):
    """Run the real signer function and assert no PUT URL after confirmed Class B cap."""

    def invoke(self, error_message):
        counters = {"presign": 0, "metadata": 0, "selected": 0}
        def probe(*args, **kwargs):
            try:
                raise ClientError(403, "AccessDenied", error_message)
            except ClientError as original:
                raise RuntimeError("cannot confirm whether image already exists") from original

        def presign(*args, **kwargs):
            counters["presign"] += 1
            return "https://example.invalid/not-a-real-put"

        def metadata(*args, **kwargs):
            counters["metadata"] += 1
            return {"asset_key": "dummy"}

        def choose(*args, **kwargs):
            counters["selected"] += 1
            return "b2_primary", {"selected": "b2_primary"}

        scope = {
            "PRIMARY": "b2_primary",
            "SECONDARY": "b2_secondary",
            "_ALLOWED_BACKENDS": {"b2_primary", "b2_secondary"},
            "_NEW_IMAGE_MAX_BYTES": 1_000_000,
            "_LEGACY_MAX_BYTES": 15 * 1024 * 1024,
            "_validate_sha256": lambda s: s,
            "_validate_content_type": lambda s: s,
            "_resolve_owner": lambda order, workflow, conn=None: (order, "customer1", workflow),
            "_existing_asset": lambda *a, **k: None,
            "_scoped_object_key": lambda *a: "new/object/key.jpg",
            "_object_key": lambda *a: "old/key.jpg",
            "_b2_existing_object": probe,
            "_thumb_object_key": lambda sha: "thumb.jpg",
            "_upsert_registered_asset": metadata,
            "_choose_upload_backend": choose,
            "_presigned_put": presign,
            "backend_ready": lambda backend: True,
            "asset_service": types.SimpleNamespace(
                _is_class_b_cap_exceeded=cap_checker()),
        }
        fn = _function(DIRECT, "_direct_presign_result", scope)
        customer_module = types.ModuleType("services.order_cloud_customer_storage")
        customer_module.stable_object_key = lambda *args: "stable/object/key.jpg"
        customer_module.find_customer_sha_asset = lambda *args: None
        services_module = types.ModuleType("services")
        services_module.__path__ = []
        payload = {
            "variant": "image", "sha256": "a" * 64, "content_type": "image/jpeg",
            "file_size": 1200, "order_number": "O1",
        }
        with patch.dict(sys.modules, {
            "services": services_module,
            "services.order_cloud_customer_storage": customer_module,
        }):
            try:
                result = fn(payload)
                return result, counters, None
            except RuntimeError as exc:
                return None, counters, exc

    def test_known_classb_cap_must_not_create_upload_url(self):
        result, counters, err = self.invoke(
            "download bandwidth or transaction (Class B) cap exceeded")
        self.assertIsNone(result)
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("upload deferred", str(err))
        self.assertEqual(counters, {"presign": 0, "metadata": 0, "selected": 0})

    def test_other_403_preserves_existing_warning_and_signer_behavior(self):
        result, counters, err = self.invoke("Access denied for one object prefix")
        self.assertIsNone(err)
        self.assertEqual(result["upload_mode"], "pc_direct_b2_batch_ready")
        self.assertIn("b2_probe_warning", result)
        self.assertEqual(counters, {"presign": 1, "metadata": 0, "selected": 1})

    def test_earlier_noncap_error_cannot_hide_later_cap(self):
        forbidden = ClientError(403, "AccessDenied", "One prefix forbidden")
        missing = ClientError(404, "NoSuchKey", "missing")
        cap = ClientError(403, "AccessDenied", "Class B cap exceeded")
        result, calls, err = ExistingObjectProbeTests().run_probe({
            ("b2_primary", "a"): forbidden,
            ("b2_primary", "b"): missing,
            ("b2_primary", "c"): missing,
            ("b2_secondary", "a"): cap,
        })
        self.assertIsNone(result)
        self.assertIsInstance(err, RuntimeError)
        self.assertTrue(cap_checker()(err.__cause__))
        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()
