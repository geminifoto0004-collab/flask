from functools import wraps
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, session

import config
from database import (
    MYSQL_AVAILABLE,
    POOLEDDB_AVAILABLE,
    _MYSQL_POOL,
    get_db_connection,
    get_cursor,
    get_row_dict,
)
from services.container_access_service import (
    clear_sessions_for_token,
    create_access_session,
    create_token,
    delete_token,
    ensure_admin_from_env,
    get_recent_session_id,
    admin_initialized,
    is_session_active,
    kick_token,
    list_tokens,
    mark_token_used,
    touch_session,
    update_token,
    validate_access_key,
    validate_access_key_status,
    verify_admin_password,
)
from services.container_iti_service import (
    build_iti_index,
    get_iti_cache_info,
    get_iti_duplicate_numeros,
    get_iti_index,
    get_iti_index_cached,
    get_iti_matches_cached,
    get_iti_matches,
    match_iti,
    normalize_container,
)
from utils.time_utils import get_chile_time_naive

container_bp = Blueprint("container", __name__)

def _get_access_key() -> Optional[str]:
    key = session.get("container_access_token") or request.headers.get("X-Access-Key", "").strip()
    return key or None


def _require_access_key():
    key = _get_access_key()
    if not key:
        return None, (jsonify({"ok": False, "msg": "access key required"}), 401)
    return key, None


def _get_latest_save_id(cursor, access_key: str) -> Optional[str]:
    cursor.execute(
        "SELECT latest_save_id FROM container_access_tokens WHERE token = ?",
        (access_key,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    data = get_row_dict(row, cursor)
    if data:
        return data.get("latest_save_id") or None
    if isinstance(row, (list, tuple)):
        return row[0] or None
    return None


def _ensure_latest_save_id(conn, cursor, access_key: str) -> Optional[str]:
    latest = _get_latest_save_id(cursor, access_key)
    if latest:
        return latest

    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM container_items
        WHERE access_token = ?
          AND (save_id IS NULL OR save_id = '')
        """,
        (access_key,),
    )
    row = cursor.fetchone()
    count = 0
    data = get_row_dict(row, cursor)
    if data:
        count = list(data.values())[0]
    elif isinstance(row, (list, tuple)):
        count = row[0]
    elif isinstance(row, int):
        count = row

    if count:
        new_save_id = str(uuid.uuid4())
        saved_at = get_chile_time_naive()
        cursor.execute(
            """
            UPDATE container_items
            SET save_id = ?,
                saved_at = ?
            WHERE access_token = ?
              AND (save_id IS NULL OR save_id = '')
            """,
            (new_save_id, saved_at, access_key),
        )
        cursor.execute(
            "UPDATE container_access_tokens SET latest_save_id = ? WHERE token = ?",
            (new_save_id, access_key),
        )
        conn.commit()
        return new_save_id

    return None


def _client_ip() -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers.get("X-Real-IP")
    if request.headers.get("CF-Connecting-IP"):
        return request.headers.get("CF-Connecting-IP")
    return request.remote_addr or ""


def container_access_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("container_admin_ok"):
            return fn(*args, **kwargs)

        session_id = session.get("container_access_session_id")
        if not session_id or not is_session_active(session_id):
            access_key = request.headers.get("X-Access-Key", "").strip()
            if access_key and request.path.startswith("/api/"):
                ok, _msg, _token = validate_access_key(access_key)
                if ok:
                    mark_token_used(access_key)
                    return fn(*args, **kwargs)
            session.pop("container_access_session_id", None)
            session.pop("container_access_token", None)
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "msg": "access required"}), 401
            return render_template("container/access_denied.html"), 403

        access_key = session.get("container_access_token", "")
        ok, msg = validate_access_key_status(access_key)
        if not ok:
            session.pop("container_access_session_id", None)
            session.pop("container_access_token", None)
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "msg": msg}), 401
            return render_template("container/access_denied.html", reason=msg), 403

        if not request.path.startswith("/api/"):
            touch_session(session_id)
        else:
            last_touch = session.get("container_access_last_touch_ts", 0)
            now_ts = time.time()
            if now_ts - float(last_touch or 0) >= 60:
                touch_session(session_id)
                session["container_access_last_touch_ts"] = now_ts
        return fn(*args, **kwargs)

    return wrapper


def container_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("container_admin_ok"):
            return jsonify({"ok": False, "msg": "admin access required"}), 401
        return fn(*args, **kwargs)

    return wrapper


@container_bp.route("/gate/<access_key>")
def gate(access_key: str):
    existing_session = session.get("container_access_session_id")
    existing_token = session.get("container_access_token")
    if (
        existing_session
        and existing_token == access_key
        and is_session_active(existing_session)
    ):
        ok, msg, _token = validate_access_key(access_key)
        if ok or msg == "max concurrent reached":
            touch_session(existing_session)
            return render_template("container/excel_mode.html")
        session.pop("container_access_session_id", None)
        session.pop("container_access_token", None)

    ok, msg, _token = validate_access_key(access_key)
    if not ok:
        if msg == "max concurrent reached":
            existing_id = get_recent_session_id(
                access_key, _client_ip(), request.headers.get("User-Agent", "")
            )
            if existing_id:
                session["container_access_session_id"] = existing_id
                session["container_access_token"] = access_key
                return render_template("container/excel_mode.html")
        return render_template("container/access_denied.html", reason=msg), 403

    session_id = create_access_session(
        access_key, _client_ip(), request.headers.get("User-Agent", "")
    )
    session["container_access_session_id"] = session_id
    session["container_access_token"] = access_key
    return render_template("container/excel_mode.html")


@container_bp.route("/container")
@container_access_required
def container_page():
    return render_template("container/excel_mode.html")


@container_bp.route("/container/access-denied")
def container_access_denied_page():
    session.pop("container_access_session_id", None)
    session.pop("container_access_token", None)
    return render_template("container/access_denied.html"), 403


@container_bp.route("/container/access/heartbeat", methods=["POST"])
@container_access_required
def container_heartbeat():
    session_id = session.get("container_access_session_id")
    if not session_id:
        return jsonify({"ok": False, "msg": "no session"}), 401
    touch_session(session_id)
    return jsonify({"ok": True})


@container_bp.route("/container/access-admin", methods=["GET"])
def container_admin_page():
    ensure_admin_from_env()
    if session.get("container_admin_ok"):
        return render_template("container/access_admin_manage.html")
    return render_template("container/access_admin_login.html")


@container_bp.route("/container/access-admin/login", methods=["POST"])
def container_admin_login():
    ensure_admin_from_env()
    password = request.form.get("password", "").strip()
    if verify_admin_password(password):
        session["container_admin_ok"] = True
        return redirect("/container/access-admin")
    if not admin_initialized():
        return render_template(
            "container/access_admin_login.html",
            error="Admin password not initialized",
        ), 403
    return render_template("container/access_admin_login.html", error="Invalid password"), 403


@container_bp.route("/container/access-admin/logout", methods=["POST"])
def container_admin_logout():
    session.pop("container_admin_ok", None)
    return redirect("/container/access-admin")


@container_bp.route("/container/access-admin/tokens", methods=["GET"])
@container_admin_required
def container_tokens_list():
    return jsonify({"ok": True, "tokens": list_tokens()})


@container_bp.route("/container/access-admin/tokens", methods=["POST"])
@container_admin_required
def container_tokens_create():
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip() or None
    expires_at = (data.get("expires_at") or "").strip() or None
    max_concurrent = data.get("max_concurrent")
    token = create_token(note, expires_at, max_concurrent)
    return jsonify({"ok": True, "token": token})


@container_bp.route("/container/access-admin/tokens/<int:token_id>", methods=["PUT"])
@container_admin_required
def container_tokens_update(token_id: int):
    data = request.get_json(silent=True) or {}
    note = data.get("note")
    status = data.get("status")
    expires_at = data.get("expires_at")
    max_concurrent = data.get("max_concurrent")
    ok = update_token(token_id, note, status, expires_at, max_concurrent)
    if not ok:
        return jsonify({"ok": False, "msg": "no changes"}), 400
    return jsonify({"ok": True})


@container_bp.route("/container/access-admin/tokens/<int:token_id>", methods=["DELETE"])
@container_admin_required
def container_tokens_delete(token_id: int):
    delete_token(token_id)
    return jsonify({"ok": True})


@container_bp.route("/container/access-admin/tokens/<int:token_id>/clear-sessions", methods=["POST"])
@container_admin_required
def container_tokens_clear_sessions(token_id: int):
    clear_sessions_for_token(token_id)
    return jsonify({"ok": True})


@container_bp.route("/container/access-admin/tokens/<int:token_id>/kick", methods=["POST"])
@container_admin_required
def container_tokens_kick(token_id: int):
    data = request.get_json(force=True) or {}
    minutes = data.get("minutes")
    if not kick_token(token_id, minutes):
        return jsonify({"ok": False, "msg": "token not found"}), 404
    return jsonify({"ok": True})


def _row_to_dict(row, cursor) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, (list, tuple)):
        return {
            "company": row[0],
            "container_no": row[1],
            "vessel": row[2],
            "eta": row[3],
            "status": row[4],
            "folio": row[5],
            "sigla": row[6],
            "numero": row[7],
            "digito": row[8],
            "fecha_entrega": row[9],
            "pies": row[10],
        }
    return {}


def _select_container_rows(
    cursor, access_key: str, save_id: str
) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT company, container_no, vessel, eta, status,
               folio, sigla, numero, digito, fecha_entrega, pies
        FROM container_items
        WHERE access_token = ?
          AND save_id = ?
        ORDER BY id DESC
        """
        ,
        (access_key, save_id),
    )
    rows = cursor.fetchall()
    return [get_row_dict(r, cursor) or _row_to_dict(r, cursor) for r in rows]


@container_bp.route("/api/containers/save", methods=["POST"])
@container_access_required
def save_containers():
    t0 = time.time()
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    access_key, error = _require_access_key()
    if error:
        return error

    t_conn0 = time.time()
    conn = get_db_connection()
    t_conn1 = time.time()
    cursor = get_cursor(conn)

    iti_index = {}
    iti_ok = True
    t_iti0 = time.time()
    try:
        iti_index = get_iti_index_cached(allow_stale=True)
    except Exception:
        iti_ok = False
    t_iti1 = time.time()

    save_id = str(uuid.uuid4())
    saved_at = get_chile_time_naive()

    if not rows:
        cursor.execute(
            "UPDATE container_access_tokens SET latest_save_id = ? WHERE token = ?",
            (save_id, access_key),
        )
        conn.commit()
        conn.close()
        t_end = time.time()
        print(
            "[perf] /api/containers/save rows=0 "
            f"total={t_end - t0:.3f}s conn={t_conn1 - t_conn0:.3f}s iti={t_iti1 - t_iti0:.3f}s"
        )
        return jsonify({"ok": True, "rows": [], "iti_ok": iti_ok, "deleted": 0})

    results = []
    insert_rows = []
    for r in rows:
        company = (r.get("company") or "").strip()
        container_no = (r.get("container_no") or "").strip()
        if not container_no:
            continue

        iti = match_iti(iti_index, container_no)
        if iti:
            vessel = iti.get("vessel")
            status = "Con datos"
            folio = iti.get("folio") or ""
            sigla = iti.get("sigla") or ""
            numero = iti.get("numero") or ""
            digito = iti.get("digito") or ""
            fecha_entrega = iti.get("fecha_entrega") or ""
            pies = iti.get("pies") or ""
            has_data = 1
        else:
            vessel = None
            status = "Sin datos"
            folio = ""
            sigla = ""
            numero = ""
            digito = ""
            fecha_entrega = ""
            pies = ""
            has_data = 0

        insert_rows.append(
            (
                access_key,
                company,
                container_no,
                vessel,
                None,
                status,
                folio,
                sigla,
                numero,
                digito,
                fecha_entrega,
                pies,
                has_data,
                save_id,
                saved_at,
            )
        )

        results.append(
            {
                "company": company,
                "container_no": container_no,
                "vessel": vessel or "",
                "eta": "",
                "status": status,
                "folio": folio,
                "sigla": sigla,
                "numero": numero,
                "digito": digito,
                "fecha_entrega": fecha_entrega,
                "pies": pies,
            }
        )

    if insert_rows:
        cursor.executemany(
            """
            INSERT INTO container_items (
                access_token,
                company,
                container_no,
                vessel,
                eta,
                status,
                folio,
                sigla,
                numero,
                digito,
                fecha_entrega,
                pies,
                has_data,
                save_id,
                saved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        cursor.execute(
            "UPDATE container_access_tokens SET latest_save_id = ? WHERE token = ?",
            (save_id, access_key),
        )
    else:
        cursor.execute(
            "UPDATE container_access_tokens SET latest_save_id = NULL WHERE token = ?",
            (access_key,),
        )

    conn.commit()
    conn.close()
    t_end = time.time()
    print(
        f"[perf] /api/containers/save rows={len(results)} "
        f"total={t_end - t0:.3f}s conn={t_conn1 - t_conn0:.3f}s iti={t_iti1 - t_iti0:.3f}s"
    )
    return jsonify({"ok": True, "rows": results, "iti_ok": iti_ok})


@container_bp.route("/api/containers/list")
@container_access_required
def list_containers():
    t0 = time.time()
    conn = get_db_connection()
    t_conn1 = time.time()
    cursor = get_cursor(conn)
    access_key, error = _require_access_key()
    if error:
        conn.close()
        return error
    save_id = _ensure_latest_save_id(conn, cursor, access_key)
    if not save_id:
        conn.close()
        t_end = time.time()
        print(
            f"[perf] /api/containers/list rows=0 "
            f"total={t_end - t0:.3f}s conn={t_conn1 - t0:.3f}s"
        )
        return jsonify([])
    rows = _select_container_rows(cursor, access_key, save_id)
    conn.close()
    t_end = time.time()
    print(
        f"[perf] /api/containers/list rows={len(rows)} "
        f"total={t_end - t0:.3f}s conn={t_conn1 - t0:.3f}s"
    )
    return jsonify(rows)


@container_bp.route("/api/containers/debug/db-pool")
@container_access_required
def debug_db_pool():
    return jsonify(
        {
            "ok": True,
            "db_type": config.DATABASE_TYPE,
            "mysql_available": bool(MYSQL_AVAILABLE),
            "pooleddb_available": bool(POOLEDDB_AVAILABLE),
            "pool_initialized": _MYSQL_POOL is not None,
        }
    )


@container_bp.route("/api/containers/lookup", methods=["POST"])
@container_access_required
def lookup_containers():
    data = request.get_json(force=True) or {}
    containers = data.get("containers", [])
    force_refresh = bool(data.get("force"))
    access_key, error = _require_access_key()
    if error:
        return error

    if not isinstance(containers, list):
        return jsonify({"ok": False, "msg": "invalid data"}), 400

    if not containers:
        return jsonify({"ok": True, "items": []})

    items = []
    for value in containers:
        key = normalize_container(value)
        if not key:
            continue
        matches = get_iti_matches_cached(value)
        if not matches:
            continue
        for iti in matches:
            items.append(
                {
                    "key": key,
                    "vessel": iti.get("vessel") or "",
                    "folio": iti.get("folio") or "",
                    "sigla": iti.get("sigla") or "",
                    "numero": iti.get("numero") or "",
                    "digito": iti.get("digito") or "",
                    "fecha_entrega": iti.get("fecha_entrega") or "",
                    "pies": iti.get("pies") or "",
                }
            )

    return jsonify({"ok": True, "items": items})


@container_bp.route("/api/containers/iti-test")
def iti_test():
    t0 = time.time()
    try:
        iti_index = build_iti_index()
    except Exception as e:
        return jsonify({"ok": False, "msg": "iti fetch failed", "error": str(e)}), 502

    items = []
    for container_no, iti in (iti_index or {}).items():
        items.append(
            {
                "container_no": container_no,
                "vessel": iti.get("vessel") or "",
                "folio": iti.get("folio") or "",
                "sigla": iti.get("sigla") or "",
                "numero": iti.get("numero") or "",
                "digito": iti.get("digito") or "",
                "fecha_entrega": iti.get("fecha_entrega") or "",
                "pies": iti.get("pies") or "",
            }
        )

    return jsonify(
        {
            "ok": True,
            "count": len(items),
            "items": items,
            "elapsed": round(time.time() - t0, 3),
        }
    )


@container_bp.route("/api/containers/iti-cache")
@container_access_required
def iti_cache():
    access_key, error = _require_access_key()
    if error:
        return error

    try:
        iti_index = get_iti_index_cached(allow_stale=True)
    except Exception:
        iti_index = {}

    items = []
    for container_no, iti in (iti_index or {}).items():
        items.append(
            {
                "container_no": container_no,
                "vessel": iti.get("vessel") or "",
                "folio": iti.get("folio") or "",
                "sigla": iti.get("sigla") or "",
                "numero": iti.get("numero") or "",
                "digito": iti.get("digito") or "",
                "fecha_entrega": iti.get("fecha_entrega") or "",
                "pies": iti.get("pies") or "",
            }
        )

    cache_info = get_iti_cache_info()
    return jsonify(
        {
            "ok": True,
            "items": items,
            "cache_updated_at": cache_info.get("updated_at"),
            "cache_age_seconds": cache_info.get("age_seconds"),
            "cache_ttl_seconds": cache_info.get("ttl_seconds"),
            "cache_next_refresh_at": cache_info.get("next_refresh_at"),
            "cache_next_refresh_in_seconds": cache_info.get("next_refresh_in_seconds"),
        }
    )


@container_bp.route("/api/containers/refresh", methods=["POST"])
@container_access_required
def refresh_containers():
    logger = logging.getLogger(__name__)
    data = request.get_json(force=True) or {}
    force_refresh = bool(data.get("force"))
    access_key, error = _require_access_key()
    if error:
        return error

    t0 = time.time()
    cache_before = get_iti_cache_info()
    logger.info(
        "[refresh] start force=%s cache_before_age=%s cache_before_updated_at=%s",
        force_refresh,
        cache_before.get("age_seconds"),
        cache_before.get("updated_at"),
    )

    t_iti0 = time.time()
    try:
        iti_index = get_iti_index(force_refresh=force_refresh)
    except Exception:
        t_iti1 = time.time()
        logger.exception(
            "[refresh] iti fetch failed elapsed=%.3fs",
            t_iti1 - t_iti0,
        )
        return jsonify({"ok": False, "msg": "iti fetch failed"}), 502
    t_iti1 = time.time()
    logger.info(
        "[refresh] iti fetch ok elapsed=%.3fs items=%s",
        t_iti1 - t_iti0,
        len(iti_index or {}),
    )

    cache_after = get_iti_cache_info()
    refreshed = False
    if force_refresh:
        refreshed = True
    if cache_after.get("updated_at") and (
        cache_before.get("updated_at") != cache_after.get("updated_at")
    ):
        refreshed = True

    updated = 0
    t_end = time.time()
    logger.info(
        "[refresh] cache-only done total=%.3fs refreshed=%s",
        t_end - t0,
        refreshed,
    )
    return jsonify(
        {
            "ok": True,
            "updated": updated,
            "refreshed": refreshed,
            "cache_updated_at": cache_after.get("updated_at"),
            "cache_age_seconds": cache_after.get("age_seconds"),
            "cache_ttl_seconds": cache_after.get("ttl_seconds"),
            "cache_next_refresh_at": cache_after.get("next_refresh_at"),
            "cache_next_refresh_in_seconds": cache_after.get("next_refresh_in_seconds"),
        }
    )


@container_bp.route("/api/containers/delete", methods=["POST"])
@container_access_required
def delete_containers():
    t0 = time.time()
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    access_key, error = _require_access_key()
    if error:
        return error

    if not rows:
        return jsonify({"ok": False, "msg": "no data"}), 400

    conn = get_db_connection()
    t_conn1 = time.time()
    cursor = get_cursor(conn)
    deleted = 0
    save_id = _ensure_latest_save_id(conn, cursor, access_key)
    if not save_id:
        conn.close()
        t_end = time.time()
        print(
            f"[perf] /api/containers/delete deleted=0 "
            f"total={t_end - t0:.3f}s conn={t_conn1 - t0:.3f}s"
        )
        return jsonify({"ok": True, "deleted": 0})

    for r in rows:
        container_no = (r.get("container_no") or "").strip()
        if not container_no:
            continue
        company = (r.get("company") or "").strip()
        cursor.execute(
            """
            DELETE FROM container_items
            WHERE container_no = ?
              AND COALESCE(company, '') = ?
              AND access_token = ?
              AND save_id = ?
            """,
            (container_no, company, access_key, save_id),
        )
        deleted += cursor.rowcount or 0

    conn.commit()
    conn.close()
    t_end = time.time()
    print(
        f"[perf] /api/containers/delete deleted={deleted} "
        f"total={t_end - t0:.3f}s conn={t_conn1 - t0:.3f}s"
    )
    return jsonify({"ok": True, "deleted": deleted})


@container_bp.route("/api/containers/delete_disappeared", methods=["POST"])
@container_access_required
def delete_disappeared():
    access_key, error = _require_access_key()
    if error:
        return error
    conn = get_db_connection()
    cursor = get_cursor(conn)
    save_id = _ensure_latest_save_id(conn, cursor, access_key)
    if not save_id:
        conn.close()
        return jsonify({"ok": True, "deleted": 0})
    cursor.execute(
        """
        DELETE FROM container_items
        WHERE COALESCE(folio, '') = ''
          AND access_token = ?
          AND save_id = ?
        """
        ,
        (access_key, save_id),
    )
    conn.commit()
    deleted = cursor.rowcount or 0
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@container_bp.route("/api/containers/clear", methods=["POST"])
@container_access_required
def clear_containers():
    access_key, error = _require_access_key()
    if error:
        return error
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        "UPDATE container_access_tokens SET latest_save_id = NULL WHERE token = ?",
        (access_key,),
    )
    conn.commit()
    conn.close()
    t_end = time.time()
    logger.info(
        "[refresh] done updated=%s total=%.3fs db=%.3fs",
        updated,
        t_end - t0,
        t_end - t_db0,
    )
    return jsonify({"ok": True, "deleted": 0})


@container_bp.route("/api/containers/cleanup", methods=["POST"])
def cleanup_containers():
    data = request.get_json(silent=True) or {}
    limit = data.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = None
        if limit is not None and limit <= 0:
            limit = None

    access_key = data.get("token") or data.get("access_token")
    conn = get_db_connection()
    cursor = get_cursor(conn)

    if access_key:
        save_id = _ensure_latest_save_id(conn, cursor, access_key)
        if not save_id:
            conn.close()
            return jsonify({"ok": True, "deleted": 0})
        sql = """
            SELECT id
            FROM container_items
            WHERE access_token = ?
              AND (save_id IS NULL OR save_id != ?)
            ORDER BY saved_at ASC
        """
        params = [access_key, save_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor.execute(sql, params)
    else:
        sql = """
            SELECT id
            FROM container_items
            WHERE save_id IS NULL
               OR save_id NOT IN (
                   SELECT latest_save_id
                   FROM container_access_tokens
                   WHERE latest_save_id IS NOT NULL
               )
            ORDER BY saved_at ASC
        """
        params = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor.execute(sql, params)
    rows = cursor.fetchall()
    ids = []
    for row in rows:
        data = get_row_dict(row, cursor)
        if data and data.get("id") is not None:
            ids.append(data["id"])
        elif isinstance(row, (list, tuple)) and row:
            ids.append(row[0])

    deleted = 0
    if ids:
        placeholders = ", ".join(["?"] * len(ids))
        cursor.execute(
            f"DELETE FROM container_items WHERE id IN ({placeholders})",
            ids,
        )
        deleted = cursor.rowcount or 0
        conn.commit()

    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@container_bp.route("/api/containers/restore-previous", methods=["POST"])
@container_access_required
def restore_previous_snapshot():
    access_key, error = _require_access_key()
    if error:
        return error

    conn = get_db_connection()
    cursor = get_cursor(conn)
    current = _get_latest_save_id(cursor, access_key)
    cursor.execute(
        """
        SELECT save_id, MAX(saved_at) AS saved_at, MAX(id) AS max_id
        FROM container_items
        WHERE access_token = ?
          AND save_id IS NOT NULL
          AND save_id != ?
        GROUP BY save_id
        ORDER BY saved_at DESC, max_id DESC
        LIMIT 1
        """,
        (access_key, current or ""),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "msg": "no previous snapshot"})

    data = get_row_dict(row, cursor)
    save_id = data.get("save_id") if data else (row[0] if isinstance(row, (list, tuple)) else None)
    if not save_id:
        conn.close()
        return jsonify({"ok": False, "msg": "no previous snapshot"})

    cursor.execute(
        "UPDATE container_access_tokens SET latest_save_id = ? WHERE token = ?",
        (save_id, access_key),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "save_id": save_id})


@container_bp.route("/api/iti/duplicates")
@container_access_required
def iti_duplicates():
    force = request.args.get("force") in ("1", "true", "yes")
    try:
        duplicates = get_iti_duplicate_numeros(force_refresh=force)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"iti duplicates failed: {e}"}), 500

    return jsonify({"ok": True, "total": len(duplicates), "duplicates": duplicates})
