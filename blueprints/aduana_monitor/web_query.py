# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import date
from functools import wraps

from flask import redirect, render_template, request, session, url_for
from config import admin_config

from . import aduana_bp, query, settings


def _admin_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        allowed_roles = {"admin", admin_config.SUPER_ADMIN_ROLE}
        if not session.get("logged_in") or session.get("role") not in allowed_roles:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


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


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/query", methods=["GET", "POST"])
@_admin_login_required
def admin_query():
    current_year = date.today().year
    primary_years = [current_year, current_year - 1, current_year - 2]
    older_years = list(range(current_year - 3, settings.UNLIMITED_START_YEAR - 1, -1))
    available_years = primary_years + older_years

    selected_years = primary_years.copy() if request.method == "GET" else []
    aduana = "7"
    rut = ""
    rows = []
    logs = []
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
        columns=WEB_COLUMNS,
        searched=searched,
        all_ok=all_ok,
        message=message,
        elapsed=elapsed,
    )
