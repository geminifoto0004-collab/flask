import hashlib
import hmac
import os
import secrets
from typing import Dict, Optional, Tuple

from database import get_db_connection, get_cursor, get_row_dict
from utils.time_utils import get_chile_time_naive


def _normalize_token(token: Optional[str]) -> str:
    return str(token or "").strip()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_last4(last4: str) -> str:
    if not last4:
        return ""
    return "*" * 16 + str(last4)


def _ensure_table_and_row(conn) -> None:
    cursor = get_cursor(conn)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_batch_config (
            id INTEGER PRIMARY KEY,
            token_hash TEXT,
            token_last4 TEXT,
            updated_at TIMESTAMP,
            updated_by INTEGER
        )
        """
    )
    cursor.execute("SELECT id FROM monitor_batch_config WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO monitor_batch_config (id, token_hash, token_last4, updated_at, updated_by)
            VALUES (1, NULL, NULL, NULL, NULL)
            """
        )
    conn.commit()


def _read_db_token_meta() -> Dict[str, Optional[object]]:
    conn = get_db_connection()
    try:
        _ensure_table_and_row(conn)
        cursor = get_cursor(conn)
        cursor.execute(
            """
            SELECT token_hash, token_last4, updated_at, updated_by
            FROM monitor_batch_config
            WHERE id = 1
            """
        )
        row = cursor.fetchone()
        data = get_row_dict(row, cursor) if row else {}
        token_hash = (data or {}).get("token_hash")
        token_last4 = (data or {}).get("token_last4") or ""
        return {
            "has_db_token": bool(token_hash),
            "token_hash": token_hash,
            "token_last4": token_last4,
            "token_masked": _mask_last4(token_last4),
            "updated_at": (data or {}).get("updated_at"),
            "updated_by": (data or {}).get("updated_by"),
        }
    finally:
        conn.close()


def has_monitor_batch_token_configured() -> bool:
    meta = _read_db_token_meta()
    if meta.get("has_db_token"):
        return True
    return bool(
        _normalize_token(os.environ.get("MONITOR_BATCH_API_KEY"))
        or _normalize_token(os.environ.get("MONITOR_CRON_KEY"))
    )


def get_monitor_batch_token_status() -> Dict[str, Optional[object]]:
    meta = _read_db_token_meta()
    env_fallback_exists = bool(
        _normalize_token(os.environ.get("MONITOR_BATCH_API_KEY"))
        or _normalize_token(os.environ.get("MONITOR_CRON_KEY"))
    )
    source = "db" if meta.get("has_db_token") else ("env" if env_fallback_exists else "none")
    return {
        "configured": bool(meta.get("has_db_token") or env_fallback_exists),
        "source": source,
        "token_masked": meta.get("token_masked"),
        "token_last4": meta.get("token_last4"),
        "updated_at": meta.get("updated_at"),
        "updated_by": meta.get("updated_by"),
    }


def set_monitor_batch_token(token: str, updated_by: Optional[int] = None) -> Tuple[bool, str]:
    normalized = _normalize_token(token)
    if len(normalized) < 16:
        return False, "Token too short (min 16 chars)"

    token_hash = _hash_token(normalized)
    token_last4 = normalized[-4:]
    now = get_chile_time_naive().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    try:
        _ensure_table_and_row(conn)
        cursor = get_cursor(conn)
        cursor.execute(
            """
            UPDATE monitor_batch_config
            SET token_hash = ?, token_last4 = ?, updated_at = ?, updated_by = ?
            WHERE id = 1
            """,
            (token_hash, token_last4, now, updated_by),
        )
        conn.commit()
        return True, normalized
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def rotate_monitor_batch_token(updated_by: Optional[int] = None) -> Tuple[bool, str]:
    generated = secrets.token_urlsafe(36)
    return set_monitor_batch_token(generated, updated_by=updated_by)


def validate_monitor_batch_token(provided_token: str) -> bool:
    provided = _normalize_token(provided_token)
    if not provided:
        return False

    meta = _read_db_token_meta()
    db_hash = meta.get("token_hash")
    if db_hash:
        return hmac.compare_digest(_hash_token(provided), str(db_hash))

    env_expected = (
        _normalize_token(os.environ.get("MONITOR_BATCH_API_KEY"))
        or _normalize_token(os.environ.get("MONITOR_CRON_KEY"))
    )
    if not env_expected:
        return False
    return hmac.compare_digest(provided, env_expected)
