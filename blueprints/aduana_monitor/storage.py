# -*- coding: utf-8 -*-
"""Persistence helpers for Aduana Monitor using the parent app's DB connection.

No SQLAlchemy and no second DATABASE_URL are introduced. The blueprint reuses
`database.get_db_connection()` so Render continues to use the same TiDB pool
already used by the main FLASK service.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from config import config as app_config
from database import get_db_connection, get_cursor, get_lastrowid
from utils.time_utils import get_chile_time_naive

from . import settings

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def now():
    return get_chile_time_naive()


def _row_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return row


def _rows_dict(rows):
    return [_row_dict(row) for row in (rows or [])]


@contextmanager
def transaction():
    conn = get_db_connection()
    cursor = get_cursor(conn)
    try:
        yield conn, cursor
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _id_type():
    db_type = str(getattr(app_config, "DATABASE_TYPE", "sqlite") or "sqlite").lower()
    if db_type in ("mysql", "tidb"):
        return "BIGINT PRIMARY KEY AUTO_INCREMENT"
    if db_type == "postgresql":
        return "BIGSERIAL PRIMARY KEY"
    return "INTEGER PRIMARY KEY AUTOINCREMENT"


def ensure_schema(force=False):
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY and not force:
            return
        id_type = _id_type()
        with transaction() as (_conn, cur):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_users (
                    id {id_type},
                    telegram_user_id BIGINT NOT NULL UNIQUE,
                    chat_id BIGINT NOT NULL,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    role VARCHAR(20) NOT NULL DEFAULT 'USER',
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    permission_level VARCHAR(30) NOT NULL DEFAULT 'THREE_MONTHS',
                    max_ruts INTEGER NOT NULL DEFAULT 3,
                    can_query INTEGER NOT NULL DEFAULT 1,
                    can_monitor INTEGER NOT NULL DEFAULT 1,
                    pending_action VARCHAR(64),
                    pending_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP NULL,
                    last_activity_at TIMESTAMP NULL
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_monitors (
                    id {id_type},
                    user_id BIGINT NOT NULL,
                    rut VARCHAR(32) NOT NULL,
                    aduana VARCHAR(16) NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    baseline_done INTEGER NOT NULL DEFAULT 0,
                    baseline_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, rut, aduana)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_scan_targets (
                    id {id_type},
                    rut VARCHAR(32) NOT NULL,
                    aduana VARCHAR(16) NOT NULL,
                    baseline_done INTEGER NOT NULL DEFAULT 0,
                    first_checked_at TIMESTAMP NULL,
                    last_checked_at TIMESTAMP NULL,
                    last_row_count INTEGER NOT NULL DEFAULT 0,
                    last_status VARCHAR(40),
                    last_error TEXT,
                    UNIQUE (rut, aduana)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_records (
                    id {id_type},
                    rut VARCHAR(32) NOT NULL,
                    aduana VARCHAR(16) NOT NULL,
                    n_denuncia VARCHAR(80) NOT NULL,
                    doc_aduanero VARCHAR(255) NOT NULL,
                    emision VARCHAR(40),
                    notificacion VARCHAR(40),
                    art_infraccion TEXT,
                    infractor TEXT,
                    multa_max_legal VARCHAR(120),
                    multa_c_allan VARCHAR(120),
                    multa_s_allan VARCHAR(120),
                    venc_allan VARCHAR(80),
                    venc_recl_junta VARCHAR(80),
                    audiencia VARCHAR(255),
                    n_despacho VARCHAR(255),
                    aduana_nombre VARCHAR(255),
                    row_hash VARCHAR(64) NOT NULL,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (rut, aduana, n_denuncia, doc_aduanero)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_notifications (
                    id {id_type},
                    record_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    monitor_id BIGINT,
                    chat_id BIGINT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP NULL,
                    UNIQUE (record_id, user_id)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS aduana_runs (
                    id {id_type},
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
                    targets_checked INTEGER NOT NULL DEFAULT 0,
                    unique_queries INTEGER NOT NULL DEFAULT 0,
                    records_found INTEGER NOT NULL DEFAULT 0,
                    new_records_found INTEGER NOT NULL DEFAULT 0,
                    notifications_sent INTEGER NOT NULL DEFAULT 0,
                    notifications_failed INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                )
            """)
        _SCHEMA_READY = True


def get_user_by_telegram_id(telegram_user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_users WHERE telegram_user_id = ?", (int(telegram_user_id),))
        return _row_dict(cur.fetchone())


def get_user(user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_users WHERE id = ?", (int(user_id),))
        return _row_dict(cur.fetchone())


def get_or_create_telegram_user(telegram_user_id, chat_id, username="", first_name=""):
    ensure_schema()
    tg_id = int(telegram_user_id)
    chat_id = int(chat_id)
    is_owner = bool(settings.OWNER_TELEGRAM_ID and tg_id == settings.OWNER_TELEGRAM_ID)
    with transaction() as (conn, cur):
        cur.execute("SELECT * FROM aduana_users WHERE telegram_user_id = ?", (tg_id,))
        row = _row_dict(cur.fetchone())
        current = now()
        if row is None:
            role = "OWNER" if is_owner else "USER"
            status = "ACTIVE" if is_owner else "PENDING"
            permission = settings.OWNER_PERMISSION if is_owner else settings.DEFAULT_PERMISSION
            max_ruts = 999999 if is_owner else settings.DEFAULT_MAX_RUTS
            cur.execute(
                """
                INSERT INTO aduana_users
                    (telegram_user_id, chat_id, username, first_name, role, status,
                     permission_level, max_ruts, can_query, can_monitor,
                     approved_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (tg_id, chat_id, username or None, first_name or None, role, status,
                 permission, max_ruts, current if is_owner else None, current),
            )
            user_id = get_lastrowid(cur, conn)
            cur.execute("SELECT * FROM aduana_users WHERE id = ?", (user_id,))
            return _row_dict(cur.fetchone()), True

        if is_owner:
            cur.execute(
                """
                UPDATE aduana_users
                SET chat_id=?, username=?, first_name=?, role='OWNER', status='ACTIVE',
                    permission_level='UNLIMITED', max_ruts=999999, can_query=1,
                    can_monitor=1, approved_at=COALESCE(approved_at, ?), last_activity_at=?
                WHERE id=?
                """,
                (chat_id, username or None, first_name or None, current, current, row["id"]),
            )
        else:
            cur.execute(
                "UPDATE aduana_users SET chat_id=?, username=?, first_name=?, last_activity_at=? WHERE id=?",
                (chat_id, username or None, first_name or None, current, row["id"]),
            )
        cur.execute("SELECT * FROM aduana_users WHERE id = ?", (row["id"],))
        return _row_dict(cur.fetchone()), False


def set_pending(user_id, action=None, data=None):
    ensure_schema()
    payload = json.dumps(data or {}, ensure_ascii=False) if action else None
    with transaction() as (_conn, cur):
        cur.execute(
            "UPDATE aduana_users SET pending_action=?, pending_data=?, last_activity_at=? WHERE id=?",
            (action, payload, now(), int(user_id)),
        )


def pending_data(user):
    raw = (user or {}).get("pending_data")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def distinct_ruts(user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT DISTINCT rut FROM aduana_monitors WHERE user_id=? ORDER BY rut", (int(user_id),))
        rows = cur.fetchall() or []
        values = []
        for row in rows:
            data = _row_dict(row)
            values.append(data.get("rut") if isinstance(data, dict) else row[0])
        return [value for value in values if value]


def list_user_monitors(user_id, include_disabled=True):
    ensure_schema()
    sql = "SELECT * FROM aduana_monitors WHERE user_id=?"
    params = [int(user_id)]
    if not include_disabled:
        sql += " AND enabled=1"
    sql += " ORDER BY rut, aduana"
    with transaction() as (_conn, cur):
        cur.execute(sql, tuple(params))
        return _rows_dict(cur.fetchall())


def get_monitor_for_user(monitor_id, user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_monitors WHERE id=? AND user_id=?", (int(monitor_id), int(user_id)))
        return _row_dict(cur.fetchone())


def add_or_enable_monitor(user_id, rut, aduana):
    ensure_schema()
    current = now()
    with transaction() as (conn, cur):
        cur.execute(
            "SELECT * FROM aduana_monitors WHERE user_id=? AND rut=? AND aduana=?",
            (int(user_id), rut, aduana),
        )
        existing = _row_dict(cur.fetchone())
        if existing:
            if bool(existing.get("enabled")):
                return existing["id"], False
            cur.execute(
                "UPDATE aduana_monitors SET enabled=1, baseline_done=0, baseline_at=NULL, updated_at=? WHERE id=?",
                (current, existing["id"]),
            )
            return existing["id"], False
        cur.execute(
            """
            INSERT INTO aduana_monitors
                (user_id, rut, aduana, enabled, baseline_done, created_at, updated_at)
            VALUES (?, ?, ?, 1, 0, ?, ?)
            """,
            (int(user_id), rut, aduana, current, current),
        )
        return get_lastrowid(cur, conn), True


def set_monitor_enabled(monitor_id, user_id, enabled):
    ensure_schema()
    with transaction() as (_conn, cur):
        if enabled:
            cur.execute(
                """
                UPDATE aduana_monitors
                SET enabled=1, baseline_done=0, baseline_at=NULL, updated_at=?
                WHERE id=? AND user_id=?
                """,
                (now(), int(monitor_id), int(user_id)),
            )
        else:
            cur.execute(
                "UPDATE aduana_monitors SET enabled=0, updated_at=? WHERE id=? AND user_id=?",
                (now(), int(monitor_id), int(user_id)),
            )
        return cur.rowcount > 0


def delete_monitor(monitor_id, user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("DELETE FROM aduana_monitors WHERE id=? AND user_id=?", (int(monitor_id), int(user_id)))
        return cur.rowcount > 0


def admin_counts():
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM aduana_users WHERE status='PENDING'")
        pending = int(_row_dict(cur.fetchone()).get("n") or 0)
        cur.execute("SELECT COUNT(*) AS n FROM aduana_users WHERE status='ACTIVE'")
        active = int(_row_dict(cur.fetchone()).get("n") or 0)
        cur.execute("SELECT COUNT(*) AS n FROM aduana_monitors WHERE enabled=1")
        monitors = int(_row_dict(cur.fetchone()).get("n") or 0)
        cur.execute("SELECT COUNT(DISTINCT rut) AS n FROM aduana_monitors WHERE enabled=1")
        ruts = int(_row_dict(cur.fetchone()).get("n") or 0)
        return {"pending": pending, "active": active, "monitors": monitors, "ruts": ruts}


def list_pending_users():
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_users WHERE status='PENDING' ORDER BY created_at")
        return _rows_dict(cur.fetchall())


def list_users():
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(DISTINCT m.rut) FROM aduana_monitors m WHERE m.user_id=u.id) AS rut_count,
                   (SELECT COUNT(*) FROM aduana_monitors m WHERE m.user_id=u.id AND m.enabled=1) AS monitor_count
            FROM aduana_users u
            ORDER BY CASE WHEN u.role='OWNER' THEN 0 ELSE 1 END, u.created_at DESC
            """
        )
        return _rows_dict(cur.fetchall())


def approve_user(user_id, permission_level=None, max_ruts=None, can_query=True, can_monitor=True):
    ensure_schema()
    user = get_user(user_id)
    if not user:
        return None
    if user.get("role") == "OWNER":
        permission_level = settings.OWNER_PERMISSION
        max_ruts = 999999
    else:
        permission_level = permission_level if permission_level in settings.PERMISSION_LEVELS else settings.DEFAULT_PERMISSION
        try:
            max_ruts = max(1, min(int(max_ruts or settings.DEFAULT_MAX_RUTS), 999))
        except Exception:
            max_ruts = settings.DEFAULT_MAX_RUTS
    with transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_users
            SET status='ACTIVE', permission_level=?, max_ruts=?, can_query=?, can_monitor=?, approved_at=?
            WHERE id=?
            """,
            (permission_level, max_ruts, 1 if can_query else 0, 1 if can_monitor else 0, now(), int(user_id)),
        )
        cur.execute("SELECT * FROM aduana_users WHERE id=?", (int(user_id),))
        return _row_dict(cur.fetchone())


def reject_user(user_id):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("UPDATE aduana_users SET status='REJECTED' WHERE id=? AND role<>'OWNER'", (int(user_id),))
        return cur.rowcount > 0


def update_user_permissions(user_id, status, permission_level, max_ruts, can_query, can_monitor):
    ensure_schema()
    user = get_user(user_id)
    if not user:
        return None
    if user.get("role") == "OWNER":
        status = "ACTIVE"
        permission_level = settings.OWNER_PERMISSION
        max_ruts = 999999
        can_query = can_monitor = True
    else:
        status = status if status in ("ACTIVE", "DISABLED", "PENDING", "REJECTED") else user.get("status", "DISABLED")
        permission_level = permission_level if permission_level in settings.PERMISSION_LEVELS else settings.DEFAULT_PERMISSION
        try:
            max_ruts = max(1, min(int(max_ruts), 999))
        except Exception:
            max_ruts = settings.DEFAULT_MAX_RUTS
    with transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_users
            SET status=?, permission_level=?, max_ruts=?, can_query=?, can_monitor=?
            WHERE id=?
            """,
            (status, permission_level, max_ruts, 1 if can_query else 0, 1 if can_monitor else 0, int(user_id)),
        )
        cur.execute("SELECT * FROM aduana_users WHERE id=?", (int(user_id),))
        return _row_dict(cur.fetchone())


def latest_run():
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_runs ORDER BY started_at DESC, id DESC LIMIT 1")
        return _row_dict(cur.fetchone())


def list_runs(limit=100):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute("SELECT * FROM aduana_runs ORDER BY started_at DESC, id DESC LIMIT ?", (int(limit),))
        return _rows_dict(cur.fetchall())


def try_start_run():
    ensure_schema()
    cutoff = now() - timedelta(minutes=settings.RUN_LOCK_STALE_MINUTES)
    with transaction() as (conn, cur):
        cur.execute("SELECT * FROM aduana_runs WHERE status='RUNNING' ORDER BY started_at DESC, id DESC LIMIT 1")
        running = _row_dict(cur.fetchone())
        if running:
            started = running.get("started_at")
            if isinstance(started, str):
                try:
                    started = datetime.fromisoformat(started.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    started = None
            if started and started >= cutoff:
                return None, running
            cur.execute(
                "UPDATE aduana_runs SET status='ABANDONED', finished_at=?, error_message=? WHERE id=?",
                (now(), "Stale RUNNING lock replaced by a new run", running["id"]),
            )
        cur.execute("INSERT INTO aduana_runs (started_at, status) VALUES (?, 'RUNNING')", (now(),))
        run_id = get_lastrowid(cur, conn)
        return run_id, None


def finish_run(run_id, *, status, targets_checked=0, unique_queries=0, records_found=0,
               new_records=0, sent=0, failed=0, error=None):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_runs
            SET finished_at=?, status=?, targets_checked=?, unique_queries=?, records_found=?,
                new_records_found=?, notifications_sent=?, notifications_failed=?, error_message=?
            WHERE id=?
            """,
            (now(), status, int(targets_checked), int(unique_queries), int(records_found),
             int(new_records), int(sent), int(failed), error, int(run_id)),
        )


def active_targets():
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute(
            """
            SELECT m.id AS monitor_id, m.user_id, m.rut, m.aduana,
                   m.baseline_done AS monitor_baseline_done,
                   u.chat_id, u.role
            FROM aduana_monitors m
            JOIN aduana_users u ON u.id=m.user_id
            WHERE m.enabled=1 AND u.status='ACTIVE' AND u.can_monitor=1
            ORDER BY m.rut, m.aduana, m.id
            """
        )
        subscriptions = _rows_dict(cur.fetchall())
    targets = {}
    for sub in subscriptions:
        codes = settings.ADUANA_CODES if sub.get("aduana") == "ALL" and sub.get("role") == "OWNER" else [sub.get("aduana")]
        for code in codes:
            if code not in settings.ADUANA_CODES:
                continue
            key = (sub.get("rut"), code)
            targets.setdefault(key, []).append(sub)
    return targets


def _get_or_create_scan_target(cur, conn, rut, aduana):
    cur.execute("SELECT * FROM aduana_scan_targets WHERE rut=? AND aduana=?", (rut, aduana))
    target = _row_dict(cur.fetchone())
    if target:
        return target
    cur.execute("INSERT INTO aduana_scan_targets (rut, aduana, baseline_done) VALUES (?, ?, 0)", (rut, aduana))
    target_id = get_lastrowid(cur, conn)
    cur.execute("SELECT * FROM aduana_scan_targets WHERE id=?", (target_id,))
    return _row_dict(cur.fetchone())


def mark_target_failure(rut, aduana, logs):
    ensure_schema()
    errors = []
    for item in logs or []:
        if item.get("estado") != "OK":
            errors.append(f"{item.get('desde')}-{item.get('hasta')}: {item.get('estado')} {item.get('error','')}")
    message = "; ".join(errors)[:4000] or "REQUEST_OR_PARSE_FAILED"
    with transaction() as (conn, cur):
        target = _get_or_create_scan_target(cur, conn, rut, aduana)
        cur.execute(
            "UPDATE aduana_scan_targets SET last_checked_at=?, last_status='REQUEST_OR_PARSE_FAILED', last_error=? WHERE id=?",
            (now(), message, target["id"]),
        )


def apply_successful_scan(rut, aduana, rows, subscriptions, row_hash_func):
    """Persist one complete target scan atomically and create notifications.

    Partial/failed scans never call this function, so they cannot poison a
    baseline or insert records that later suppress a notification.
    """
    ensure_schema()
    current = now()
    new_records = []
    with transaction() as (conn, cur):
        target = _get_or_create_scan_target(cur, conn, rut, aduana)
        target_was_baselined = bool(target.get("baseline_done"))

        for row in rows:
            n_denuncia = str(row.get("n_denuncia") or "").strip()
            doc = str(row.get("doc_aduanero") or "").strip()
            if not n_denuncia or not doc:
                continue
            cur.execute(
                "SELECT * FROM aduana_records WHERE rut=? AND aduana=? AND n_denuncia=? AND doc_aduanero=?",
                (rut, aduana, n_denuncia, doc),
            )
            existing = _row_dict(cur.fetchone())
            h = row_hash_func(row)
            values = [
                row.get("emision"), row.get("notificacion"), row.get("art_infraccion"),
                row.get("infractor"), row.get("multa_max_legal"), row.get("multa_c_allan"),
                row.get("multa_s_allan"), row.get("venc_allan"), row.get("venc_recl_junta"),
                row.get("audiencia"), row.get("n_despacho"), row.get("aduana_nombre"),
            ]
            if existing:
                cur.execute(
                    """
                    UPDATE aduana_records
                    SET emision=?, notificacion=?, art_infraccion=?, infractor=?, multa_max_legal=?,
                        multa_c_allan=?, multa_s_allan=?, venc_allan=?, venc_recl_junta=?, audiencia=?,
                        n_despacho=?, aduana_nombre=?, row_hash=?, last_seen_at=?
                    WHERE id=?
                    """,
                    tuple(values + [h, current, existing["id"]]),
                )
                continue
            cur.execute(
                """
                INSERT INTO aduana_records
                    (rut, aduana, n_denuncia, doc_aduanero, emision, notificacion,
                     art_infraccion, infractor, multa_max_legal, multa_c_allan, multa_s_allan,
                     venc_allan, venc_recl_junta, audiencia, n_despacho, aduana_nombre,
                     row_hash, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple([rut, aduana, n_denuncia, doc] + values + [h, current, current]),
            )
            record_id = get_lastrowid(cur, conn)
            new_records.append(record_id)

        suppress_global = not target_was_baselined
        for sub in subscriptions:
            monitor_id = int(sub["monitor_id"])
            cur.execute("SELECT baseline_done, enabled FROM aduana_monitors WHERE id=?", (monitor_id,))
            monitor_state = _row_dict(cur.fetchone())
            if not monitor_state or not bool(monitor_state.get("enabled")):
                continue
            monitor_was_baselined = bool(monitor_state.get("baseline_done"))
            if not suppress_global and monitor_was_baselined:
                for record_id in new_records:
                    cur.execute("SELECT id FROM aduana_notifications WHERE record_id=? AND user_id=?", (record_id, int(sub["user_id"])))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        """
                        INSERT INTO aduana_notifications
                            (record_id, user_id, monitor_id, chat_id, status, attempts, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 'PENDING', 0, ?, ?)
                        """,
                        (record_id, int(sub["user_id"]), monitor_id, int(sub["chat_id"]), current, current),
                    )
            if not monitor_was_baselined:
                cur.execute(
                    "UPDATE aduana_monitors SET baseline_done=1, baseline_at=?, updated_at=? WHERE id=?",
                    (current, current, monitor_id),
                )

        cur.execute(
            """
            UPDATE aduana_scan_targets
            SET baseline_done=1,
                first_checked_at=COALESCE(first_checked_at, ?),
                last_checked_at=?, last_row_count=?, last_status=?, last_error=NULL
            WHERE id=?
            """,
            (current, current, len(rows), "OK" if rows else "SUCCESS_WITH_ZERO_ROWS", target["id"]),
        )
    return len(new_records)


def pending_notifications(limit=500):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute(
            """
            SELECT n.*, u.status AS user_status, u.can_monitor,
                   m.enabled AS monitor_enabled,
                   r.rut, r.aduana, r.n_denuncia, r.doc_aduanero, r.emision,
                   r.notificacion, r.art_infraccion, r.infractor, r.multa_max_legal,
                   r.multa_c_allan, r.multa_s_allan, r.venc_allan, r.venc_recl_junta,
                   r.audiencia, r.n_despacho, r.aduana_nombre
            FROM aduana_notifications n
            JOIN aduana_users u ON u.id=n.user_id
            JOIN aduana_records r ON r.id=n.record_id
            LEFT JOIN aduana_monitors m ON m.id=n.monitor_id
            WHERE n.status IN ('PENDING','FAILED')
            ORDER BY n.created_at, n.id
            LIMIT ?
            """,
            (int(limit),),
        )
        return _rows_dict(cur.fetchall())


def mark_notification(notification_id, status, attempts, error=None, sent_at=None):
    ensure_schema()
    with transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_notifications
            SET status=?, attempts=?, last_error=?, updated_at=?, sent_at=?
            WHERE id=?
            """,
            (status, int(attempts), error, now(), sent_at, int(notification_id)),
        )
