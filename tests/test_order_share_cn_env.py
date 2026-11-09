"""Ensure the Render-managed China password and share URL need no TiDB auth lookup."""
import importlib.util
import os
import sys
import types
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "china_links_env_test", ROOT / "services/order_share_cn_access.py")
cn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cn)


class ChinaLinksRenderPasswordTests(unittest.TestCase):
    def setUp(self):
        cn._FAILURES.clear()
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        self.app.secret_key = "test-secret-that-is-at-least-32-characters"
        self.app.testing = True
        self.app.register_blueprint(cn.cn_bp)
        self.client = self.app.test_client()

    def test_six_digit_plaintext_render_setting_without_tidb(self):
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "123456"}), \
             patch.object(cn, "_db", side_effect=AssertionError("no auth database")):
            self.assertEqual(self.client.get("/cn/order-links").status_code, 200)
            self.assertEqual(self.client.post("/cn/order-links/login",
                             data={"password": "bad"}).status_code, 401)
            response = self.client.post("/cn/order-links/login",
                                        data={"password": "123456"})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(self.client.get("/cn/order-links").status_code, 200)

    def test_password_change_revokes_old_cookie(self):
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "123456"}):
            self.client.post("/cn/order-links/login", data={"password": "123456"})
            self.assertIn(b'id="search"', self.client.get("/cn/order-links").data)
            with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "654321"}):
                self.assertIn(b'name="password"', self.client.get("/cn/order-links").data)
                self.assertEqual(self.client.post("/cn/order-links/login",
                                  data={"password": "123456"}).status_code, 401)
                self.assertEqual(self.client.post("/cn/order-links/login",
                                  data={"password": "654321"}).status_code, 303)

    def test_logout_always_clears_cookie_and_redirects_to_password_page(self):
        # A stale/missing CSRF token previously stranded the user on a 403
        # instead of logging out. The logout action is cookie revocation only.
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "123456"}), \
             patch.object(cn, "_db", side_effect=AssertionError("no auth database")):
            response = self.client.post("/cn/order-links/login",
                                        data={"password": "123456"})
            self.assertEqual(response.status_code, 303)
            self.assertIn(b'id="search"', self.client.get("/cn/order-links").data)
            response = self.client.post("/cn/order-links/logout",
                                        data={"csrf": "expired-or-invalid"})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["Location"], "/cn/order-links")
            self.assertIn("xingwang_cn_links=", response.headers.get("Set-Cookie", ""))
            self.assertIn(b'name="password"',
                          self.client.get("/cn/order-links").data)
            # The directory imports the Telegram module before auth checks.
            # Stub only that import, not the real authorization branch.
            lookup_stub = types.SimpleNamespace(order_share_telegram_bot=None)
            with patch.dict(sys.modules, {"services": lookup_stub}):
                self.assertEqual(self.client.get("/cn/order-links/data").status_code, 403)

            # Re-login works, and even a missing token must not trap the user.
            self.client.post("/cn/order-links/login", data={"password": "123456"})
            response = self.client.post("/cn/order-links/logout", data={})
            self.assertEqual(response.status_code, 303)
            self.assertIn(b'name="password"',
                          self.client.get("/cn/order-links").data)

    def test_hash_setting_and_missing_secret(self):
        hashed = generate_password_hash("long-and-safe-secret", method="pbkdf2:sha256:600000")
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": hashed}):
            self.assertEqual(self.client.post("/cn/order-links/login",
                             data={"password": "long-and-safe-secret"}).status_code, 303)
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": ""}):
            self.assertEqual(self.client.get("/cn/order-links").status_code, 503)

    def test_rate_limit_and_no_legacy_admin_password_post(self):
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "123456"}):
            for _ in range(8):
                self.assertEqual(self.client.post("/cn/order-links/login",
                                 data={"password": "wrong"}).status_code, 401)
            self.assertEqual(self.client.post("/cn/order-links/login",
                             data={"password": "123456"}).status_code, 429)
            self.assertEqual(self.client.post("/admin/automation/china-links",
                             data={"password": "123456"}).status_code, 405)

    def test_qr_is_self_hosted_and_contains_no_password_text(self):
        with patch.dict(os.environ, {"CN_ORDER_LINKS_PASSWORD_HASH": "123456"}):
            qr = self.client.get("/cn/order-links/qr.svg")
            self.assertEqual(qr.status_code, 200)
            self.assertIn("image/svg+xml", qr.content_type)
            self.assertIn(b"<svg", qr.data)
            self.assertNotIn(b"123456", qr.data)
            self.assertIn(b"qr.svg", self.client.get("/cn/order-links").data)


if __name__ == "__main__":
    unittest.main()
