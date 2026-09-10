# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import logging
import re
import threading
from datetime import date

from . import permissions, query, settings, storage, telegram

log = logging.getLogger(__name__)
RUT_RE = re.compile(r"^\d{7,8}-[0-9Kk]$")


def _normalize_rut(value):
    return re.sub(r"[^0-9Kk-]", "", str(value or "").strip()).upper()


def _valid_rut(value):
    return bool(RUT_RE.match(value or ""))


def _main_menu(chat_id, text="Elige una opción:"):
    telegram.send_message(chat_id, text, reply_markup=telegram.MAIN_MENU)


def _refresh_user(user_id):
    return storage.get_user(user_id)


def _set_pending(user_id, action=None, data=None):
    storage.set_pending(user_id, action, data)


def _pending(user):
    return storage.pending_data(user)


def _status_message(user):
    status = user.get("status")
    if status == "PENDING":
        return "⏳ Tu solicitud está pendiente de aprobación. Te avisaremos por este mismo chat."
    if status == "REJECTED":
        return "Tu solicitud no está habilitada actualmente."
    if status == "DISABLED":
        return "Tu acceso está desactivado actualmente."
    return "Tu cuenta no está disponible."


def handle_update(update):
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    source = message or callback.get("message") or {}
    chat = source.get("chat") or {}

    if chat.get("type") != "private":
        return

    if callback:
        callback_id = callback.get("id")
        try:
            if callback_id:
                telegram.answer_callback(callback_id)
        except Exception:
            pass
        from_user = callback.get("from") or {}
        data = callback.get("data") or ""
        user, _ = storage.get_or_create_telegram_user(
            from_user.get("id"), chat.get("id"), from_user.get("username") or "",
            from_user.get("first_name") or "",
        )
        return _handle_callback(user, data)

    from_user = message.get("from") or {}
    text = str(message.get("text") or "").strip()
    if not from_user.get("id") or not chat.get("id"):
        return
    user, _ = storage.get_or_create_telegram_user(
        from_user.get("id"), chat.get("id"), from_user.get("username") or "",
        from_user.get("first_name") or "",
    )

    if text.startswith("/start"):
        if user.get("status") == "ACTIVE":
            return _main_menu(user["chat_id"], "⚓ <b>Aduana Monitor</b>\n\nTu acceso está activo.")
        telegram.send_message(user["chat_id"], _status_message(user))
        return

    if user.get("status") != "ACTIVE":
        telegram.send_message(user["chat_id"], _status_message(user))
        return

    if text in ("🔍 Consultar", "Consultar"):
        return _start_query(user)
    if text in ("➕ Agregar RUT", "Agregar RUT"):
        return _start_add(user)
    if text in ("📋 Mis monitoreos", "Mis monitoreos"):
        return _show_monitors(user)

    action = user.get("pending_action")
    if action == "QUERY_RUT_OWNER":
        return _query_owner_rut(user, text)
    if action == "ADD_RUT":
        return _add_rut_text(user, text)

    _main_menu(user["chat_id"], "No entendí eso. Usa el menú de abajo.")


def _start_query(user):
    try:
        permissions.assert_can_query(user)
    except permissions.PermissionDenied as exc:
        return telegram.send_message(user["chat_id"], str(exc))
    _set_pending(user["id"])
    if user.get("role") == "OWNER":
        _set_pending(user["id"], "QUERY_RUT_OWNER", {})
        return telegram.send_message(user["chat_id"], "Ingresa el RUT que quieres consultar:")
    ruts = storage.distinct_ruts(user["id"])
    if not ruts:
        return _main_menu(user["chat_id"], "Aún no tienes RUT agregados. Usa “Agregar RUT” primero.")
    rows = [[(rut, f"q_rut:{rut}")] for rut in ruts]
    telegram.send_message(user["chat_id"], "Selecciona uno de tus RUT:", reply_markup=telegram.inline_keyboard(rows))


def _query_owner_rut(user, text):
    rut = _normalize_rut(text)
    if not _valid_rut(rut):
        return telegram.send_message(user["chat_id"], "RUT inválido. Ejemplo: 76315010-0")
    _ask_query_aduana(user, rut)


def _ask_query_aduana(user, rut):
    _set_pending(user["id"], "QUERY_ADUANA", {"rut": rut})
    rows = [[(name, f"q_ad:{code}")] for code, name in settings.ADUANAS]
    if user.get("role") == "OWNER":
        rows.append([("TODAS", "q_ad:ALL")])
    telegram.send_message(user["chat_id"], "Selecciona la Aduana:", reply_markup=telegram.inline_keyboard(rows))


def _query_aduana_selected(user, code):
    if code == "ALL" and user.get("role") != "OWNER":
        return telegram.send_message(user["chat_id"], "Opción no disponible.")
    if code != "ALL" and code not in settings.ADUANA_CODES:
        return telegram.send_message(user["chat_id"], "Aduana inválida.")
    data = _pending(user)
    rut = data.get("rut")
    if not rut:
        return _main_menu(user["chat_id"], "La sesión de consulta venció. Intenta de nuevo.")
    data["aduana"] = code
    if user.get("role") == "OWNER":
        _set_pending(user["id"], "QUERY_YEARS", data)
        years = permissions.available_years_for(user)
        rows = []
        for i in range(0, len(years), 3):
            rows.append([(str(y), f"q_year:{y}") for y in years[i:i+3]])
        rows.append([("✅ Buscar", "q_year_go")])
        return telegram.send_message(user["chat_id"], "Selecciona uno o más años y luego Buscar:", reply_markup=telegram.inline_keyboard(rows))

    options = permissions.range_options_for(user)
    data["ranges"] = {key: [start.isoformat(), end.isoformat()] for key, _label, start, end in options}
    _set_pending(user["id"], "QUERY_RANGE", data)
    rows = [[(label, f"q_range:{key}")] for key, label, _start, _end in options]
    telegram.send_message(user["chat_id"], "Selecciona el período:", reply_markup=telegram.inline_keyboard(rows))


def _query_year_toggle(user, year):
    if user.get("role") != "OWNER":
        return
    data = _pending(user)
    chosen = {int(v) for v in data.get("years", [])}
    if year in chosen:
        chosen.remove(year)
    else:
        chosen.add(year)
    data["years"] = sorted(chosen, reverse=True)
    _set_pending(user["id"], "QUERY_YEARS", data)
    telegram.send_message(user["chat_id"], "Años seleccionados: " + (", ".join(map(str, data["years"])) or "ninguno"))


def _query_year_go(user):
    if user.get("role") != "OWNER":
        return
    data = _pending(user)
    years = data.get("years") or []
    if not years:
        return telegram.send_message(user["chat_id"], "Selecciona al menos un año.")
    _set_pending(user["id"])
    telegram.send_message(user["chat_id"], "Consultando…")
    _run_manual_async(user["chat_id"], "years", rut=data["rut"], aduana=data["aduana"], years=years)


def _query_range_go(user, key):
    data = _pending(user)
    option = (data.get("ranges") or {}).get(key)
    if not option:
        return _main_menu(user["chat_id"], "La sesión de consulta venció. Intenta de nuevo.")
    start, end = date.fromisoformat(option[0]), date.fromisoformat(option[1])
    _set_pending(user["id"])
    telegram.send_message(user["chat_id"], f"Consultando {start.strftime('%d-%m-%Y')} → {end.strftime('%d-%m-%Y')}…")
    _run_manual_async(user["chat_id"], "range", rut=data["rut"], aduana=data["aduana"], start=start, end=end)


def _run_manual_async(chat_id, kind, **kwargs):
    threading.Thread(target=_manual_worker, args=(chat_id, kind), kwargs=kwargs, daemon=True).start()


def _manual_worker(chat_id, kind, **kwargs):
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
        _send_results(chat_id, rows, rut, aduana, all_ok)
    except Exception:
        log.exception("Aduana manual query failed")
        _main_menu(chat_id, "No se pudo completar la consulta. Intenta nuevamente más tarde.")


def _send_results(chat_id, rows, rut, aduana, all_ok):
    warning = "⚠️ La consulta quedó incompleta por un error del sitio Aduana.\n\n" if not all_ok else ""
    if not rows:
        return _main_menu(chat_id, warning + "Sin resultados para ese período.")
    if len(rows) <= 12:
        lines = [warning + f"<b>{len(rows)} resultado(s)</b>\n"]
        for row in rows:
            lines.append(
                f"• <b>N° {telegram.escape_html(row.get('n_denuncia'))}</b> | "
                f"{telegram.escape_html(row.get('emision'))} | "
                f"{telegram.escape_html(row.get('infractor'))}\n"
                f"  Doc: {telegram.escape_html(row.get('doc_aduanero'))} | "
                f"Multa: {telegram.escape_html(row.get('multa_max_legal'))}"
            )
        return _main_menu(chat_id, "\n".join(lines))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=settings.COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    label = settings.ADUANA_LABELS.get(aduana, aduana)
    telegram.send_document(chat_id, f"ADUANA_{label}_{rut}.csv", buf.getvalue().encode("utf-8-sig"), f"{len(rows)} resultado(s)")
    _main_menu(chat_id, warning + "Consulta terminada.")


def _start_add(user):
    try:
        permissions.assert_can_monitor(user)
    except permissions.PermissionDenied as exc:
        return telegram.send_message(user["chat_id"], str(exc))
    _set_pending(user["id"], "ADD_RUT", {})
    telegram.send_message(user["chat_id"], "Ingresa el RUT que quieres monitorear:")


def _add_rut_text(user, text):
    rut = _normalize_rut(text)
    if not _valid_rut(rut):
        return telegram.send_message(user["chat_id"], "RUT inválido. Ejemplo: 76315010-0")
    try:
        permissions.assert_can_add_rut(user, storage.distinct_ruts(user["id"]), rut)
    except permissions.PermissionDenied as exc:
        return _main_menu(user["chat_id"], str(exc))
    _set_pending(user["id"], "ADD_ADUANA", {"rut": rut})
    rows = [[(name, f"a_ad:{code}")] for code, name in settings.ADUANAS]
    if user.get("role") == "OWNER":
        rows.append([("TODAS", "a_ad:ALL")])
    telegram.send_message(user["chat_id"], "Selecciona la Aduana a monitorear:", reply_markup=telegram.inline_keyboard(rows))


def _add_aduana(user, code):
    if code == "ALL" and user.get("role") != "OWNER":
        return telegram.send_message(user["chat_id"], "Opción no disponible.")
    if code != "ALL" and code not in settings.ADUANA_CODES:
        return telegram.send_message(user["chat_id"], "Aduana inválida.")
    data = _pending(user)
    rut = data.get("rut")
    if not rut:
        return _main_menu(user["chat_id"], "La sesión venció. Intenta de nuevo.")
    storage.add_or_enable_monitor(user["id"], rut, code)
    _set_pending(user["id"])
    label = "TODAS" if code == "ALL" else settings.ADUANA_LABELS.get(code, code)
    _main_menu(user["chat_id"], f"✅ Monitoreo activado\n\nRUT: <b>{telegram.escape_html(rut)}</b>\nAduana: <b>{telegram.escape_html(label)}</b>\n\nLa primera revisión completa crea la línea base y no envía avisos antiguos.")


def _show_monitors(user):
    monitors = storage.list_user_monitors(user["id"])
    if not monitors:
        return _main_menu(user["chat_id"], "No tienes monitoreos configurados.")
    lines = ["<b>📋 Mis monitoreos</b>\n"]
    buttons = []
    for monitor in monitors:
        label = "TODAS" if monitor["aduana"] == "ALL" else settings.ADUANA_LABELS.get(monitor["aduana"], monitor["aduana"])
        icon = "🟢" if bool(monitor.get("enabled")) else "⚪"
        lines.append(f"{icon} {telegram.escape_html(monitor['rut'])} · {telegram.escape_html(label)}")
        toggle = "⏸ Pausar" if bool(monitor.get("enabled")) else "▶️ Activar"
        buttons.append([(toggle, f"m_toggle:{monitor['id']}"), ("🗑 Eliminar", f"m_delete:{monitor['id']}")])
    telegram.send_message(user["chat_id"], "\n".join(lines), reply_markup=telegram.inline_keyboard(buttons))


def _toggle_monitor(user, monitor_id):
    monitor = storage.get_monitor_for_user(monitor_id, user["id"])
    if not monitor:
        return telegram.send_message(user["chat_id"], "Monitoreo no encontrado.")
    storage.set_monitor_enabled(monitor_id, user["id"], not bool(monitor.get("enabled")))
    _show_monitors(user)


def _delete_monitor(user, monitor_id):
    storage.delete_monitor(monitor_id, user["id"])
    _show_monitors(user)


def _handle_callback(user, data):
    if user.get("status") != "ACTIVE":
        return telegram.send_message(user["chat_id"], _status_message(user))
    if data.startswith("q_rut:"):
        rut = _normalize_rut(data.split(":", 1)[1])
        if user.get("role") != "OWNER" and rut not in storage.distinct_ruts(user["id"]):
            return telegram.send_message(user["chat_id"], "Ese RUT no está disponible para tu cuenta.")
        return _ask_query_aduana(user, rut)
    if data.startswith("q_ad:"):
        return _query_aduana_selected(_refresh_user(user["id"]), data.split(":", 1)[1])
    if data.startswith("q_year:"):
        try:
            year = int(data.split(":", 1)[1])
        except Exception:
            return
        return _query_year_toggle(_refresh_user(user["id"]), year)
    if data == "q_year_go":
        return _query_year_go(_refresh_user(user["id"]))
    if data.startswith("q_range:"):
        return _query_range_go(_refresh_user(user["id"]), data.split(":", 1)[1])
    if data.startswith("a_ad:"):
        return _add_aduana(_refresh_user(user["id"]), data.split(":", 1)[1])
    if data.startswith("m_toggle:"):
        return _toggle_monitor(user, int(data.split(":", 1)[1]))
    if data.startswith("m_delete:"):
        return _delete_monitor(user, int(data.split(":", 1)[1]))
