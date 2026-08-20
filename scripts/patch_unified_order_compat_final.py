#!/usr/bin/env python3
"""One-time hardening for unified SQLite/TiDB ORDER compatibility."""
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'order_tracking' / 'db_compat.py'
text = path.read_text('utf-8')
original = text

old = '''    text = re.sub(\n        r"ltrim\\(\\s*([^,\\)]+)\\s*,\\s*['\\\"]ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz['\\\"]\\s*\\)",\n        r"REGEXP_REPLACE(\\1, '^[A-Za-z]+', '')",\n        text,\n        flags=re.I,\n    )\n    text = re.sub(r"^\\s*BEGIN\\s+(IMMEDIATE|EXCLUSIVE)\\b", "START TRANSACTION", text, flags=re.I)\n'''
new = '''    text = re.sub(\n        r"ltrim\\(\\s*([^,\\)]+)\\s*,\\s*['\\\"]ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz['\\\"]\\s*\\)",\n        r"REGEXP_REPLACE(\\1, '^[A-Za-z]+', '')",\n        text,\n        flags=re.I,\n    )\n\n    # SQLite GLOB appears in ORDER's numeric-section filters. TiDB/MySQL uses\n    # REGEXP. The media-extension GLOB queries are intercepted separately because\n    # WAN deliberately exposes no local attachment bytes.\n    text = re.sub(\n        r"\\b([A-Za-z_][A-Za-z0-9_\\.]*)\\s+NOT\\s+GLOB\\s+['\\\"]\\[0-9\\]\\*['\\\"]",\n        r"\\1 NOT REGEXP '^[0-9]'",\n        text,\n        flags=re.I,\n    )\n    text = re.sub(\n        r"\\b([A-Za-z_][A-Za-z0-9_\\.]*)\\s+GLOB\\s+['\\\"]\\[0-9\\]\\*['\\\"]",\n        r"\\1 REGEXP '^[0-9]'",\n        text,\n        flags=re.I,\n    )\n\n    text = re.sub(r"^\\s*BEGIN\\s+(IMMEDIATE|EXCLUSIVE)\\b", "START TRANSACTION", text, flags=re.I)\n'''
if new not in text:
    if old not in text:
        raise RuntimeError('GLOB translation anchor not found')
    text = text.replace(old, new, 1)

old = '''        if 'count(' in low:\n            alias = 'count'\n            m = re.search(r"count\\s*\\([^\\)]*\\)\\s+(?:as\\s+)?([a-zA-Z_][\\w]*)", low)\n            if m:\n                alias = m.group(1)\n            self._set_rows([CompatRow({alias: 0})])\n        else:\n            self._set_rows([])\n        return True\n'''
new = '''        # A grouped count such as ``SELECT order_number, COUNT(*) ... GROUP BY``\n        # represents one row per local attachment owner. With no WAN attachment\n        # bytes the correct result is zero rows, not a synthetic row missing the\n        # grouping column. Scalar COUNT queries still receive one zero value.\n        if 'count(' in low and 'group by' not in low:\n            alias = 'count'\n            m = re.search(r"count\\s*\\([^\\)]*\\)\\s+(?:as\\s+)?([a-zA-Z_][\\w]*)", low)\n            if m:\n                alias = m.group(1)\n            self._set_rows([CompatRow({alias: 0})])\n        else:\n            self._set_rows([])\n        return True\n'''
if new not in text:
    if old not in text:
        raise RuntimeError('media grouped count anchor not found')
    text = text.replace(old, new, 1)

if text != original:
    path.write_text(text, 'utf-8')

py_compile.compile(str(path), doraise=True)

# Small deterministic translator smoke tests. These do not require TiDB.
import importlib.util
spec = importlib.util.spec_from_file_location('order_db_compat_smoke', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert "section REGEXP '^[0-9]'" in mod.translate_sqlite_sql("WHERE section GLOB '[0-9]*'")
assert "section NOT REGEXP '^[0-9]'" in mod.translate_sqlite_sql("WHERE section NOT GLOB '[0-9]*'")
assert '%s' in mod.translate_sqlite_sql("SELECT * FROM orders WHERE order_number=?")
print('unified ORDER compatibility hardening', 'applied' if text != original else 'already present')
