# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import io
import json

import requests

from . import settings

TIMEOUT = 20
PLUGIN_KEY = "ADUANA"


def escape_html(value):
    return html.escape(str(value if value is not None else ""))


def _hub_bot():
    """Return the appropriate Automation Hub bot for Aduana, if configured.

    Incoming Telegram updates reply through the same bot that received them.
    Background notifications use the plugin's default active bot. Any Hub
    lookup failure falls back to the existing ADUANA_* environment flow.
    """
    try:
        from blueprints.automation_hub import registry as hub_registry
        from blueprints.automation_hub import storage as hub_storage

        current_key = hub_registry.current_bot_key()
        if current_key:
            current = hub_storage.get_bot_by_key(current_key, with_token=True)
            if (
                current
                and bool(current.get("enabled"))
                and str(current.get("plugin_key") or "").upper() == PLUGIN_KEY
            ):
                return current
        return hub_storage.get_active_bot_for_plugin(PLUGIN_KEY, with_token=True)
    except Exception:
        return None


def _resolved_token():
    bot = _hub_bot()
    if bot and bot.get("token"):
        return str(bot["token"]).strip()
    return settings.TELEGRAM_BOT_TOKEN


def is_configured():
    return bool(_resolved_token())


def _api_url(method, token=None):
    token = str(token or _resolved_token() or "").strip()
    if not token:
        raise RuntimeError("Telegram Bot Token no está configurado")
    return f"https://api.telegram.org/bot{token}/{method}"


def _post(method, *, data=None, files=None, token=None):
    response = requests.post(_api_url(method, token=token), data=data, files=files, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or f"Telegram {method} failed")
    return payload


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    data = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_markup is not None:
        data["reply_markup"] = reply_markup
    return _post("sendMessage", data=data)


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    data = {"chat_id": str(chat_id), "message_id": str(message_id), "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    # Explicitly send an empty inline keyboard when callers want old buttons
    # removed from the same message.
    if reply_markup is not None:
        data["reply_markup"] = reply_markup
    return _post("editMessageText", data=data)


def delete_message(chat_id, message_id):
    if not message_id:
        return None
    return _post("deleteMessage", data={"chat_id": str(chat_id), "message_id": str(message_id)})


def send_document(chat_id, filename, content_bytes, caption=None):
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption
    files = {"document": (filename, io.BytesIO(content_bytes), "text/csv")}
    return _post("sendDocument", data=data, files=files)


def answer_callback(callback_id, text=None):
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text[:180]
    return _post("answerCallbackQuery", data=data)


def set_webhook(url):
    """Connect the appropriate webhook.

    If an Automation Hub bot exists, connect that bot to the generic Hub
    endpoint. Otherwise preserve the original Aduana-specific environment flow.
    """
    bot = _hub_bot()
    if bot and bot.get("token"):
        from blueprints.automation_hub import settings as hub_settings
        from blueprints.automation_hub import telegram as hub_telegram
        if not hub_settings.PUBLIC_BASE_URL:
            raise RuntimeError("AUTOMATION_PUBLIC_BASE_URL no está configurado")
        target = (
            hub_settings.PUBLIC_BASE_URL
            + "/api/automation/telegram/"
            + bot["bot_key"]
            + "/webhook"
        )
        return hub_telegram.set_webhook(bot["token"], target, bot.get("webhook_secret") or "")

    data = {"url": url}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        data["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET
    return _post("setWebhook", data=data)


def get_webhook_info():
    return _post("getWebhookInfo", data={})


def reply_keyboard(rows):
    return json.dumps({
        "keyboard": [[{"text": text} for text in row] for row in rows],
        "resize_keyboard": True,
        "is_persistent": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "Elige una opción",
    }, ensure_ascii=False)


def inline_keyboard(rows):
    return json.dumps({
        "inline_keyboard": [
            [{"text": text, "callback_data": callback} for text, callback in row]
            for row in rows
        ]
    }, ensure_ascii=False)


MAIN_MENU = reply_keyboard([
    ["📋 Mis monitoreos"],
    ["➕ Agregar RUT", "🔍 Consulta manual"],
    ["🧹 Limpiar pantalla"],
])
