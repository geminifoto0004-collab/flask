"""Company passcode enrolment for the Render ORDER share Telegram bot.

Stored Telegram user IDs survive restarts. The record includes a keyed fingerprint
of the current passcode, so rotating it revokes every previous enrolment.
Do not expose the passcode or fingerprints in logs or replies.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time

from database import get_db_connection, get_cursor

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_FAILURE_LOCK = threading.Lock()
_FAILURES = {}
_WINDOW = 15 * 60
_MAX_FAILURES = 5


def _company_code():
    code = (os.environ.get("ORDER_SHARE_TELEGRAM_ACCESS_CODE") or "").strip()
    return code if len(code) >= 8 else ""


def configured():
    return bool(_company_code())


def _fingerprint(bot_key):
    secret = (os.environ.get("AUTOMATION_MASTER_KEY") or "").strip()
    code = _company_code()
    if not secret or not code:
        raise RuntimeError("ORDER share company code or master key not configured")
    msg = ("order-share-staff-v1\x00" + str(bot_key) + "\x00" + code).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _ensure_schema(conn):
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        cursor = get_cursor(conn)
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS automation_order_share_staff (
                 bot_key VARCHAR(64) NOT NULL,
                 telegram_user_id BIGINT NOT NULL,
                 code_fingerprint CHAR(64) NOT NULL,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 PRIMARY KEY (bot_key, telegram_user_id)
               )"""
        )
        conn.commit()
        _SCHEMA_READY = True


def is_authorized(bot_key, user_id):
    if not configured():
        return False
    fingerprint = _fingerprint(bot_key)
    conn = get_db_connection()
    try:
        _ensure_schema(conn)
        cursor = get_cursor(conn)
        cursor.execute(
            """SELECT code_fingerprint FROM automation_order_share_staff
               WHERE bot_key = ? AND telegram_user_id = ?""",
            (bot_key, int(user_id)),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        digest = row.get("code_fingerprint") if isinstance(row, dict) else row[0]
        return hmac.compare_digest(str(digest or ""), fingerprint)
    finally:
        conn.close()


def _blocked(bot_key, user_id, now):
    key = (bot_key, user_id)
    with _FAILURE_LOCK:
        attempts = [t for t in _FAILURES.get(key, []) if now - t < _WINDOW]
        if attempts:
            _FAILURES[key] = attempts
        else:
            _FAILURES.pop(key, None)
        return len(attempts) >= _MAX_FAILURES


def _record_failure(bot_key, user_id, now):
    key = (bot_key, user_id)
    with _FAILURE_LOCK:
        _FAILURES.setdefault(key, []).append(now)
        return len(_FAILURES[key]) >= _MAX_FAILURES


def authenticate(bot_key, user_id, supplied):
    """Returns ok, incorrect, locked or not_configured; no secret in replies."""
    if not configured():
        return "not_configured"
    now = time.monotonic()
    if _blocked(bot_key, user_id, now):
        return "locked"
    if not hmac.compare_digest(str(supplied), _company_code()):
        return "locked" if _record_failure(bot_key, user_id, now) else "incorrect"
    fingerprint = _fingerprint(bot_key)
    conn = get_db_connection()
    try:
        _ensure_schema(conn)
        cursor = get_cursor(conn)
        # Both SQLite (tests/local) and TiDB (Render) support REPLACE INTO.
        cursor.execute(
            """REPLACE INTO automation_order_share_staff
               (bot_key, telegram_user_id, code_fingerprint)
               VALUES (?, ?, ?)""",
            (bot_key, int(user_id), fingerprint),
        )
        conn.commit()
    finally:
        conn.close()
    with _FAILURE_LOCK:
        _FAILURES.pop((bot_key, user_id), None)
    return "ok"


def revoke_self(bot_key, user_id):
    conn = get_db_connection()
    try:
        _ensure_schema(conn)
        cursor = get_cursor(conn)
        cursor.execute(
            """DELETE FROM automation_order_share_staff
               WHERE bot_key = ? AND telegram_user_id = ?""",
            (bot_key, int(user_id)),
        )
        conn.commit()
    finally:
        conn.close()
