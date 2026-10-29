"""Dedicated XINGWANG crawler service with safe setup mode.

Start on Render: gunicorn crawler_app:app --workers 1 --threads 2 --timeout 120

Setup mode (default) runs login/setup pages without a database or crawler.
After provisioning an independent TiDB, set CRAWLER_TIDB_URL and
CRAWLER_SETUP_MODE=0 to enable the crawler and container blueprints.

The service never mounts ORDER sharing, tracking or B2 ORDER endpoints.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

_SETUP_MODE = os.environ.get("CRAWLER_SETUP_MODE", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
os.environ["XINGWANG_SERVICE_ROLE"] = "CRAWLER"

# Configure a crawler-only DB before importing database/config. A copy of
# ORDER's DATABASE_URL or TIDB1_* must never be used as a fallback.
if not _SETUP_MODE:
    _database_url = (os.environ.get("CRAWLER_TIDB_URL") or "").strip()
    if not _database_url:
        raise RuntimeError("CRAWLER_TIDB_URL is required when CRAWLER_SETUP_MODE=0")
    parsed = urlparse(_database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"} or not (
        parsed.hostname and parsed.username and parsed.path.strip("/")
    ):
        raise RuntimeError("CRAWLER_TIDB_URL must be a MySQL URL with host/user/database")
    if parsed.path.strip("/") == "order_tracking":
        raise RuntimeError("Crawler service cannot use ORDER's order_tracking database")
    if any(_database_url == (os.environ.get(key) or "").strip() for key in (
        "ORDER_DATABASE_URL", "ORDER_TIDB1_URL", "ORDER_TIDB2_URL"
    )):
        raise RuntimeError("Crawler database URL must be separate from ORDER")
    os.environ["DATABASE_TYPE"] = "tidb"
    os.environ["DB_TARGET"] = "TIDB1"  # compatibility alias, maps to crawler TiDB
    os.environ["TIDB1_URL"] = _database_url
    os.environ["DATABASE_URL"] = _database_url
    os.environ["TIDB_MIRROR_ENABLED"] = "false"
    os.environ["TIDB_FAILOVER_ENABLED"] = "false"
    for key in ("TIDB2_URL", "TIDB2_HOST", "TIDB2_USER",
                "TIDB2_PASSWORD", "TIDB2_NAME"):
        os.environ.pop(key, None)

# Existing names are supported so there is no second admin password to learn.
# With no configured credentials, setup page is public but login is disabled.
_key_candidates = [
    (os.environ.get("CRAWLER_SECRET_KEY") or "").strip(),
    (os.environ.get("SECRET_KEY") or "").strip(),
]
# A short crawler key must not shadow a valid existing SECRET_KEY.
_secret_key = next((key for key in _key_candidates if len(key) >= 32), "")
_admin_email = (os.environ.get("SUPER_ADMIN_EMAIL") or "").strip()
_admin_password = os.environ.get("SUPER_ADMIN_PASSWORD") or ""
_login_setup_problems = []
if not _secret_key:
    _login_setup_problems.append("SECRET_KEY 或 CRAWLER_SECRET_KEY 必須至少 32 字元")
if not _admin_email:
    _login_setup_problems.append("未設定 SUPER_ADMIN_EMAIL")
if not _admin_password:
    _login_setup_problems.append("未設定 SUPER_ADMIN_PASSWORD")
_credentials_ready = not _login_setup_problems
if not _SETUP_MODE and not _credentials_ready:
    raise RuntimeError(
        "Configure SECRET_KEY (32+ chars), SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD"
    )

app = Flask(__name__)
# Ephemeral secret makes public setup page render safely, but no login is
# accepted until a stable environment secret is configured.
app.secret_key = _secret_key if len(_secret_key) >= 32 else secrets.token_hex(32)
app.config.update(
    PERMANENT_SESSION_LIFETIME=3600,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="XW_CRAWLER_SESSION",
    MAX_CONTENT_LENGTH=16 * 1024,
)
_db_init_lock = threading.Lock()
_db_initialized = False


def _login_marker():
    """Invalidate sessions when login credentials change."""
    data = (_admin_email + "\0" + _admin_password).encode("utf-8")
    return hmac.new(app.secret_key.encode("utf-8"), data, hashlib.sha256).hexdigest()


def _logged_in():
    return bool(
        _credentials_ready
        and session.get("crawler_admin") is True
        and hmac.compare_digest(str(session.get("credential_marker") or ""),
                                _login_marker())
    )


if not _SETUP_MODE:
    from config import config, admin_config
    from database import init_database, get_db_connection, get_cursor, get_lastrowid
    from utils.time_utils import get_chile_time_naive

    app.config["PERMANENT_SESSION_LIFETIME"] = config.PERMANENT_SESSION_LIFETIME
    from blueprints.user_auth_bp import user_auth_bp
    from blueprints.api_auth_bp import api_auth_bp
    from blueprints.monitor_bp import monitor_bp
    from blueprints.container_bp import container_bp
    from blueprints.container_excel_bp import container_excel_bp
    from blueprints.aduana_monitor import aduana_bp
    from blueprints.automation_hub import automation_hub_bp
    for blueprint in (user_auth_bp, api_auth_bp, monitor_bp, container_bp,
                      container_excel_bp, aduana_bp, automation_hub_bp):
        app.register_blueprint(blueprint)


@app.before_request
def crawler_guard():
    global _db_initialized
    path = request.path
    # Never serve the ORDER site or order sync on this process.
    if (path.startswith("/share/") or path.startswith("/tracking")
            or path.startswith("/api/order-cloud/")
            or path.startswith("/api/telegram/order-shares/")
            or path.startswith("/telegram/order-shares")
            or path.startswith("/cn/order-links")):
        return jsonify(ok=False, error="not_on_crawler_service"), 404
    if _SETUP_MODE:
        allowed = {"/", "/ping", "/health", "/ready", "/login",
                   "/logout", "/admin", "/admin/dashboard", "/admin/setup"}
        if path not in allowed and not path.startswith("/static/"):
            return jsonify(ok=False, error="crawler_not_configured"), 503
        return None
    if path in ("/ping", "/health") or path.startswith("/static/"):
        return None
    if not _db_initialized:
        with _db_init_lock:
            if not _db_initialized:
                init_database()  # Do not mark failed migrations as completed.
                _db_initialized = True
    return None


@app.get("/health")
@app.get("/ping")
def crawler_ping():
    response = app.response_class("OK", 200, mimetype="text/plain")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/ready")
def crawler_ready():
    if _SETUP_MODE:
        return jsonify(ok=False, service="crawler", setup_mode=True,
                       database="not_configured"), 503
    try:
        conn = get_db_connection()
        try:
            cur = get_cursor(conn)
            cur.execute("SELECT 1")
            cur.fetchone()
        finally:
            conn.close()
    except Exception:
        return jsonify(ok=False, service="crawler", database="unavailable"), 503
    return jsonify(ok=True, service="crawler", database="ready")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("crawler/login.html",
                               login_enabled=_credentials_ready,
                               login_setup_problems=_login_setup_problems)
    if not _credentials_ready:
        return render_template("crawler/login.html", login_enabled=False,
                               login_setup_problems=_login_setup_problems,
                               error="請先完成下列 Render Environment 設定"), 503
    # Prevent cross-origin login requests; do not rely solely on SameSite.
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify(ok=False, error="invalid_origin"), 403
    email = str(request.form.get("email") or "").strip()
    password = str(request.form.get("password") or "")
    if not (hmac.compare_digest(email, _admin_email)
            and hmac.compare_digest(password, _admin_password)):
        return render_template("crawler/login.html", login_enabled=True,
                               error="Correo electrónico o contraseña incorrectos"), 401
    session.clear()
    session.update(crawler_admin=True, logged_in=True,
                   role="super_admin", username="super_admin",
                   email=email, credential_marker=_login_marker())
    return redirect("/admin/setup" if _SETUP_MODE else "/admin/automation")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return redirect("/admin/setup" if _SETUP_MODE and _logged_in()
                    else ("/admin/automation" if _logged_in() else "/login"))


@app.get("/admin")
@app.get("/admin/dashboard")
def admin_dashboard():
    if not _logged_in():
        return redirect(url_for("login"))
    return redirect("/admin/setup" if _SETUP_MODE else "/admin/automation")


@app.get("/admin/setup")
def setup_dashboard():
    if not _logged_in():
        return redirect(url_for("login"))
    return render_template(
        "crawler/setup.html", setup_mode=_SETUP_MODE,
        database_configured=bool((os.environ.get("CRAWLER_TIDB_URL") or "").strip()),
        automation_key_configured=bool((os.environ.get("AUTOMATION_MASTER_KEY") or "").strip()),
    )
