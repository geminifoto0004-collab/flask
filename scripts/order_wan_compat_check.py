#!/usr/bin/env python3
"""Call the protected Render ORDER compatibility smoke test."""
from __future__ import annotations

import json
import os
import sys

import requests

BASE_URL = (os.environ.get('ORDER_CLOUD_BASE_URL') or 'https://flask-393d.onrender.com').rstrip('/')
API_KEY = (os.environ.get('ORDER_SYNC_API_KEY') or '').strip()


def main():
    if not API_KEY:
        print('ORDER WAN COMPAT ERROR: ORDER_SYNC_API_KEY is not configured', file=sys.stderr)
        return 2
    try:
        response = requests.get(
            BASE_URL + '/api/order-cloud/sync/compat-check',
            headers={'X-Order-Sync-Key': API_KEY},
            timeout=(10, 120),
        )
    except Exception as exc:
        print(f'ORDER WAN COMPAT ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2

    try:
        payload = response.json()
    except ValueError:
        print(f'ORDER WAN COMPAT ERROR: HTTP {response.status_code}: {response.text[:1200]}', file=sys.stderr)
        return 2

    if not response.ok or not payload.get('ok'):
        print('ORDER WAN COMPAT ERROR: ' + json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    result = payload.get('result') or {}
    print(f"ORDER TiDB database: {result.get('order_database')}")
    state = result.get('mirror_state') or {}
    print(
        'Mirror: '
        f"tables={state.get('table_count')} rows={state.get('row_count')} "
        f"committed_at={state.get('committed_at')}"
    )

    for name in ('raw_tidb_counts', 'runtime_flags', 'compat_wrapper_smoke', 'exact_home_loader'):
        step = result.get(name) or {}
        if step.get('ok'):
            print(f"[OK] {name} ({step.get('ms')} ms): {json.dumps(step.get('value'), ensure_ascii=False)}")
        else:
            print(
                f"[FAIL] {name} ({step.get('ms')} ms): "
                f"{step.get('error_type')}: {step.get('error')}"
            )

    print('OVERALL:', 'OK' if result.get('overall_ok') else 'FAILED')
    return 0 if result.get('overall_ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
