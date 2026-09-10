# -*- coding: utf-8 -*-
from __future__ import annotations

import hmac
from functools import wraps

from flask import jsonify, redirect, render_template, request, session, url_for
from config import admin_config

from . import aduana_bp, bot, cron, owner_admin, settings, storage, telegram


@aduana_bp.before_request
def _aduana_schema_guard():
    storage.ensure_schema()


@aduana_bp.route("/api/aduana/health", methods=["GET"])
def health():
    owner = owner_admin.get_owner()
    return jsonify({
        "ok": True,
        "telegram_configured": telegram.is_configured(),
        "owner_configured": bool(owner or settings.OWNER_TELEGRAM_ID),
        "cron_secret_configured": bool(settings.CRON_SECRET),
    })


# Legacy webhook kept only for backwards compatibility with ADUANA_TELEGRAM_BOT_TOKEN.
# New bots created in Automation Hub use /api/automation/telegram/<bot_key>/webhook.
@aduana_bp.route("/api/aduana/telegram/webhook", methods=["POST"])
def telegram_webhook():
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "webhook secret not configured"}), 503
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied, settings.TELEGRAM_WEBHOOK_SECRET):
        return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    try:
        bot.handle_update(update)
    except Exception as exc:
        from flask import current_app
        current_app.logger.exception("Aduana Telegram update failed: %s", exc)
    return jsonify({"ok": True})


@aduana_bp.route("/api/aduana/check-all", methods=["GET", "POST"])
def check_all():
    if not settings.CRON_SECRET:
        return jsonify({"ok": False, "error": "cron secret not configured"}), 503
    supplied = request.headers.get("X-Cron-Secret") or request.args.get("secret") or ""
    if not hmac.compare_digest(str(supplied), settings.CRON_SECRET):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    started = cron.start_background_batch()
    return jsonify({"ok": True, "accepted": started, "status": "accepted" if started else "already_running"}), 202


def _admin_login_required(view):
    """Use the exact same parent FLASK admin session as /admin."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        allowed_roles = {"admin", admin_config.SUPER_ADMIN_ROLE}
        if not session.get("logged_in") or session.get("role") not in allowed_roles:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@aduana_bp.route(settings.ADMIN_PREFIX, methods=["GET"], strict_slashes=False)
@_admin_login_required
def admin_dashboard():
    return render_template(
        "aduana_admin/dashboard.html",
        counts=storage.admin_counts(),
        pending=storage.list_pending_users(),
        users=storage.list_users(),
        latest_run=storage.latest_run(),
        owner_user=owner_admin.get_owner(),
        telegram_configured=telegram.is_configured(),
        message=request.args.get("message") or "",
        settings=settings,
    )


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/users/<int:user_id>/approve", methods=["POST"])
@_admin_login_required
def admin_approve(user_id):
    user = storage.approve_user(
        user_id,
        permission_level=request.form.get("permission_level"),
        max_ruts=request.form.get("max_ruts"),
        can_query="can_query" in request.form,
        can_monitor="can_monitor" in request.form,
    )
    if user:
        try:
            telegram.send_message(
                user["chat_id"],
                "✅ <b>Tu acceso fue aprobado.</b>\n\nYa puedes usar Aduana Monitor.",
                reply_markup=telegram.MAIN_MENU,
            )
        except Exception:
            pass
    return redirect(url_for(".admin_dashboard"))


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/users/<int:user_id>/make-owner", methods=["POST"])
@_admin_login_required
def admin_make_owner(user_id):
    try:
        user = owner_admin.promote_to_owner(user_id)
    except ValueError as exc:
        return redirect(url_for(".admin_dashboard", message=str(exc)))

    if not user:
        return redirect(url_for(".admin_dashboard", message="Usuario no encontrado"))

    try:
        telegram.send_message(
            user["chat_id"],
            "⭐ <b>Tu cuenta fue configurada como OWNER.</b>\n\n"
            "Tienes acceso sin límite de RUT, consulta histórica completa y todas las aduanas.",
            reply_markup=telegram.MAIN_MENU,
        )
    except Exception:
        pass
    return redirect(url_for(".admin_dashboard", message="OWNER configurado correctamente"))


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/users/<int:user_id>/reject", methods=["POST"])
@_admin_login_required
def admin_reject(user_id):
    storage.reject_user(user_id)
    return redirect(url_for(".admin_dashboard"))


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/users/<int:user_id>", methods=["GET", "POST"])
@_admin_login_required
def admin_user(user_id):
    if request.method == "POST":
        storage.update_user_permissions(
            user_id,
            status=request.form.get("status"),
            permission_level=request.form.get("permission_level"),
            max_ruts=request.form.get("max_ruts") or settings.DEFAULT_MAX_RUTS,
            can_query="can_query" in request.form,
            can_monitor="can_monitor" in request.form,
        )
        return redirect(url_for(".admin_user", user_id=user_id))
    user = storage.get_user(user_id)
    if not user:
        return "Not found", 404
    return render_template(
        "aduana_admin/user.html",
        user=user,
        monitors=storage.list_user_monitors(user_id),
        settings=settings,
    )


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/runs", methods=["GET"])
@_admin_login_required
def admin_runs():
    return render_template("aduana_admin/runs.html", runs=storage.list_runs(100), settings=settings)


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/run-now", methods=["POST"])
@_admin_login_required
def admin_run_now():
    cron.start_background_batch()
    return redirect(url_for(".admin_dashboard"))


@aduana_bp.route(f"{settings.ADMIN_PREFIX}/telegram/set-webhook", methods=["POST"])
@_admin_login_required
def admin_set_webhook():
    if not settings.PUBLIC_BASE_URL:
        return redirect(url_for(".admin_dashboard", webhook="missing_base_url"))
    try:
        telegram.set_webhook(settings.PUBLIC_BASE_URL + "/api/aduana/telegram/webhook")
        return redirect(url_for(".admin_dashboard", webhook="ok"))
    except Exception:
        return redirect(url_for(".admin_dashboard", webhook="failed"))
