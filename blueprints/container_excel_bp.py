"""Admin-only browser-parsed A/C/F/H Excel import for ITI Monitor.

No Excel bytes reach the server; only explicitly selected normalized records.
Keeps this dataset separate from ITI, Aduana and manually assigned free time.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

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


def admin_only(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify(success=False, error="請先登入管理員"), 401
            return redirect(url_for("login", next=request.path))
        if session.get("role") not in ("admin", "super_admin"):
            return jsonify(success=False, error="需要管理員權限"), 403
        return fn(*args, **kwargs)
    return guarded


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
@admin_only
def excel_page():
    response = render_template("admin/container_excel_import.html")
    return response, 200, {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@container_excel_bp.route("/api/admin/container-excel/commit", methods=["POST"])
@admin_only
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
@admin_only
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
