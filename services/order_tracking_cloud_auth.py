"""Native ORDER login mirror for Render.

Render uses the same ORDER username/password hashes/roles as the local ORDER system,
but authentication data is kept in an isolated cloud_order_users table so it never
collides with the parent Flask app's own users table.

Only the existing one-way password hash is stored; plaintext passwords are never
synced or logged. Cloud ORDER stays read-only: password reset/registration must be
done in the local ORDER system and will be reflected on the next sync.
"""
from __future__ import annotations

from database import get_cursor, get_db_connection, get_row_dict
from werkzeug.security import check_password_hash


def init_order_auth_table() -> None:
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_order_users (
                username VARCHAR(191) PRIMARY KEY,
                local_user_id BIGINT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NULL,
                real_name VARCHAR(255) NULL,
                role VARCHAR(64) NOT NULL DEFAULT 'viewer',
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                needs_password_reset BOOLEAN NOT NULL DEFAULT FALSE,
                source_site VARCHAR(16) NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sync_order_users(users, source_site=None):
    """Replace the small ORDER authentication mirror with the supplied local snapshot."""
    if not isinstance(users, list):
        raise ValueError("users must be a list")
    if len(users) > 1000:
        raise ValueError("too many ORDER users in one sync")

    source_site = (str(source_site or "").strip().upper()[:16] or None)
    normalized = []
    seen = set()
    for raw in users:
        if not isinstance(raw, dict):
            continue
        username = str(raw.get("username") or "").strip()
        password_hash = str(raw.get("password_hash") or "").strip()
        if not username or not password_hash or username in seen:
            continue
        seen.add(username)
        normalized.append({
            "username": username,
            "local_user_id": raw.get("id"),
            "password_hash": password_hash,
            "display_name": str(raw.get("display_name") or username).strip()[:255],
            "real_name": str(raw.get("real_name") or "").strip()[:255] or None,
            "role": str(raw.get("role") or "viewer").strip()[:64] or "viewer",
            "status": str(raw.get("status") or "active").strip().lower()[:32] or "active",
            "needs_password_reset": bool(raw.get("needs_password_reset")),
        })

    init_order_auth_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT username FROM cloud_order_users")
        existing = {
            str((get_row_dict(row, cur) or {}).get("username") or "")
            for row in cur.fetchall()
        }

        for user in normalized:
            username = user["username"]
            values = (
                user["local_user_id"],
                user["password_hash"],
                user["display_name"],
                user["real_name"],
                user["role"],
                user["status"],
                user["needs_password_reset"],
                source_site,
                username,
            )
            if username in existing:
                cur.execute(
                    """UPDATE cloud_order_users
                       SET local_user_id=?, password_hash=?, display_name=?, real_name=?,
                           role=?, status=?, needs_password_reset=?, source_site=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE username=?""",
                    values,
                )
            else:
                cur.execute(
                    """INSERT INTO cloud_order_users
                       (local_user_id, password_hash, display_name, real_name, role,
                        status, needs_password_reset, source_site, username)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )

        for username in existing - seen:
            cur.execute("DELETE FROM cloud_order_users WHERE username=?", (username,))

        conn.commit()
        return {"users": len(normalized), "deleted": len(existing - seen)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def authenticate_order_user(username: str, password: str):
    """Validate credentials with the same Werkzeug password hash used by local ORDER."""
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        return None, "invalid"

    init_order_auth_table()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT username, local_user_id, password_hash, display_name, real_name,
                      role, status, needs_password_reset
               FROM cloud_order_users WHERE username=?""",
            (username,),
        )
        row = cur.fetchone()
        user = get_row_dict(row, cur) if row else None
    finally:
        conn.close()

    if not user:
        return None, "invalid"

    status = str(user.get("status") or "active").strip().lower()
    if status in {"pending", "rejected", "suspended"}:
        return None, status
    if bool(user.get("needs_password_reset")):
        return None, "needs_password_reset"
    try:
        if not check_password_hash(str(user.get("password_hash") or ""), password):
            return None, "invalid"
    except Exception:
        return None, "invalid"

    return {
        "id": user.get("local_user_id"),
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("real_name") or user.get("username"),
        "real_name": user.get("real_name"),
        "role": user.get("role") or "viewer",
    }, None
