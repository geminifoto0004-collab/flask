# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import io
import json

import requests

from . import settings

TIMEOUT = 20


def escape_html(value):
    return html.escape(str(value if value is not None else ""))


def _api_url(method):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("ADUANA_TELEGRAM_BOT_TOKEN no está configurado")
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def _post(method, *, data=None, files=None):
    response = requests.post(_api_url(method), data=data, files=files, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or f"Telegram {method} failed")
    return payload


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    data = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_markup:
        data["reply_markup"] = reply_markup
    return _post("sendMessage", data=data)


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    data = {"chat_id": str(chat_id), "message_id": str(message_id), "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_markup:
        data["reply_markup"] = reply_markup
    return _post("editMessageText", data=data)


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
    }, ensure_ascii=False)


def inline_keyboard(rows):
    return json.dumps({
        "inline_keyboard": [
            [{"text": text, "callback_data": callback} for text, callback in row]
            for row in rows
        ]
    }, ensure_ascii=False)


MAIN_MENU = reply_keyboard([
    ["🔍 Consultar"],
    ["➕ Agregar RUT", "📋 Mis monitoreos"],
])
