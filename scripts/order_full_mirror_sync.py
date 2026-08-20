#!/usr/bin/env python3
"""Mirror the complete ORDER SQLite database schema/data to Render/TiDB.

Only SQLite contents are read. External upload/image/PDF files are never opened or
sent. Large mirrors are transported in short gzip-compressed row chunks so Render
does not have to insert hundreds of thousands of rows inside one HTTP request.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
import sqlite3
import sys
from typing import Any

import requests

import order_cloud_sync_real_order as one

BASE_URL = (os.environ.get('ORDER_CLOUD_BASE_URL') or 'https://flask-393d.onrender.com').rstrip('/')
API_KEY = (os.environ.get('ORDER_SYNC_API_KEY') or '').strip()
DEFAULT_CHUNK_ROWS = 5000
MAX_CHUNK_ROWS = 20000
# Keep the notifications table schema on WAN so the shared ORDER code never
# hits a missing-table error, but do not mirror its high-volume historical rows.
SCHEMA_ONLY_TABLES = {'notifications'}


def _headers(extra=None):
    if not API_KEY:
        raise one.SyncError('ORDER_SYNC_API_KEY is not configured')
    result = {'X-Order-Sync-Key': API_KEY}
    result.update(extra or {})
    return result


def _encode_value(value: Any):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'__bytes__': base64.b64encode(bytes(value)).decode('ascii')}
    return value


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_indexes(conn: sqlite3.Connection, table_name: str):
    result = []
    for row in conn.execute(f'PRAGMA index_list({_quote_ident(table_name)})').fetchall():
        d = dict(row)
        index_name = str(d.get('name') or '').strip()
        if not index_name:
            continue
        cols = []
        try:
            for c in conn.execute(f'PRAGMA index_info({_quote_ident(index_name)})').fetchall():
                cd = dict(c)
                name = cd.get('name')
                if name:
                    cols.append(str(name))
        except Exception:
            cols = []
        if not cols:
            continue
        result.append({
            'name': index_name,
            'unique': bool(d.get('unique')),
            'origin': d.get('origin') or '',
            'partial': bool(d.get('partial')),
            'columns': cols,
        })
    result.sort(key=lambda x: (x.get('name') or '', x.get('columns') or []))
    return result


def _row_order_sql(columns):
    pk = []
    for col in columns:
        order = int(col.get('pk') or 0)
        if order > 0:
            pk.append((order, str(col.get('name') or '')))
    if pk:
        pk.sort()
        return ' ORDER BY ' + ','.join(_quote_ident(name) for _, name in pk)
    return ' ORDER BY rowid'


def _dump_tables(conn: sqlite3.Connection):
    rows = conn.execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name"""
    ).fetchall()
    tables = []
    total_rows = 0
    skipped_rows = {}
    for row in rows:
        name = str(row[0] or '').strip()
        if not name:
            continue
        cols_raw = conn.execute(f'PRAGMA table_info({_quote_ident(name)})').fetchall()
        columns = []
        for c in cols_raw:
            d = dict(c)
            columns.append({
                'name': str(d.get('name') or ''),
                'type': str(d.get('type') or ''),
                'notnull': bool(d.get('notnull')),
                'default': d.get('dflt_value'),
                'pk': int(d.get('pk') or 0),
            })
        if not columns:
            continue

        col_names = [c['name'] for c in columns]
        quoted = ','.join(_quote_ident(n) for n in col_names)

        if name in SCHEMA_ONLY_TABLES:
            count_row = conn.execute(f'SELECT COUNT(*) FROM {_quote_ident(name)}').fetchone()
            skipped_rows[name] = int(count_row[0] or 0) if count_row else 0
            source_rows = []
        else:
            select_sql = f'SELECT {quoted} FROM {_quote_ident(name)}' + _row_order_sql(columns)
            try:
                source_rows = conn.execute(select_sql).fetchall()
            except sqlite3.DatabaseError:
                source_rows = conn.execute(f'SELECT {quoted} FROM {_quote_ident(name)}').fetchall()

        data_rows = [[_encode_value(data[n]) for n in col_names] for data in source_rows]
        total_rows += len(data_rows)
        tables.append({
            'name': name,
            'columns': columns,
            'indexes': _table_indexes(conn, name),
            'rows': data_rows,
        })
    tables.sort(key=lambda t: t['name'])
    return tables, total_rows, skipped_rows


def _source_watermark(conn: sqlite3.Connection):
    candidates = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    names = ('updated_at', 'created_at', 'status_updated_at', 'action_date', 'order_date', 'visit_date')
    for table in tables:
        if table in SCHEMA_ONLY_TABLES:
            continue
        cols = {str(r['name']) for r in conn.execute(f'PRAGMA table_info({_quote_ident(table)})').fetchall()}
        for col in names:
            if col not in cols:
                continue
            try:
                row = conn.execute(
                    f'SELECT MAX(CAST({_quote_ident(col)} AS TEXT)) FROM {_quote_ident(table)} '
                    f'WHERE {_quote_ident(col)} IS NOT NULL'
                ).fetchone()
                if row and row[0] is not None:
                    value = str(row[0]).strip()
                    if value:
                        candidates.append(value)
            except Exception:
                pass
    return max(candidates) if candidates else None


def _canonical_hash(tables):
    raw = json.dumps(
        tables, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _request_json(session, method, path, *, body=None, timeout=120):
    kwargs = {'timeout': (10, timeout)}
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
        compressed = gzip.compress(raw, compresslevel=6)
        kwargs['data'] = compressed
        kwargs['headers'] = _headers({'Content-Type': 'application/json', 'Content-Encoding': 'gzip'})
    else:
        kwargs['headers'] = _headers()
    response = session.request(method, BASE_URL + path, **kwargs)
    try:
        data = response.json()
    except ValueError:
        data = {'raw': response.text[:1200]}
    if not response.ok or not data.get('ok'):
        raise one.SyncError(
            f'{method} {path} failed ({response.status_code}): ' + json.dumps(data, ensure_ascii=False)
        )
    return data


def _manifest(tables):
    return [{
        'name': table['name'],
        'columns': table['columns'],
        'indexes': table['indexes'],
        'expected_rows': len(table['rows']),
    } for table in tables]


def _print_stale(result):
    print('TiDB full ORDER mirror: NOT UPDATED (source is older than cloud)')
    print(f"Local watermark: {result.get('source_watermark')}")
    print(f"Cloud watermark: {result.get('cloud_watermark')}")


def main():
    ap = argparse.ArgumentParser(description='Mirror complete ORDER SQLite into TiDB')
    ap.add_argument('--db', help='explicit tracking.db path')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--chunk-rows', type=int, default=DEFAULT_CHUNK_ROWS,
                    help=f'rows per HTTP request (default {DEFAULT_CHUNK_ROWS}, max {MAX_CHUNK_ROWS})')
    args = ap.parse_args()
    if args.chunk_rows < 1 or args.chunk_rows > MAX_CHUNK_ROWS:
        ap.error(f'--chunk-rows must be between 1 and {MAX_CHUNK_ROWS}')

    db = one._discover_db(args.db)
    conn = one._open_read_only(db)
    try:
        tables, total_rows, skipped_rows = _dump_tables(conn)
        watermark = _source_watermark(conn)
    finally:
        conn.close()

    snapshot_hash = _canonical_hash(tables)
    manifest = _manifest(tables)
    diagnostic_body = {
        'version': 2,
        'snapshot_hash': snapshot_hash,
        'source_watermark': watermark,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'force': bool(args.force),
        'tables': tables,
    }
    raw = json.dumps(diagnostic_body, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
    gz = gzip.compress(raw, compresslevel=6)

    print(f'ORDER SQLite: {db}')
    print(f'Tables: {len(tables)} | rows: {total_rows}')
    print(f'Full JSON: {len(raw) / 1024 / 1024:.2f} MB | gzip: {len(gz) / 1024 / 1024:.2f} MB')
    print(f'Snapshot HASH: {snapshot_hash}')
    print(f'Source watermark: {watermark or "(none)"}')
    print('External images/PDF/upload files: NOT READ / NOT SENT')
    for table_name, count in sorted(skipped_rows.items()):
        print(f'{table_name}: schema only | {count} SQLite rows NOT uploaded')
    print(f'Transport: chunked ({args.chunk_rows} rows/request)')

    if args.dry_run:
        print('DRY RUN OK')
        return 0

    common = {
        'version': 2,
        'snapshot_hash': snapshot_hash,
        'source_watermark': watermark,
        'force': bool(args.force),
        'manifest': manifest,
    }

    with requests.Session() as session:
        state_body = _request_json(session, 'GET', '/api/order-cloud/sync/full-mirror-state')
        state = state_body.get('result') or {}
        if str(state.get('snapshot_hash') or '') == snapshot_hash and not args.force:
            print('TiDB full ORDER mirror: SAME HASH -> no rebuild')
            return 0

        begin_body = _request_json(
            session,
            'POST',
            '/api/order-cloud/sync/full-mirror/begin',
            body=common,
            timeout=120,
        )
        begin_result = begin_body.get('result') or {}
        if begin_result.get('stale'):
            _print_stale(begin_result)
            return 3
        if not begin_result.get('ready'):
            if begin_result.get('reason') == 'same_hash':
                print('TiDB full ORDER mirror: SAME HASH -> no rebuild')
                return 0
            raise one.SyncError('full mirror begin did not become ready: ' + json.dumps(begin_result, ensure_ascii=False))

        print('TiDB staging: READY')
        table_total = len(tables)
        for table_index, table in enumerate(tables, start=1):
            name = table['name']
            rows = table['rows']
            columns = [str(c.get('name') or '') for c in table['columns']]
            count = len(rows)
            if count == 0:
                print(f'[{table_index}/{table_total}] {name}: 0 rows')
                continue

            sent = 0
            while sent < count:
                chunk = rows[sent:sent + args.chunk_rows]
                _request_json(
                    session,
                    'POST',
                    '/api/order-cloud/sync/full-mirror/chunk',
                    body={
                        'snapshot_hash': snapshot_hash,
                        'table_name': name,
                        'columns': columns,
                        'rows': chunk,
                    },
                    timeout=120,
                )
                sent += len(chunk)
                print(f'[{table_index}/{table_total}] {name}: {sent}/{count}')

        print('All chunks uploaded; verifying and swapping TiDB tables...')
        result_body = _request_json(
            session,
            'POST',
            '/api/order-cloud/sync/full-mirror/finalize',
            body=common,
            timeout=120,
        )
        result = result_body.get('result') or {}
        if result.get('stale'):
            _print_stale(result)
            return 3
        if not result.get('changed'):
            print(f"TiDB full ORDER mirror: skipped ({result.get('reason') or 'no change'})")
            return 0

        print(
            'TIDB FULL ORDER MIRROR OK: '
            f"tables={result.get('tables')} rows={result.get('rows')} "
            f"committed_at={result.get('committed_at')}"
        )
        print('WAN uses the same ORDER tables/routes; local attachment bytes remain unavailable.')
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('ORDER full mirror cancelled', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f'ORDER FULL MIRROR ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(2)
