# -*- coding: utf-8 -*-
from __future__ import annotations

import hmac
import re
from functools import wraps

from flask import current_app, jsonify, redirect, render_template, request, session, url_for

from . import automation_hub_bp, registry, settings, storage, telegram

BOT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


@automation_hub_bp.before_request
def _schema_guard():
    storage.ensure_schema()


@automation_hub_bp.route("/api/automation/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "master_key_configured": bool(settings.MASTER_KEY),
        "public_base_url_configured": bool(settings.PUBLIC_BASE_URL),
        "plugins": [p["key"] for p in registry.list_plugins()],
        "bots": len(storage.list_bots()),
    })


@automation_hub_bp.route("/api/automation/telegram/<bot_key>/webhook", methods=["POST"])
def telegram_webhook(bot_key):
    bot = storage.get_bot_by_key(bot_key, with_token=False)
    if not bot or not bool(bot.get("enabled")):
        return jsonify({"ok": False}), 404
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(str(supplied), str(bot.get("webhook_secret") or "")):
        return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    try:
        registry.dispatch(bot["plugin_key"], update, bot_key=bot["bot_key"])
    except Exception as exc:
        current_app.logger.exception(
            "Automation Hub Telegram dispatch failed bot=%s plugin=%s: %s",
            bot_key, bot.get("plugin_key"), exc,
        )
    return jsonify({"ok": True})


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("automation_hub_admin_ok"):
            return redirect(url_for(".admin_login"))
        return view(*args, **kwargs)
    return wrapped


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        supplied = request.form.get("password") or ""
        if settings.ADMIN_PASSWORD and hmac.compare_digest(supplied, settings.ADMIN_PASSWORD):
            session["automation_hub_admin_ok"] = True
            return redirect(url_for(".admin_dashboard"))
        error = "Contraseña incorrecta"
    return render_template("automation_hub/login.html", error=error, settings=settings)


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/logout", methods=["POST", "GET"])
def admin_logout():
    session.pop("automation_hub_admin_ok", None)
    return redirect(url_for(".admin_login"))


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/", methods=["GET"])
@_admin_required
def admin_dashboard():
    return render_template(
        "automation_hub/dashboard.html",
        bots=storage.list_bots(),
        plugins=registry.list_plugins(),
        settings=settings,
        message=request.args.get("message") or "",
    )


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/bots", methods=["POST"])
@_admin_required
def admin_create_bot():
    bot_key = (request.form.get("bot_key") or "").strip().lower()
    display_name = (request.form.get("display_name") or "").strip()
    plugin_key = (request.form.get("plugin_key") or "").strip().upper()
    token = (request.form.get("token") or "").strip()
    if not BOT_KEY_RE.match(bot_key):
        return redirect(url_for(".admin_dashboard", message="Bot key inválido"))
    if not registry.has_plugin(plugin_key):
        return redirect(url_for(".admin_dashboard", message="Plugin no registrado"))
    try:
        info = telegram.test_bot(token)
        bot = storage.save_bot(
            bot_key=bot_key,
            display_name=display_name,
            plugin_key=plugin_key,
            token=token,
            bot_username=info.get("username") or "",
            make_default="make_default" in request.form,
        )
        if settings.PUBLIC_BASE_URL:
            webhook_url = (
                settings.PUBLIC_BASE_URL
                + "/api/automation/telegram/"
                + bot["bot_key"]
                + "/webhook"
            )
            telegram.set_webhook(bot["token"], webhook_url, bot["webhook_secret"])
            storage.mark_test(bot["id"], None)
            msg = f"@{info.get('username') or bot_key} conectado"
        else:
            storage.mark_test(bot["id"], "PUBLIC_BASE_URL no configurado")
            msg = "Bot guardado; falta PUBLIC_BASE_URL para webhook"
    except Exception as exc:
        msg = f"Error: {str(exc)[:180]}"
    return redirect(url_for(".admin_dashboard", message=msg))


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/bots/<int:bot_id>/test", methods=["POST"])
@_admin_required
def admin_test_bot(bot_id):
    bot = storage.get_bot_by_id(bot_id, with_token=True)
    if not bot:
        return redirect(url_for(".admin_dashboard", message="Bot no encontrado"))
    try:
        info = telegram.test_bot(bot["token"])
        storage.mark_test(bot_id, None)
        msg = f"OK @{info.get('username') or bot['bot_key']}"
    except Exception as exc:
        storage.mark_test(bot_id, str(exc)[:500])
        msg = f"Error: {str(exc)[:180]}"
    return redirect(url_for(".admin_dashboard", message=msg))


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/bots/<int:bot_id>/webhook", methods=["POST"])
@_admin_required
def admin_reconnect_webhook(bot_id):
    bot = storage.get_bot_by_id(bot_id, with_token=True)
    if not bot:
        return redirect(url_for(".admin_dashboard", message="Bot no encontrado"))
    if not settings.PUBLIC_BASE_URL:
        return redirect(url_for(".admin_dashboard", message="PUBLIC_BASE_URL no configurado"))
    try:
        url = settings.PUBLIC_BASE_URL + "/api/automation/telegram/" + bot["bot_key"] + "/webhook"
        telegram.set_webhook(bot["token"], url, bot["webhook_secret"])
        storage.mark_test(bot_id, None)
        msg = "Webhook conectado"
    except Exception as exc:
        storage.mark_test(bot_id, str(exc)[:500])
        msg = f"Error webhook: {str(exc)[:180]}"
    return redirect(url_for(".admin_dashboard", message=msg))


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/bots/<int:bot_id>/toggle", methods=["POST"])
@_admin_required
def admin_toggle_bot(bot_id):
    bot = storage.get_bot_by_id(bot_id)
    if bot:
        storage.set_enabled(bot_id, not bool(bot.get("enabled")))
    return redirect(url_for(".admin_dashboard"))


@automation_hub_bp.route(f"{settings.ADMIN_PREFIX}/bots/<int:bot_id>/default", methods=["POST"])
@_admin_required
def admin_set_default(bot_id):
    storage.set_default(bot_id)
    return redirect(url_for(".admin_dashboard"))
