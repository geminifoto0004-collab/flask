"""Dedicated XINGWANG crawler/containers/aduana service.

Run with: gunicorn crawler_app:app --workers 1 --threads 2 --timeout 120
No ORDER blueprints, B2 asset modules, ORDER background jobs, or ORDER DB credentials.
The caller MUST supply a separate TiDB Cloud instance using CRAWLER_TIDB_URL.
"""
from __future__ import annotations

import hmac
import os
import threading
from urllib.parse import urlparse

# Set the crawler-only database identity before importing any application modules.
_database_url = (os.environ.get("CRAWLER_TIDB_URL") or "").strip()
if not _database_url:
    raise RuntimeError("CRAWLER_TIDB_URL is required (a separate physical TiDB instance)")
_parsed = urlparse(_database_url)
if _parsed.scheme not in {"mysql", "mysql+pymysql"} or not (
    _parsed.hostname and _parsed.username and _parsed.path.strip("/")
):
    raise RuntimeError("CRAWLER_TIDB_URL must identify a TiDB MySQL database")
if _parsed.path.strip("/") == "order_tracking":
    raise RuntimeError("Crawler service must not use ORDER's order_tracking database")
for key in ("CRAWLER_SECRET_KEY", "SUPER_ADMIN_EMAIL", "SUPER_ADMIN_PASSWORD"):
    if not (os.environ.get(key) or "").strip():
        raise RuntimeError(key + " must be configured for crawler service")
if len(os.environ["CRAWLER_SECRET_KEY"]) < 32:
    raise RuntimeError("CRAWLER_SECRET_KEY must have at least 32 characters")

os.environ["XINGWANG_SERVICE_ROLE"] = "CRAWLER"
os.environ["DATABASE_TYPE"] = "tidb"
os.environ["DB_TARGET"] = "TIDB1"  # compatibility alias; points to CRAWLER_TIDB_URL, NOT ORDER TiDB1.
os.environ["TIDB1_URL"] = _database_url
os.environ["DATABASE_URL"] = _database_url
os.environ["TIDB_MIRROR_ENABLED"] = "false"
os.environ["TIDB_FAILOVER_ENABLED"] = "false"
# Do not let inherited ORDER standby credentials enable a second database path.
for key in ("TIDB2_URL", "TIDB2_HOST", "TIDB2_USER", "TIDB2_PASSWORD", "TIDB2_NAME"):
    os.environ.pop(key, None)

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from config import config, admin_config
from database import init_database, get_db_connection, get_cursor, get_lastrowid
from utils.time_utils import get_chile_time_naive

app = Flask(__name__)
app.secret_key = os.environ["CRAWLER_SECRET_KEY"]
app.config.update(
    PERMANENT_SESSION_LIFETIME=config.PERMANENT_SESSION_LIFETIME,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="XW_CRAWLER_SESSION",
)

# Only crawler and container blueprints. Do not import app:app, ORDER, /tracking,
# /share or the B2 ORDER metadata writers.
from blueprints.user_auth_bp import user_auth_bp
from blueprints.api_auth_bp import api_auth_bp
from blueprints.monitor_bp import monitor_bp
from blueprints.container_bp import container_bp
from blueprints.container_excel_bp import container_excel_bp
from blueprints.aduana_monitor import aduana_bp
from blueprints.automation_hub import automation_hub_bp

for blueprint in (
    user_auth_bp, api_auth_bp, monitor_bp, container_bp,
    container_excel_bp, aduana_bp, automation_hub_bp,
):
    app.register_blueprint(blueprint)

_db_init_lock = threading.Lock()
_db_initialized = False


@app.before_request
def crawler_guard():
    global _db_initialized
    path = request.path
    if (path.startswith("/share/") or path.startswith("/tracking")
            or path.startswith("/api/order-cloud/")
            or path.startswith("/api/telegram/order-shares/")
            or path.startswith("/telegram/order-shares")
            or path.startswith("/cn/order-links")):
        return jsonify(ok=False, error="not_on_crawler_service"), 404
    if path in ("/ping", "/health") or path.startswith("/static/"):
        return None
    if not _db_initialized:
        with _db_init_lock:
            if not _db_initialized:
                # Unlike the legacy main app, do not silently mark a failed init
                # as complete. A subsequent authorized call can retry.
                init_database()
                _db_initialized = True
    return None


@app.get("/health")
@app.get("/ping")
def crawler_ping():
    resp = app.response_class("OK", 200, mimetype="text/plain")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/ready")
def crawler_ready():
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
        next_path = str(request.args.get("next") or "").strip()
        if next_path.startswith("/") and not next_path.startswith("//"):
            session["post_login_next"] = next_path
        return render_template("user/login.html")
    email = str(request.form.get("email") or "").strip()
    password = str(request.form.get("password") or "")
    allowed = (hmac.compare_digest(email, os.environ["SUPER_ADMIN_EMAIL"])
               and hmac.compare_digest(password, os.environ["SUPER_ADMIN_PASSWORD"]))
    if not allowed:
        return render_template("user/login.html", error="Correo electrónico o contraseña incorrectos"), 401
    conn = get_db_connection()
    try:
        cur = get_cursor(conn)
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        user_id = (row.get("id") if isinstance(row, dict) else row[0]) if row else None
        if user_id is None:
            from services.user_service import hash_password
            cur.execute(
                "INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                (admin_config.SUPER_ADMIN_USERNAME, email, hash_password(password),
                 admin_config.SUPER_ADMIN_ROLE,
                 get_chile_time_naive().strftime("%Y-%m-%d %H:%M:%S")),
            )
            user_id = get_lastrowid(cur, conn)
            conn.commit()
    finally:
        conn.close()
    session.clear()
    session.update(
        logged_in=True, user_id=user_id, email=email,
        username=admin_config.SUPER_ADMIN_USERNAME,
        role=admin_config.SUPER_ADMIN_ROLE,
    )
    # Limit login redirection to local paths.
    return redirect("/admin/automation")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return redirect("/admin/automation" if session.get("logged_in") else "/login")


@app.get("/admin")
@app.get("/admin/dashboard")
def admin_dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return redirect("/admin/automation")
