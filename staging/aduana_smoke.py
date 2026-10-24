"""Staging-only smoke test: real Oregon-to-Aduana POST, and countdown math.
No TiDB credentials and no production imports of Flask app.
"""
from datetime import date
from flask import Flask, jsonify
from services.aduana_free_time_service import fetch_month, calculate, normalize_ship

app = Flask(__name__)
TARGET = ("MSC IKARIA VI", "MANZANILLO EXPRESS", "MSC TORONTO VIII")


@app.get("/")
def index():
    return jsonify(service="aduana-monitor-staging", status="ok", routes=["/verify"])


def verify():
    checks = {}
    checks["14_days_oct31"] = calculate("20/10/2026", at=date(2026, 10, 31))
    checks["21_days_oct31"] = calculate("20/10/2026", days=21, at=date(2026, 10, 31))
    checks["21_days_delivery"] = calculate("20/10/2026", days=21,
                                          at=date(2026, 10, 31), entrega="08/11/2026")
    assert checks["14_days_oct31"]["remaining"] == 3
    assert checks["21_days_oct31"]["remaining"] == 10
    assert checks["21_days_delivery"]["delivery_remaining"] == 2
    assert checks["21_days_delivery"]["delivery_warning"] is True
    # Live read-only query from Oregon (same region as the official Render service).
    rows = fetch_month(2026, 10)
    matched = {}
    for target in TARGET:
        matched[target] = [
            {"ship": r["ship_name"], "voyage": r["voyage"], "eta": r["eta"].isoformat(),
             "ata": r["ata"], "programacion": r["programacion"]}
            for r in rows if normalize_ship(r["ship_key"]) == normalize_ship(target)]
    return jsonify(ok=True, fetched_rows=len(rows), vessels=matched, tests=checks)


# Run once as the isolated staging worker starts; log verified values, not secrets.
import json
import logging
try:
    _check = verify().get_json()
    logging.warning("ADUANA_STAGING_TEST %s", json.dumps(_check, ensure_ascii=False))
except Exception as e:
    logging.exception("ADUANA_STAGING_TEST_FAILED %s", type(e).__name__)

@app.get("/verify")
def verify_cached():
    return jsonify(_check if "_check" in globals() else {"ok": False, "reason":"staging smoke failed"})
