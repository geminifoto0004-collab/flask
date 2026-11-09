"""Password-protected read-only China entry for existing ORDER share links.

The China access password is read from Render's CN_ORDER_LINKS_PASSWORD_HASH.
Share directory contents are still read from TiDB after authentication.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from io import BytesIO
from urllib.parse import urlsplit

from flask import (Blueprint, current_app, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

cn_bp = Blueprint("order_share_cn", __name__)
_FAILURES = {}
_FAILURES_LOCK = threading.Lock()
_GLOBAL_FAILURE_KEY = "__all__"
_GLOBAL_FAILURE_LIMIT = 40
_PUBLIC_LINK = "https://flask-393d.onrender.com/cn/order-links"
_COOKIE_NAME = "xingwang_cn_links"
_COOKIE_AGE = 7 * 24 * 3600
_COOKIE_PATH = "/cn/order-links"
_LOGIN_WINDOW = 15 * 60
_MAX_FAILURES = 8
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


def _settings():
    """No TiDB lookup: derive the cookie revision from the active Render secret.

    Accept an existing Werkzeug PBKDF2/scrypt hash or a raw passcode for
    compatibility with the six-digit Render setting. A missing configuration
    fails closed rather than falling back to the old TiDB password.
    """
    configured = os.environ.get("CN_ORDER_LINKS_PASSWORD_HASH", "").strip()
    if not 1 <= len(configured) <= 256 or not _secret_ready():
        return {}
    key = str(current_app.secret_key).encode("utf-8")
    revision = hmac.new(
        key, b"china-links-password-revision-v1:\x00" + configured.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"password_hash": configured, "revision": revision}


def _password_matches(configured, supplied):
    if not isinstance(supplied, str):
        return False
    if configured.startswith(("pbkdf2:", "scrypt:")) and configured.count("$") == 2:
        try:
            return check_password_hash(configured, supplied)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(configured.encode("utf-8"), supplied.encode("utf-8"))


def _client_hash():
    # Preserve the original peer-based bucket. Do not trust spoofable headers.
    peer = str(request.remote_addr or "unknown")[:128]
    key = str(current_app.secret_key or "no-key").encode("utf-8")
    return hmac.new(key, peer.encode("utf-8"), hashlib.sha256).hexdigest()


def _prune_bucket(key, now):
    attempts = _FAILURES.get(key)
    if attempts is not None:
        while attempts and attempts[0] <= now - _LOGIN_WINDOW:
            attempts.popleft()
        if not attempts:
            _FAILURES.pop(key, None)
    return _FAILURES.get(key, ())


def _failure_count():
    now = time.monotonic()
    with _FAILURES_LOCK:
        # The global cap also limits attempts from many different client IPs.
        global_attempts = _prune_bucket(_GLOBAL_FAILURE_KEY, now)
        peer_attempts = _prune_bucket(_client_hash(), now)
        if len(global_attempts) >= _GLOBAL_FAILURE_LIMIT:
            return _MAX_FAILURES
        return len(peer_attempts)


def _record_failure():
    now = time.monotonic()
    with _FAILURES_LOCK:
        peer_key = _client_hash()
        for key in (peer_key, _GLOBAL_FAILURE_KEY):
            _prune_bucket(key, now)
            _FAILURES.setdefault(key, deque()).append(now)
        # Bound stale per-peer state if many addresses hit this small endpoint.
        if len(_FAILURES) > 4096:
            for key in list(_FAILURES):
                _prune_bucket(key, now)


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


@cn_bp.get("/admin/automation/china-links")
def admin_password():
    """Display status and share QR; credentials are managed only in Render."""
    if not _admin():
        return redirect(url_for("login", next=request.path))
    ready = bool(_settings().get("password_hash"))
    return make_response(render_template(
        "order_share_telegram/cn_admin.html", ready=ready, public_url=_PUBLIC_LINK))


@cn_bp.get("/cn/order-links/qr.svg")
def share_qr():
    """Locally render a QR containing only the public URL, never the secret."""
    import qrcode
    from qrcode.image.svg import SvgPathImage

    out = BytesIO()
    qrcode.make(_PUBLIC_LINK, image_factory=SvgPathImage,
                box_size=8, border=4).save(out)
    response = make_response(out.getvalue())
    response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
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
    # Login changes no pre-existing authenticated state. Logout keeps CSRF
    # verification; administrator password changes are handled in Render.
    password = request.form.get("password", "")
    if not isinstance(password, str) or len(password) > 128:
        return make_response("密碼不正確。", 403)
    try:
        settings = _settings()
        if not settings.get("password_hash"):
            return make_response("入口尚未啟用。", 503)
        if _failure_count() >= _MAX_FAILURES:
            return make_response("嘗試次數過多，請 15 分鐘後再試。", 429)
        if not _password_matches(settings["password_hash"], password):
            _record_failure()
            return _login_page(error="密碼錯誤，請重新輸入。", status=401)
    except Exception:
        return make_response("驗證暫時無法使用，請稍後再試。", 503)
    response = redirect(url_for(".page"), code=303)
    return _set_cookie(response, settings["revision"])


@cn_bp.route("/cn/order-links/logout", methods=["POST"])
def logout():
    # Logout only deletes the China read-only access cookie. Do not block
    # an explicit logout because a signed form token has expired or is stale
    # after a Render deploy, a restored tab, or a browser/proxy header change.
    # Never revoke or modify unrelated Flask/ORDER sessions here.
    response = redirect(url_for(".page"), code=303)
    return _clear_cookie(response)


@cn_bp.get("/cn/order-links/app.js")
def frontend():
    from pathlib import Path
    from flask import send_file
    path = Path(__file__).resolve().parents[1] / "templates/order_share_telegram/app.js"
    return send_file(path, mimetype="text/javascript")


def _read_snapshot_update(conn):
    """Return a truthful ORDER timestamp from the selected TiDB.

    The whole-text snapshot marker is optional: newer standalone upload paths
    update cloud_orders without running the snapshot importer. A successful
    snapshot timestamp is preferred; otherwise clearly label the latest
    committed order-row update rather than pretending a crawler finished.
    Never read the other TiDB or create/mutate schema in this customer page.
    """
    target = str(getattr(conn, "active_target", "") or "").upper()
    if target not in {"TIDB1", "TIDB2"}:
        target = None
    meta = {"target": target, "updated_epoch": None, "status": "no_record"}
    snapshot_epoch = 0
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT UNIX_TIMESTAMP(updated_at) AS updated_epoch "
            "FROM cloud_order_snapshot_state WHERE snapshot_key=?",
            ("order_text_v1",),
        )
        row = _row(cur.fetchone(), cur)
        epoch = row.get("updated_epoch")
        if epoch is not None and int(epoch) > 0:
            snapshot_epoch = int(epoch)
    except Exception as exc:
        # Missing snapshot-state table on a standalone-sync TiDB is expected.
        # Do not expose SQL/connection details to an authenticated customer page.
        code = (getattr(exc, "args", None) or [None])[0]
        print(f"[ORDER CN time] snapshot marker unavailable on {target or 'DB'}: {type(exc).__name__} code={code}", flush=True)

    # A bounded-output read. Unlike the marker above, this is a data-change
    # timestamp, not proof that all crawler work finished successfully.
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT UNIX_TIMESTAMP(MAX(updated_at)) AS updated_epoch "
            "FROM cloud_orders WHERE active=TRUE"
        )
        row = _row(cur.fetchone(), cur)
        epoch = row.get("updated_epoch")
        if epoch is not None and int(epoch) > snapshot_epoch:
            meta.update(updated_epoch=int(epoch), status="orders_updated")
    except Exception as exc:
        code = (getattr(exc, "args", None) or [None])[0]
        print(f"[ORDER CN time] order timestamp unavailable on {target or 'DB'}: {type(exc).__name__} code={code}", flush=True)
        if not snapshot_epoch:
            meta["status"] = "unavailable"
    if snapshot_epoch and meta["status"] != "orders_updated":
        meta.update(updated_epoch=snapshot_epoch, status="recorded")
    return meta


@cn_bp.get("/cn/order-links/data")
def directory():
    from services import order_share_telegram_bot as lookup

    try:
        settings = _settings()
        if not _authorized(settings):
            return jsonify(ok=False, error="unauthorized"), 403
        conn = _db()
        try:
            rows = lookup._lookup_all_full(conn=conn)
            sync_meta = _read_snapshot_update(conn)
        finally:
            conn.close()
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
    return jsonify(ok=True, count=len(items), items=items, sync=sync_meta)
