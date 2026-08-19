"""End-to-end smoke test for the Render ORDER cloud API.

Windows CMD:
    set ORDER_SYNC_API_KEY=<same key configured in Render>
    python scripts/order_cloud_roundtrip_test.py

No TiDB/B2 credentials are needed on the client.
"""
import hashlib
import json
import os
import struct
import uuid
import zlib

import requests

BASE_URL = (os.environ.get("ORDER_CLOUD_BASE_URL") or "https://flask-393d.onrender.com").rstrip("/")
API_KEY = (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()


def fail(message, response=None):
    print("FAIL:", message)
    if response is not None:
        print("HTTP", response.status_code)
        print(response.text[:4000])
    raise SystemExit(1)


def make_png(seed_hex):
    """Create a valid unique 1x1 RGB PNG without external image libraries."""
    rgb = bytes(int(seed_hex[i:i + 2], 16) for i in (0, 2, 4))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"\x00" + rgb
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def main():
    if not API_KEY:
        fail("ORDER_SYNC_API_KEY environment variable is required")

    headers = {"X-Order-Sync-Key": API_KEY}
    json_headers = {**headers, "Content-Type": "application/json"}

    r = requests.get(f"{BASE_URL}/api/order-cloud/health", timeout=30)
    if r.status_code != 200:
        fail("health failed", r)
    health = r.json()
    if int(health.get("phase") or 0) < 3:
        fail("Render has not deployed phase 3 yet; wait for deploy and retry", r)
    print("0. phase 3 health OK")

    suffix = uuid.uuid4().hex[:8].upper()
    order_number = f"CLOUDTEST-{suffix}"
    customer_key = f"CLOUDTEST-CUSTOMER-{suffix}"
    workflow_number = f"{order_number}-01"

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

    r = requests.post(f"{BASE_URL}/api/order-cloud/sync/order", headers=json_headers, json=payload, timeout=30)
    if r.status_code != 200:
        fail("sync/order failed", r)
    print("1. sync/order OK")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str))

    r = requests.get(f"{BASE_URL}/api/order-cloud/debug/order/{order_number}", headers=headers, timeout=30)
    if r.status_code != 200:
        fail("debug/order failed", r)
    encoded = json.dumps(r.json(), ensure_ascii=False).lower()
    for forbidden in ("phone", "deposit", "notes", "factory", "secret should not store", "internal note should not store"):
        if forbidden in encoded:
            fail(f"forbidden cloud field leaked: {forbidden}", r)
    print("2. TiDB safe-field verification OK")

    png = make_png(suffix)
    sha256_hex = hashlib.sha256(png).hexdigest()

    r = requests.post(
        f"{BASE_URL}/api/order-cloud/assets/check",
        headers=json_headers,
        json={"sha256": sha256_hex, "content_type": "image/png"},
        timeout=30,
    )
    if r.status_code != 200:
        fail("asset/check failed", r)
    if (r.json().get("result") or {}).get("exists"):
        fail("fresh unique test image unexpectedly already exists", r)
    print("3. SHA-256 preflight reports image missing")

    files = {"file": ("+56-SECRET-PHONE-NAME.png", png, "image/png")}
    form = {"order_number": order_number, "workflow_key": workflow_number, "sha256": sha256_hex}
    r = requests.post(f"{BASE_URL}/api/order-cloud/assets/upload", headers=headers, files=files, data=form, timeout=30)
    if r.status_code != 200:
        fail("asset/upload failed", r)
    asset_result = (r.json() or {}).get("result") or {}
    asset_key = asset_result.get("asset_key")
    if not asset_key or asset_result.get("sha256") != sha256_hex:
        fail("asset/upload returned invalid metadata", r)
    if not asset_result.get("uploaded_to_b2"):
        fail("fresh test image was not uploaded to B2", r)
    print("4. image -> Render -> private B2 + TiDB metadata OK")

    r = requests.post(
        f"{BASE_URL}/api/order-cloud/assets/check",
        headers=json_headers,
        json={"sha256": sha256_hex, "content_type": "image/png"},
        timeout=30,
    )
    if r.status_code != 200 or not ((r.json().get("result") or {}).get("exists")):
        fail("asset/check did not find uploaded SHA-256", r)

    r = requests.post(
        f"{BASE_URL}/api/order-cloud/assets/register",
        headers=json_headers,
        json={"order_number": order_number, "workflow_key": workflow_number, "sha256": sha256_hex, "content_type": "image/png"},
        timeout=30,
    )
    if r.status_code != 200:
        fail("asset/register failed", r)
    dedupe = (r.json().get("result") or {})
    if not dedupe.get("deduplicated") or dedupe.get("uploaded_to_b2"):
        fail("existing SHA-256 was not reused", r)
    print("5. SHA-256 deduplication/reuse OK")

    r = requests.get(f"{BASE_URL}/api/order-cloud/debug/customer/{customer_key}", headers=headers, timeout=30)
    if r.status_code != 200:
        fail("debug/customer failed", r)
    encoded = json.dumps(r.json(), ensure_ascii=False).lower()
    if "+56-secret-phone-name" in encoded or "original_filename" in encoded:
        fail("original private filename leaked into cloud metadata", r)
    if sha256_hex not in encoded:
        fail("safe asset metadata missing from customer space", r)
    print("6. original filename is not stored; safe asset metadata present")

    r = requests.post(
        f"{BASE_URL}/api/order-cloud/share/create",
        headers=json_headers,
        json={"customer_key": customer_key, "expires_hours": 24},
        timeout=30,
    )
    if r.status_code != 200:
        fail("share/create failed", r)
    result = (r.json() or {}).get("result") or {}
    share_url = result.get("share_url")
    if not share_url:
        fail("share/create returned no share_url", r)
    print("7. share/create OK")
    print("SHARE_URL:", share_url)

    r = requests.get(share_url, timeout=30)
    if r.status_code != 200:
        fail("public share page failed", r)
    if order_number not in r.text or asset_key not in r.text:
        fail("public page did not render expected order/image", r)
    print("8. public share page contains private image reference")

    asset_url = f"{share_url}/asset/{asset_key}"
    r = requests.get(asset_url, timeout=30)
    if r.status_code != 200:
        fail("token-protected asset read failed", r)
    if hashlib.sha256(r.content).hexdigest() != sha256_hex:
        fail("downloaded B2 image hash mismatch", r)
    print("9. token -> Render -> private B2 image read OK")
    print("ROUNDTRIP PHASE 3 PASSED")


if __name__ == "__main__":
    main()
