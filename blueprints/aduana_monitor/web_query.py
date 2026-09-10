# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import date

import requests
from flask import jsonify, render_template, request

from . import aduana_bp, query, settings


def _normalize_rut(value):
    compact = re.sub(r"[^0-9Kk]", "", str(value or "")).upper()
    if len(compact) not in (8, 9) or not compact[:-1].isdigit():
        raise ValueError("RUT inválido")
    return compact[:-1] + "-" + compact[-1]


WEB_COLUMNS = [
    ("n_denuncia", "N° Denuncia"),
    ("emision", "Emisión"),
    ("notificacion", "Notificación"),
    ("doc_aduanero", "Doc. Aduanero"),
    ("art_infraccion", "Art. Infracción"),
    ("infractor", "Infractor"),
    ("multa_max_legal", "Multa Max. Legal"),
    ("multa_c_allan", "Multa c/Allan."),
    ("multa_s_allan", "Multa s/Allan."),
    ("venc_allan", "Venc. Allan."),
    ("venc_recl_junta", "Venc. Recl. Junta"),
    ("audiencia", "Audiencia"),
    ("n_despacho", "N° Despacho"),
    ("aduana_nombre", "Aduana"),
]


def _failure_examples(logs, limit=4):
    examples = []
    seen = set()
    for item in logs or []:
        if str(item.get("estado") or "").upper() == "OK":
            continue
        error = " ".join(str(item.get("error") or "sin detalle").split())
        key = (str(item.get("estado") or ""), str(item.get("phase") or ""), error)
        if key in seen:
            continue
        seen.add(key)
        examples.append({
            "estado": item.get("estado") or "ERROR",
            "error": error,
            "desde": item.get("desde") or "",
            "hasta": item.get("hasta") or "",
            "worker": item.get("worker") or "",
            "phase": item.get("phase") or "",
        })
        if len(examples) >= limit:
            break
    return examples


# Public query page. No XINGWANG/admin login is required.
# Keep the old admin-prefixed URL as an alias so existing links/bookmarks do not break.
@aduana_bp.route("/aduana", methods=["GET", "POST"])
@aduana_bp.route(f"{settings.ADMIN_PREFIX}/query", methods=["GET", "POST"])
def admin_query():
    current_year = date.today().year
    primary_years = [current_year, current_year - 1, current_year - 2]
    older_years = list(range(current_year - 3, settings.UNLIMITED_START_YEAR - 1, -1))
    available_years = primary_years + older_years

    # Fast/simple default: current year only. Older years stay available, but
    # opening the page must not automatically launch a 3-year query selection.
    selected_years = [current_year] if request.method == "GET" else []
    aduana = "7"
    rut = ""
    rows = []
    logs = []
    failure_examples = []
    searched = False
    all_ok = True
    message = ""
    elapsed = None

    if request.method == "POST":
        searched = True
        aduana = str(request.form.get("aduana") or "7").strip()
        rut_input = str(request.form.get("rut") or "").strip()

        for raw in request.form.getlist("years"):
            try:
                year = int(raw)
            except Exception:
                continue
            if year in available_years:
                selected_years.append(year)
        selected_years = sorted(set(selected_years), reverse=True)

        try:
            if not selected_years:
                raise ValueError("至少選擇一個年份")
            if aduana not in settings.ADUANA_CODES:
                raise ValueError("請選擇 Aduana")
            rut = _normalize_rut(rut_input)

            started = time.perf_counter()
            rows, logs, all_ok = query.query_years(selected_years, aduana, rut)
            elapsed = round(time.perf_counter() - started, 2)
            failure_examples = _failure_examples(logs)

            failed = sum(1 for item in logs if item.get("estado") != "OK")
            if all_ok:
                message = f"查詢完成，共 {len(rows)} 筆。"
            else:
                message = f"查詢完成，共 {len(rows)} 筆；{failed} 個月份查詢失敗。"
        except Exception as exc:
            all_ok = False
            message = str(exc)
            rut = rut_input

    return render_template(
        "aduana_admin/query.html",
        primary_years=primary_years,
        older_years=older_years,
        selected_years=selected_years,
        aduanas=settings.ADUANAS,
        aduana=aduana,
        aduana_label=settings.ADUANA_LABELS.get(aduana, aduana),
        rut=rut,
        rows=rows,
        logs=logs,
        failure_examples=failure_examples,
        columns=WEB_COLUMNS,
        searched=searched,
        all_ok=all_ok,
        message=message,
        elapsed=elapsed,
    )


# Temporary, no-signup proxy connectivity probe.
# IMPORTANT: this only requests the public Aduana landing page; it never sends a RUT.
# The proxy is an open Chile HTTP proxy published by Geonode and is deliberately
# not used by Telegram, cron, or the real query flow.
@aduana_bp.route("/aduana/proxy-test-public", methods=["GET"])
def proxy_test_public():
    proxy_url = "http://45.225.204.11:999"
    started = time.perf_counter()
    try:
        response = requests.get(
            settings.BASE_URL,
            headers=settings.HEADERS,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=6,
            allow_redirects=True,
        )
        elapsed = round(time.perf_counter() - started, 2)
        text = response.text or ""
        return jsonify({
            "ok": response.status_code == 200 and "P1_FECHA_DESDE" in text,
            "status_code": response.status_code,
            "elapsed_seconds": elapsed,
            "final_url": response.url,
            "aduana_form_found": "P1_FECHA_DESDE" in text,
            "response_bytes": len(response.content or b""),
            "note": "Public proxy probe only; no RUT was sent.",
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "note": "Public proxy probe only; no RUT was sent.",
        }), 502
