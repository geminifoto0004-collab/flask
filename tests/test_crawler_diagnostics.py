"""TiDB connection diagnostic tests without network or credentials."""
import unittest

from crawler_db_bootstrap import _safe_error_category


class TiDBDiagnosticsTest(unittest.TestCase):
    def test_authentication_failure(self):
        err = RuntimeError("No TiDB target is reachable")
        err.__cause__ = Exception(1045, "Access denied (fake credential not leaked)")
        typ, detail, code = _safe_error_category(err)
        self.assertEqual((typ, code), ("auth", 1045))
        self.assertNotIn("fake credential", detail)

    def test_unknown_database(self):
        err = Exception(1049, "Unknown database")
        typ, _, code = _safe_error_category(err)
        self.assertEqual((typ, code), ("database_missing", 1049))

    def test_network_failure(self):
        err = Exception(2003, "Can't connect to MySQL server")
        typ, _, code = _safe_error_category(err)
        self.assertEqual((typ, code), ("network", 2003))

    def test_missing_config(self):
        typ, _, _ = _safe_error_category(RuntimeError("No TiDB target is configured"))
        self.assertEqual(typ, "config")

    def test_schema_incomplete(self):
        typ, _, _ = _safe_error_category(RuntimeError("Crawler schema incomplete: tables=users"))
        self.assertEqual(typ, "schema")


if __name__ == "__main__":
    unittest.main()
