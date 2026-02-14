import os
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database import get_db_connection, get_cursor, get_row_dict
from utils.time_utils import get_chile_time_naive

DEFAULT_SESSION_TIMEOUT_MINUTES = 2


def _coerce_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        parsed = int(value)
        if parsed <= 0:
            return None
        return parsed
    except ValueError:
        return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M")
        if len(value) == 10:
            base = datetime.strptime(value, "%Y-%m-%d")
            return base.replace(hour=23, minute=59, second=59)
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _format_dt(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _extract_count(row) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        for key in ("count", "cnt", "COUNT(*)"):
            if key in row:
                return int(row[key] or 0)
        return int(next(iter(row.values()), 0) or 0)
    if isinstance(row, (list, tuple)):
        return int(row[0] or 0)
    return int(row or 0)


def _session_timeout_minutes(conn=None) -> int:
    env_value = os.environ.get("CONTAINER_SESSION_TIMEOUT_MINUTES")
    if env_value:
        try:
            return max(1, int(env_value))
        except ValueError:
            pass

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    try:
        cursor = get_cursor(conn)
        cursor.execute("SELECT session_timeout_minutes FROM container_access_admin WHERE id = 1")
        row = cursor.fetchone()
        if row:
            data = get_row_dict(row, cursor)
            if data and data.get("session_timeout_minutes") is not None:
                return max(1, int(data["session_timeout_minutes"]))
    except Exception:
        pass
    finally:
        if close_conn:
            conn.close()
    return DEFAULT_SESSION_TIMEOUT_MINUTES


def ensure_admin_from_env() -> None:
    env_password = os.environ.get("CONTAINER_ADMIN_PASSWORD")
    if not env_password:
        return

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT id FROM container_access_admin WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        now = get_chile_time_naive()
        cursor.execute(
            "INSERT INTO container_access_admin (id, password, updated_at) VALUES (?, ?, ?)",
            (1, env_password, now),
        )
        conn.commit()
    conn.close()


def verify_admin_password(password: str) -> bool:
    if not password:
        return False

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT password FROM container_access_admin WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    data = get_row_dict(row, cursor)
    stored = None
    if data:
        stored = data.get("password")
    elif isinstance(row, (list, tuple)):
        stored = row[0]
    conn.close()
    return stored == password


def admin_initialized() -> bool:
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT id FROM container_access_admin WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return row is not None


def list_tokens() -> List[Dict]:
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        SELECT id, token, note, status, expires_at, blocked_until, max_concurrent, created_at, last_used_at
        FROM container_access_tokens
        ORDER BY id DESC
        """
    )
    rows = cursor.fetchall()
    now = get_chile_time_naive()
    timeout_minutes = _session_timeout_minutes(conn)
    cutoff = now - timedelta(minutes=timeout_minutes)

    results: List[Dict] = []
    needs_commit = False
    for row in rows:
        data = get_row_dict(row, cursor)
        if not data:
            continue
        blocked_until = data.get("blocked_until")
        blocked_until_dt = blocked_until
        if isinstance(blocked_until, str):
            blocked_until_dt = _parse_datetime(blocked_until)
        if blocked_until_dt and now >= blocked_until_dt:
            cursor.execute(
                "UPDATE container_access_tokens SET blocked_until = NULL WHERE id = ?",
                (data.get("id"),),
            )
            data["blocked_until"] = None
            needs_commit = True
        token = data.get("token")
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM container_access_sessions WHERE token = ? AND last_heartbeat >= ?",
            (token, cutoff),
        )
        count_row = cursor.fetchone()
        data["active_sessions"] = _extract_count(count_row)
        data["expires_at"] = _format_dt(data.get("expires_at"))
        data["blocked_until"] = _format_dt(data.get("blocked_until"))
        data["created_at"] = _format_dt(data.get("created_at"))
        data["last_used_at"] = _format_dt(data.get("last_used_at"))
        results.append(data)
    if needs_commit:
        conn.commit()
    conn.close()
    return results


def create_token(note: Optional[str], expires_at: Optional[str], max_concurrent: Optional[str]) -> Dict:
    token = secrets.token_urlsafe(20)
    now = get_chile_time_naive()
    expires_dt = _parse_datetime(expires_at)
    max_concurrent_value = _coerce_int(max_concurrent)

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        INSERT INTO container_access_tokens
            (token, note, status, expires_at, blocked_until, max_concurrent, created_at, last_used_at)
        VALUES (?, ?, 'active', ?, NULL, ?, ?, NULL)
        """,
        (token, note, expires_dt, max_concurrent_value, now),
    )
    conn.commit()
    conn.close()
    return {
        "token": token,
        "note": note,
        "status": "active",
        "expires_at": _format_dt(expires_dt),
        "blocked_until": None,
        "max_concurrent": max_concurrent_value,
        "created_at": _format_dt(now),
    }


def update_token(
    token_id: int,
    note: Optional[str],
    status: Optional[str],
    expires_at: Optional[str],
    max_concurrent: Optional[str],
) -> bool:
    updates = []
    params = []

    if note is not None:
        updates.append("note = ?")
        params.append(note)
    if status in ("active", "disabled"):
        updates.append("status = ?")
        params.append(status)

    if expires_at is not None:
        updates.append("expires_at = ?")
        params.append(_parse_datetime(expires_at))

    if max_concurrent is not None:
        updates.append("max_concurrent = ?")
        params.append(_coerce_int(max_concurrent))

    if not updates:
        return False

    token_value = None
    conn = get_db_connection()
    cursor = get_cursor(conn)
    if status == "disabled":
        cursor.execute(
            "SELECT token FROM container_access_tokens WHERE id = ?",
            (token_id,),
        )
        row = cursor.fetchone()
        if row:
            data = get_row_dict(row, cursor)
            token_value = data.get("token") if data else row[0]

    params.append(token_id)
    cursor.execute(
        f"""
        UPDATE container_access_tokens
        SET {', '.join(updates)}
        WHERE id = ?
        """,
        params,
    )
    if token_value:
        cursor.execute(
            "DELETE FROM container_access_sessions WHERE token = ?",
            (token_value,),
        )
    conn.commit()
    conn.close()
    return True


def delete_token(token_id: int) -> None:
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT token FROM container_access_tokens WHERE id = ?", (token_id,))
    row = cursor.fetchone()
    token_value = None
    if row:
        data = get_row_dict(row, cursor)
        if data:
            token_value = data.get("token")
        elif isinstance(row, (list, tuple)):
            token_value = row[0]

    if token_value:
        cursor.execute(
            "DELETE FROM container_items WHERE access_token = ?",
            (token_value,),
        )
        cursor.execute(
            "DELETE FROM container_access_sessions WHERE token = ?",
            (token_value,),
        )

    cursor.execute("DELETE FROM container_access_tokens WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


def clear_sessions_for_token(token_id: int) -> None:
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT token FROM container_access_tokens WHERE id = ?", (token_id,))
    row = cursor.fetchone()
    if row:
        data = get_row_dict(row, cursor)
        token = data.get("token") if data else row[0]
        cursor.execute("DELETE FROM container_access_sessions WHERE token = ?", (token,))
    cursor.execute(
        "UPDATE container_access_tokens SET blocked_until = NULL WHERE id = ?",
        (token_id,),
    )
    conn.commit()
    conn.close()


def kick_token(token_id: int, minutes: Optional[int]) -> bool:
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute("SELECT token FROM container_access_tokens WHERE id = ?", (token_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    data = get_row_dict(row, cursor)
    token = data.get("token") if data else row[0]

    block_minutes = 0
    if minutes is not None:
        try:
            block_minutes = int(minutes)
        except (TypeError, ValueError):
            block_minutes = 0

    if block_minutes > 0:
        blocked_until = get_chile_time_naive() + timedelta(minutes=block_minutes)
        cursor.execute(
            "UPDATE container_access_tokens SET blocked_until = ? WHERE id = ?",
            (blocked_until, token_id),
        )
    else:
        cursor.execute(
            "UPDATE container_access_tokens SET blocked_until = NULL WHERE id = ?",
            (token_id,),
        )

    cursor.execute("DELETE FROM container_access_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return True


def _purge_expired_sessions(conn, token: Optional[str] = None) -> None:
    cutoff = get_chile_time_naive() - timedelta(minutes=_session_timeout_minutes(conn))
    cursor = get_cursor(conn)
    if token:
        cursor.execute(
            "DELETE FROM container_access_sessions WHERE token = ? AND last_heartbeat < ?",
            (token, cutoff),
        )
    else:
        cursor.execute(
            "DELETE FROM container_access_sessions WHERE last_heartbeat < ?",
            (cutoff,),
        )
    conn.commit()


def validate_access_key(access_key: str) -> Tuple[bool, str, Optional[Dict]]:
    if not access_key:
        return False, "missing access key", None

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        SELECT id, token, status, expires_at, blocked_until, max_concurrent
        FROM container_access_tokens
        WHERE token = ?
        """,
        (access_key,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "invalid access key", None

    data = get_row_dict(row, cursor)
    if not data:
        conn.close()
        return False, "invalid access key", None

    if data.get("status") != "active":
        conn.close()
        return False, "access disabled", None

    expires_at = data.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires_at = None
        if expires_at and get_chile_time_naive() > expires_at:
            conn.close()
            return False, "access expired", None

    blocked_until = data.get("blocked_until")
    if blocked_until:
        if isinstance(blocked_until, str):
            try:
                blocked_until = datetime.strptime(blocked_until, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                blocked_until = None
        if blocked_until and get_chile_time_naive() < blocked_until:
            conn.close()
            return False, "access blocked", None

    _purge_expired_sessions(conn, data.get("token"))

    max_concurrent = data.get("max_concurrent")
    if max_concurrent is not None:
        try:
            max_concurrent = int(max_concurrent)
        except (TypeError, ValueError):
            max_concurrent = None
    if max_concurrent:
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM container_access_sessions WHERE token = ?",
            (data.get("token"),),
        )
        count = _extract_count(cursor.fetchone())
        if count >= max_concurrent:
            conn.close()
            return False, "max concurrent reached", None

    conn.close()
    return True, "ok", data


def validate_access_key_status(access_key: str) -> Tuple[bool, str]:
    if not access_key:
        return False, "missing access key"

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        SELECT status, expires_at, blocked_until
        FROM container_access_tokens
        WHERE token = ?
        """,
        (access_key,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "invalid access key"

    data = get_row_dict(row, cursor) or {}
    status = data.get("status")
    expires_at = data.get("expires_at")
    blocked_until = data.get("blocked_until")
    conn.close()

    if status != "active":
        return False, "access disabled"

    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires_at = None
        if expires_at and get_chile_time_naive() > expires_at:
            return False, "access expired"

    if blocked_until:
        if isinstance(blocked_until, str):
            try:
                blocked_until = datetime.strptime(blocked_until, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                blocked_until = None
        if blocked_until and get_chile_time_naive() < blocked_until:
            return False, "access blocked"

    return True, "ok"


def create_access_session(access_key: str, ip: str, user_agent: str) -> str:
    session_id = secrets.token_urlsafe(18)
    now = get_chile_time_naive()

    conn = get_db_connection()
    cursor = get_cursor(conn)
    _purge_expired_sessions(conn, access_key)
    cutoff = get_chile_time_naive() - timedelta(minutes=_session_timeout_minutes(conn))
    cursor.execute(
        """
        SELECT session_id
        FROM container_access_sessions
        WHERE token = ? AND ip = ? AND user_agent = ? AND last_heartbeat >= ?
        ORDER BY last_heartbeat DESC
        LIMIT 1
        """,
        (access_key, ip, user_agent, cutoff),
    )
    row = cursor.fetchone()
    if row:
        existing_id = None
        if isinstance(row, (list, tuple)):
            existing_id = row[0]
        else:
            data = get_row_dict(row, cursor)
            existing_id = data.get("session_id") if data else None
        if existing_id:
            cursor.execute(
                "UPDATE container_access_sessions SET last_heartbeat = ? WHERE session_id = ?",
                (now, existing_id),
            )
            cursor.execute(
                "UPDATE container_access_tokens SET last_used_at = ? WHERE token = ?",
                (now, access_key),
            )
            conn.commit()
            conn.close()
            return existing_id

    cursor.execute(
        """
        INSERT INTO container_access_sessions (token, session_id, last_heartbeat, ip, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (access_key, session_id, now, ip, user_agent, now),
    )
    cursor.execute(
        "UPDATE container_access_tokens SET last_used_at = ? WHERE token = ?",
        (now, access_key),
    )
    conn.commit()
    conn.close()
    return session_id


def get_recent_session_id(access_key: str, ip: str, user_agent: str) -> Optional[str]:
    if not access_key:
        return None
    now = get_chile_time_naive()
    conn = get_db_connection()
    cursor = get_cursor(conn)
    _purge_expired_sessions(conn, access_key)
    cutoff = get_chile_time_naive() - timedelta(minutes=_session_timeout_minutes(conn))
    cursor.execute(
        """
        SELECT session_id
        FROM container_access_sessions
        WHERE token = ? AND ip = ? AND user_agent = ? AND last_heartbeat >= ?
        ORDER BY last_heartbeat DESC
        LIMIT 1
        """,
        (access_key, ip, user_agent, cutoff),
    )
    row = cursor.fetchone()
    existing_id = None
    if row:
        if isinstance(row, (list, tuple)):
            existing_id = row[0]
        else:
            data = get_row_dict(row, cursor)
            existing_id = data.get("session_id") if data else None
    if existing_id:
        cursor.execute(
            "UPDATE container_access_sessions SET last_heartbeat = ? WHERE session_id = ?",
            (now, existing_id),
        )
        cursor.execute(
            "UPDATE container_access_tokens SET last_used_at = ? WHERE token = ?",
            (now, access_key),
        )
        conn.commit()
    conn.close()
    return existing_id


def mark_token_used(access_key: str) -> None:
    if not access_key:
        return
    now = get_chile_time_naive()
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        "UPDATE container_access_tokens SET last_used_at = ? WHERE token = ?",
        (now, access_key),
    )
    conn.commit()
    conn.close()


def get_session(session_id: str) -> Optional[Dict]:
    if not session_id:
        return None
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        SELECT token, last_heartbeat
        FROM container_access_sessions
        WHERE session_id = ?
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    data = get_row_dict(row, cursor)
    conn.close()
    return data


def touch_session(session_id: str) -> bool:
    if not session_id:
        return False
    now = get_chile_time_naive()
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        "UPDATE container_access_sessions SET last_heartbeat = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    return updated > 0


def is_session_active(session_id: str) -> bool:
    session = get_session(session_id)
    if not session:
        return False
    last = session.get("last_heartbeat") if isinstance(session, dict) else None
    if isinstance(last, str):
        try:
            last = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            last = None
    if not last:
        return False
    cutoff = get_chile_time_naive() - timedelta(minutes=_session_timeout_minutes())
    if last < cutoff:
        return False

    token_value = session.get("token") if isinstance(session, dict) else None
    if not token_value:
        return False

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        "SELECT status, expires_at FROM container_access_tokens WHERE token = ?",
        (token_value,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    data = get_row_dict(row, cursor) or {}
    conn.close()
    if data.get("status") != "active":
        return False
    expires_at = data.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            expires_at = None
    if expires_at and get_chile_time_naive() > expires_at:
        return False
    return True
