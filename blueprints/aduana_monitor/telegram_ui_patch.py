# -*- coding: utf-8 -*-
"""Stabilise the Telegram UI into one reusable screen.

The existing bot workflow is intentionally kept intact.  This module only
patches the presentation/state helpers so old panels do not accumulate and a
finished background query cannot resurrect a screen after the user has moved
on or cleared the chat.
"""
from __future__ import annotations

import threading
import time
import uuid

from . import bot, permissions, query, settings, storage, telegram

_MAX_TRACKED_PANELS = 8


def _ui_ids_from_data(data):
    data = data or {}
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
    return result[-_MAX_TRACKED_PANELS:]


def _panel_ids(user):
    return _ui_ids_from_data(storage.pending_data(user) if user else {})


def _panel_id(user):
    data = storage.pending_data(user) if user else {}
    try:
        primary = int(data.get("_ui_message_id") or 0)
    except Exception:
        primary = 0
    if primary:
        return primary
    ids = _ui_ids_from_data(data)
    return ids[-1] if ids else 0


def _set_state(user_id, action="IDLE", data=None, panel_id=None):
    """Persist workflow state while keeping every known UI panel id."""
    current = storage.get_user(user_id)
    old = storage.pending_data(current) if current else {}
    payload = dict(data or {})

    ids = _ui_ids_from_data(old)
    ids.extend(_ui_ids_from_data(payload))
    deduped = []
    for mid in ids:
        if mid not in deduped:
            deduped.append(mid)

    if panel_id is not None:
        try:
            pid = int(panel_id or 0)
        except Exception:
            pid = 0
        if pid:
            if pid in deduped:
                deduped.remove(pid)
            deduped.append(pid)
            payload["_ui_message_id"] = pid
    else:
        try:
            old_primary = int(old.get("_ui_message_id") or 0)
        except Exception:
            old_primary = 0
        if old_primary:
            payload["_ui_message_id"] = old_primary
        elif deduped:
            payload["_ui_message_id"] = deduped[-1]

    deduped = deduped[-_MAX_TRACKED_PANELS:]
    if deduped:
        payload["_ui_message_ids"] = deduped
    storage.set_pending(user_id, action or "IDLE", payload)


def _remember_panel(user_id, message_id):
    try:
        mid = int(message_id or 0)
    except Exception:
        mid = 0
    if not mid:
        return
    current = storage.get_user(user_id)
    action = (current or {}).get("pending_action") or "IDLE"
    data = storage.pending_data(current) if current else {}
    ids = _ui_ids_from_data(data)
    if mid in ids:
        ids.remove(mid)
    ids.append(mid)
    data["_ui_message_id"] = mid
    data["_ui_message_ids"] = ids[-_MAX_TRACKED_PANELS:]
    storage.set_pending(user_id, action, data)


def _forget_panel(user_id):
    # Clearing also cancels any pending background manual-query UI delivery.
    storage.set_pending(user_id, "IDLE", {})


def _safe_delete(chat_id, message_id):
    try:
        mid = int(message_id or 0)
    except Exception:
        mid = 0
    if not mid:
        return False
    last_exc = None
    for attempt in range(2):
        try:
            telegram.delete_message(chat_id, mid)
            return True
        except Exception as exc:  # Telegram may fail transiently.
            last_exc = exc
            if attempt == 0:
                time.sleep(0.12)
    if last_exc:
        bot.log.debug("Telegram deleteMessage failed for %s: %s", mid, last_exc)
    return False


def _clean_rows(rows):
    """Keep one cleaner only: the persistent bottom 'Limpiar pantalla' button."""
    cleaned = []
    for row in rows or []:
        kept = []
        for item in row or []:
            try:
                text, callback = item
            except Exception:
                continue
            if callback == "ui_clear":
                continue
            kept.append((text, callback))
        if kept:
            cleaned.append(kept)
    return cleaned


def _rewrite_tracked_panels(user_id, keep_id=None):
    current = storage.get_user(user_id)
    if not current:
        return
    action = current.get("pending_action") or "IDLE"
    data = storage.pending_data(current)
    data.pop("_ui_message_id", None)
    data.pop("_ui_message_ids", None)
    if keep_id:
        keep_id = int(keep_id)
        data["_ui_message_id"] = keep_id
        data["_ui_message_ids"] = [keep_id]
    storage.set_pending(user_id, action, data)


def _delete_other_panels(user, keep_id=None):
    current = storage.get_user(user["id"]) or user
    ids = _panel_ids(current)
    keep = int(keep_id or 0)
    for mid in ids:
        if mid != keep:
            _safe_delete(user["chat_id"], mid)
    _rewrite_tracked_panels(user["id"], keep or None)


def _show_panel(user, text, rows=None, message_id=None):
    """Always converge to exactly one bot UI message."""
    current = storage.get_user(user["id"]) or user
    try:
        explicit = int(message_id or 0)
    except Exception:
        explicit = 0
    target = explicit or _panel_id(current)
    markup = telegram.inline_keyboard(_clean_rows(rows))

    if target:
        try:
            result = telegram.edit_message(user["chat_id"], target, text, reply_markup=markup)
            _remember_panel(user["id"], target)
            _delete_other_panels(user, keep_id=target)
            return result
        except Exception as exc:
            if "not modified" in str(exc).lower():
                _remember_panel(user["id"], target)
                _delete_other_panels(user, keep_id=target)
                return None
            _safe_delete(user["chat_id"], target)

    result = telegram.send_message(user["chat_id"], text, reply_markup=markup)
    new_id = bot._result_message_id(result)
    if new_id:
        _remember_panel(user["id"], new_id)
        _delete_other_panels(user, keep_id=new_id)
    return result


def _send_home(user, force_new=False, note=None):
    monitors = storage.list_user_monitors(user["id"])
    active = [m for m in monitors if bool(m.get("enabled"))]
    lines = ["⚓ <b>ADUANA MONITOR</b>", ""]
    if note:
        lines.extend([telegram.escape_html(note), ""])
    if active:
        lines.append(f"🟢 Monitoreo automático activo: <b>{len(active)}</b>")
        for monitor in active[:6]:
            label = (
                "TODAS"
                if monitor.get("aduana") == "ALL"
                else settings.ADUANA_LABELS.get(monitor.get("aduana"), monitor.get("aduana"))
            )
            lines.append(
                f"• {telegram.escape_html(monitor.get('rut'))} · {telegram.escape_html(label)}"
            )
        if len(active) > 6:
            lines.append(f"… y {len(active) - 6} más")
        lines.extend([
            "",
            f"Cada revisión automática busca los últimos <b>{settings.CRON_LOOKBACK_DAYS} días</b>.",
        ])
    else:
        lines.extend([
            "Todavía no tienes monitoreos activos.",
            "",
            "Pulsa <b>➕ Agregar RUT</b> una sola vez para dejarlo configurado.",
        ])

    if force_new:
        current = storage.get_user(user["id"]) or user
        for mid in _panel_ids(current):
            _safe_delete(user["chat_id"], mid)
        storage.set_pending(user["id"], "IDLE", {})
        result = telegram.send_message(
            user["chat_id"],
            "\n".join(lines),
            reply_markup=telegram.MAIN_MENU,
        )
        mid = bot._result_message_id(result)
        if mid:
            _remember_panel(user["id"], mid)
        return result

    _set_state(user["id"], "IDLE", {})
    # No inline Limpiar button; the persistent bottom menu already has it.
    return _show_panel(storage.get_user(user["id"]) or user, "\n".join(lines), rows=[])


def _clear_screen(user, incoming_message_id=None, panel_message_id=None):
    ids = set(_panel_ids(storage.get_user(user["id"]) or user))
    for candidate in (incoming_message_id, panel_message_id):
        try:
            mid = int(candidate or 0)
        except Exception:
            mid = 0
        if mid:
            ids.add(mid)
    for mid in sorted(ids):
        _safe_delete(user["chat_id"], mid)
    _forget_panel(user["id"])


def _query_is_current(user_id, run_id, message_id=0):
    user = storage.get_user(user_id)
    if not user or user.get("pending_action") != "QUERY_RUNNING":
        return False
    data = storage.pending_data(user)
    if str(data.get("_query_run_id") or "") != str(run_id or ""):
        return False
    current_panel = _panel_id(user)
    if message_id and current_panel and int(message_id) != int(current_panel):
        return False
    return True


def _run_query(user, message_id=None):
    """Start one cancellable manual-query run without letting old runs overwrite UI."""
    data = storage.pending_data(user)
    rut = data.get("rut")
    aduana = data.get("aduana") or bot.DEFAULT_ADUANA
    if not rut:
        return _send_home(user, note="La consulta venció. Intenta nuevamente.")

    if data.get("query_kind") == "years":
        years = [int(y) for y in data.get("years", [])]
        if not years:
            return _show_panel(
                user,
                "Selecciona al menos un año.",
                rows=[[('📅 Elegir año', 'q_change_period')]],
                message_id=message_id,
            )
        kind = "years"
        kwargs = {"years": years}
    else:
        selected = data.get("range_key")
        option = None
        for item in permissions.range_options_for(user):
            if item[0] == selected:
                option = item
                break
        if not option:
            return bot._show_query_period(user, message_id=message_id)
        kind = "range"
        kwargs = {"start": option[2], "end": option[3]}

    try:
        panel_id = int(message_id or _panel_id(user) or 0)
    except Exception:
        panel_id = 0
    run_id = uuid.uuid4().hex
    _set_state(
        user["id"],
        "QUERY_RUNNING",
        {"_query_run_id": run_id},
        panel_id=panel_id or None,
    )
    _show_panel(
        storage.get_user(user["id"]) or user,
        "⏳ <b>Consultando Aduana…</b>\n\n"
        "Puedes cerrar Telegram. El resultado aparecerá aquí cuando termine.",
        rows=[],
        message_id=panel_id or None,
    )
    current = storage.get_user(user["id"])
    panel_id = _panel_id(current)

    threading.Thread(
        target=_manual_worker,
        args=(user["id"], user["chat_id"], panel_id, kind, run_id),
        kwargs={"rut": rut, "aduana": aduana, **kwargs},
        daemon=True,
    ).start()


def _manual_worker(user_id, chat_id, message_id, kind, run_id, **kwargs):
    try:
        aduana = kwargs["aduana"]
        rut = kwargs["rut"]
        if aduana == "ALL":
            all_rows, all_ok = [], True
            for code in settings.ADUANA_CODES:
                if kind == "years":
                    rows, _logs, ok = query.query_years(kwargs["years"], code, rut)
                else:
                    rows, _logs, ok = query.query_range(kwargs["start"], kwargs["end"], code, rut)
                all_rows.extend(rows)
                all_ok = all_ok and ok
            rows = query.sort_rows(query._dedupe_full_rows(all_rows))
        elif kind == "years":
            rows, _logs, all_ok = query.query_years(kwargs["years"], aduana, rut)
        else:
            rows, _logs, all_ok = query.query_range(kwargs["start"], kwargs["end"], aduana, rut)

        if not _query_is_current(user_id, run_id, message_id):
            return
        bot._send_results(user_id, chat_id, message_id, rows, rut, aduana, all_ok)
    except Exception:
        bot.log.exception("Aduana manual query failed")
        if not _query_is_current(user_id, run_id, message_id):
            return
        user = storage.get_user(user_id)
        if user:
            _show_panel(
                user,
                "⚠️ No se pudo completar la consulta. Intenta nuevamente más tarde.",
                rows=[],
                message_id=message_id or None,
            )


def install():
    if getattr(bot, "_telegram_ui_patch_installed", False):
        return

    bot._panel_id = _panel_id
    bot._set_state = _set_state
    bot._remember_panel = _remember_panel
    bot._forget_panel = _forget_panel
    bot._safe_delete = _safe_delete
    bot._show_panel = _show_panel
    bot._send_home = _send_home
    bot._clear_screen = _clear_screen
    bot._run_query = _run_query
    bot._telegram_ui_patch_installed = True


install()
