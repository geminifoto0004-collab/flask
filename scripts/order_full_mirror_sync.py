#!/usr/bin/env python3
"""Mirror the complete ORDER SQLite database schema/data to Render/TiDB.

Only SQLite contents are read. External upload/image/PDF files are never opened or
sent.  The Render ORDER code can therefore use the same logical tables on WAN while
local attachment areas remain empty.
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


def _table_indexes(conn: sqlite3.Connection, table_name: str):
    result = []
    for row in conn.execute(f'PRAGMA index_list("{table_name}")').fetchall():
        d = dict(row)
        index_name = str(d.get('name') or '').strip()
        if not index_name:
            continue
        cols = []
        try:
            for c in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall():
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


def _dump_tables(conn: sqlite3.Connection):
    rows = conn.execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name"""
    ).fetchall()
    tables = []
    total_rows = 0
    for row in rows:
        name = str(row[0] or '').strip()
        if not name:
            continue
        cols_raw = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
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
        quoted = ','.join('"' + n.replace('"', '""') + '"' for n in col_names)
        data_rows = []
        for data in conn.execute(f'SELECT {quoted} FROM "{name}"').fetchall():
            data_rows.append([_encode_value(data[n]) for n in col_names])
        total_rows += len(data_rows)
        tables.append({
            'name': name,
            'columns': columns,
            'indexes': _table_indexes(conn, name),
            'rows': data_rows,
        })
    tables.sort(key=lambda t: t['name'])
    return tables, total_rows


def _source_watermark(conn: sqlite3.Connection):
    candidates = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    names = ('updated_at', 'created_at', 'status_updated_at', 'action_date', 'order_date', 'visit_date')
    for table in tables:
        cols = {str(r['name']) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
        for col in names:
            if col not in cols:
                continue
            try:
                row = conn.execute(
                    f'SELECT MAX(CAST("{col}" AS TEXT)) FROM "{table}" WHERE "{col}" IS NOT NULL'
                ).fetchone()
                if row and row[0] is not None:
                    value = str(row[0]).strip()
                    if value:
                        candidates.append(value)
            except Exception:
                pass
    return max(candidates) if candidates else None


def _canonical_hash(tables):
    raw = json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _request_json(session, method, path, *, body=None, timeout=300):
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


def main():
    ap = argparse.ArgumentParser(description='Mirror complete ORDER SQLite into TiDB')
    ap.add_argument('--db', help='explicit tracking.db path')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    db = one._discover_db(args.db)
    conn = one._open_read_only(db)
    try:
        tables, total_rows = _dump_tables(conn)
        watermark = _source_watermark(conn)
    finally:
        conn.close()

    snapshot_hash = _canonical_hash(tables)
    body = {
        'version': 1,
        'snapshot_hash': snapshot_hash,
        'source_watermark': watermark,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'force': bool(args.force),
        'tables': tables,
    }
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
    gz = gzip.compress(raw, compresslevel=6)

    print(f'ORDER SQLite: {db}')
    print(f'Tables: {len(tables)} | rows: {total_rows}')
    print(f'Full JSON: {len(raw) / 1024 / 1024:.2f} MB | gzip: {len(gz) / 1024 / 1024:.2f} MB')
    print(f'Snapshot HASH: {snapshot_hash}')
    print(f'Source watermark: {watermark or "(none)"}')
    print('External images/PDF/upload files: NOT READ / NOT SENT')

    if args.dry_run:
        print('DRY RUN OK')
        return 0

    with requests.Session() as session:
        state_body = _request_json(session, 'GET', '/api/order-cloud/sync/full-mirror-state')
        state = state_body.get('result') or {}
        if str(state.get('snapshot_hash') or '') == snapshot_hash and not args.force:
            print('TiDB full ORDER mirror: SAME HASH -> no rebuild')
            return 0

        result_body = _request_json(
            session,
            'POST',
            '/api/order-cloud/sync/full-mirror',
            body=body,
            timeout=300,
        )
        result = result_body.get('result') or {}
        if result.get('stale'):
            print('TiDB full ORDER mirror: NOT UPDATED (source is older than cloud)')
            print(f"Local watermark: {result.get('source_watermark')}")
            print(f"Cloud watermark: {result.get('cloud_watermark')}")
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
