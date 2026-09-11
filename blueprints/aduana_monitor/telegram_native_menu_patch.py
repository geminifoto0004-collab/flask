# -*- coding: utf-8 -*-
"""Expose an always-available native Telegram menu in private chats.

Inline buttons belong to individual messages, so they can be pushed upward by
results or Excel documents.  Telegram's native bot menu sits beside the input
field and remains reachable regardless of chat history.  This patch configures
that menu lazily and maps its slash commands onto the existing Aduana flows.
"""
from __future__ import annotations

import threading

from . import bot, telegram

_BASE_HANDLE_UPDATE = bot.handle_update
_MENU_CONFIG_STARTED = False
_MENU_CONFIG_LOCK = threading.Lock()

_COMMAND_MAP = {
    "/menu": "/start",
    "/query": "🔍 Consulta manual",
    "/monitors": "📋 Mis monitoreos",
    "/add": "➕ Agregar RUT",
    "/clear": "🧹 Limpiar pantalla",
}


def _configure_menu_once():
    global _MENU_CONFIG_STARTED
    with _MENU_CONFIG_LOCK:
        if _MENU_CONFIG_STARTED:
            return
        _MENU_CONFIG_STARTED = True

    def _worker():
        try:
            telegram.configure_native_menu()
        except Exception as exc:
            try:
                bot.log.debug("Telegram native menu setup failed: %s", exc)
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True, name="aduana-telegram-menu").start()


def _normalize_command(text):
    value = str(text or "").strip()
    if not value.startswith("/"):
        return value

    first = value.split(None, 1)[0]
    # Telegram may send /query@ChileAduanaBot in some clients/chats.
    command = first.split("@", 1)[0].lower()
    return _COMMAND_MAP.get(command, value)


def _handle_update(update):
    _configure_menu_once()

    message = (update or {}).get("message") or {}
    text = str(message.get("text") or "")
    normalized = _normalize_command(text)
    if normalized == text:
        return _BASE_HANDLE_UPDATE(update)

    # Preserve the update payload but feed the existing bot the equivalent
    # button action so permissions/state handling stays in one place.
    patched = dict(update or {})
    patched_message = dict(message)
    patched_message["text"] = normalized
    patched["message"] = patched_message
    return _BASE_HANDLE_UPDATE(patched)


def install():
    if getattr(bot, "_telegram_native_menu_patch_installed", False):
        return
    bot.handle_update = _handle_update
    bot._telegram_native_menu_patch_installed = True


install()
