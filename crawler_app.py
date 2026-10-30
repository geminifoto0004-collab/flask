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
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from jinja2 import ChoiceLoader, FileSystemLoader

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

# Keep the same administrator email/password as ORDER, with no new
# credential to memorize. Never use short/guessable strings as Flask signing keys.
# Prefer existing long secrets; if absent, use a cryptographically random
# process-local key. The latter safely invalidates sessions on redeploy/restart.
_key_candidates = [
    (os.environ.get("CRAWLER_SECRET_KEY") or "").strip(),
    (os.environ.get("SECRET_KEY") or "").strip(),
    (os.environ.get("AUTOMATION_MASTER_KEY") or "").strip(),
]
_existing_long_key = next((key for key in _key_candidates if len(key) >= 32), "")
if _existing_long_key:
    # Domain separation: a key also used to encrypt Telegram tokens is never
    # directly repurposed as Flask's cookie signing key.
    _secret_key = hashlib.sha256(
        ("xingwang-crawler-session:v1:" + _existing_long_key).encode("utf-8")
    ).hexdigest()
    _session_key_mode = "stable"
else:
    _secret_key = secrets.token_hex(32)
    _session_key_mode = "temporary"

_admin_email = (os.environ.get("SUPER_ADMIN_EMAIL") or "").strip()
_admin_password = os.environ.get("SUPER_ADMIN_PASSWORD") or ""
_login_setup_problems = []
if not _admin_email:
    _login_setup_problems.append("未設定 SUPER_ADMIN_EMAIL")
if not _admin_password:
    _login_setup_problems.append("未設定 SUPER_ADMIN_PASSWORD")
_credentials_ready = not _login_setup_problems
if not _SETUP_MODE and not _credentials_ready:
    raise RuntimeError(
        "SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD must be configured"
    )

app = Flask(__name__)
# This is the original Automation Hub template folder used on Render 0004.
# In setup mode its Blueprint is not registered (no TiDB connection), so
# explicitly expose the *same* templates to the Flask loader.
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(str(Path(__file__).resolve().parent /
                         "blueprints" / "automation_hub" / "templates")),
])
app.secret_key = _secret_key
app.config.update(
    PERMANENT_SESSION_LIFETIME=3600,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="XW_CRAWLER_SESSION",
    # The original container Excel/API bulk imports can exceed a login form.
    # Keep setup mode small, but allow bounded operational payloads when active.
    MAX_CONTENT_LENGTH=(16 * 1024 if _SETUP_MODE else 10 * 1024 * 1024),
)
_db_init_lock = threading.Lock()
_db_initialized = False


@app.context_processor
def crawler_template_context():
    # Reuse the original XINGWANG Admin UI while showing only crawler modules.
    return {"crawler_only": True, "crawler_setup_mode": _SETUP_MODE}


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
    from crawler_db_bootstrap import probe_schema, initialize_schema, diagnose_connection
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

    # Reuse the 0004 admin functions, actual routes, templates and CRUD.
    # This is imported only after independent TiDB and the CRAWLER service
    # role have been set. It does not import or initialize ORDER app:app.
    from crawler_legacy_admin import install_crawler_admin
    install_crawler_admin(app)

    # These two pages originally lived in app.py (0004). The dedicated
    # crawler process does not import app.py, so expose them here as well.
    @app.get("/user/services")
    def crawler_user_services():
        if not session.get("logged_in") or not session.get("user_id"):
            return redirect(url_for("user_auth.login_page"))
        return render_template("user/services.html")

    @app.get("/user/services/api")
    def crawler_user_services_api():
        if not session.get("logged_in") or not session.get("user_id"):
            return jsonify(success=False, error="請先登入"), 401

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT us.id, us.service_id, us.status, us.start_date,
                       us.end_date, us.created_at,
                       s.name AS service_name, s.description
                FROM user_services us
                JOIN services s ON us.service_id = s.id
                WHERE us.user_id = ?
                ORDER BY us.created_at DESC
                """,
                (session["user_id"],),
            )
            rows = cursor.fetchall()
            today = get_chile_time_naive().strftime("%Y-%m-%d")
            result = []
            for row in rows:
                item = dict(row)
                for field in ("start_date", "end_date", "created_at"):
                    value = item.get(field)
                    if value is not None:
                        item[field] = str(value)
                end_date = (item.get("end_date") or "")[:10]
                if item.get("status") == "active" and end_date and end_date < today:
                    item["status"] = "inactive"
                    item["is_expired"] = True
                result.append(item)
            return jsonify(success=True, services=result)
        except Exception:
            app.logger.exception("Crawler user services query failed")
            return jsonify(success=False, error="Error al cargar servicios"), 500
        finally:
            if conn is not None:
                conn.close()


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
                   "/logout", "/admin", "/admin/dashboard", "/admin/setup",
                   "/admin/automation", "/admin/system-check"}
        if path not in allowed and not path.startswith("/static/"):
            return jsonify(ok=False, error="crawler_not_configured"), 503
        return None
    # Login and system-check must remain reachable even if a TiDB migration
    # fails, so the administrator can see and repair missing tables.
    if path in ("/", "/ping", "/health", "/ready", "/login",
                "/logout", "/admin/setup", "/admin/system-check",
                "/admin/system-check/initialize") or path.startswith("/static/"):
        return None
    if not _db_initialized:
        try:
            with _db_init_lock:
                if not _db_initialized:
                    initialize_schema()
                    _db_initialized = True
        except Exception as exc:
            app.logger.warning("Crawler TiDB initialization failed: %s", type(exc).__name__)
            if request.method == "GET" and not path.startswith("/api/"):
                return redirect("/admin/system-check")
            return jsonify(ok=False, error="crawler_tidb_schema_not_ready",
                           diagnostic="/admin/system-check"), 503
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
        return render_template("user/login.html",
                               login_enabled=_credentials_ready,
                               login_setup_problems=_login_setup_problems)
    if not _credentials_ready:
        return render_template("user/login.html", login_enabled=False,
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
        return render_template("user/login.html", login_enabled=True,
                               error="Correo electrónico o contraseña incorrectos"), 401
    # In active mode keep the original admin's actual TiDB user_id in the
    # session: monitoring and container management require it.
    user_id = None
    if not _SETUP_MODE:
        try:
            global _db_initialized
            if not _db_initialized:
                with _db_init_lock:
                    if not _db_initialized:
                        initialize_schema()
                        _db_initialized = True
            conn = get_db_connection()
            try:
                cur = get_cursor(conn)
                cur.execute("SELECT id FROM users WHERE email = ?", (email,))
                row = cur.fetchone()
                if row:
                    user_id = row.get("id") if isinstance(row, dict) else row[0]
            finally:
                conn.close()
            if user_id is None:
                raise RuntimeError("Crawler administrator record unavailable")
        except Exception as exc:
            # Keep the existing environment-variable credentials usable:
            # only the authenticated admin may open the repair page.
            app.logger.warning("Crawler admin TiDB not ready: %s", type(exc).__name__)
            user_id = None
    session.clear()
    session.update(crawler_admin=True, logged_in=True,
                   role="super_admin", username="super_admin",
                   user_id=user_id, email=email, credential_marker=_login_marker())
    return redirect("/admin/system-check" if not _SETUP_MODE and user_id is None else
                    ("/admin/automation" if _SETUP_MODE else "/admin"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return redirect(("/admin/automation" if _SETUP_MODE else "/admin") if _logged_in() else "/login")


if _SETUP_MODE:
    # Before the new TiDB is activated, no original admin routes are imported.
    @app.get("/admin")
    @app.get("/admin/dashboard")
    def admin_dashboard():
        if not _logged_in():
            return redirect(url_for("login"))
        return redirect("/admin/automation")


if _SETUP_MODE:
    # When TiDB3 is not yet active, render the actual 0004 Automation Hub
    # template read-only. After activation the registered Blueprint owns the
    # exact same route and template.
    @app.get("/admin/automation")
    def setup_automation_dashboard():
        if not _logged_in():
            return redirect(url_for("login", next=request.path))
        return render_template(
            "automation_hub/dashboard.html",
            bots=[],
            plugins=[{"key": "ADUANA", "label": "Aduana Monitor",
                      "admin_path": "/admin/automation/aduana"}],
            settings=SimpleNamespace(
                MASTER_KEY=(os.environ.get("AUTOMATION_MASTER_KEY") or "").strip(),
                PUBLIC_BASE_URL=(os.environ.get("AUTOMATION_PUBLIC_BASE_URL")
                                 or os.environ.get("RENDER_EXTERNAL_URL") or "").strip(),
            ),
            message="",
            database_configured=bool((os.environ.get("CRAWLER_TIDB_URL") or "").strip()),
        )


@app.get("/admin/system-check")
def crawler_system_check():
    if not _logged_in():
        return redirect(url_for("login"))
    probe = None
    error = None
    connection_diagnostic = None
    if not _SETUP_MODE:
        connection_diagnostic = diagnose_connection()
        if connection_diagnostic["connected"]:
            try:
                probe = probe_schema()
            except Exception as exc:
                app.logger.warning("Crawler TiDB schema inspection failed: %s", type(exc).__name__)
                error = (
                    "TiDB 連線正常，但資料表檢查失敗（" + type(exc).__name__
                    + "）。請查看 Render 日誌中的 SQL 錯誤代碼。"
                )
    csrf_token = session.get("crawler_db_csrf")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session["crawler_db_csrf"] = csrf_token
    message = session.pop("crawler_db_notice", None)
    return render_template("admin/crawler_system_check.html",
                           setup_mode=_SETUP_MODE, probe=probe, error=error,
                           connection_diagnostic=connection_diagnostic,
                           csrf_token=csrf_token, message=message)


@app.post("/admin/system-check/initialize")
def crawler_system_initialize():
    global _db_initialized
    if not _logged_in() or _SETUP_MODE:
        return jsonify(ok=False, error="forbidden"), 403
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin != request.host_url.rstrip("/"):
        return jsonify(ok=False, error="invalid_origin"), 403
    expected = str(session.get("crawler_db_csrf") or "")
    supplied = str(request.form.get("csrf_token") or "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return jsonify(ok=False, error="invalid_csrf"), 403
    try:
        with _db_init_lock:
            result = initialize_schema()
            _db_initialized = True
        # User id is set during a successful login against TiDB; after initial
        # provisioning, log in again to refresh that identity.
        session["crawler_db_notice"] = (
            f"資料表檢查完成：{result['found']}/{result['expected']}。"
            "如果剛剛第一次建立資料庫，請登出後再登入一次。"
        )
    except Exception as exc:
        app.logger.warning("Crawler TiDB schema repair failed: %s", type(exc).__name__)
        session["crawler_db_notice"] = (
            "初始化失敗（" + type(exc).__name__
            + "），請檢查 Render Logs 中的 TiDB 初始化錯誤。"
        )
    return redirect("/admin/system-check")


@app.get("/admin/setup")
def setup_dashboard():
    if not _logged_in():
        return redirect(url_for("login"))
    return redirect("/admin/automation")
