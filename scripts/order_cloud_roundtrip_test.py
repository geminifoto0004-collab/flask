"""End-to-end smoke test for the Render ORDER cloud API.

Usage (Windows PowerShell):
    $env:ORDER_SYNC_API_KEY="<same key configured in Render>"
    python scripts/order_cloud_roundtrip_test.py

No TiDB/B2 credentials are needed on the client.
"""
import json
import os
import sys
import uuid

import requests

BASE_URL = (os.environ.get("ORDER_CLOUD_BASE_URL") or "https://flask-393d.onrender.com").rstrip("/")
API_KEY = (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()


def fail(message, response=None):
    print("FAIL:", message)
    if response is not None:
        print("HTTP", response.status_code)
        print(response.text[:4000])
    raise SystemExit(1)


def main():
    if not API_KEY:
        fail("ORDER_SYNC_API_KEY environment variable is required")

    headers = {"X-Order-Sync-Key": API_KEY, "Content-Type": "application/json"}
    suffix = uuid.uuid4().hex[:8].upper()
    order_number = f"CLOUDTEST-{suffix}"
    customer_key = f"CLOUDTEST-CUSTOMER-{suffix}"
    workflow_number = f"{order_number}-01"

    # Deliberately contains forbidden fields. Render must ignore them.
    payload = {
        "order_number": order_number,
        "customer_key": customer_key,
        "customer_name": "CLIENTE PRUEBA CLOUD",
        "order_date": "2026-08-19",
        "current_status": "PRODUCTION",
        "production_type": "Cortina",
        "product_name": "CORTINA TEST",
        "product_code": "TEST-01",
        "pattern_code": "P-01",
        "quantity": "1200",
        "expected_delivery_date": "2026-09-15",
        "phone": "+56 SECRET SHOULD NOT STORE",
        "deposit": "SECRET SHOULD NOT STORE",
        "notes": "INTERNAL NOTE SHOULD NOT STORE",
        "source_site": "FAKE-CLIENT-SOURCE",
        "workflows": [
            {
                "workflow_number": workflow_number,
                "current_status": "PRODUCTION",
                "production_type": "Cortina",
                "product_name": "CORTINA TEST",
                "product_code": "TEST-01",
                "quantity": "1200",
                "expected_delivery_date": "2026-09-15",
                "notes": "WORKFLOW INTERNAL NOTE SHOULD NOT STORE",
                "factory": "INTERNAL FACTORY SHOULD NOT STORE",
                "timeline": [
                    {"id": f"{workflow_number}-H1", "to_status": "NEW_ORDER", "action_date": "2026-08-19"},
                    {"id": f"{workflow_number}-H2", "to_status": "PRODUCTION", "action_date": "2026-08-20", "notes": "HISTORY NOTE SHOULD NOT STORE"},
                ],
            }
        ],
    }

    r = requests.post(f"{BASE_URL}/api/order-cloud/sync/order", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        fail("sync/order failed", r)
    print("1. sync/order OK")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str))

    r = requests.get(f"{BASE_URL}/api/order-cloud/debug/order/{order_number}", headers={"X-Order-Sync-Key": API_KEY}, timeout=30)
    if r.status_code != 200:
        fail("debug/order failed", r)
    data = r.json()
    encoded = json.dumps(data, ensure_ascii=False).lower()
    for forbidden in ("phone", "deposit", "notes", "factory", "secret should not store", "internal note should not store"):
        if forbidden in encoded:
            fail(f"forbidden cloud field leaked: {forbidden}", r)
    print("2. TiDB safe-field verification OK")

    r = requests.post(
        f"{BASE_URL}/api/order-cloud/share/create",
        headers=headers,
        json={"customer_key": customer_key, "expires_hours": 24},
        timeout=30,
    )
    if r.status_code != 200:
        fail("share/create failed", r)
    result = (r.json() or {}).get("result") or {}
    share_url = result.get("share_url")
    if not share_url:
        fail("share/create returned no share_url", r)
    print("3. share/create OK")
    print("SHARE_URL:", share_url)

    r = requests.get(share_url, timeout=30)
    if r.status_code != 200:
        fail("public share page failed", r)
    if order_number not in r.text or "CLIENTE PRUEBA CLOUD" not in r.text:
        fail("public page did not render expected customer/order", r)
    print("4. public /share/<token> OK")
    print("ROUNDTRIP TEST PASSED")


if __name__ == "__main__":
    main()
