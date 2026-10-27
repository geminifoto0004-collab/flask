"""Feature PIN validation checks; no production DB access needed."""
import ast
import hashlib
import hmac
import os
import pathlib
import re
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "blueprints" / "container_excel_bp.py").read_text(encoding="utf-8")
tree = ast.parse(src)
names = {"_configured_pin", "_pin_signature", "_has_excel_access"}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(nodes) == 3

class MockApp:
    secret_key = "a-unit-test-secret"

class Session(dict):
    pass

fake_session = Session()
ns = {
    "os": os, "re": re, "hmac": hmac, "hashlib": hashlib, "time": time,
    "current_app": MockApp(), "session": fake_session,
    "PIN_TTL_SECONDS": 3600,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "pin_functions", "exec"), ns)

class PinTests(unittest.TestCase):
    def setUp(self):
        fake_session.clear()

    def test_one_to_six_digit_pin_supported(self):
        for candidate in ("0", "9", "12", "1234", "000001", "999999"):
            with self.subTest(candidate=candidate), patch.dict(os.environ, {"XINGWANG_EXCEL_PIN": candidate}):
                self.assertEqual(ns["_configured_pin"](), candidate)
        for candidate in ("", "1234567", "1a3", "12-34"):
            with self.subTest(candidate=candidate), patch.dict(os.environ, {"XINGWANG_EXCEL_PIN": candidate}):
                self.assertIsNone(ns["_configured_pin"]())

    def test_valid_session_is_scoped_and_expires(self):
        with patch.dict(os.environ, {"XINGWANG_EXCEL_PIN": "012345"}):
            fake_session["excel_pin_signature"] = ns["_pin_signature"]("012345")
            fake_session["excel_pin_granted_at"] = int(time.time()) - 120
            self.assertTrue(ns["_has_excel_access"]())
            fake_session["excel_pin_granted_at"] = int(time.time()) - 3700
            self.assertFalse(ns["_has_excel_access"]())

    def test_pin_rotation_revokes_previous_session(self):
        with patch.dict(os.environ, {"XINGWANG_EXCEL_PIN": "123456"}):
            fake_session["excel_pin_signature"] = ns["_pin_signature"]("123456")
            fake_session["excel_pin_granted_at"] = int(time.time())
            self.assertTrue(ns["_has_excel_access"]())
        with patch.dict(os.environ, {"XINGWANG_EXCEL_PIN": "654321"}):
            self.assertFalse(ns["_has_excel_access"]())

if __name__ == "__main__":
    unittest.main()
