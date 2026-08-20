#!/usr/bin/env python3
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'scripts' / 'order_full_mirror_sync.py'
text = path.read_text('utf-8')
original = text

anchor = "DEFAULT_CHUNK_ROWS = 5000\nMAX_CHUNK_ROWS = 20000\n"
replacement = "DEFAULT_CHUNK_ROWS = 5000\nMAX_CHUNK_ROWS = 20000\n# Keep the notifications table schema on WAN so the shared ORDER code never\n# hits a missing-table error, but do not mirror its high-volume historical rows.\nSCHEMA_ONLY_TABLES = {'notifications'}\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('constants anchor not found')
    text = text.replace(anchor, replacement, 1)

anchor = "    tables = []\n    total_rows = 0\n    for row in rows:\n"
replacement = "    tables = []\n    total_rows = 0\n    skipped_rows = {}\n    for row in rows:\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('dump init anchor not found')
    text = text.replace(anchor, replacement, 1)

old = """        col_names = [c['name'] for c in columns]\n        quoted = ','.join(_quote_ident(n) for n in col_names)\n        select_sql = f'SELECT {quoted} FROM {_quote_ident(name)}' + _row_order_sql(columns)\n        try:\n            source_rows = conn.execute(select_sql).fetchall()\n        except sqlite3.DatabaseError:\n            source_rows = conn.execute(f'SELECT {quoted} FROM {_quote_ident(name)}').fetchall()\n\n        data_rows = [[_encode_value(data[n]) for n in col_names] for data in source_rows]\n"""
new = """        col_names = [c['name'] for c in columns]\n        quoted = ','.join(_quote_ident(n) for n in col_names)\n\n        if name in SCHEMA_ONLY_TABLES:\n            count_row = conn.execute(f'SELECT COUNT(*) FROM {_quote_ident(name)}').fetchone()\n            skipped_rows[name] = int(count_row[0] or 0) if count_row else 0\n            source_rows = []\n        else:\n            select_sql = f'SELECT {quoted} FROM {_quote_ident(name)}' + _row_order_sql(columns)\n            try:\n                source_rows = conn.execute(select_sql).fetchall()\n            except sqlite3.DatabaseError:\n                source_rows = conn.execute(f'SELECT {quoted} FROM {_quote_ident(name)}').fetchall()\n\n        data_rows = [[_encode_value(data[n]) for n in col_names] for data in source_rows]\n"""
if new not in text:
    if old not in text:
        raise RuntimeError('row load anchor not found')
    text = text.replace(old, new, 1)

anchor = "    tables.sort(key=lambda t: t['name'])\n    return tables, total_rows\n"
replacement = "    tables.sort(key=lambda t: t['name'])\n    return tables, total_rows, skipped_rows\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('dump return anchor not found')
    text = text.replace(anchor, replacement, 1)

anchor = "    for table in tables:\n        cols = {str(r['name']) for r in conn.execute(f'PRAGMA table_info({_quote_ident(table)})').fetchall()}\n"
replacement = "    for table in tables:\n        if table in SCHEMA_ONLY_TABLES:\n            continue\n        cols = {str(r['name']) for r in conn.execute(f'PRAGMA table_info({_quote_ident(table)})').fetchall()}\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('watermark anchor not found')
    text = text.replace(anchor, replacement, 1)

anchor = "        tables, total_rows = _dump_tables(conn)\n        watermark = _source_watermark(conn)\n"
replacement = "        tables, total_rows, skipped_rows = _dump_tables(conn)\n        watermark = _source_watermark(conn)\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('main unpack anchor not found')
    text = text.replace(anchor, replacement, 1)

anchor = "    print('External images/PDF/upload files: NOT READ / NOT SENT')\n    print(f'Transport: chunked ({args.chunk_rows} rows/request)')\n"
replacement = "    print('External images/PDF/upload files: NOT READ / NOT SENT')\n    for table_name, count in sorted(skipped_rows.items()):\n        print(f'{table_name}: schema only | {count} SQLite rows NOT uploaded')\n    print(f'Transport: chunked ({args.chunk_rows} rows/request)')\n"
if replacement not in text:
    if anchor not in text:
        raise RuntimeError('diagnostic print anchor not found')
    text = text.replace(anchor, replacement, 1)

if text != original:
    path.write_text(text, 'utf-8')

py_compile.compile(str(path), doraise=True)
print('notification schema-only mirror patch', 'applied' if text != original else 'already present')
