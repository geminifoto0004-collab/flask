"""Static isolation regression checks without opening TiDB or importing Flask."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CrawlerIsolationTests(unittest.TestCase):
    def test_dedicated_entrypoint_parses(self):
        self.assertTrue((ROOT / "crawler_app.py").is_file())
        ast.parse((ROOT / "crawler_app.py").read_text(encoding="utf-8"))

    def test_crawler_does_not_import_order_runtime(self):
        code = (ROOT / "crawler_app.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [part.name for part in node.names]
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse([x for x in imports if x == "app" or x.startswith(
            ("order_tracking", "services.order_", "blueprints.b2_test_bp"))])

    def test_independent_database_is_required(self):
        code = (ROOT / "crawler_app.py").read_text(encoding="utf-8")
        for marker in (
            'CRAWLER_TIDB_URL', 'CRAWLER_SECRET_KEY',
            'TIDB_MIRROR_ENABLED', 'TIDB_FAILOVER_ENABLED',
            'TIDB1_URL', 'XINGWANG_SERVICE_ROLE',
        ):
            self.assertIn(marker, code)
        for denied in (
            '/share/', '/tracking', '/api/order-cloud/', '/api/telegram/order-shares/',
        ):
            self.assertIn(denied, code)

    def test_order_telegram_plugin_disabled_for_crawler(self):
        code = (ROOT / "blueprints/automation_hub/__init__.py").read_text(encoding="utf-8")
        self.assertIn('XINGWANG_SERVICE_ROLE', code)
        self.assertIn('ORDER_SHARES', code)


if __name__ == "__main__":
    unittest.main()
