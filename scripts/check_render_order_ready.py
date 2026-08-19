#!/usr/bin/env python3
"""Public smoke check for the Render-hosted read-only ORDER mount.

No login credentials or sync keys are required. This verifies that Render is alive,
the ORDER cloud/TiDB gateway initializes, and /order is actually mounted and sends
an unauthenticated browser to the existing login flow.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import requests

BASE_URL = (os.environ.get("ORDER_CLOUD_BASE_URL") or "https://flask-393d.onrender.com").rstrip("/")


def check_once() -> list[str]:
    problems = []

    try:
        r = requests.get(BASE_URL + "/api/order-cloud/health", timeout=(5, 30))
        data = r.json() if "json" in (r.headers.get("content-type") or "").lower() else {}
        if r.status_code != 200 or not data.get("ok"):
            problems.append(f"cloud health HTTP {r.status_code}: {data or r.text[:160]}")
        else:
            print("Render TiDB ORDER gateway: OK")
    except Exception as exc:
        problems.append(f"cloud health request failed: {type(exc).__name__}: {exc}")

    try:
        r = requests.get(BASE_URL + "/order", timeout=(5, 30), allow_redirects=False)
        location = r.headers.get("location") or ""
        if r.status_code not in (301, 302, 303, 307, 308):
            problems.append(f"/order expected login redirect, got HTTP {r.status_code}")
        elif "/login" not in location:
            problems.append(f"/order redirected somewhere unexpected: {location}")
        else:
            print("Render /order mount: OK")
    except Exception as exc:
        problems.append(f"/order request failed: {type(exc).__name__}: {exc}")

    try:
        r = requests.get(BASE_URL + "/tracking/", timeout=(5, 30), allow_redirects=False)
        location = r.headers.get("location") or ""
        if r.status_code not in (200, 301, 302, 303, 307, 308):
            problems.append(f"/tracking/ returned HTTP {r.status_code}")
        elif r.status_code != 200 and "/login" not in location:
            problems.append(f"/tracking/ redirect unexpected: {location}")
        else:
            print("Render ORDER blueprint: OK")
    except Exception as exc:
        problems.append(f"/tracking request failed: {type(exc).__name__}: {exc}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-seconds", type=int, default=0, help="poll until ready for up to this many seconds")
    ap.add_argument("--interval", type=int, default=15, help="poll interval while waiting")
    args = ap.parse_args()

    deadline = time.time() + max(0, int(args.wait_seconds))
    attempt = 0
    while True:
        attempt += 1
        if attempt > 1:
            print(f"Render readiness retry #{attempt}")
        problems = check_once()
        if not problems:
            print("RENDER ORDER READY")
            return 0
        if time.time() >= deadline:
            print("RENDER ORDER NOT READY", file=sys.stderr)
            for problem in problems:
                print(" - " + problem, file=sys.stderr)
            return 1
        time.sleep(max(3, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
