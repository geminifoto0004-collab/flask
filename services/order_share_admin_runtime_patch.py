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

from flask import jsonify, make_response, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import check_column_exists, get_cursor, get_db_connection, get_row_dict
from services import order_public_share_fast as _fast

_ACCESS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="order-share-access")
_BASE_CREATE = _fast._create_scoped_share
_BASE_UPDATE = _fast._update_share_settings


def _ensure_columns():
    """Keep public-share schema additive and safe across older TiDB deployments."""
    _ensure_order_cloud_tables()
    try:
        _fast._ensure_share_columns()
    except Exception:
        pass
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
            if source_site and str(source_site).upper() != "LEGACY":
                cur.execute(
                    """SELECT token_hash, customer_key, status, source_site, created_at, expires_at,
                              access_count, last_accessed_at
                       FROM cloud_share_tokens
                       WHERE source_site=?
                       ORDER BY created_at DESC""",
                    (str(source_site).upper(),),
                )
            else:
                cur.execute(
                    """SELECT token_hash, customer_key, status, source_site, created_at, expires_at,
                              access_count, last_accessed_at
                       FROM cloud_share_tokens
                       ORDER BY created_at DESC"""
                )
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
                    "access_count": int(item.get("access_count") or 0),
                    "last_accessed_at": _dt_iso(item.get("last_accessed_at")),
                    "last_accessed_at_epoch": _dt_epoch(item.get("last_accessed_at")),
                })
        finally:
            conn.close()
        return jsonify({"ok": True, "result": {"shares": rows}})
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
    """Make create resilient to older share-table schemas before the final create patch runs."""
    try:
        _ensure_columns()
    except Exception as exc:
        print(f"[WARN] ORDER share create schema preflight failed: {type(exc).__name__}: {exc}")
    return _BASE_CREATE()


def _update_share_settings_with_expiry():
    payload = request.get_json(silent=True) or {}
    base = _BASE_UPDATE()
    base_response = make_response(base)
    if base_response.status_code >= 400:
        return base

    try:
        changed, permanent, expires_at = _expiry_from_payload(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not changed:
        return base

    token = str(payload.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token is required"}), 400
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        _ensure_columns()
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute("SELECT token_hash FROM cloud_share_tokens WHERE token_hash=? AND status='active' LIMIT 1", (token_hash,))
            if not cur.fetchone():
                return jsonify({"ok": False, "error": "active share not found"}), 404
            cur.execute(
                "UPDATE cloud_share_tokens SET expires_at=? WHERE token_hash=? AND status='active'",
                (expires_at, token_hash),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _drop_token_caches(token)

        data = base_response.get_json(silent=True) or {"ok": True}
        result = dict(data.get("result") or {})
        expires_epoch = _dt_epoch(expires_at)
        result.update({
            "share_id": token_hash,
            "is_permanent": bool(permanent),
            "expires_at": _dt_iso(expires_at),
            "expires_at_epoch": expires_epoch,
            "remaining_seconds": None if permanent else max(0, expires_epoch - int(time.time())),
        })
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


_fast._create_scoped_share = _create_scoped_share_guarded
_fast._update_share_settings = _update_share_settings_with_expiry

try:
    _ensure_columns()
    print("[ORDER] share admin runtime patch ready")
except Exception as exc:
    print(f"[WARN] ORDER share admin migration deferred: {type(exc).__name__}: {exc}")
