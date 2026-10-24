"""Staging-only smoke test: real Oregon-to-Aduana POST, and countdown math.
No TiDB credentials and no production imports of Flask app.
"""
from datetime import date
from flask import Flask, jsonify
# Import the exact production module without importing unrelated ORDER/ZOFRI packages.
# In this staging environment DB access is deliberately forbidden.
import importlib.util
import pathlib
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo
fake_db = types.ModuleType("database")
def denied(*args, **kwargs):
    raise RuntimeError("No database access in isolated staging")
fake_db.execute_sql = denied
fake_db.get_db_connection = denied
sys.modules["database"] = fake_db
fake_utils = types.ModuleType("utils")
fake_utils.__path__ = []
sys.modules["utils"] = fake_utils
fake_time = types.ModuleType("utils.time_utils")
fake_time.get_chile_time_naive = lambda: datetime.now(ZoneInfo("America/Santiago")).replace(tzinfo=None)
sys.modules["utils.time_utils"] = fake_time
source = pathlib.Path(__file__).parents[1] / "services" / "aduana_free_time_service.py"
spec = importlib.util.spec_from_file_location("staging_aduana_service", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fetch_month, calculate, normalize_ship = module.fetch_month, module.calculate, module.normalize_ship

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
    with app.app_context():
        _check = verify().get_json()
    logging.warning("ADUANA_STAGING_TEST %s", json.dumps(_check, ensure_ascii=False))
except Exception as e:
    logging.exception("ADUANA_STAGING_TEST_FAILED %s", type(e).__name__)

@app.get("/verify")
def verify_cached():
    return jsonify(_check if "_check" in globals() else {"ok": False, "reason":"staging smoke failed"})


@app.get("/preview")
def preview():
    """Render unchanged mobile report template with fake data; no TiDB."""
    from flask import render_template_string
    from jinja2 import Environment, FileSystemLoader
    template_dir = pathlib.Path(__file__).parents[1] / "templates" / "reports"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("iti_telegram_report.html")
    normal = calculate("20/10/2026", 14, at=date(2026,10,31))
    custom = calculate("20/10/2026", 21, at=date(2026,10,31),entrega="08/11/2026")
    def group(ship, eta, n, matched, free=None):
        return {"nave":ship,"count":n,"eta":eta,"ship_timer":calculate(eta, at=date(2026,10,31)),
                "contenedores":[]}
    m=group("MSC IKARIA VI","20/10/2026",2,True)
    m["contenedores"]=[
        {"folio":"115","contenedor":"TXGU5436783","fecha_entrega":"24/10/2026 · 12:18",
         "estado":"CONTROLADO","manual_days":None,"delivery_risk":None},
        {"folio":"262","contenedor":"TGBU9874527","fecha_entrega":"08/11/2026 · 11:52",
         "estado":"CONTROLADO","manual_days":21,"delivery_risk":2},
    ]
    u1=group("MANZANILLO EXPRESS","24/10/2026",6,False)
    u1["contenedores"]=[{"contenedor":code,"estado":"VISADO","manual_days":None} for code in
        ["CAJU5973223","HAMU2343723","HLBU9941809","TEMU7551438","TLLU5363704","UETU6873190"]]
    u2=group("MSC TORONTO VIII","27/10/2026",3,False)
    u2["contenedores"]=[{"contenedor":code,"estado":"VISADO","manual_days":None} for code in
        ["MSGU5404705","MSGU5404726","MSGU5407833"]]
    html=template.render(company_name="XINGWANG",total_count=11,matched_count=2,unmatched_count=9,
        matched_groups=[m],unmatched_groups=[u1,u2],show_matched=True,show_unmatched=True,
        generated_date="31/10/2026",generated_time="14:47",api_key="",result_hash="")
    assert "Hoy: 31/10/2026 (Chile)" in html
    assert "08/11/2026" in html and "VISADO" in html and "CONTROLADO" in html
    assert "21d" in html and "2 matched" in html and "6 contenedores" in html
    return html,200,{"Content-Type":"text/html; charset=utf-8"}


# Validate the exact shared HTML template on startup, without DB access.
try:
    with app.app_context():
        preview_html, preview_status, _ = preview()
        assert preview_status == 200 and "2 matched" in preview_html
        logging.warning("MONITOR_ORIGINAL_UI_TEMPLATE_OK size=%d matched=2 unmatched=9 custom=21d",len(preview_html))
except Exception:
    logging.exception("MONITOR_ORIGINAL_UI_TEMPLATE_FAILED")


# Whole integration syntax checks, without importing connected DB or auth services.
for _name in ("services/aduana_free_time_service.py","services/monitor_service.py",
              "blueprints/monitor_bp.py"):
    _path = pathlib.Path(__file__).parents[1] / _name
    compile(_path.read_text(encoding="utf-8"), str(_path), "exec")
logging.warning("MONITOR_INTEGRATION_PYTHON_COMPILE_OK files=3")


@app.get("/verify-november")
def verify_november():
    """Read-only real Aduana request to confirm cross-month parsing in Oregon."""
    try:
        rows = fetch_month(2026, 11)
        target = {k: [] for k in TARGET}
        for r in rows:
            for name in TARGET:
                if normalize_ship(r["ship_key"]) == normalize_ship(name):
                    target[name].append({"eta":r["eta"].isoformat(),"voyage":r["voyage"],
                                       "programacion":r["programacion"]})
        return jsonify(ok=True, month="2026-11", parsed_rows=len(rows), vessels=target)
    except Exception as exc:
        return jsonify(ok=False, month="2026-11", error_type=type(exc).__name__,
                       message=str(exc)[:200]), 502


try:
    _november_rows = fetch_month(2026, 11)
    logging.warning("ADUANA_NOVEMBER_REAL_CHECK parsed_rows=%d sample=%s",
                    len(_november_rows), 
                    [{"ship":x["ship_name"],"eta":x["eta"].isoformat()} for x in _november_rows[:3]])
except Exception as e:
    logging.warning("ADUANA_NOVEMBER_REAL_CHECK_FAILED %s: %s",type(e).__name__,str(e)[:160])
