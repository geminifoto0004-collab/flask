from functools import wraps
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, session

from database import get_db_connection, get_cursor, get_row_dict
from services.container_access_service import (
    clear_sessions_for_token,
    create_access_session,
    create_token,
    delete_token,
    ensure_admin_from_env,
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
    get_iti_cache_info,
    get_iti_duplicate_numeros,
    get_iti_index,
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
            return redirect("/container")
        session.pop("container_access_session_id", None)
        session.pop("container_access_token", None)

    ok, msg, _token = validate_access_key(access_key)
    if not ok:
        return render_template("container/access_denied.html", reason=msg), 403

    session_id = create_access_session(
        access_key, _client_ip(), request.headers.get("User-Agent", "")
    )
    session["container_access_session_id"] = session_id
    session["container_access_token"] = access_key
    return redirect("/container")


@container_bp.route("/container")
@container_access_required
def container_page():
    return render_template("container/excel_mode.html")


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


def _select_container_rows(cursor, access_key: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT company, container_no, vessel, eta, status,
               folio, sigla, numero, digito, fecha_entrega, pies
        FROM container_items
        WHERE access_token = ?
        ORDER BY id DESC
        """
        ,
        (access_key,),
    )
    rows = cursor.fetchall()
    return [get_row_dict(r, cursor) or _row_to_dict(r, cursor) for r in rows]


@container_bp.route("/api/containers/save", methods=["POST"])
@container_access_required
def save_containers():
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    access_key, error = _require_access_key()
    if error:
        return error

    conn = get_db_connection()
    cursor = get_cursor(conn)

    iti_index = {}
    iti_ok = True
    try:
        iti_index = get_iti_index()
    except Exception:
        iti_ok = False

    if not rows:
        cursor.execute("DELETE FROM container_items WHERE access_token = ?", (access_key,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "rows": [], "iti_ok": iti_ok, "deleted": cursor.rowcount or 0})

    cursor.execute("DELETE FROM container_items WHERE access_token = ?", (access_key,))

    results = []
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

        cursor.execute(
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
                has_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
            ),
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

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "rows": results, "iti_ok": iti_ok})


@container_bp.route("/api/containers/list")
@container_access_required
def list_containers():
    conn = get_db_connection()
    cursor = get_cursor(conn)
    access_key, error = _require_access_key()
    if error:
        conn.close()
        return error
    rows = _select_container_rows(cursor, access_key)
    conn.close()
    return jsonify(rows)


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


@container_bp.route("/api/containers/iti-cache")
@container_access_required
def iti_cache():
    access_key, error = _require_access_key()
    if error:
        return error

    try:
        iti_index = get_iti_index(force_refresh=False)
    except Exception:
        return jsonify({"ok": False, "msg": "iti fetch failed"}), 502

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

    return jsonify({"ok": True, "items": items})


@container_bp.route("/api/containers/refresh", methods=["POST"])
@container_access_required
def refresh_containers():
    data = request.get_json(force=True) or {}
    force_refresh = bool(data.get("force"))
    access_key, error = _require_access_key()
    if error:
        return error

    cache_before = get_iti_cache_info()

    try:
        iti_index = get_iti_index(force_refresh=force_refresh)
    except Exception:
        return jsonify({"ok": False, "msg": "iti fetch failed"}), 502

    cache_after = get_iti_cache_info()
    refreshed = False
    if force_refresh:
        refreshed = True
    if cache_after.get("updated_at") and (
        cache_before.get("updated_at") != cache_after.get("updated_at")
    ):
        refreshed = True

    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        "SELECT id, container_no FROM container_items WHERE access_token = ?",
        (access_key,),
    )
    rows = cursor.fetchall()

    updated = 0
    for r in rows:
        row = get_row_dict(r, cursor) or {}
        container_no = row.get("container_no")
        row_id = row.get("id") if isinstance(row, dict) else None
        if row_id is None and isinstance(r, (list, tuple)):
            row_id = r[0]
            if len(r) > 1:
                container_no = r[1]

        iti = match_iti(iti_index, container_no)
        if iti:
            vessel = iti.get("vessel") or ""
            status = "Con datos"
            folio = iti.get("folio") or ""
            sigla = iti.get("sigla") or ""
            numero = iti.get("numero") or ""
            digito = iti.get("digito") or ""
            fecha_entrega = iti.get("fecha_entrega") or ""
            pies = iti.get("pies") or ""
            has_data = 1
        else:
            vessel = ""
            status = "Sin datos"
            folio = ""
            sigla = ""
            numero = ""
            digito = ""
            fecha_entrega = ""
            pies = ""
            has_data = 0

        cursor.execute(
            """
            UPDATE container_items
            SET vessel = ?,
                status = ?,
                folio = ?,
                sigla = ?,
                numero = ?,
                digito = ?,
                fecha_entrega = ?,
                pies = ?,
                has_data = ?
            WHERE id = ?
            """,
            (vessel, status, folio, sigla, numero, digito, fecha_entrega, pies, has_data, row_id),
        )
        updated += 1

    conn.commit()
    conn.close()
    return jsonify(
        {
            "ok": True,
            "updated": updated,
            "refreshed": refreshed,
            "cache_updated_at": cache_after.get("updated_at"),
            "cache_age_seconds": cache_after.get("age_seconds"),
            "cache_ttl_seconds": cache_after.get("ttl_seconds"),
        }
    )


@container_bp.route("/api/containers/delete", methods=["POST"])
@container_access_required
def delete_containers():
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    access_key, error = _require_access_key()
    if error:
        return error

    if not rows:
        return jsonify({"ok": False, "msg": "no data"}), 400

    conn = get_db_connection()
    cursor = get_cursor(conn)
    deleted = 0

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
            """,
            (container_no, company, access_key),
        )
        deleted += cursor.rowcount or 0

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@container_bp.route("/api/containers/delete_disappeared", methods=["POST"])
@container_access_required
def delete_disappeared():
    access_key, error = _require_access_key()
    if error:
        return error
    conn = get_db_connection()
    cursor = get_cursor(conn)
    cursor.execute(
        """
        DELETE FROM container_items
        WHERE COALESCE(folio, '') = ''
          AND access_token = ?
        """
        ,
        (access_key,),
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
    cursor.execute("DELETE FROM container_items WHERE access_token = ?", (access_key,))
    conn.commit()
    deleted = cursor.rowcount or 0
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@container_bp.route("/api/iti/duplicates")
@container_access_required
def iti_duplicates():
    force = request.args.get("force") in ("1", "true", "yes")
    try:
        duplicates = get_iti_duplicate_numeros(force_refresh=force)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"iti duplicates failed: {e}"}), 500

    return jsonify({"ok": True, "total": len(duplicates), "duplicates": duplicates})
