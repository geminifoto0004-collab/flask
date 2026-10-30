"""Check the standalone crawler mounts ORIGINAL modules, not ORDER.
No network, TiDB or Telegram secrets are required; avoid runtime DB requests.
"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CrawlerProductionRoutingTest(unittest.TestCase):
    def test_actual_blueprints_import_and_register_without_db_connection(self):
        env = os.environ.copy()
        env.update({
            "CRAWLER_SETUP_MODE": "0",
            "CRAWLER_TIDB_URL":
                "mysql://fake_username:fake%40password%23@127.0.0.1:4000/xingwang_crawler",
            "SUPER_ADMIN_EMAIL": "owner@example.test",
            "SUPER_ADMIN_PASSWORD": "test-admin-pass",
        })
        for name in ("TIDB2_URL","TIDB2_HOST","TIDB2_USER","TIDB2_PASSWORD",
                     "TIDB2_NAME","TIDB1_URL","DATABASE_URL","DB_TARGET"):
            env.pop(name, None)
        code = textwrap.dedent("""
            import crawler_app
            from tidb_targets import target_settings
            from blueprints.automation_hub import registry
            assert target_settings("TIDB1")["password"] == "fake@password#"
            assert target_settings("TIDB1")["database"] == "xingwang_crawler"
            app = crawler_app.app
            paths = {r.rule for r in app.url_map.iter_rules()}
            for path in (
                "/login",
                "/admin/automation",
                "/admin/automation/aduana",
                "/api/automation/health",
                "/api/aduana/health",
                "/api/containers/list",
                "/admin/container-excel",
                "/admin/system-check",
                "/admin/system-check/initialize",
                "/api/monitor/check-all",
            ):
                assert path in paths, (path, sorted(paths))
            # Original 0004 management routes must be present and functional,
            # not just sidebar decorations.
            for path in (
                "/admin",
                "/admin/dashboard",
                "/admin/users",
                "/admin/services",
                "/admin/user-services",
                "/admin/monitor-tasks",
                "/admin/user-sessions",
                "/admin/database",
            ):
                assert path in paths, ("missing original admin route", path)
            admin_endpoints = {r.endpoint for r in app.url_map.iter_rules()
                               if r.rule.startswith("/admin")}
            assert "admin_dashboard" in admin_endpoints
            assert "admin_users" in admin_endpoints
            assert "admin_services" in admin_endpoints
            assert "admin_database" in admin_endpoints
            assert "/share/<token>" not in paths
            assert "/tracking" not in paths
            assert "/api/order-cloud/sync/order" not in paths
            assert not registry.has_plugin("ORDER_SHARES")
            assert registry.has_plugin("ADUANA")
            assert crawler_app._SETUP_MODE is False
            assert crawler_app.os.environ["TIDB_MIRROR_ENABLED"] == "false"
            assert crawler_app.os.environ["TIDB_FAILOVER_ENABLED"] == "false"
            assert crawler_app.os.environ["TIDB1_URL"] == crawler_app.os.environ["CRAWLER_TIDB_URL"]
            c = app.test_client()
            assert c.get("/ping",base_url="https://crawler.example.test").status_code == 200
            assert c.get("/login",base_url="https://crawler.example.test").status_code == 200
            assert c.get("/admin/system-check",
                         base_url="https://crawler.example.test").status_code == 302
            assert c.post("/admin/system-check/initialize",
                          base_url="https://crawler.example.test").status_code == 403
            assert c.get("/share/redacted",base_url="https://crawler.example.test").status_code == 404
        """)
        r = subprocess.run(
            [sys.executable, "-c", code],
            env=env, cwd=ROOT, capture_output=True, text=True, timeout=65,
        )
        self.assertEqual(r.returncode, 0, msg=(r.stderr or r.stdout)[-5000:])

if __name__ == "__main__":
    unittest.main()
