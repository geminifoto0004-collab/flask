"""No-network regression checks for passive B2 SDK telemetry."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "services" / "order_b2_metrics.py"
spec = importlib.util.spec_from_file_location("b2_metrics_test_subject", SRC)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


class FakeEvents:
    def __init__(self):
        self.handlers = {}

    def register(self, name, callback, unique_id=None):
        self.handlers.setdefault(name, {})[unique_id] = callback

    def emit(self, name):
        for callback in self.handlers[name].values():
            callback(request=object(), event_name=name)


class FakeClient:
    def __init__(self):
        self.meta = type("Meta", (), {"events": FakeEvents()})()


class B2MetricsTests(unittest.TestCase):
    def setUp(self):
        metrics.snapshot(drain=True)

    def test_attaching_client_makes_no_b2_request(self):
        client = FakeClient()
        self.assertIs(metrics.instrument_client(client, backend="b2_primary", component="asset_service"), client)
        self.assertEqual(metrics.snapshot(drain=True)["totals"]["HEAD"], 0)

    def test_one_head_one_attempt(self):
        client = FakeClient()
        metrics.instrument_client(client, backend="b2_primary", component="asset_service")
        client.meta.events.emit("before-send.s3.HeadObject")
        summary = metrics.snapshot(drain=True)
        self.assertEqual(summary["totals"], {"HEAD": 1, "GET": 0, "PUT": 0, "LIST": 0})
        self.assertEqual(summary["details"][0]["backend"], "b2_primary")

    def test_retries_count_per_http_send(self):
        client = FakeClient()
        metrics.instrument_client(client, backend="b2_secondary", component="multi_b2")
        for _ in range(3):
            client.meta.events.emit("before-send.s3.GetObject")
        self.assertEqual(metrics.snapshot(drain=True)["totals"]["GET"], 3)

    def test_head_get_put_list_are_separate(self):
        client = FakeClient()
        metrics.instrument_client(client, backend="b2_primary", component="direct_presign")
        for name in ("HeadObject", "GetObject", "PutObject", "ListObjectsV2"):
            client.meta.events.emit("before-send.s3." + name)
        self.assertEqual(metrics.snapshot(drain=True)["totals"], {
            "HEAD": 1, "GET": 1, "PUT": 1, "LIST": 1,
        })

    def test_double_instrumentation_has_no_duplicate_count(self):
        client = FakeClient()
        metrics.instrument_client(client, backend="b2_primary", component="direct_presign")
        metrics.instrument_client(client, backend="b2_primary", component="direct_presign")
        client.meta.events.emit("before-send.s3.HeadObject")
        self.assertEqual(metrics.snapshot(drain=True)["totals"]["HEAD"], 1)

    def test_audit_context_and_background_are_separated(self):
        with metrics.activity_context("deep_audit"):
            metrics.record_attempt("b2_primary", "asset_service", "HeadObject")
        metrics.record_attempt("b2_primary", "asset_service", "HeadObject")
        details = metrics.snapshot(drain=True)["details"]
        self.assertEqual({row["activity"] for row in details}, {"deep_audit", "background"})

    def test_audit_attribution_in_thread_workers(self):
        def work():
            with metrics.activity_context("deep_audit"):
                metrics.record_attempt("b2_primary", "asset_service", "HeadObject")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: work(), range(10)))
        result = metrics.snapshot(drain=True)
        self.assertEqual(result["totals"]["HEAD"], 10)
        self.assertTrue(all(row["activity"] == "deep_audit" for row in result["details"]))

    def test_context_restored_after_exception(self):
        with self.assertRaises(ValueError):
            with metrics.activity_context("deep_audit"):
                raise ValueError("test")
        metrics.record_attempt("b2_primary", "asset_service", "GetObject")
        self.assertEqual(metrics.snapshot(drain=True)["details"][0]["activity"], "background")

    def test_log_contains_counts_not_b2_secrets(self):
        client = FakeClient()
        metrics.instrument_client(client, backend="b2_primary", component="multi_b2")
        client.meta.events.emit("before-send.s3.HeadObject")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            metrics.log_pending()
        logged = output.getvalue()
        self.assertIn("[ORDER B2 USAGE]", logged)
        self.assertIn("render_botocore_http_send_attempts_only", logged)
        self.assertNotIn("X-Amz-", logged)
        self.assertNotIn("secret", logged.lower())
        self.assertEqual(metrics.snapshot(drain=True)["totals"]["HEAD"], 0)

    def test_production_client_factories_are_instrumented(self):
        root = SRC.parents[1]
        for name in (
            "order_cloud_asset_service.py",
            "order_cloud_multi_b2.py",
            "order_cloud_direct_multi_b2.py",
            "order_cloud_multi_b2_public.py",
        ):
            with self.subTest(name=name):
                source = (root / "services" / name).read_text()
                self.assertIn("instrument_client(", source)


if __name__ == "__main__":
    unittest.main()
