# -*- coding: utf-8 -*-
from __future__ import annotations

import secrets
from datetime import datetime

from database import get_db_connection, get_cursor, get_id_type, get_lastrowid

from .crypto import decrypt_secret, encrypt_secret

_SCHEMA_READY = False


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def ensure_schema():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_telegram_bots (
                id {id_type},
                bot_key VARCHAR(64) UNIQUE NOT NULL,
                display_name VARCHAR(120) NOT NULL,
                plugin_key VARCHAR(64) NOT NULL,
                bot_username VARCHAR(120),
                token_encrypted TEXT NOT NULL,
                token_last4 VARCHAR(8),
                webhook_secret VARCHAR(255) NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                last_test_at VARCHAR(32),
                last_error TEXT,
                created_at VARCHAR(32) NOT NULL,
                updated_at VARCHAR(32) NOT NULL
            )
            """.format(id_type=get_id_type())
        )
        conn.commit()
        _SCHEMA_READY = True
    finally:
        conn.close()


def _row_dict(row):
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else dict(row)


def list_bots():
    ensure_schema()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            SELECT id, bot_key, display_name, plugin_key, bot_username,
                   token_last4, webhook_secret, enabled, is_default,
                   last_test_at, last_error, created_at, updated_at
            FROM automation_telegram_bots
            ORDER BY plugin_key, is_default DESC, id
            """
        )
        return [_row_dict(r) for r in (cur.fetchall() or [])]
    finally:
        conn.close()


def get_bot_by_key(bot_key: str, with_token: bool = False):
    ensure_schema()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            SELECT id, bot_key, display_name, plugin_key, bot_username,
                   token_encrypted, token_last4, webhook_secret, enabled,
                   is_default, last_test_at, last_error, created_at, updated_at
            FROM automation_telegram_bots
            WHERE bot_key = ?
            """,
            (str(bot_key or "").strip(),),
        )
        row = _row_dict(cur.fetchone())
        if row and with_token:
            row["token"] = decrypt_secret(row.pop("token_encrypted"))
        elif row:
            row.pop("token_encrypted", None)
        return row
    finally:
        conn.close()


def get_bot_by_id(bot_id: int, with_token: bool = False):
    ensure_schema()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            SELECT id, bot_key, display_name, plugin_key, bot_username,
                   token_encrypted, token_last4, webhook_secret, enabled,
                   is_default, last_test_at, last_error, created_at, updated_at
            FROM automation_telegram_bots
            WHERE id = ?
            """,
            (int(bot_id),),
        )
        row = _row_dict(cur.fetchone())
        if row and with_token:
            row["token"] = decrypt_secret(row.pop("token_encrypted"))
        elif row:
            row.pop("token_encrypted", None)
        return row
    finally:
        conn.close()


def get_active_bot_for_plugin(plugin_key: str, with_token: bool = True):
    ensure_schema()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """
            SELECT id, bot_key, display_name, plugin_key, bot_username,
                   token_encrypted, token_last4, webhook_secret, enabled,
                   is_default, last_test_at, last_error, created_at, updated_at
            FROM automation_telegram_bots
            WHERE plugin_key = ? AND enabled = 1
            ORDER BY is_default DESC, id
            LIMIT 1
            """,
            (str(plugin_key or "").strip().upper(),),
        )
        row = _row_dict(cur.fetchone())
        if row and with_token:
            row["token"] = decrypt_secret(row.pop("token_encrypted"))
        elif row:
            row.pop("token_encrypted", None)
        return row
    finally:
        conn.close()


def save_bot(*, bot_key, display_name, plugin_key, token, bot_username="", make_default=True):
    ensure_schema()
    bot_key = str(bot_key or "").strip().lower()
    plugin_key = str(plugin_key or "").strip().upper()
    display_name = str(display_name or "").strip()
    if not bot_key or not display_name or not plugin_key or not token:
        raise ValueError("Datos incompletos")
    encrypted = encrypt_secret(token)
    now = _now()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        if make_default:
            cur.execute(
                "UPDATE automation_telegram_bots SET is_default = 0, updated_at = ? WHERE plugin_key = ?",
                (now, plugin_key),
            )
        cur.execute("SELECT id FROM automation_telegram_bots WHERE bot_key = ?", (bot_key,))
        existing = cur.fetchone()
        if existing:
            existing_id = _row_dict(existing)["id"]
            cur.execute(
                """
                UPDATE automation_telegram_bots
                SET display_name = ?, plugin_key = ?, bot_username = ?,
                    token_encrypted = ?, token_last4 = ?, enabled = 1,
                    is_default = ?, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    display_name, plugin_key, bot_username, encrypted,
                    str(token)[-4:], 1 if make_default else 0, now, existing_id,
                ),
            )
            bot_id = int(existing_id)
        else:
            webhook_secret = secrets.token_urlsafe(32)[:64]
            cur.execute(
                """
                INSERT INTO automation_telegram_bots
                (bot_key, display_name, plugin_key, bot_username,
                 token_encrypted, token_last4, webhook_secret, enabled,
                 is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    bot_key, display_name, plugin_key, bot_username,
                    encrypted, str(token)[-4:], webhook_secret,
                    1 if make_default else 0, now, now,
                ),
            )
            bot_id = int(get_lastrowid(cur, conn))
        conn.commit()
    finally:
        conn.close()
    return get_bot_by_id(bot_id, with_token=True)


def set_default(bot_id: int):
    bot = get_bot_by_id(bot_id)
    if not bot:
        return False
    conn = get_db_connection()
    cur = get_cursor(conn)
    now = _now()
    try:
        cur.execute(
            "UPDATE automation_telegram_bots SET is_default = 0, updated_at = ? WHERE plugin_key = ?",
            (now, bot["plugin_key"]),
        )
        cur.execute(
            "UPDATE automation_telegram_bots SET is_default = 1, enabled = 1, updated_at = ? WHERE id = ?",
            (now, int(bot_id)),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def set_enabled(bot_id: int, enabled: bool):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            "UPDATE automation_telegram_bots SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), int(bot_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_test(bot_id: int, error):
    conn = get_db_connection()
    cur = get_cursor(conn)
    now = _now()
    try:
        cur.execute(
            """
            UPDATE automation_telegram_bots
            SET last_test_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, error, now, int(bot_id)),
        )
        conn.commit()
    finally:
        conn.close()
