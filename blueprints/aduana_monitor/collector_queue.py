# -*- coding: utf-8 -*-
"""Render <-> residential Aduana worker queue.

Render never connects to the Windows/Raspberry Pi machine.  The worker polls
Render for a pending job, performs the legacy Aduana APEX request from its own
ISP connection, then posts the result back.  This keeps Telegram, permissions,
TiDB and scheduling on Render without requiring a public port, fixed IP or
Cloudflare Tunnel on the worker machine.
"""
from __future__ import annotations

import hmac
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from flask import jsonify, redirect, render_template_string, request, session, url_for

from config import admin_config, config as app_config
from database import get_cursor, get_db_connection, get_lastrowid
from utils.time_utils import get_chile_time_naive

from . import aduana_bp, settings

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _now():
    return get_chile_time_naive()


def _db_type():
    return str(getattr(app_config, "DATABASE_TYPE", "sqlite") or "sqlite").lower()


def _id_type():
    db_type = _db_type()
    if db_type in ("mysql", "tidb"):
        return "BIGINT PRIMARY KEY AUTO_INCREMENT"
    if db_type == "postgresql":
        return "BIGSERIAL PRIMARY KEY"
    return "INTEGER PRIMARY KEY AUTOINCREMENT"


def _large_text_type():
    return "LONGTEXT" if _db_type() in ("mysql", "tidb") else "TEXT"


def _row_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return row


@contextmanager
def _transaction():
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def ensure_schema(force=False):
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY and not force:
            return
        id_type = _id_type()
        large_text = _large_text_type()
        with _transaction() as (_conn, cur):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_worker_jobs (
                    id {id_type},
                    request_id VARCHAR(64) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    rut VARCHAR(32) NOT NULL,
                    aduana VARCHAR(16) NOT NULL,
                    payload_json {large_text} NOT NULL,
                    result_json {large_text},
                    error_message TEXT,
                    worker_id VARCHAR(128),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_at TIMESTAMP NULL,
                    completed_at TIMESTAMP NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_worker_nodes (
                    worker_id VARCHAR(128) PRIMARY KEY,
                    version VARCHAR(64),
                    last_seen_at TIMESTAMP NULL,
                    last_status VARCHAR(40),
                    last_error TEXT
                )
            """)
        _SCHEMA_READY = True


def _touch_worker(worker_id, version="", status="ONLINE", error=""):
    ensure_schema()
    worker_id = str(worker_id or "worker").strip()[:128] or "worker"
    with _transaction() as (_conn, cur):
        cur.execute("SELECT worker_id FROM aduana_worker_nodes WHERE worker_id=?", (worker_id,))
        if cur.fetchone():
            cur.execute(
                """
                UPDATE aduana_worker_nodes
                SET version=?, last_seen_at=?, last_status=?, last_error=?
                WHERE worker_id=?
                """,
                (str(version or "")[:64], _now(), status, str(error or "")[:2000] or None, worker_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO aduana_worker_nodes
                    (worker_id, version, last_seen_at, last_status, last_error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (worker_id, str(version or "")[:64], _now(), status, str(error or "")[:2000] or None),
            )


def worker_status():
    ensure_schema()
    with _transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_worker_nodes ORDER BY last_seen_at DESC")
        row = _row_dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) AS n FROM aduana_worker_jobs WHERE status='PENDING'")
        pending_row = _row_dict(cur.fetchone()) or {}
    online = False
    if row and row.get("last_seen_at"):
        last_seen = row["last_seen_at"]
        if isinstance(last_seen, str):
            try:
                last_seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                last_seen = None
        if last_seen:
            online = (_now() - last_seen) <= timedelta(seconds=20)
    return {
        "configured": bool(settings.WORKER_TOKEN),
        "enabled": bool(settings.WORKER_ENABLED),
        "online": online,
        "pending_jobs": int(pending_row.get("n") or 0),
        "worker": row,
    }


def create_job(periods, aduana, rut, max_workers=None):
    ensure_schema()
    payload = {
        "periods": [
            {"start": d1.isoformat(), "end": d2.isoformat()}
            for d1, d2 in periods
        ],
        "max_workers": int(max_workers or settings.PERIOD_WORKERS),
    }
    request_id = uuid.uuid4().hex
    current = _now()
    with _transaction() as (conn, cur):
        # Small automatic cleanup.  Completed payloads can be large, so there is
        # no reason to keep old transport jobs indefinitely after callers used them.
        cutoff = current - timedelta(days=2)
        cur.execute(
            "DELETE FROM aduana_worker_jobs WHERE status IN ('DONE','FAILED','EXPIRED') AND updated_at < ?",
            (cutoff,),
        )
        cur.execute(
            """
            INSERT INTO aduana_worker_jobs
                (request_id, status, rut, aduana, payload_json, created_at, updated_at)
            VALUES (?, 'PENDING', ?, ?, ?, ?, ?)
            """,
            (request_id, str(rut), str(aduana), json.dumps(payload, ensure_ascii=False), current, current),
        )
        job_id = get_lastrowid(cur, conn)
    return int(job_id)


def get_job(job_id):
    ensure_schema()
    with _transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_worker_jobs WHERE id=?", (int(job_id),))
        return _row_dict(cur.fetchone())


def claim_next_job(worker_id, version=""):
    ensure_schema()
    worker_id = str(worker_id or "worker").strip()[:128] or "worker"
    _touch_worker(worker_id, version=version, status="ONLINE")
    current = _now()
    stale_before = current - timedelta(minutes=10)

    # Conditional UPDATE makes this safe if a second worker is added later.
    for _ in range(3):
        with _transaction() as (_conn, cur):
            cur.execute(
                """
                UPDATE aduana_worker_jobs
                SET status='PENDING', worker_id=NULL, claimed_at=NULL, updated_at=?
                WHERE status='RUNNING' AND claimed_at IS NOT NULL AND claimed_at < ?
                """,
                (current, stale_before),
            )
            cur.execute(
                "SELECT * FROM aduana_worker_jobs WHERE status='PENDING' ORDER BY id LIMIT 1"
            )
            row = _row_dict(cur.fetchone())
            if not row:
                return None
            cur.execute(
                """
                UPDATE aduana_worker_jobs
                SET status='RUNNING', worker_id=?, attempts=attempts+1,
                    claimed_at=?, updated_at=?
                WHERE id=? AND status='PENDING'
                """,
                (worker_id, current, current, int(row["id"])),
            )
            if cur.rowcount <= 0:
                continue
            cur.execute("SELECT * FROM aduana_worker_jobs WHERE id=?", (int(row["id"]),))
            claimed = _row_dict(cur.fetchone())
            try:
                payload = json.loads(claimed.get("payload_json") or "{}")
            except Exception:
                payload = {}
            return {
                "id": int(claimed["id"]),
                "request_id": claimed.get("request_id"),
                "rut": claimed.get("rut"),
                "aduana": claimed.get("aduana"),
                "payload": payload,
            }
    return None


def complete_job(job_id, worker_id, result):
    ensure_schema()
    result_json = json.dumps(result or {}, ensure_ascii=False)
    current = _now()
    with _transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_worker_jobs
            SET status='DONE', result_json=?, error_message=NULL,
                completed_at=?, updated_at=?
            WHERE id=? AND status='RUNNING' AND worker_id=?
            """,
            (result_json, current, current, int(job_id), str(worker_id)),
        )
        ok = cur.rowcount > 0
    _touch_worker(worker_id, status="ONLINE")
    return ok


def fail_job(job_id, worker_id, error):
    ensure_schema()
    current = _now()
    message = str(error or "Worker failed")[:8000]
    with _transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_worker_jobs
            SET status='FAILED', error_message=?, completed_at=?, updated_at=?
            WHERE id=? AND status='RUNNING' AND worker_id=?
            """,
            (message, current, current, int(job_id), str(worker_id)),
        )
        ok = cur.rowcount > 0
    _touch_worker(worker_id, status="ERROR", error=message)
    return ok


def _failure_logs(periods, message, phase="COLLECTOR"):
    return [
        {
            "worker": "REMOTE",
            "desde": d1.strftime("%d-%m-%Y"),
            "hasta": d2.strftime("%d-%m-%Y"),
            "estado": "REQUEST_FAILED",
            "filas": 0,
            "segundos": 0,
            "phase": phase,
            "error": str(message),
        }
        for d1, d2 in periods
    ]


def submit_and_wait(periods, aduana, rut, max_workers=None):
    """Queue one query and wait for the residential worker result.

    Telegram/cron already call this from background threads.  The public web
    form has a shorter ceiling so a missing worker does not hold a Gunicorn
    request forever.
    """
    periods = list(periods)
    if not periods:
        return [], [], True
    if not settings.WORKER_TOKEN:
        return [], _failure_logs(periods, "Aduana worker token is not configured"), False

    job_id = create_job(periods, aduana, rut, max_workers=max_workers)

    try:
        from flask import has_request_context
        in_web_request = bool(has_request_context())
    except Exception:
        in_web_request = False

    timeout_seconds = (
        settings.WORKER_WEB_WAIT_SECONDS
        if in_web_request
        else settings.WORKER_WAIT_SECONDS
    )
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        job = get_job(job_id)
        if not job:
            return [], _failure_logs(periods, "Worker job disappeared"), False

        status = str(job.get("status") or "").upper()
        if status == "DONE":
            try:
                result = json.loads(job.get("result_json") or "{}")
            except Exception as exc:
                return [], _failure_logs(periods, f"Invalid worker result: {exc}"), False
            rows = result.get("rows") if isinstance(result.get("rows"), list) else []
            logs = result.get("logs") if isinstance(result.get("logs"), list) else []
            all_ok = bool(result.get("all_ok"))
            return rows, logs, all_ok

        if status == "FAILED":
            return [], _failure_logs(
                periods,
                job.get("error_message") or "Residential worker failed",
            ), False

        time.sleep(0.45)

    # Only expire jobs that were never picked up. A running worker is allowed to
    # finish and report; the caller simply timed out waiting for this request.
    with _transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_worker_jobs
            SET status='EXPIRED', updated_at=?
            WHERE id=? AND status='PENDING'
            """,
            (_now(), int(job_id)),
        )
    return [], _failure_logs(
        periods,
        f"Residential worker did not return within {timeout_seconds}s",
        phase="WORKER_TIMEOUT",
    ), False


def _worker_authorized():
    if not settings.WORKER_TOKEN:
        return False
    supplied = str(request.headers.get("X-Aduana-Worker-Token") or "")
    return hmac.compare_digest(supplied, settings.WORKER_TOKEN)


def _worker_auth_error():
    return jsonify({"ok": False, "error": "unauthorized"}), 403


@aduana_bp.route("/api/aduana/worker/heartbeat", methods=["POST"])
def worker_heartbeat():
    if not _worker_authorized():
        return _worker_auth_error()
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id") or "worker")[:128]
    _touch_worker(worker_id, version=data.get("version") or "", status="ONLINE")
    return jsonify({"ok": True})


@aduana_bp.route("/api/aduana/worker/next", methods=["POST"])
def worker_next():
    if not _worker_authorized():
        return _worker_auth_error()
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id") or "worker")[:128]
    version = str(data.get("version") or "")[:64]
    job = claim_next_job(worker_id, version=version)
    return jsonify({"ok": True, "job": job})


@aduana_bp.route("/api/aduana/worker/jobs/<int:job_id>/complete", methods=["POST"])
def worker_complete(job_id):
    if not _worker_authorized():
        return _worker_auth_error()
    if request.content_length and request.content_length > 12 * 1024 * 1024:
        return jsonify({"ok": False, "error": "result too large"}), 413
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id") or "worker")[:128]
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if not complete_job(job_id, worker_id, result):
        return jsonify({"ok": False, "error": "job is not owned by this worker"}), 409
    return jsonify({"ok": True})


@aduana_bp.route("/api/aduana/worker/jobs/<int:job_id>/fail", methods=["POST"])
def worker_fail(job_id):
    if not _worker_authorized():
        return _worker_auth_error()
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id") or "worker")[:128]
    if not fail_job(job_id, worker_id, data.get("error") or "Worker failed"):
        return jsonify({"ok": False, "error": "job is not owned by this worker"}), 409
    return jsonify({"ok": True})


def _admin_allowed():
    allowed_roles = {"admin", admin_config.SUPER_ADMIN_ROLE}
    return bool(session.get("logged_in") and session.get("role") in allowed_roles)


_SETUP_HTML = """
<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aduana Worker Setup</title>
<style>
body{font-family:Arial,'Microsoft JhengHei',sans-serif;max-width:900px;margin:32px auto;padding:0 18px;color:#1f2937;background:#f5f7fa}
.card{background:#fff;border:1px solid #dfe3e8;border-radius:12px;padding:20px;margin:15px 0}code{word-break:break-all;background:#f2f4f7;padding:4px 7px;border-radius:5px}.ok{color:#087f23}.bad{color:#b42318}
</style></head><body>
<h2>Aduana Residential Worker</h2>
<div class="card"><b>狀態：</b>
{% if state.online %}<span class="ok">ONLINE</span>{% else %}<span class="bad">OFFLINE</span>{% endif %}
<br>Pending jobs: {{state.pending_jobs}}
{% if state.worker %}<br>Worker: {{state.worker.worker_id}}<br>Last seen: {{state.worker.last_seen_at}}{% endif %}
</div>
<div class="card"><h3>Windows Worker 設定</h3>
<p>Render URL</p><p><code>{{base_url}}</code></p>
<p>Worker Token</p><p><code>{{token}}</code></p>
<p>這個 Token 只給你的 Windows / Raspberry Pi Worker 使用，不要公開。</p>
</div>
<div class="card"><p>架構：Telegram / 網頁 → Render 建立工作 → Windows 主動向 Render 拿工作 → Windows 查 Aduana → 回傳 Render。</p>
<p>Render 不需要知道 Windows IP，不需要固定 IP、DDNS、Router Port 或 Tunnel。</p></div>
</body></html>
"""


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/worker-setup", methods=["GET"])
def worker_setup_page():
    if not _admin_allowed():
        return redirect(url_for("login", next=request.path))
    base_url = (
        settings.PUBLIC_BASE_URL
        or request.url_root.rstrip("/")
    )
    return render_template_string(
        _SETUP_HTML,
        state=worker_status(),
        base_url=base_url,
        token=settings.WORKER_TOKEN or "NOT CONFIGURED",
    )
