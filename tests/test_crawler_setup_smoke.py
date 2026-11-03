"""Crawler setup smoke tests: no TiDB, no Bot token, no ORDER imports."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEST_ORIGIN = "https://crawler.example.test"


def run_isolated(code, *, with_credentials, with_secret=True):
    env = os.environ.copy()
    env["CRAWLER_SETUP_MODE"] = "1"
    env["TIDB1_URL"] = "mysql://must-never-connect:bad@127.0.0.1:4000/order"
    env["DATABASE_URL"] = "mysql://must-never-connect:bad@127.0.0.1:4000/order"
    for name in ("CRAWLER_TIDB_URL", "CRAWLER_SECRET_KEY", "SECRET_KEY",
                 "SUPER_ADMIN_EMAIL", "SUPER_ADMIN_PASSWORD", "AUTOMATION_MASTER_KEY"):
        env.pop(name, None)
    if with_credentials:
        if with_secret:
            env["SECRET_KEY"] = "unit-test-only-secret-key-with-64-chars-required-1234567890abcdef"
        env["SUPER_ADMIN_EMAIL"] = "owner@example.test"
        env["SUPER_ADMIN_PASSWORD"] = "unit-test-only-password"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )


class CrawlerSetupSmokeTest(unittest.TestCase):
    def test_can_boot_without_database_and_credentials(self):
        r = run_isolated("""
            import sys
            import crawler_app
            c = crawler_app.app.test_client()
            base = "https://crawler.example.test"
            assert c.get("/ping", base_url=base).status_code == 200
            assert c.get("/ready", base_url=base).status_code == 503
            assert c.get("/login", base_url=base).status_code == 200
            assert c.post("/login", base_url=base, data={
                "email":"owner@example.test", "password":"test"
            }).status_code == 503
            assert "database" not in sys.modules
        """, with_credentials=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr or r.stdout)

    def test_short_crawler_key_does_not_shadow_valid_secret_key(self):
        env = os.environ.copy()
        env["CRAWLER_SETUP_MODE"] = "1"
        env["CRAWLER_SECRET_KEY"] = "short"
        env["SECRET_KEY"] = "a-secure-existing-secret-key-at-least-thirty-two-chars"
        env["SUPER_ADMIN_EMAIL"] = "owner@example.test"
        env["SUPER_ADMIN_PASSWORD"] = "unit-test-password"
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""
                import crawler_app
                assert crawler_app._credentials_ready
                assert crawler_app._session_key_mode == "stable"\n                assert len(crawler_app.app.secret_key) == 64
                c = crawler_app.app.test_client()
                response = c.post("/login", base_url="https://crawler.example.test",
                                  headers={"Origin":"https://crawler.example.test"},
                                  data={"email":"owner@example.test",
                                        "password":"unit-test-password"})
                assert response.status_code == 302
            """)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_login_shows_precise_missing_settings(self):
        r = run_isolated("""
            import crawler_app
            c = crawler_app.app.test_client()
            response = c.get("/login", base_url="https://crawler.example.test")
            assert response.status_code == 200
            assert b"SUPER_ADMIN_EMAIL" in response.data
            assert b"SUPER_ADMIN_PASSWORD" in response.data
        """, with_credentials=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr or r.stdout)

    def test_existing_admin_credentials_no_long_secret_can_log_in(self):
        r = run_isolated("""
            import sys
            import crawler_app
            assert crawler_app._session_key_mode == "temporary"
            assert crawler_app._credentials_ready
            assert len(crawler_app.app.secret_key) == 64
            c = crawler_app.app.test_client()
            base = "https://crawler.example.test"
            assert c.get("/login", base_url=base).status_code == 200
            r = c.post("/login", base_url=base, headers={"Origin":base}, data={
                "email":"owner@example.test", "password":"unit-test-only-password"
            })
            assert r.status_code == 302
            page = c.get("/admin/automation", base_url=base)
            assert page.status_code == 200
            assert "自動化中心".encode("utf-8") in page.data
            assert "管理控制台".encode("utf-8") in page.data
            assert b"css/admin.css" in page.data
            assert "中國同事".encode("utf-8") not in page.data
            assert "BotFather Token".encode("utf-8") not in page.data
            assert b"/api/order-cloud" not in page.data
            assert c.get("/admin/setup", base_url=base).status_code == 302
            assert c.get("/ready", base_url=base).status_code == 503
            assert "database" not in sys.modules
        """, with_credentials=True, with_secret=False)
        self.assertEqual(r.returncode, 0, msg=r.stderr or r.stdout)

    def test_setup_login_without_touching_order_db(self):
        r = run_isolated("""
            import sys
            import crawler_app
            c = crawler_app.app.test_client()
            base = "https://crawler.example.test"
            assert c.get("/admin/setup", base_url=base).status_code == 302
            assert c.post("/login", base_url=base, headers={"Origin":base},
                          data={"email":"owner@example.test",
                                "password":"unit-test-only-password"}).status_code == 302
            result = c.get("/admin/automation", base_url=base)
            assert result.status_code == 200
            assert "自動化中心".encode() in result.data
            assert "安全設定模式".encode() in result.data
            assert "未讀取".encode() in result.data
            assert "中國同事".encode() not in result.data
            assert b"css/admin.css" in result.data
            assert c.get("/admin/setup", base_url=base).status_code == 302
            assert c.post("/admin/automation/bots", base_url=base,
                          data={"token":"should-not-be-sent"}).status_code == 503
            assert c.get("/ready", base_url=base).status_code == 503
            assert c.get("/share/abc", base_url=base).status_code == 404
            assert c.post("/api/order-cloud/sync/orders-fast-batch",
                          base_url=base).status_code == 404
            assert c.get("/api/aduana/health", base_url=base).status_code == 503
            assert "database" not in sys.modules
        """, with_credentials=True)
        self.assertEqual(r.returncode, 0, msg=r.stderr or r.stdout)


if __name__ == "__main__":
    unittest.main()
