# -*- coding: utf-8 -*-
"""Expose an always-available native Telegram menu in private chats.

Inline buttons belong to individual messages, so they can be pushed upward by
results or Excel documents. Telegram's native bot menu sits beside the input
field and remains reachable regardless of chat history.

The menu is configured proactively when the Aduana blueprint is imported. If
Telegram/DB is temporarily unavailable during startup, later user updates retry
configuration automatically.
"""
from __future__ import annotations

import threading

from . import bot, telegram

_BASE_HANDLE_UPDATE = bot.handle_update
_MENU_CONFIG_RUNNING = False
_MENU_CONFIGURED = False
_MENU_CONFIG_LOCK = threading.Lock()

_COMMAND_MAP = {
    "/menu": "/start",
    "/query": "🔍 Consulta manual",
    "/monitors": "📋 Mis monitoreos",
    "/add": "➕ Agregar RUT",
    "/clear": "🧹 Limpiar pantalla",
}


def _configure_menu_async():
    """Configure the global Telegram command/menu button without blocking Flask.

    We intentionally do not permanently mark a failed startup attempt as done;
    the next incoming Telegram update can retry.
    """
    global _MENU_CONFIG_RUNNING
    with _MENU_CONFIG_LOCK:
        if _MENU_CONFIGURED or _MENU_CONFIG_RUNNING:
            return
        _MENU_CONFIG_RUNNING = True

    def _worker():
        global _MENU_CONFIG_RUNNING, _MENU_CONFIGURED
        ok = False
        try:
            telegram.configure_native_menu()
            ok = True
        except Exception as exc:
            try:
                bot.log.debug("Telegram native menu setup failed: %s", exc)
            except Exception:
                pass
        finally:
            with _MENU_CONFIG_LOCK:
                _MENU_CONFIGURED = ok
                _MENU_CONFIG_RUNNING = False

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
    # Retry if startup configuration failed for any transient reason.
    _configure_menu_async()

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

    # Configure immediately on Render startup, not only after the first user
    # message. This is important when a user has cleared the chat and therefore
    # there is no existing reply keyboard or bot message to interact with.
    _configure_menu_async()


install()
