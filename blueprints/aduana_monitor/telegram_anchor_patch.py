# -*- coding: utf-8 -*-
"""Keep Telegram controls anchored at the bottom of the conversation.

Telegram edits keep a message at its original chronological position.  That is
fine while a workflow stays inside one message, but once an Excel/document or
other message is sent, the old control panel ends up above newer content and is
hard to find.  This patch deliberately re-anchors top-level menu screens and
reposts the result controls after Excel so the active controls are always the
latest bot message.
"""
from __future__ import annotations

from . import bot, storage, telegram_result_patch

_BASE_HANDLE_UPDATE = bot.handle_update
_BASE_HANDLE_CALLBACK = bot._handle_callback

_MENU_TEXTS = {
    "📋 Mis monitoreos",
    "Mis monitoreos",
    "➕ Agregar RUT",
    "Agregar RUT",
    "🔍 Consulta manual",
    "🔍 Consultar",
    "Consultar",
    "Consulta manual",
}


def _tracked_panel_ids(user):
    data = storage.pending_data(user) if user else {}
    values = []
    raw = data.get("_ui_message_ids")
    if isinstance(raw, list):
        values.extend(raw)
    values.append(data.get("_ui_message_id"))

    result = []
    for value in values:
        try:
            mid = int(value or 0)
        except Exception:
            continue
        if mid and mid not in result:
            result.append(mid)
    return result


def _drop_old_panel(user, *, keep_state=False):
    """Delete the old panel so the next screen is sent at the chat bottom."""
    if not user:
        return
    for mid in _tracked_panel_ids(user):
        try:
            bot._safe_delete(user["chat_id"], mid)
        except Exception:
            pass

    if keep_state:
        current = storage.get_user(user["id"]) or user
        action = current.get("pending_action") or "IDLE"
        data = dict(storage.pending_data(current) or {})
        data.pop("_ui_message_id", None)
        data.pop("_ui_message_ids", None)
        storage.set_pending(user["id"], action, data)
    else:
        storage.set_pending(user["id"], "IDLE", {})


def _handle_update(update):
    """Top-level bottom-keyboard actions always open a fresh panel at bottom."""
    message = (update or {}).get("message") or {}
    text = str(message.get("text") or "").strip()
    if text in _MENU_TEXTS:
        from_user = message.get("from") or {}
        chat = message.get("chat") or {}
        if from_user.get("id") and chat.get("id") and chat.get("type") == "private":
            user, _ = storage.get_or_create_telegram_user(
                from_user.get("id"),
                chat.get("id"),
                from_user.get("username") or "",
                from_user.get("first_name") or "",
            )
            _drop_old_panel(user, keep_state=False)
    return _BASE_HANDLE_UPDATE(update)


def _result_buttons(page, pages):
    """Give result pages a complete, obvious control block."""
    rows = []
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(("⬅️ Anterior", f"res_page:{page - 1}"))
        nav.append((f"{page + 1}/{pages}", "res_noop"))
        if page < pages - 1:
            nav.append(("Siguiente ➡️", f"res_page:{page + 1}"))
        rows.append(nav)
    rows.append([("📊 Excel", "res_xlsx"), ("🔄 Otra consulta", "ui_query")])
    rows.append([("📋 Mis monitoreos", "ui_monitors"), ("➕ Agregar RUT", "ui_add")])
    return rows


def _handle_callback(user, data, message_id=None):
    """After sending Excel, move the result/control panel below the document."""
    result = _BASE_HANDLE_CALLBACK(user, data, message_id)
    if data != "res_xlsx":
        return result

    current = storage.get_user(user["id"]) or user
    state = dict(storage.pending_data(current) or {})
    if not isinstance(state.get("_result_rows"), list) or not state.get("_result_rows"):
        return result

    # Excel is a separate Telegram document message. Remove the old result
    # panel and recreate it afterwards so users never have to scroll upward to
    # find controls again.
    _drop_old_panel(current, keep_state=True)
    refreshed = storage.get_user(user["id"]) or user
    return telegram_result_patch._render_result_page(refreshed, 0, message_id=None)


def install():
    if getattr(bot, "_telegram_anchor_patch_installed", False):
        return
    telegram_result_patch._result_buttons = _result_buttons
    bot.handle_update = _handle_update
    bot._handle_callback = _handle_callback
    bot._telegram_anchor_patch_installed = True


install()
