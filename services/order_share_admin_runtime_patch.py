"""Runtime support for ORDER public-share administration.

Adds three control-plane behaviours without putting B2/image work on the customer path:
- count successful public HTML opens,
- expose small authenticated share state for the desktop admin mirror,
- let an existing token change its expiry/permanent setting.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import time
import threading

from flask import jsonify, make_response, redirect, render_template, request, session, url_for

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import check_column_exists, get_cursor, get_db_connection, get_row_dict
from services import order_public_share_fast as _fast

_ACCESS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="order-share-access")
_BASE_CREATE = _fast._create_scoped_share
_BASE_UPDATE = _fast._update_share_settings


_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _ensure_columns():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        _ensure_columns_uncached()
        _SCHEMA_READY = True


def _ensure_columns_uncached():
    """Keep public-share schema additive and safe across older TiDB deployments."""
    _ensure_order_cloud_tables()
    _fast._ensure_share_columns()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        columns = (
            ("show_pdf_pages", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("allow_report_pdf_download", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("show_images", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("show_workflow_images", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("access_count", "BIGINT NOT NULL DEFAULT 0"),
            ("last_accessed_at", "TIMESTAMP NULL"),
        )
        for name, definition in columns:
            if not check_column_exists(cur, "cloud_share_tokens", name):
                cur.execute(f"ALTER TABLE cloud_share_tokens ADD COLUMN {name} {definition}")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS cloud_share_order_visibility (
                   token_hash VARCHAR(64) NOT NULL,
                   order_number VARCHAR(191) NOT NULL,
                   show_order BOOLEAN NOT NULL DEFAULT TRUE,
                   show_images BOOLEAN NULL,
                   show_workflow_images BOOLEAN NULL,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   PRIMARY KEY (token_hash, order_number),
                   INDEX idx_share_visibility_order (order_number)
               )"""
        )
        if not check_column_exists(cur, "cloud_share_order_visibility", "show_logistics"):
            cur.execute("ALTER TABLE cloud_share_order_visibility ADD COLUMN show_logistics BOOLEAN NULL")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _dt_iso(value):
    if value in (None, ""):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dt_epoch(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except Exception:
        return 0


def _drop_token_caches(token):
    token = str(token or "").strip()
    try:
        from services import order_share_image_source_patch as source_patch
        source_patch._drop_caches(token)
        return
    except Exception:
        pass
    try:
        with _fast._cache_lock:
            _fast._share_cache.pop(token, None)
    except Exception:
        pass


def _record_access(token):
    token = str(token or "").strip()
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """UPDATE cloud_share_tokens
                   SET access_count=COALESCE(access_count, 0)+1,
                       last_accessed_at=CURRENT_TIMESTAMP
                   WHERE token_hash=? AND status='active'
                     AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP)""",
                (token_hash,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:
        print(f"[WARN] ORDER share access counter skipped: {type(exc).__name__}: {exc}")


@b2_test_bp.after_app_request
def _count_successful_public_share_open(response):
    """Count one real page open; the 45s live-refresh fetch must not inflate visits."""
    try:
        path = str(request.path or "")
        parts = path.strip("/").split("/")
        content_type = str(response.headers.get("Content-Type") or "").lower()
        auto_refresh = str(request.headers.get("X-Guest-Auto-Refresh") or "").strip().lower() in {"1", "true", "yes", "on"}
        if (
            request.method == "GET"
            and not auto_refresh
            and len(parts) == 2
            and parts[0] == "share"
            and parts[1] != "test"
            and response.status_code == 200
            and "text/html" in content_type
        ):
            _ACCESS_EXECUTOR.submit(_record_access, parts[1])
    except Exception as exc:
        print(f"[WARN] ORDER share access scheduling skipped: {type(exc).__name__}: {exc}")
    return response


@b2_test_bp.route("/api/order-cloud/share/admin-state", methods=["GET"])
def _share_admin_state():
    """Small authenticated state feed used by the desktop mirror/admin page."""
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            # ORDER currently uses one global Render gate (no per-client CN/CL split).
            # Historical shares can therefore carry older source_site values such as
            # LEGACY/NULL/previous site names. Filtering by the current literal "ORDER"
            # hides valid old links from the desktop admin mirror even though the public
            # token remains active. Return the full share control-plane history here.
            wanted = str(request.args.get('share_id') or '').strip().lower()
            if wanted and (len(wanted) != 64 or any(c not in '0123456789abcdef' for c in wanted)):
                return jsonify({'ok': False, 'error': 'share_id is invalid'}), 400
            sql = """SELECT token_hash, customer_key, status, source_site, created_at, expires_at,
                            history_scope, show_pdf_pages, allow_report_pdf_download,
                            show_images, show_workflow_images, access_count, last_accessed_at
                     FROM cloud_share_tokens"""
            if wanted:
                cur.execute(sql + ' WHERE token_hash=?', (wanted,))
            else:
                cur.execute(sql + ' ORDER BY created_at DESC')
            rows = []
            now = int(time.time())
            for raw in cur.fetchall():
                item = get_row_dict(raw, cur) or {}
                expires_epoch = _dt_epoch(item.get("expires_at"))
                status = str(item.get("status") or "active").strip().lower()
                if status == "active" and expires_epoch and expires_epoch <= now:
                    effective_status = "expired"
                else:
                    effective_status = status
                rows.append({
                    "id": str(item.get("token_hash") or ""),
                    "share_id": str(item.get("token_hash") or ""),
                    "customer_key": str(item.get("customer_key") or ""),
                    "status": effective_status,
                    "source_site": str(item.get("source_site") or ""),
                    "created_at": _dt_iso(item.get("created_at")),
                    "created_at_epoch": _dt_epoch(item.get("created_at")),
                    "expires_at": _dt_iso(item.get("expires_at")),
                    "expires_at_epoch": expires_epoch,
                    "is_permanent": not bool(item.get("expires_at")),
                    "history_scope": str(item.get("history_scope") or "current"),
                    "show_pdf_pages": bool(item.get("show_pdf_pages")),
                    "allow_report_pdf_download": bool(item.get("allow_report_pdf_download")),
                    "show_images": bool(item.get("show_images")),
                    "show_workflow_images": bool(item.get("show_workflow_images")),
                    "access_count": int(item.get("access_count") or 0),
                    "last_accessed_at": _dt_iso(item.get("last_accessed_at")),
                    "last_accessed_at_epoch": _dt_epoch(item.get("last_accessed_at")),
                })
        finally:
            conn.close()
        return jsonify({"ok": True, "result": {"shares": rows, "idempotent_create": True}})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _drop_share_hash_caches(token_hash):
    token_hash = str(token_hash or "").strip().lower()
    if not token_hash:
        return
    try:
        from services import order_public_share_fast as fast
        with fast._cache_lock:
            stale = [
                raw_token for raw_token in list(fast._share_cache.keys())
                if hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest() == token_hash
            ]
            for raw_token in stale:
                fast._share_cache.pop(raw_token, None)
    except Exception as exc:
        print(f"[WARN] share hash fast-cache invalidation skipped: {type(exc).__name__}: {exc}")
    try:
        from services import order_public_share_multi_b2_page as page
        from services import order_customer_share_hot_cache as hot
        with page._cache_lock:
            hot._HASH_TOKEN_CACHE.pop(token_hash, None)
            stale = [
                raw_token for raw_token in list(page._token_cache.keys())
                if hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest() == token_hash
            ]
            for raw_token in stale:
                page._token_cache.pop(raw_token, None)
    except Exception as exc:
        print(f"[WARN] share hash hot-cache invalidation skipped: {type(exc).__name__}: {exc}")
    try:
        from services import order_share_render_cache as html_cache
        with html_cache._LOCK:
            html_cache._TOKEN_HTML.pop(token_hash, None)
    except Exception as exc:
        print(f"[WARN] share hash HTML-cache invalidation skipped: {type(exc).__name__}: {exc}")


@b2_test_bp.route("/api/order-cloud/share/revoke-by-hash", methods=["POST"])
def _share_revoke_by_hash():
    """Admin-only revoke for legacy/remote-only shares whose raw token is not stored locally."""
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    token_hash = str(payload.get("token_hash") or payload.get("share_id") or "").strip().lower()
    if len(token_hash) != 64 or any(ch not in "0123456789abcdef" for ch in token_hash):
        return jsonify({"ok": False, "error": "valid token_hash is required"}), 400
    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                "SELECT customer_key, status FROM cloud_share_tokens WHERE token_hash=? LIMIT 1",
                (token_hash,),
            )
            row = cur.fetchone()
            item = get_row_dict(row, cur) if row else {}
            if not item:
                return jsonify({"ok": False, "error": "share not found"}), 404
            if str(item.get("status") or "").strip().lower() != "revoked":
                cur.execute(
                    "UPDATE cloud_share_tokens SET status='revoked' WHERE token_hash=?",
                    (token_hash,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _drop_share_hash_caches(token_hash)
        return jsonify({"ok": True, "revoked": True, "share_id": token_hash})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500



def _valid_token_hash(value):
    value = str(value or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("valid token_hash is required")
    return value


def _share_settings_detail(token_hash):
    token_hash = _valid_token_hash(token_hash)
    _ensure_columns()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT token_hash, customer_key, status, source_site, history_scope,
                      include_cancelled, created_at, expires_at,
                      show_pdf_pages, allow_report_pdf_download,
                      show_images, show_workflow_images,
                      access_count, last_accessed_at
               FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("share not found")
        share = get_row_dict(row, cur) or {}
        cur.execute(
            """SELECT order_number, show_order, show_images, show_workflow_images, show_logistics
               FROM cloud_share_order_visibility WHERE token_hash=?""",
            (token_hash,),
        )
        overrides = {
            str(item.get("order_number") or ""): item
            for item in (get_row_dict(r, cur) or {} for r in cur.fetchall())
            if str(item.get("order_number") or "").strip()
        }
        customer_key = str(share.get("customer_key") or "")
        cur.execute(
            """SELECT order_number, order_date, production_type, product_name, product_code,
                      pattern_code, quantity, order_status
               FROM cloud_orders
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_date DESC, order_number DESC""",
            (customer_key,),
        )
        orders = []
        global_images = bool(share.get("show_images"))
        global_workflow_images = bool(share.get("show_workflow_images"))
        for raw in cur.fetchall():
            item = get_row_dict(raw, cur) or {}
            number = str(item.get("order_number") or "")
            override = overrides.get(number) or {}
            orders.append({
                "order_number": number,
                "order_date": item.get("order_date"),
                "production_type": item.get("production_type"),
                "product_name": item.get("product_name"),
                "product_code": item.get("product_code"),
                "pattern_code": item.get("pattern_code"),
                "quantity": item.get("quantity"),
                "order_status": item.get("order_status"),
                "show_order": bool(override.get("show_order")) if override else True,
                "show_images": global_images if override.get("show_images") is None else bool(override.get("show_images")),
                "show_workflow_images": global_workflow_images if override.get("show_workflow_images") is None else bool(override.get("show_workflow_images")),
                "show_logistics": True if override.get("show_logistics") is None else bool(override.get("show_logistics")),
            })
        expires_epoch = _dt_epoch(share.get("expires_at"))
        return {
            "id": token_hash,
            "share_id": token_hash,
            "customer_key": customer_key,
            "status": str(share.get("status") or "active").lower(),
            "source_site": str(share.get("source_site") or ""),
            "history_scope": str(share.get("history_scope") or "current"),
            "include_cancelled": bool(share.get("include_cancelled")),
            "created_at": _dt_iso(share.get("created_at")),
            "created_at_epoch": _dt_epoch(share.get("created_at")),
            "expires_at": _dt_iso(share.get("expires_at")),
            "expires_at_epoch": expires_epoch,
            "is_permanent": not bool(share.get("expires_at")),
            "show_pdf_pages": bool(share.get("show_pdf_pages")),
            "allow_report_pdf_download": bool(share.get("allow_report_pdf_download")),
            "show_images": global_images,
            "show_workflow_images": global_workflow_images,
            "access_count": int(share.get("access_count") or 0),
            "last_accessed_at": _dt_iso(share.get("last_accessed_at")),
            "last_accessed_at_epoch": _dt_epoch(share.get("last_accessed_at")),
            "orders": orders,
        }
    finally:
        conn.close()


def _apply_share_settings(token_hash, payload):
    token_hash = _valid_token_hash(token_hash)
    payload = dict(payload or {})
    try:
        expiry_changed, permanent, expires_at = _expiry_from_payload(payload)
    except ValueError:
        raise

    _ensure_columns()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            "SELECT customer_key, status FROM cloud_share_tokens WHERE token_hash=? LIMIT 1",
            (token_hash,),
        )
        row = cur.fetchone()
        current = get_row_dict(row, cur) if row else {}
        if not current:
            raise ValueError("share not found")
        if str(current.get("status") or "").strip().lower() == "revoked":
            raise ValueError("revoked share cannot be edited")

        updates = []
        values = []
        for key in ("show_pdf_pages", "allow_report_pdf_download", "show_images", "show_workflow_images"):
            if key in payload:
                updates.append(f"{key}=?")
                values.append(bool(payload.get(key)))
        if "history_scope" in payload:
            scope = str(payload.get("history_scope") or "current").strip().lower()
            if scope not in {"current", "3m", "6m", "12m", "all"}:
                scope = "current"
            updates.append("history_scope=?")
            values.append(scope)
        if expiry_changed:
            updates.append("expires_at=?")
            values.append(expires_at)
            updates.append("status='active'")
        if updates:
            values.append(token_hash)
            cur.execute(
                "UPDATE cloud_share_tokens SET " + ", ".join(updates) + " WHERE token_hash=?",
                tuple(values),
            )

        if "order_visibility" in payload:
            rows = payload.get("order_visibility")
            if not isinstance(rows, list):
                raise ValueError("order_visibility must be a list")
            cur.execute("DELETE FROM cloud_share_order_visibility WHERE token_hash=?", (token_hash,))
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                order_number = str(raw.get("order_number") or "").strip()
                if not order_number:
                    continue
                cur.execute(
                    """INSERT INTO cloud_share_order_visibility
                       (token_hash, order_number, show_order, show_images, show_workflow_images, show_logistics, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (
                        token_hash,
                        order_number,
                        bool(raw.get("show_order", True)),
                        None if raw.get("show_images") is None else bool(raw.get("show_images")),
                        None if raw.get("show_workflow_images") is None else bool(raw.get("show_workflow_images")),
                        None if raw.get("show_logistics") is None else bool(raw.get("show_logistics")),
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _drop_share_hash_caches(token_hash)
    return _share_settings_detail(token_hash)


@b2_test_bp.route("/api/order-cloud/share/admin-detail/<token_hash>", methods=["GET"])
def _share_admin_detail_by_hash(token_hash):
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        return jsonify({"ok": True, "result": _share_settings_detail(token_hash)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/api/order-cloud/share/update-by-hash", methods=["POST"])
def _share_update_by_hash():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True) or {}
    try:
        token_hash = _valid_token_hash(payload.get("token_hash") or payload.get("share_id"))
        settings = dict(payload)
        settings.pop("token_hash", None)
        settings.pop("share_id", None)
        result = _apply_share_settings(token_hash, settings)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _cloud_admin_allowed():
    if not session.get("logged_in"):
        return False
    try:
        from config import admin_config
        return session.get("role") in ("admin", admin_config.SUPER_ADMIN_ROLE)
    except Exception:
        return session.get("role") == "admin"


@b2_test_bp.route("/admin/order-shares", methods=["GET"])
def _cloud_share_admin_page():
    """Render-hosted share control panel. Does not depend on desktop ORDER being online."""
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))
    if not _cloud_admin_allowed():
        return redirect(url_for("login", next=request.path))
    return render_template(
        "admin/order_share_cloud.html",
        admin_username=session.get("username") or session.get("email") or "admin",
    )


def _cloud_admin_share_rows():
    _ensure_columns()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT s.token_hash, s.customer_key,
                      COALESCE(NULLIF(c.customer_name,''), s.customer_key) AS customer_name,
                      s.mode, s.status, s.source_site, s.history_scope,
                      s.include_cancelled, s.created_at, s.expires_at,
                      s.show_pdf_pages, s.allow_report_pdf_download,
                      s.show_images, s.show_workflow_images,
                      s.access_count, s.last_accessed_at
               FROM cloud_share_tokens s
               LEFT JOIN cloud_customers c ON c.customer_key=s.customer_key
               ORDER BY s.created_at DESC"""
        )
        result = []
        now = int(time.time())
        for raw in cur.fetchall():
            item = get_row_dict(raw, cur) or {}
            expires_epoch = _dt_epoch(item.get("expires_at"))
            stored_status = str(item.get("status") or "active").strip().lower()
            effective_status = (
                "expired"
                if stored_status == "active" and expires_epoch and expires_epoch <= now
                else stored_status
            )
            result.append({
                "id": str(item.get("token_hash") or ""),
                "customer_key": str(item.get("customer_key") or ""),
                "customer_name": str(item.get("customer_name") or item.get("customer_key") or ""),
                "mode": str(item.get("mode") or "LIVE"),
                "status": effective_status,
                "stored_status": stored_status,
                "source_site": str(item.get("source_site") or ""),
                "history_scope": str(item.get("history_scope") or "current"),
                "include_cancelled": bool(item.get("include_cancelled")),
                "created_at": _dt_iso(item.get("created_at")),
                "created_at_epoch": _dt_epoch(item.get("created_at")),
                "expires_at": _dt_iso(item.get("expires_at")),
                "expires_at_epoch": expires_epoch,
                "is_permanent": not bool(item.get("expires_at")),
                "show_pdf_pages": bool(item.get("show_pdf_pages")),
                "allow_report_pdf_download": bool(item.get("allow_report_pdf_download")),
                "show_images": bool(item.get("show_images")),
                "show_workflow_images": bool(item.get("show_workflow_images")),
                "access_count": int(item.get("access_count") or 0),
                "last_accessed_at": _dt_iso(item.get("last_accessed_at")),
                "last_accessed_at_epoch": _dt_epoch(item.get("last_accessed_at")),
            })
        return result
    finally:
        conn.close()


@b2_test_bp.route("/admin/order-shares/api/list", methods=["GET"])
def _cloud_share_admin_list():
    if not _cloud_admin_allowed():
        return jsonify({"ok": False, "error": "admin login required"}), 403
    try:
        return jsonify({"ok": True, "shares": _cloud_admin_share_rows()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/admin/order-shares/api/<token_hash>/detail", methods=["GET"])
def _cloud_share_admin_detail(token_hash):
    if not _cloud_admin_allowed():
        return jsonify({"ok": False, "error": "admin login required"}), 403
    try:
        return jsonify({"ok": True, "share": _share_settings_detail(token_hash)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/admin/order-shares/api/<token_hash>/settings", methods=["PATCH"])
def _cloud_share_admin_settings(token_hash):
    if not _cloud_admin_allowed():
        return jsonify({"ok": False, "error": "admin login required"}), 403
    try:
        result = _apply_share_settings(token_hash, request.get_json(silent=True) or {})
        return jsonify({"ok": True, "share": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/admin/order-shares/api/<token_hash>/revoke", methods=["POST"])
def _cloud_share_admin_revoke(token_hash):
    if not _cloud_admin_allowed():
        return jsonify({"ok": False, "error": "admin login required"}), 403
    token_hash = str(token_hash or "").strip().lower()
    if len(token_hash) != 64 or any(ch not in "0123456789abcdef" for ch in token_hash):
        return jsonify({"ok": False, "error": "invalid share id"}), 400
    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                "UPDATE cloud_share_tokens SET status='revoked' WHERE token_hash=?",
                (token_hash,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _drop_share_hash_caches(token_hash)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@b2_test_bp.route("/admin/order-shares/api/<token_hash>/expiry", methods=["PATCH"])
def _cloud_share_admin_expiry(token_hash):
    if not _cloud_admin_allowed():
        return jsonify({"ok": False, "error": "admin login required"}), 403
    token_hash = str(token_hash or "").strip().lower()
    if len(token_hash) != 64 or any(ch not in "0123456789abcdef" for ch in token_hash):
        return jsonify({"ok": False, "error": "invalid share id"}), 400

    payload = request.get_json(silent=True) or {}
    permanent = bool(payload.get("permanent"))
    expires_at = None
    if not permanent:
        if payload.get("expires_at_epoch"):
            try:
                epoch = int(payload.get("expires_at_epoch"))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "invalid expires_at_epoch"}), 400
            if epoch <= int(time.time()):
                return jsonify({"ok": False, "error": "expiry must be in the future"}), 400
            expires_at = datetime.utcfromtimestamp(epoch)
        else:
            try:
                hours = int(payload.get("hours") or 0)
            except (TypeError, ValueError):
                hours = 0
            if hours < 1 or hours > 24 * 365:
                return jsonify({"ok": False, "error": "hours must be between 1 and 8760"}), 400
            expires_at = datetime.utcnow() + timedelta(hours=hours)

    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute(
                """UPDATE cloud_share_tokens
                   SET expires_at=?, status=CASE WHEN status='revoked' THEN status ELSE 'active' END
                   WHERE token_hash=?""",
                (expires_at, token_hash),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _drop_share_hash_caches(token_hash)
        return jsonify({
            "ok": True,
            "is_permanent": permanent,
            "expires_at": _dt_iso(expires_at),
            "expires_at_epoch": _dt_epoch(expires_at),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _expiry_from_payload(payload):
    """Return (changed, permanent, expires_at) for update payload."""
    payload = dict(payload or {})
    permanent_key = "is_permanent" if "is_permanent" in payload else "permanent" if "permanent" in payload else None
    permanent = False
    if permanent_key is not None:
        raw = payload.get(permanent_key)
        permanent = bool(raw is True or str(raw).strip().lower() in {"1", "true", "yes", "on"})
        if permanent:
            return True, True, None

    if "expires_at_epoch" in payload:
        try:
            epoch = int(float(payload.get("expires_at_epoch") or 0))
        except (TypeError, ValueError):
            raise ValueError("expires_at_epoch must be a unix timestamp")
        if epoch <= int(time.time()):
            raise ValueError("expires_at_epoch must be in the future")
        return True, False, datetime.utcfromtimestamp(epoch)

    if "duration_minutes" in payload:
        try:
            minutes = int(payload.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            raise ValueError("duration_minutes must be an integer")
        if minutes < 1 or minutes > 365 * 24 * 60:
            raise ValueError("duration_minutes must be between 1 and 525600")
        return True, False, datetime.utcnow() + timedelta(minutes=minutes)

    if "expires_hours" in payload:
        try:
            hours = int(payload.get("expires_hours") or 0)
        except (TypeError, ValueError):
            raise ValueError("expires_hours must be an integer")
        if hours < 1 or hours > 24 * 365:
            raise ValueError("expires_hours must be between 1 and 8760")
        return True, False, datetime.utcnow() + timedelta(hours=hours)

    return False, False, None


def _create_scoped_share_guarded():
    """Create the share, then persist display/visibility controls on the same token."""
    try:
        _ensure_columns()
    except Exception as exc:
        print(f"[WARN] ORDER share create schema preflight failed: {type(exc).__name__}: {exc}")
    payload = request.get_json(silent=True) or {}
    base = _BASE_CREATE()
    response = make_response(base)
    if response.status_code >= 400:
        return base
    try:
        data = response.get_json(silent=True) or {}
        result = dict(data.get("result") or {})
        token_hash = str(result.get("share_id") or "").strip().lower()
        if not token_hash:
            share_url = str(result.get("share_url") or "").strip()
            raw_token = share_url.rstrip("/").split("/")[-1] if share_url else ""
            if raw_token:
                token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        if token_hash:
            settings = {
                key: payload.get(key)
                for key in (
                    "show_pdf_pages", "allow_report_pdf_download",
                    "show_images", "show_workflow_images", "order_visibility",
                )
                if key in payload
            }
            if settings:
                detail = _apply_share_settings(token_hash, settings)
                result.update({
                    "show_pdf_pages": detail.get("show_pdf_pages"),
                    "allow_report_pdf_download": detail.get("allow_report_pdf_download"),
                    "show_images": detail.get("show_images"),
                    "show_workflow_images": detail.get("show_workflow_images"),
                })
                data["result"] = result
                return jsonify(data)
    except Exception as exc:
        print(f"[WARN] ORDER share create settings persistence deferred: {type(exc).__name__}: {exc}")
    return base


def _update_share_settings_with_expiry():
    payload = request.get_json(silent=True) or {}
    base = _BASE_UPDATE()
    response = make_response(base)
    if response.status_code >= 400:
        return base

    token = str(payload.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token is required"}), 400
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        detail = _apply_share_settings(token_hash, payload)
        data = response.get_json(silent=True) or {"ok": True}
        result = dict(data.get("result") or {})
        result.update({
            "share_id": token_hash,
            "history_scope": detail.get("history_scope"),
            "is_permanent": detail.get("is_permanent"),
            "expires_at": detail.get("expires_at"),
            "expires_at_epoch": detail.get("expires_at_epoch"),
            "remaining_seconds": None if detail.get("is_permanent") else max(
                0, int(detail.get("expires_at_epoch") or 0) - int(time.time())
            ),
            "show_pdf_pages": detail.get("show_pdf_pages"),
            "allow_report_pdf_download": detail.get("allow_report_pdf_download"),
            "show_images": detail.get("show_images"),
            "show_workflow_images": detail.get("show_workflow_images"),
            "orders": detail.get("orders") or [],
        })
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


_fast._create_scoped_share = _create_scoped_share_guarded
_fast._update_share_settings = _update_share_settings_with_expiry

try:
    _ensure_columns()
    print("[ORDER] share admin runtime patch ready")
except Exception as exc:
    print(f"[WARN] ORDER share admin migration deferred: {type(exc).__name__}: {exc}")
