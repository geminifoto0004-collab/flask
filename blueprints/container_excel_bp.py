"""Admin-only browser-parsed A/C/F/H Excel import for ITI Monitor.

No Excel bytes reach the server; only explicitly selected normalized records.
Keeps this dataset separate from ITI, Aduana and manually assigned free time.
"""
from __future__ import annotations

import logging
import re
import os
import secrets
import hmac
import hashlib
import time
import threading
from collections import deque
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, current_app

from config import config
from database import get_db_connection, get_db_connection_for_target
from tidb_targets import preferred_target, target_configured, mirror_enabled
from utils.time_utils import get_chile_time_naive

LOG = logging.getLogger(__name__)
container_excel_bp = Blueprint("container_excel", __name__)
TABLE = "monitor_excel_container_days"
CODE_RE = re.compile(r"^[A-Z]{4}[0-9]{7}$")
CREATE_TABLE = """CREATE TABLE IF NOT EXISTS monitor_excel_container_days (
    container_no VARCHAR(20) NOT NULL,
    loading_date DATE NOT NULL,
    loading_text TEXT NOT NULL,
    remark TEXT NOT NULL,
    free_days SMALLINT NOT NULL,
    imported_by VARCHAR(120) NOT NULL DEFAULT '',
    imported_at DATETIME NOT NULL,
    PRIMARY KEY (container_no, loading_date),
    INDEX idx_excel_loading_date (loading_date)
)"""
UPSERT = """INSERT INTO monitor_excel_container_days
 (container_no, loading_date, loading_text, remark, free_days, imported_by, imported_at)
 VALUES (?,?,?,?,?,?,?)
 ON DUPLICATE KEY UPDATE loading_text=VALUES(loading_text),
 remark=VALUES(remark), free_days=VALUES(free_days),
 imported_by=VALUES(imported_by), imported_at=VALUES(imported_at)"""


# This scoped PIN never grants any main-site administrator permissions.
PIN_TTL_SECONDS = 3600
PIN_WINDOW_SECONDS = 900
PIN_GLOBAL_FAILURE_LIMIT = 24
PIN_CLIENT_FAILURE_LIMIT = 4
_PIN_FAILURES = deque()
_PIN_CLIENT_FAILURES = {}
_PIN_LOCK = threading.Lock()


def _configured_pin():
    pin = (os.environ.get("XINGWANG_EXCEL_PIN") or "").strip()
    return pin if re.fullmatch(r"[0-9]{1,6}", pin) else None


def _pin_signature(pin):
    secret = current_app.secret_key
    secret = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
    return hmac.new(secret, b"container_excel_access_v1:" + pin.encode("ascii"),
                    hashlib.sha256).hexdigest()


def _has_excel_access():
    if session.get("logged_in") and session.get("role") in ("admin", "super_admin"):
        return True
    pin = _configured_pin()
    try:
        granted = int(session.get("excel_pin_granted_at") or 0)
        stored = str(session.get("excel_pin_signature") or "")
    except (TypeError, ValueError):
        return False
    return bool(pin and granted and 0 <= time.time()-granted < PIN_TTL_SECONDS
                and hmac.compare_digest(stored, _pin_signature(pin)))


def excel_access(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        if not _has_excel_access():
            if request.path.startswith("/api/"):
                return jsonify(success=False, error="請先輸入 Excel 匯入密碼"), 401
            return redirect(url_for("container_excel.excel_page"))
        return fn(*args, **kwargs)
    return guarded


def _csrf_token():
    token = session.get("excel_pin_csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["excel_pin_csrf"] = token
    return token


def _pin_client_id():
    # Do not trust user-provided forwarding headers; use the request peer only.
    return str(request.remote_addr or "unknown")


def _prune_failures(now):
    while _PIN_FAILURES and now - _PIN_FAILURES[0] >= PIN_WINDOW_SECONDS:
        _PIN_FAILURES.popleft()
    for client_id in list(_PIN_CLIENT_FAILURES):
        recent = _PIN_CLIENT_FAILURES[client_id]
        while recent and now - recent[0] >= PIN_WINDOW_SECONDS:
            recent.popleft()
        if not recent:
            del _PIN_CLIENT_FAILURES[client_id]


def _pin_attempt_allowed(client_id):
    with _PIN_LOCK:
        now = time.monotonic()
        _prune_failures(now)
        recent = _PIN_CLIENT_FAILURES.get(client_id, ())
        return (len(_PIN_FAILURES) < PIN_GLOBAL_FAILURE_LIMIT
                and len(recent) < PIN_CLIENT_FAILURE_LIMIT)


def _record_pin_failure(client_id):
    with _PIN_LOCK:
        now = time.monotonic()
        _prune_failures(now)
        _PIN_FAILURES.append(now)
        _PIN_CLIENT_FAILURES.setdefault(client_id, deque()).append(now)


@container_excel_bp.route("/admin/container-excel/login", methods=["POST"])
def excel_pin_login():
    pin = _configured_pin()
    if not pin:
        return render_template("admin/container_excel_pin.html",
                               csrf=_csrf_token(), unconfigured=True,
                               error="尚未在 Render 設定 XINGWANG_EXCEL_PIN"), 503
    supplied_csrf = str(request.form.get("csrf") or "")
    stored_csrf = str(session.get("excel_pin_csrf") or "")
    if not (stored_csrf and hmac.compare_digest(supplied_csrf, stored_csrf)):
        return render_template("admin/container_excel_pin.html",
                               csrf=_csrf_token(), unconfigured=False,
                               error="驗證頁面已失效，請重新輸入"), 403
    user_pin = str(request.form.get("pin") or "")
    client = _pin_client_id()
    if not _pin_attempt_allowed(client):
        return render_template("admin/container_excel_pin.html",
                               csrf=_csrf_token(), unconfigured=False,
                               error="嘗試次數過多，請稍後再試"), 429
    if not re.fullmatch(r"[0-9]{1,6}", user_pin) or not hmac.compare_digest(user_pin, pin):
        _record_pin_failure(client)
        return render_template("admin/container_excel_pin.html",
                               csrf=_csrf_token(), unconfigured=False,
                               error="密碼不正確"), 401
    session.clear()
    session["excel_pin_granted_at"] = int(time.time())
    session["excel_pin_signature"] = _pin_signature(pin)
    session.permanent = False
    return redirect(url_for("container_excel.excel_page"), code=303)


@container_excel_bp.route("/admin/container-excel/logout", methods=["POST"])
def excel_pin_logout():
    session.pop("excel_pin_granted_at", None)
    session.pop("excel_pin_signature", None)
    return redirect(url_for("container_excel.excel_page"), code=303)


def _check_origin():
    """Reject cross-origin JSON write requests even with existing session cookies."""
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        # Render normally terminates HTTPS at its reverse proxy.
        if parsed.netloc.lower() != request.host.lower() or parsed.scheme not in ("http", "https"):
            return False
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _normalize_code(value):
    code = re.sub(r"[\s._·-]+", "", str(value or "").upper())
    return code if CODE_RE.fullmatch(code) else None


def _validate_records(body):
    if not isinstance(body, dict) or body.get("format") != "xingwang-container-import-v1":
        raise ValueError("匯入格式不正確")
    records = body.get("records")
    if not isinstance(records, list) or not (1 <= len(records) <= 2000):
        raise ValueError("每次須選擇 1 至 2000 筆")
    validated, seen = [], set()
    today = get_chile_time_naive().date()
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 筆格式錯誤")
        code = _normalize_code(row.get("container_no"))
        if not code:
            raise ValueError(f"第 {index} 筆貨櫃號碼不正確")
        try:
            loading = date.fromisoformat(str(row.get("loading_date", "")))
        except ValueError as exc:
            raise ValueError(f"第 {index} 筆裝櫃日期無效") from exc
        if not (date(2024, 1, 1) <= loading <= today):
            raise ValueError(f"第 {index} 筆裝櫃日期不在允許範圍")
        days = row.get("free_days")
        if isinstance(days, bool) or isinstance(days, float) or not re.fullmatch(r"[0-9]{1,3}", str(days)):
            raise ValueError(f"第 {index} 筆免箱天數無效")
        days = int(days)
        if not 1 <= days <= 120:
            raise ValueError(f"第 {index} 筆免箱天數須在 1～120")
        if code in seen:
            raise ValueError(f"{code} 重複選取；請只選一筆")
        seen.add(code)
        loading_text = str(row.get("loading_text") or "").strip()[:1000]
        remark = str(row.get("remark") or "").strip()[:1000]
        if not loading_text:
            raise ValueError(f"第 {index} 筆缺少 A 欄裝櫃原文")
        validated.append((code, loading, loading_text, remark, days))
    return validated


def _write_target(target, rows, username, now):
    conn = get_db_connection_for_target(target)
    try:
        cur = conn.cursor()
        cur.execute(CREATE_TABLE)
        values = [(code, loading, text, remark, days, username, now)
                  for code, loading, text, remark, days in rows]
        cur.executemany(UPSERT, values)
        conn.commit()
        cur.execute("SELECT COUNT(*) AS n FROM monitor_excel_container_days")
        total = int(cur.fetchone()["n"])
        return total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _targets():
    if config.DATABASE_TYPE not in ("mysql", "tidb"):
        raise RuntimeError("目前的 Render 未設定 TiDB；沒有寫入任何資料")
    first = preferred_target()
    second = "TIDB2" if first == "TIDB1" else "TIDB1"
    # Match existing Render mirror policy; never write a disabled standby.
    ordered = [first, second] if mirror_enabled() else [first]
    configured = [t for t in ordered if target_configured(t)]
    if not configured and target_configured(second):
        configured = [second]
    return configured


@container_excel_bp.route("/admin/container-excel", methods=["GET"])
def excel_page():
    if _has_excel_access():
        response = render_template("admin/container_excel_import.html")
    else:
        response = render_template(
            "admin/container_excel_pin.html", csrf=_csrf_token(),
            unconfigured=(_configured_pin() is None), error=None,
        )
    return response, 200, {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@container_excel_bp.route("/api/admin/container-excel/commit", methods=["POST"])
@excel_access
def excel_commit():
    if not request.is_json or not _check_origin():
        return jsonify(success=False, error="請從匯入頁面確認後送出"), 403
    if request.content_length is not None and request.content_length > 2500000:
        return jsonify(success=False, error="選取資料量過大"), 413
    try:
        payload = request.get_json(silent=False)
        rows = _validate_records(payload)
        targets = _targets()
        if not targets:
            raise RuntimeError("沒有可用的 TiDB 連線設定")
    except (ValueError, RuntimeError, TypeError) as exc:
        return jsonify(success=False, error=str(exc)), 400

    username = str(session.get("username") or "admin")[:120]
    now = get_chile_time_naive()
    saved, failures = {}, {}
    for target in targets:
        try:
            saved[target] = _write_target(target, rows, username, now)
        except Exception as exc:
            LOG.exception("Excel import failed on %s", target)
            failures[target] = type(exc).__name__
    if not saved:
        return jsonify(success=False, error="TiDB 目前無法寫入，請查看 Render 日誌", targets=failures), 503
    return jsonify(
        success=True, count=len(rows), totals=saved, failed_targets=failures,
        warning=("部分 TiDB 副本寫入失敗，請重新同步" if failures else ""),
    ), (207 if failures else 200)


@container_excel_bp.route("/api/admin/container-excel/status", methods=["GET"])
@excel_access
def excel_status():
    try:
        targets = _targets()
    except RuntimeError:
        return jsonify(success=False, configured=False), 503
    statuses = {}
    for target in targets:
        try:
            conn = get_db_connection_for_target(target)
            try:
                cur = conn.cursor()
                cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema=DATABASE() AND table_name=%s""", (TABLE,))
                exists = bool(cur.fetchone()["n"])
                total = 0
                if exists:
                    cur.execute("SELECT COUNT(*) AS n FROM monitor_excel_container_days")
                    total = int(cur.fetchone()["n"])
                statuses[target] = {"ready": exists, "rows": total}
            finally:
                conn.close()
        except Exception as exc:
            statuses[target] = {"ready": False, "error": type(exc).__name__}
    return jsonify(success=True, databases=statuses)


def lookup_excel_days(container_names, today=None):
    """Batch read only. Return unambiguous, in-range 3-month days; never auto-create schema.

    A reused container number within the active window is ambiguous and skipped.
    A missing table or DB outage never changes Monitor's existing behaviour.
    """
    codes = sorted({_normalize_code(c) for c in container_names} - {None})
    if not codes or config.DATABASE_TYPE not in ("mysql", "tidb"):
        return {}
    today = today or get_chile_time_naive().date()
    month = today.month - 3
    year = today.year
    if month <= 0:
        month += 12
        year -= 1
    import calendar
    first = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Chunk codes to avoid oversized IN expressions for large monitors.
        result = {}
        for start in range(0, len(codes), 200):
            chunk = codes[start:start+200]
            sql = ("SELECT container_no, MAX(free_days) AS free_days FROM monitor_excel_container_days "
                   "WHERE loading_date BETWEEN ? AND ? AND container_no IN (" +
                   ",".join("?" for _ in chunk) +
                   ") GROUP BY container_no HAVING COUNT(*) = 1")
            # MAX(free_days) satisfies ONLY_FULL_GROUP_BY; HAVING 1 row prevents ambiguity.
            cur.execute(sql, [first, today] + chunk)
            for row in cur.fetchall():
                value = int(row["free_days"])
                if 1 <= value <= 120:
                    result[row["container_no"]] = value
        return result
    except Exception as exc:
        LOG.warning("Excel free days lookup unavailable: %s", type(exc).__name__)
        return {}
    finally:
        if conn is not None:
            conn.close()
