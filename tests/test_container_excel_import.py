"""Safety regression tests for browser-selected Excel records, without production DB."""
import ast
import datetime
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "blueprints" / "container_excel_bp.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTIONS = {"_normalize_code", "_validate_records"}
nodes = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
assert len(nodes) == 2
ns = {"re": re, "date": datetime.date, "CODE_RE": re.compile(r"^[A-Z]{4}[0-9]{7}$"),
      "get_chile_time_naive": lambda: datetime.datetime(2026, 10, 27)}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(ROOT), "exec"), ns)

class ExcelValidationTests(unittest.TestCase):
    def base(self):
        return {"format": "xingwang-container-import-v1", "records": [
            {"loading_date": "2026-09-12",
             "loading_text": "26年09月12日 FRANCISCO一个柜",
             "container_no": "UETU 5792432", "remark": "德畅", "free_days": 21}
        ]}
    def test_normalization_and_full_a_text(self):
        records = ns["_validate_records"](self.base())
        self.assertEqual(records[0][0], "UETU5792432")
        self.assertEqual(records[0][2], "26年09月12日 FRANCISCO一个柜")
        self.assertEqual(records[0][4], 21)
    def test_missing_days_is_rejected(self):
        obj = self.base(); obj["records"][0]["free_days"] = None
        with self.assertRaises(ValueError): ns["_validate_records"](obj)
    def test_bad_code_is_rejected(self):
        obj = self.base(); obj["records"][0]["container_no"] = "UT 123"
        with self.assertRaises(ValueError): ns["_validate_records"](obj)
    def test_duplicate_code_is_rejected(self):
        obj = self.base()
        obj["records"].append(dict(obj["records"][0], loading_date="2026-09-14"))
        with self.assertRaises(ValueError): ns["_validate_records"](obj)
    def test_future_date_rejected(self):
        obj = self.base(); obj["records"][0]["loading_date"] = "2027-01-01"
        with self.assertRaises(ValueError): ns["_validate_records"](obj)

if __name__ == "__main__":
    unittest.main()
