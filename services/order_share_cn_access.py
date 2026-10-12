"""Password-protected read-only China entry for existing ORDER share links.

This service never accepts Telegram identifiers as password substitutes. Password
hash and current session revision are stored in TiDB, separate from ORDER logins.
The password is set/reset exclusively via the existing XINGWANG admin session.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

from flask import (Blueprint, current_app, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

cn_bp = Blueprint("order_share_cn", __name__)
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()
_COOKIE_NAME = "xingwang_cn_links"
_COOKIE_AGE = 7 * 24 * 3600
_COOKIE_PATH = "/cn/order-links"
_LOGIN_WINDOW = 15 * 60
_MAX_FAILURES = 8
_ADMIN_CSRF_COOKIE = "xingwang_cn_admin_csrf"
_ADMIN_CSRF_AGE = 60 * 60
_ADMIN_CSRF_PATH = "/admin/automation/china-links"
_CN_CSRF_AGE = 60 * 60


def _secret_ready():
    secret = current_app.secret_key
    return bool(secret and len(str(secret)) >= 20
                and secret != "dev-secret-key-change-in-production")


def _serializer():
    if not _secret_ready():
        raise RuntimeError("Flask SECRET_KEY is not configured securely")
    return URLSafeTimedSerializer(str(current_app.secret_key), salt="order-share-cn-access-v1")


def _db():
    from database import get_db_connection
    return get_db_connection()


def _cursor(conn):
    from database import get_cursor
    return get_cursor(conn)


def _row(row, cur):
    from database import get_row_dict
    return get_row_dict(row, cur) or {}


def _ensure_schema():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        from database import get_id_type
        conn = _db()
        try:
            cur = _cursor(conn)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_share_cn_settings (
                    id INTEGER PRIMARY KEY,
                    password_hash VARCHAR(255) NOT NULL,
                    revision VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(32) NOT NULL
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_share_cn_failures (
                    id {id_type},
                    client_hash VARCHAR(64) NOT NULL,
                    attempted_at BIGINT NOT NULL
                )""".format(id_type=get_id_type()))
            conn.commit()
            _SCHEMA_READY = True
        finally:
            conn.close()


def _settings():
    _ensure_schema()
    conn = _db()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT password_hash, revision FROM order_share_cn_settings WHERE id=1")
        return _row(cur.fetchone(), cur)
    finally:
        conn.close()


def _update_password(password):
    """Store only salted PBKDF2 hash. Changing it revokes all issued cookies."""
    if not _secret_ready():
        raise RuntimeError("Flask SECRET_KEY is missing")
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        raise ValueError("password must contain 1 to 128 characters")
    _ensure_schema()
    digest = generate_password_hash(password, method="pbkdf2:sha256:600000", salt_length=16)
    revision = secrets.token_hex(20)
    conn = _db()
    try:
        cur = _cursor(conn)
        # A single admin-only transaction. This table is independent of order data.
        cur.execute("DELETE FROM order_share_cn_settings WHERE id=1")
        cur.execute(
            "INSERT INTO order_share_cn_settings (id,password_hash,revision,updated_at) "
            "VALUES (1,?,?,?)",
            (digest, revision, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _client_hash():
    # Use the server's peer address, never a user-supplied forwarding header.
    peer = str(request.remote_addr or "unknown")[:128]
    key = str(current_app.secret_key or "no-key").encode("utf-8")
    return hmac.new(key, peer.encode("utf-8"), hashlib.sha256).hexdigest()


def _failure_count():
    _ensure_schema()
    conn = _db()
    try:
        cur = _cursor(conn)
        cur.execute("SELECT COUNT(*) AS n FROM order_share_cn_failures "
                    "WHERE client_hash=? AND attempted_at>=?",
                    (_client_hash(), int(time.time()) - _LOGIN_WINDOW))
        return int(_row(cur.fetchone(), cur).get("n") or 0)
    finally:
        conn.close()


def _record_failure():
    _ensure_schema()
    conn = _db()
    try:
        cur = _cursor(conn)
        cur.execute("INSERT INTO order_share_cn_failures "
                    "(client_hash, attempted_at) VALUES (?,?)",
                    (_client_hash(), int(time.time())))
        # Clean old attempts periodically to avoid an ever-growing TiDB table.
        cur.execute("DELETE FROM order_share_cn_failures WHERE attempted_at<?",
                    (int(time.time()) - 2 * _LOGIN_WINDOW,))
        conn.commit()
    finally:
        conn.close()


def _set_cookie(response, revision):
    ticket = _serializer().dumps({"v": revision})
    response.set_cookie(_COOKIE_NAME, ticket, max_age=_COOKIE_AGE, secure=True,
                        httponly=True, samesite="Lax", path=_COOKIE_PATH)
    return response


def _clear_cookie(response):
    response.delete_cookie(_COOKIE_NAME, path=_COOKIE_PATH, secure=True,
                           httponly=True, samesite="Lax")
    return response


def _authorized(settings=None):
    if not _secret_ready():
        return False
    raw = request.cookies.get(_COOKIE_NAME)
    if not raw:
        return False
    try:
        ticket = _serializer().loads(raw, max_age=_COOKIE_AGE)
        settings = settings if settings is not None else _settings()
        return bool(settings.get("revision") and settings.get("password_hash")
                    and isinstance(ticket, dict)
                    and hmac.compare_digest(str(ticket.get("v", "")),
                                            str(settings["revision"])))
    except (BadSignature, SignatureExpired, ValueError, RuntimeError):
        return False


def _same_origin():
    """Use the actual browser-facing Host, not an unrelated Render URL config.

    PUBLIC_BASE_URL is used for links and Bot webhooks and may be configured to
    a different host. The CSRF origin must instead match the host that received
    this form POST. Keep the HTTPS and signed-session token checks.
    """
    source = request.headers.get("Origin") or request.headers.get("Referer") or ""
    parsed = urlsplit(source)
    target_host = request.host.strip().lower()
    return bool(parsed.scheme == "https" and parsed.netloc.lower() == target_host)


def _csrf(scope):
    key = "share_cn_csrf_" + scope
    if key not in session:
        session[key] = secrets.token_urlsafe(28)
    return session[key]


def _csrf_valid(scope):
    supplied = str(request.form.get("csrf") or "")
    actual = str(session.get("share_cn_csrf_" + scope) or "")
    # The CSRF token lives in Flask's signed session. Some mainland
    # embedded browsers omit Origin/Referer; reject mismatches if supplied.
    origin_present = bool(request.headers.get("Origin") or request.headers.get("Referer"))
    return bool(supplied and actual and hmac.compare_digest(supplied, actual)
                and (not origin_present or _same_origin()))


def _admin_csrf_serializer():
    """Signed admin form token, independent from the parent Flask session."""
    if not _secret_ready():
        raise RuntimeError("Flask SECRET_KEY is not configured securely")
    return URLSafeTimedSerializer(str(current_app.secret_key),
                                  salt="order-share-cn-admin-csrf-v2")


def _admin_identity():
    return "|".join((str(session.get("user_id") or ""),
                     str(session.get("username") or ""),
                     str(session.get("role") or "")))


def _new_admin_csrf():
    return _admin_csrf_serializer().dumps({
        "user": _admin_identity(), "nonce": secrets.token_urlsafe(24)
    })


def _admin_csrf_valid():
    """Signed double-submit token bound to the admin and a separate cookie."""
    form_token = str(request.form.get("csrf") or "")
    cookie_token = str(request.cookies.get(_ADMIN_CSRF_COOKIE) or "")
    if (not form_token or not cookie_token or len(form_token) > 700
            or not hmac.compare_digest(form_token, cookie_token)):
        return False
    try:
        payload = _admin_csrf_serializer().loads(form_token, max_age=_ADMIN_CSRF_AGE)
        return bool(isinstance(payload, dict) and payload.get("nonce")
                    and hmac.compare_digest(
                        str(payload.get("user") or ""), _admin_identity()))
    except (BadSignature, SignatureExpired, ValueError, RuntimeError):
        return False


def _cn_csrf_serializer():
    """Independent signed token for China login/logout forms."""
    if not _secret_ready():
        raise RuntimeError("Flask SECRET_KEY is not configured securely")
    return URLSafeTimedSerializer(str(current_app.secret_key),
                                  salt="order-share-cn-form-csrf-v2")


def _new_cn_csrf(scope):
    return _cn_csrf_serializer().dumps({
        "scope": scope, "nonce": secrets.token_urlsafe(24)
    })


def _cn_csrf_valid(scope):
    """Verify fresh server-signed login/logout form, without an extra cookie.

    The password page is public and the user may open it through WeChat or
    other embedded browsers that reject cookies before login. Its signed
    form token is action-scoped and expires after one hour. Cross-site form
    submissions are rejected when browser origin/fetch metadata is available.
    The actual share data still requires the separate authenticated ticket.
    """
    form_token = str(request.form.get("csrf") or "")
    if not form_token or len(form_token) > 700:
        return False
    site = str(request.headers.get("Sec-Fetch-Site") or "").lower()
    if site == "cross-site":
        return False
    if request.headers.get("Origin") and not _same_origin():
        return False
    try:
        payload = _cn_csrf_serializer().loads(form_token, max_age=_CN_CSRF_AGE)
        return bool(isinstance(payload, dict) and payload.get("nonce")
                    and payload.get("scope") == scope)
    except (BadSignature, SignatureExpired, ValueError, RuntimeError):
        return False


def _login_page(error=None, status=200):
    # Password submission is a public authentication action, not an
    # authenticated state change. Do not require a pre-login CSRF token or
    # cookie: some browser/proxy paths discard them. The protected directory
    # API still requires a signed, seven-day login ticket after verification.
    return make_response(render_template(
        "order_share_telegram/cn_login.html", error=error
    ), status)


def _directory_page():
    return make_response(render_template(
        "order_share_telegram/index.html", china=True,
        logout_csrf=_new_cn_csrf("logout")
    ))


def _response_headers(response):
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'")
    return response


@cn_bp.after_request
def no_cache(response):
    return _response_headers(response)


def _admin():
    from config import admin_config
    return bool(session.get("logged_in") and
                session.get("role") in {"admin", admin_config.SUPER_ADMIN_ROLE})


@cn_bp.route("/admin/automation/china-links", methods=["GET", "POST"])
def admin_password():
    if not _admin():
        return redirect(url_for("login", next=request.path))
    if request.method == "GET":
        try:
            ready = bool(_settings().get("password_hash"))
        except Exception:
            return make_response("TiDB 暫時無法讀取，請稍後再試。", 503)
        try:
            token = _new_admin_csrf()
        except RuntimeError:
            return make_response("SECRET_KEY 設定異常，無法安全設定密碼。", 503)
        response = make_response(render_template(
            "order_share_telegram/cn_admin.html",
            ready=ready, csrf=token, notice=None))
        response.set_cookie(_ADMIN_CSRF_COOKIE, token, max_age=_ADMIN_CSRF_AGE,
                            secure=True, httponly=True, samesite="Strict",
                            path=_ADMIN_CSRF_PATH)
        return response

    if request.content_length is not None and request.content_length > 4096:
        return make_response("Request too large", 413)
    if not _admin_csrf_valid():
        return make_response(
            "密碼設定請求未通過安全驗證，請重新開啟管理頁後再試。", 403)
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if password != confirm or not 1 <= len(password) <= 128:
        return make_response("密碼必須至少 1 字元、最多 128 字元，且兩次輸入一致。", 400)
    try:
        _update_password(password)
    except Exception:
        return make_response("無法儲存密碼，請檢查 TiDB 和 SECRET_KEY 設定。", 503)
    response = redirect(url_for(".admin_password", updated="1"), code=303)
    response.delete_cookie(_ADMIN_CSRF_COOKIE, path=_ADMIN_CSRF_PATH,
                           secure=True, httponly=True, samesite="Strict")
    return response


@cn_bp.route("/cn/order-links", methods=["GET"])
def page():
    try:
        settings = _settings()
    except Exception:
        return make_response("服務暫時無法使用。", 503)
    if not settings.get("password_hash"):
        return make_response("中國客戶查詢入口尚未啟用，請聯絡管理員設定密碼。", 503)
    if _authorized(settings):
        return _directory_page()
    return _login_page()


@cn_bp.route("/cn/order-links/login", methods=["POST"])
def login():
    if request.content_length is not None and request.content_length > 4096:
        return make_response("Request too large", 413)
    # This only checks the submitted password and does not change any
    # authenticated user state. CSRF protection remains required for the
    # ADMIN password configuration and for authenticated logout.
    password = request.form.get("password", "")
    if not isinstance(password, str) or len(password) > 128:
        return make_response("密碼不正確。", 403)
    try:
        settings = _settings()
        if not settings.get("password_hash"):
            return make_response("入口尚未啟用。", 503)
        if _failure_count() >= _MAX_FAILURES:
            return make_response("嘗試次數過多，請 15 分鐘後再試。", 429)
        if not check_password_hash(settings["password_hash"], password):
            _record_failure()
            return _login_page(error="密碼錯誤，請重新輸入。", status=401)
    except Exception:
        return make_response("驗證暫時無法使用，請稍後再試。", 503)
    response = redirect(url_for(".page"), code=303)
    return _set_cookie(response, settings["revision"])


@cn_bp.route("/cn/order-links/logout", methods=["POST"])
def logout():
    if not _cn_csrf_valid("logout"):
        return make_response(
            "退出表單已失效，請重新整理客戶清單後再試。", 403)
    return _clear_cookie(redirect(url_for(".page"), code=303))


@cn_bp.get("/cn/order-links/app.js")
def frontend():
    from pathlib import Path
    from flask import send_file
    path = Path(__file__).resolve().parents[1] / "templates/order_share_telegram/app.js"
    return send_file(path, mimetype="text/javascript")


@cn_bp.get("/cn/order-links/data")
def directory():
    from services import order_share_telegram_bot as lookup

    try:
        settings = _settings()
        if not _authorized(settings):
            return jsonify(ok=False, error="unauthorized"), 403
        rows = lookup._lookup_all_full()
        items = [
            {
                "name": " ".join(str(row.get("customer_name")
                                      or row.get("customer_key") or "").split()),
                "url": lookup._share_url(row),
                "expires": lookup._date(row["expires_at"]) if row.get("expires_at") else None,
            }
            for row in rows
        ]
    except Exception:
        return jsonify(ok=False, error="temporarily_unavailable"), 503
    return jsonify(ok=True, count=len(items), items=items)
