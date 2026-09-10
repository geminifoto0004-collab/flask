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
RUT_RE = re.compile(r"^\d{7,8}-[0-9K]$")
DEFAULT_ADUANA = "7"  # IQUIQUE


def _normalize_rut(value):
    """Accept common Chilean RUT formats and return canonical XXXXXXXX-X."""
    compact = re.sub(r"[^0-9Kk]", "", str(value or "").strip()).upper()
    if len(compact) in (8, 9) and compact[:-1].isdigit() and compact[-1] in "0123456789K":
        return f"{compact[:-1]}-{compact[-1]}"
    return re.sub(r"[^0-9Kk-]", "", str(value or "").strip()).upper()


def _valid_rut(value):
    return bool(RUT_RE.match(value or ""))


def _refresh_user(user_id):
    return storage.get_user(user_id)


def _pending(user):
    return storage.pending_data(user)


def _panel_id(user):
    try:
        return int((_pending(user) or {}).get("_ui_message_id") or 0)
    except Exception:
        return 0


def _set_state(user_id, action="IDLE", data=None, panel_id=None):
    """Persist conversation state while keeping the single mobile UI panel id."""
    current = storage.get_user(user_id)
    old = storage.pending_data(current) if current else {}
    pid = panel_id if panel_id is not None else old.get("_ui_message_id")
    payload = dict(data or {})
    if pid:
        payload["_ui_message_id"] = int(pid)
    storage.set_pending(user_id, action or "IDLE", payload)


def _remember_panel(user_id, message_id):
    if not message_id:
        return
    current = storage.get_user(user_id)
    action = (current or {}).get("pending_action") or "IDLE"
    data = storage.pending_data(current) if current else {}
    data["_ui_message_id"] = int(message_id)
    storage.set_pending(user_id, action, data)


def _forget_panel(user_id):
    storage.set_pending(user_id, "IDLE", {})


def _result_message_id(payload):
    try:
        return int((payload or {}).get("result", {}).get("message_id") or 0)
    except Exception:
        return 0


def _safe_delete(chat_id, message_id):
    if not message_id:
        return
    try:
        telegram.delete_message(chat_id, message_id)
    except Exception:
        pass


def _inline(rows):
    return telegram.inline_keyboard(rows or [])


def _show_panel(user, text, rows=None, message_id=None):
    """Edit one existing bot message whenever possible instead of stacking screens."""
    target = int(message_id or _panel_id(user) or 0)
    markup = _inline(rows)
    if target:
        try:
            result = telegram.edit_message(user["chat_id"], target, text, reply_markup=markup)
            _remember_panel(user["id"], target)
            return result
        except Exception as exc:
            # Telegram returns "message is not modified" for identical panels.
            if "not modified" in str(exc).lower():
                _remember_panel(user["id"], target)
                return None
            _safe_delete(user["chat_id"], target)

    result = telegram.send_message(user["chat_id"], text, reply_markup=markup)
    new_id = _result_message_id(result)
    if new_id:
        _remember_panel(user["id"], new_id)
    return result


def _send_home(user, force_new=False, note=None):
    monitors = storage.list_user_monitors(user["id"])
    active = [m for m in monitors if bool(m.get("enabled"))]
    lines = ["⚓ <b>ADUANA MONITOR</b>", ""]
    if note:
        lines.extend([telegram.escape_html(note), ""])
    if active:
        lines.append(f"🟢 Monitoreo automático activo: <b>{len(active)}</b>")
        for m in active[:6]:
            label = "TODAS" if m.get("aduana") == "ALL" else settings.ADUANA_LABELS.get(m.get("aduana"), m.get("aduana"))
            lines.append(f"• {telegram.escape_html(m.get('rut'))} · {telegram.escape_html(label)}")
        if len(active) > 6:
            lines.append(f"… y {len(active) - 6} más")
        lines.extend(["", f"Cada revisión automática busca los últimos <b>{settings.CRON_LOOKBACK_DAYS} días</b>."])
    else:
        lines.extend([
            "Todavía no tienes monitoreos activos.",
            "",
            "Pulsa <b>➕ Agregar RUT</b> una sola vez para dejarlo configurado. Después el sistema lo recordará y revisará automáticamente.",
        ])

    if force_new:
        old = _panel_id(user)
        _safe_delete(user["chat_id"], old)
        result = telegram.send_message(user["chat_id"], "\n".join(lines), reply_markup=telegram.MAIN_MENU)
        mid = _result_message_id(result)
        _set_state(user["id"], "IDLE", {}, panel_id=mid or None)
        return result

    _set_state(user["id"], "IDLE", {})
    return _show_panel(_refresh_user(user["id"]), "\n".join(lines), rows=[[("🧹 Limpiar", "ui_clear")]])


def _status_message(user):
    status = user.get("status")
    if status == "PENDING":
        return "⏳ Tu solicitud está pendiente de aprobación. Te avisaremos por este mismo chat."
    if status == "REJECTED":
        return "Tu solicitud no está habilitada actualmente."
    if status == "DISABLED":
        return "Tu acceso está desactivado actualmente."
    return "Tu cuenta no está disponible."


def _clear_screen(user, incoming_message_id=None, panel_message_id=None):
    # Delete the user's menu tap/command when Telegram permits it, then remove
    # the single bot panel. The persistent bottom keyboard remains available.
    _safe_delete(user["chat_id"], incoming_message_id)
    target = int(panel_message_id or _panel_id(user) or 0)
    _safe_delete(user["chat_id"], target)
    _forget_panel(user["id"])


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
        data = str(callback.get("data") or "")
        user, _ = storage.get_or_create_telegram_user(
            from_user.get("id"), chat.get("id"), from_user.get("username") or "",
            from_user.get("first_name") or "",
        )
        message_id = source.get("message_id")
        if message_id:
            _remember_panel(user["id"], message_id)
        return _handle_callback(_refresh_user(user["id"]), data, message_id)

    from_user = message.get("from") or {}
    text = str(message.get("text") or "").strip()
    incoming_message_id = message.get("message_id")
    if not from_user.get("id") or not chat.get("id"):
        return
    user, _ = storage.get_or_create_telegram_user(
        from_user.get("id"), chat.get("id"), from_user.get("username") or "",
        from_user.get("first_name") or "",
    )

    if text.startswith("/start"):
        _safe_delete(user["chat_id"], incoming_message_id)
        if user.get("status") == "ACTIVE":
            return _send_home(user, force_new=True)
        telegram.send_message(user["chat_id"], _status_message(user))
        return

    if text in ("/clear", "🧹 Limpiar pantalla", "Limpiar pantalla"):
        if user.get("status") == "ACTIVE":
            return _clear_screen(user, incoming_message_id=incoming_message_id)
        return

    if user.get("status") != "ACTIVE":
        telegram.send_message(user["chat_id"], _status_message(user))
        return

    if text in ("📋 Mis monitoreos", "Mis monitoreos"):
        _safe_delete(user["chat_id"], incoming_message_id)
        return _show_monitors(user)
    if text in ("➕ Agregar RUT", "Agregar RUT"):
        _safe_delete(user["chat_id"], incoming_message_id)
        return _start_add(user)
    if text in ("🔍 Consulta manual", "🔍 Consultar", "Consultar", "Consulta manual"):
        _safe_delete(user["chat_id"], incoming_message_id)
        return _start_query(user)

    action = user.get("pending_action")
    if action == "ADD_RUT":
        _safe_delete(user["chat_id"], incoming_message_id)
        return _add_rut_text(user, text)
    if action == "QUERY_RUT_OWNER":
        _safe_delete(user["chat_id"], incoming_message_id)
        return _query_owner_rut(user, text)

    _safe_delete(user["chat_id"], incoming_message_id)
    return _send_home(user, note="Usa el menú inferior para continuar.")


# ---------------------------------------------------------------------------
# Monitor setup: this is the primary workflow. Configure once, remember forever.
# ---------------------------------------------------------------------------

def _start_add(user):
    try:
        permissions.assert_can_monitor(user)
    except permissions.PermissionDenied as exc:
        return _show_panel(user, telegram.escape_html(str(exc)), rows=[[("🧹 Limpiar", "ui_clear")]])
    _set_state(user["id"], "ADD_RUT", {})
    return _show_panel(
        _refresh_user(user["id"]),
        "➕ <b>Nuevo monitoreo</b>\n\nEscribe el RUT.\nEj.: <code>76315010-0</code>, <code>76.315.010-0</code> o <code>763150100</code>",
        rows=[[("❌ Cancelar", "ui_home")]],
    )


def _add_rut_text(user, text):
    rut = _normalize_rut(text)
    if not _valid_rut(rut):
        return _show_panel(
            user,
            "⚠️ <b>RUT inválido</b>\n\nEscríbelo nuevamente. Ej.: <code>76315010-0</code>",
            rows=[[("❌ Cancelar", "ui_home")]],
        )
    try:
        permissions.assert_can_add_rut(user, storage.distinct_ruts(user["id"]), rut)
    except permissions.PermissionDenied as exc:
        return _show_panel(user, telegram.escape_html(str(exc)), rows=[[("← Volver", "ui_home")]])

    data = {"rut": rut, "aduana": DEFAULT_ADUANA}
    _set_state(user["id"], "ADD_CONFIRM", data)
    return _show_add_confirm(_refresh_user(user["id"]))


def _show_add_confirm(user, message_id=None):
    data = _pending(user)
    rut = data.get("rut")
    code = data.get("aduana") or DEFAULT_ADUANA
    label = "TODAS" if code == "ALL" else settings.ADUANA_LABELS.get(code, code)
    _set_state(user["id"], "ADD_CONFIRM", {"rut": rut, "aduana": code})
    return _show_panel(
        _refresh_user(user["id"]),
        "➕ <b>Nuevo monitoreo</b>\n\n"
        f"RUT: <b>{telegram.escape_html(rut)}</b>\n"
        f"Aduana: <b>{telegram.escape_html(label)}</b>\n\n"
        f"Se guardará de forma permanente. La revisión automática buscará siempre los últimos {settings.CRON_LOOKBACK_DAYS} días.",
        rows=[
            [("✅ Activar monitoreo", "a_confirm")],
            [("🏛 Cambiar Aduana", "a_change")],
            [("❌ Cancelar", "ui_home")],
        ],
        message_id=message_id,
    )


def _show_aduana_quick(user, mode, message_id=None):
    data = _pending(user)
    _set_state(user["id"], "ADD_ADUANA_MENU" if mode == "a" else "QUERY_ADUANA_MENU", data)
    rows = [
        [("✅ IQUIQUE", f"{mode}_ad:7")],
        [("ARICA", f"{mode}_ad:3"), ("ANTOFAGASTA", f"{mode}_ad:14")],
    ]
    if user.get("role") == "OWNER":
        rows.append([("TODAS", f"{mode}_ad:ALL")])
    rows.extend([
        [("Más aduanas…", f"{mode}_ad_page:0")],
        [("← Volver", f"{mode}_back")],
    ])
    return _show_panel(
        _refresh_user(user["id"]),
        "🏛 <b>Selecciona Aduana</b>\n\nIQUIQUE está como opción predeterminada.",
        rows=rows,
        message_id=message_id,
    )


def _show_aduana_page(user, mode, page, message_id=None):
    items = list(settings.ADUANAS)
    page_size = 6
    pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(int(page), pages - 1))
    chunk = items[page * page_size:(page + 1) * page_size]
    rows = []
    for i in range(0, len(chunk), 2):
        rows.append([(name, f"{mode}_ad:{code}") for code, name in chunk[i:i + 2]])
    nav = []
    if page > 0:
        nav.append(("‹ Anterior", f"{mode}_ad_page:{page - 1}"))
    if page < pages - 1:
        nav.append(("Siguiente ›", f"{mode}_ad_page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("← Opciones rápidas", f"{mode}_ad_quick")])
    return _show_panel(
        user,
        f"🏛 <b>Aduanas</b> · página {page + 1}/{pages}",
        rows=rows,
        message_id=message_id,
    )


def _set_add_aduana(user, code, message_id=None):
    if code == "ALL" and user.get("role") != "OWNER":
        return _show_panel(user, "Opción no disponible.", rows=[[("← Volver", "a_ad_quick")]], message_id=message_id)
    if code != "ALL" and code not in settings.ADUANA_CODES:
        return
    data = _pending(user)
    rut = data.get("rut")
    if not rut:
        return _send_home(user, note="La configuración venció. Intenta nuevamente.")
    _set_state(user["id"], "ADD_CONFIRM", {"rut": rut, "aduana": code})
    return _show_add_confirm(_refresh_user(user["id"]), message_id=message_id)


def _confirm_add(user, message_id=None):
    data = _pending(user)
    rut = data.get("rut")
    code = data.get("aduana") or DEFAULT_ADUANA
    if not rut:
        return _send_home(user, note="La configuración venció. Intenta nuevamente.")
    storage.add_or_enable_monitor(user["id"], rut, code)
    label = "TODAS" if code == "ALL" else settings.ADUANA_LABELS.get(code, code)
    _set_state(user["id"], "IDLE", {})
    return _show_panel(
        _refresh_user(user["id"]),
        "✅ <b>Monitoreo guardado</b>\n\n"
        f"RUT: <b>{telegram.escape_html(rut)}</b>\n"
        f"Aduana: <b>{telegram.escape_html(label)}</b>\n\n"
        "No necesitas volver a configurarlo. La primera revisión completa crea la línea base y no envía avisos antiguos.",
        rows=[
            [("📋 Ver mis monitoreos", "ui_monitors")],
            [("➕ Agregar otro RUT", "ui_add")],
            [("🧹 Limpiar", "ui_clear")],
        ],
        message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Manual query: secondary workflow. Defaults to IQUIQUE + current year.
# ---------------------------------------------------------------------------

def _start_query(user):
    try:
        permissions.assert_can_query(user)
    except permissions.PermissionDenied as exc:
        return _show_panel(user, telegram.escape_html(str(exc)), rows=[[("🧹 Limpiar", "ui_clear")]])

    ruts = storage.distinct_ruts(user["id"])
    rows = [[(rut, f"q_rut:{rut}")] for rut in ruts[:12]]
    if user.get("role") == "OWNER":
        rows.append([("✏️ Consultar otro RUT", "q_other")])
    rows.append([("❌ Cancelar", "ui_home")])

    if not ruts and user.get("role") == "OWNER":
        _set_state(user["id"], "QUERY_RUT_OWNER", {})
        return _show_panel(
            _refresh_user(user["id"]),
            "🔍 <b>Consulta manual</b>\n\nEscribe el RUT que quieres consultar.",
            rows=[[("❌ Cancelar", "ui_home")]],
        )
    if not ruts:
        return _show_panel(
            user,
            "No tienes RUT configurados todavía. Agrega uno primero.",
            rows=[[("➕ Agregar RUT", "ui_add")], [("❌ Cancelar", "ui_home")]],
        )

    _set_state(user["id"], "QUERY_PICK_RUT", {})
    return _show_panel(
        _refresh_user(user["id"]),
        "🔍 <b>Consulta manual</b>\n\nSelecciona un RUT ya guardado.",
        rows=rows,
    )


def _query_owner_rut(user, text):
    rut = _normalize_rut(text)
    if not _valid_rut(rut):
        return _show_panel(
            user,
            "⚠️ <b>RUT inválido</b>\n\nEscríbelo nuevamente. Ej.: <code>76315010-0</code>",
            rows=[[("❌ Cancelar", "ui_home")]],
        )
    return _prepare_query(user, rut)


def _prepare_query(user, rut, message_id=None):
    if user.get("role") == "OWNER":
        data = {
            "rut": rut,
            "aduana": DEFAULT_ADUANA,
            "query_kind": "years",
            "years": [date.today().year],
        }
    else:
        options = permissions.range_options_for(user)
        chosen = options[-1]
        data = {
            "rut": rut,
            "aduana": DEFAULT_ADUANA,
            "query_kind": "range",
            "range_key": chosen[0],
        }
    _set_state(user["id"], "QUERY_READY", data)
    return _show_query_panel(_refresh_user(user["id"]), message_id=message_id)


def _query_period_label(user, data):
    if data.get("query_kind") == "years":
        years = [int(y) for y in data.get("years", [])]
        return ", ".join(map(str, sorted(years, reverse=True))) if years else "sin seleccionar"
    key = data.get("range_key")
    try:
        for option_key, label, _start, _end in permissions.range_options_for(user):
            if option_key == key:
                return label
    except Exception:
        pass
    return "Período"


def _show_query_panel(user, message_id=None):
    data = _pending(user)
    rut = data.get("rut")
    if not rut:
        return _send_home(user, note="La consulta venció. Intenta nuevamente.")
    code = data.get("aduana") or DEFAULT_ADUANA
    label = "TODAS" if code == "ALL" else settings.ADUANA_LABELS.get(code, code)
    period = _query_period_label(user, data)
    clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
    _set_state(user["id"], "QUERY_READY", clean_data)
    return _show_panel(
        _refresh_user(user["id"]),
        "🔍 <b>Consulta manual</b>\n\n"
        f"RUT: <b>{telegram.escape_html(rut)}</b>\n"
        f"Aduana: <b>{telegram.escape_html(label)}</b>\n"
        f"Período: <b>{telegram.escape_html(period)}</b>",
        rows=[
            [("🔍 Buscar", "q_go")],
            [("🏛 Aduana", "q_change_ad"), ("📅 Período", "q_change_period")],
            [("❌ Cancelar", "ui_home")],
        ],
        message_id=message_id,
    )


def _set_query_aduana(user, code, message_id=None):
    if code == "ALL" and user.get("role") != "OWNER":
        return
    if code != "ALL" and code not in settings.ADUANA_CODES:
        return
    data = _pending(user)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    data["aduana"] = code
    _set_state(user["id"], "QUERY_READY", data)
    return _show_query_panel(_refresh_user(user["id"]), message_id=message_id)


def _show_query_period(user, message_id=None, page=None):
    data = _pending(user)
    if user.get("role") != "OWNER":
        rows = []
        selected = data.get("range_key")
        for key, label, _start, _end in permissions.range_options_for(user):
            mark = "✅ " if key == selected else ""
            rows.append([(mark + label, f"q_range:{key}")])
        rows.append([("← Volver", "q_period_done")])
        _set_state(user["id"], "QUERY_PERIOD", {k: v for k, v in data.items() if not k.startswith("_")})
        return _show_panel(user, "📅 <b>Selecciona período</b>", rows=rows, message_id=message_id)

    years = permissions.available_years_for(user)
    chosen = {int(y) for y in data.get("years", [])}
    if page is None:
        quick = years[:3]
        rows = [[(("✅ " if y in chosen else "") + str(y), f"q_year:{y}:quick") for y in quick]]
        rows.append([("Más años…", "q_year_page:0")])
        rows.append([("← Volver", "q_period_done")])
        _set_state(user["id"], "QUERY_PERIOD", {k: v for k, v in data.items() if not k.startswith("_")})
        return _show_panel(
            user,
            "📅 <b>Período</b>\n\nSelecciona uno o más años. Los cambios se hacen en esta misma pantalla.",
            rows=rows,
            message_id=message_id,
        )

    page_size = 6
    pages = max(1, (len(years) + page_size - 1) // page_size)
    page = max(0, min(int(page), pages - 1))
    chunk = years[page * page_size:(page + 1) * page_size]
    rows = []
    for i in range(0, len(chunk), 3):
        rows.append([(("✅ " if y in chosen else "") + str(y), f"q_year:{y}:{page}") for y in chunk[i:i + 3]])
    nav = []
    if page > 0:
        nav.append(("‹ Anterior", f"q_year_page:{page - 1}"))
    if page < pages - 1:
        nav.append(("Siguiente ›", f"q_year_page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("← Años recientes", "q_change_period"), ("✅ Volver", "q_period_done")])
    return _show_panel(user, f"📅 <b>Años</b> · página {page + 1}/{pages}", rows=rows, message_id=message_id)


def _toggle_query_year(user, year, location, message_id=None):
    if user.get("role") != "OWNER":
        return
    data = _pending(user)
    chosen = {int(y) for y in data.get("years", [])}
    if year in chosen:
        chosen.remove(year)
    else:
        chosen.add(year)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    data["years"] = sorted(chosen, reverse=True)
    _set_state(user["id"], "QUERY_PERIOD", data)
    current = _refresh_user(user["id"])
    if location == "quick":
        return _show_query_period(current, message_id=message_id)
    try:
        page = int(location)
    except Exception:
        page = 0
    return _show_query_period(current, message_id=message_id, page=page)


def _select_query_range(user, key, message_id=None):
    options = {item[0]: item for item in permissions.range_options_for(user)}
    if key not in options:
        return
    data = _pending(user)
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    data["query_kind"] = "range"
    data["range_key"] = key
    _set_state(user["id"], "QUERY_READY", data)
    return _show_query_panel(_refresh_user(user["id"]), message_id=message_id)


def _run_query(user, message_id=None):
    data = _pending(user)
    rut = data.get("rut")
    aduana = data.get("aduana") or DEFAULT_ADUANA
    if not rut:
        return _send_home(user, note="La consulta venció. Intenta nuevamente.")

    if data.get("query_kind") == "years":
        years = [int(y) for y in data.get("years", [])]
        if not years:
            return _show_panel(user, "Selecciona al menos un año.", rows=[[("📅 Elegir año", "q_change_period")]], message_id=message_id)
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
            return _show_query_period(user, message_id=message_id)
        kind = "range"
        kwargs = {"start": option[2], "end": option[3]}

    panel_id = int(message_id or _panel_id(user) or 0)
    _set_state(user["id"], "QUERY_RUNNING", {}, panel_id=panel_id or None)
    _show_panel(
        _refresh_user(user["id"]),
        "⏳ <b>Consultando Aduana…</b>\n\nPuedes dejar Telegram abierto o cerrado. El resultado llegará aquí.",
        rows=[[("🧹 Limpiar", "ui_clear")]],
        message_id=panel_id or None,
    )
    threading.Thread(
        target=_manual_worker,
        args=(user["id"], user["chat_id"], panel_id, kind),
        kwargs={"rut": rut, "aduana": aduana, **kwargs},
        daemon=True,
    ).start()


def _manual_worker(user_id, chat_id, message_id, kind, **kwargs):
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
        _send_results(user_id, chat_id, message_id, rows, rut, aduana, all_ok)
    except Exception:
        log.exception("Aduana manual query failed")
        user = storage.get_user(user_id)
        if user:
            _show_panel(
                user,
                "⚠️ No se pudo completar la consulta. Intenta nuevamente más tarde.",
                rows=[[("🧹 Limpiar", "ui_clear")]],
                message_id=message_id or None,
            )


def _send_results(user_id, chat_id, message_id, rows, rut, aduana, all_ok):
    user = storage.get_user(user_id)
    if not user:
        return
    _set_state(user_id, "IDLE", {}, panel_id=message_id or None)
    user = storage.get_user(user_id)

    if not rows and not all_ok:
        return _show_panel(
            user,
            "⚠️ <b>Consulta incompleta</b>\n\nAduana no respondió correctamente en uno o más períodos. No podemos afirmar que no existan resultados.",
            rows=[[("🔄 Intentar otra consulta", "ui_query")], [("🧹 Limpiar", "ui_clear")]],
            message_id=message_id or None,
        )

    warning = "⚠️ Algunos períodos tuvieron error.\n\n" if not all_ok else ""
    if not rows:
        return _show_panel(
            user,
            "Sin resultados para ese período.",
            rows=[[("🔄 Otra consulta", "ui_query")], [("🧹 Limpiar", "ui_clear")]],
            message_id=message_id or None,
        )

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
        text = "\n".join(lines)
        if len(text) > 3900:
            text = text[:3800] + "\n\n…resultado abreviado."
        return _show_panel(
            user,
            text,
            rows=[[("🔄 Otra consulta", "ui_query")], [("🧹 Limpiar", "ui_clear")]],
            message_id=message_id or None,
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=settings.COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    label = settings.ADUANA_LABELS.get(aduana, aduana)
    telegram.send_document(chat_id, f"ADUANA_{label}_{rut}.csv", buf.getvalue().encode("utf-8-sig"), f"{len(rows)} resultado(s)")
    return _show_panel(
        user,
        warning + f"✅ Consulta terminada: <b>{len(rows)}</b> resultados. Se envió el archivo CSV.",
        rows=[[("🔄 Otra consulta", "ui_query")], [("🧹 Limpiar", "ui_clear")]],
        message_id=message_id or None,
    )


# ---------------------------------------------------------------------------
# Stored monitors
# ---------------------------------------------------------------------------

def _show_monitors(user, message_id=None):
    monitors = storage.list_user_monitors(user["id"])
    if not monitors:
        _set_state(user["id"], "IDLE", {})
        return _show_panel(
            _refresh_user(user["id"]),
            "📋 <b>Mis monitoreos</b>\n\nNo tienes monitoreos configurados.",
            rows=[[("➕ Agregar RUT", "ui_add")], [("🧹 Limpiar", "ui_clear")]],
            message_id=message_id,
        )

    lines = ["📋 <b>Mis monitoreos</b>", ""]
    buttons = []
    for monitor in monitors:
        label = "TODAS" if monitor["aduana"] == "ALL" else settings.ADUANA_LABELS.get(monitor["aduana"], monitor["aduana"])
        icon = "🟢" if bool(monitor.get("enabled")) else "⚪"
        baseline = "✓" if bool(monitor.get("baseline_done")) else "…"
        lines.append(f"{icon} {telegram.escape_html(monitor['rut'])} · {telegram.escape_html(label)} · base {baseline}")
        toggle = "⏸ Pausar" if bool(monitor.get("enabled")) else "▶️ Activar"
        buttons.append([(toggle, f"m_toggle:{monitor['id']}"), ("🗑 Eliminar", f"m_delete:{monitor['id']}")])
    buttons.append([("➕ Agregar RUT", "ui_add")])
    buttons.append([("🧹 Limpiar", "ui_clear")])
    _set_state(user["id"], "IDLE", {})
    return _show_panel(_refresh_user(user["id"]), "\n".join(lines), rows=buttons, message_id=message_id)


def _toggle_monitor(user, monitor_id, message_id=None):
    monitor = storage.get_monitor_for_user(monitor_id, user["id"])
    if not monitor:
        return _show_monitors(user, message_id=message_id)
    storage.set_monitor_enabled(monitor_id, user["id"], not bool(monitor.get("enabled")))
    return _show_monitors(_refresh_user(user["id"]), message_id=message_id)


def _delete_monitor(user, monitor_id, message_id=None):
    storage.delete_monitor(monitor_id, user["id"])
    return _show_monitors(_refresh_user(user["id"]), message_id=message_id)


# ---------------------------------------------------------------------------
# Inline callbacks
# ---------------------------------------------------------------------------

def _handle_callback(user, data, message_id=None):
    if user.get("status") != "ACTIVE":
        return telegram.send_message(user["chat_id"], _status_message(user))

    if data == "ui_clear":
        return _clear_screen(user, panel_message_id=message_id)
    if data == "ui_home":
        return _send_home(user)
    if data == "ui_monitors":
        return _show_monitors(user, message_id=message_id)
    if data == "ui_add":
        return _start_add(user)
    if data == "ui_query":
        return _start_query(user)

    if data == "a_confirm":
        return _confirm_add(user, message_id=message_id)
    if data == "a_change" or data == "a_ad_quick":
        return _show_aduana_quick(user, "a", message_id=message_id)
    if data == "a_back":
        return _show_add_confirm(user, message_id=message_id)
    if data.startswith("a_ad_page:"):
        try:
            page = int(data.split(":", 1)[1])
        except Exception:
            page = 0
        return _show_aduana_page(user, "a", page, message_id=message_id)
    if data.startswith("a_ad:"):
        return _set_add_aduana(user, data.split(":", 1)[1], message_id=message_id)

    if data == "q_other":
        _set_state(user["id"], "QUERY_RUT_OWNER", {})
        return _show_panel(
            _refresh_user(user["id"]),
            "🔍 <b>Consulta manual</b>\n\nEscribe el RUT que quieres consultar.",
            rows=[[("❌ Cancelar", "ui_home")]],
            message_id=message_id,
        )
    if data.startswith("q_rut:"):
        rut = _normalize_rut(data.split(":", 1)[1])
        if user.get("role") != "OWNER" and rut not in storage.distinct_ruts(user["id"]):
            return
        return _prepare_query(user, rut, message_id=message_id)
    if data == "q_change_ad" or data == "q_ad_quick":
        return _show_aduana_quick(user, "q", message_id=message_id)
    if data == "q_back":
        return _show_query_panel(user, message_id=message_id)
    if data.startswith("q_ad_page:"):
        try:
            page = int(data.split(":", 1)[1])
        except Exception:
            page = 0
        return _show_aduana_page(user, "q", page, message_id=message_id)
    if data.startswith("q_ad:"):
        return _set_query_aduana(user, data.split(":", 1)[1], message_id=message_id)
    if data == "q_change_period":
        return _show_query_period(user, message_id=message_id)
    if data.startswith("q_year_page:"):
        try:
            page = int(data.split(":", 1)[1])
        except Exception:
            page = 0
        return _show_query_period(user, message_id=message_id, page=page)
    if data.startswith("q_year:"):
        parts = data.split(":")
        try:
            year = int(parts[1])
        except Exception:
            return
        location = parts[2] if len(parts) > 2 else "quick"
        return _toggle_query_year(user, year, location, message_id=message_id)
    if data.startswith("q_range:"):
        return _select_query_range(user, data.split(":", 1)[1], message_id=message_id)
    if data == "q_period_done":
        return _show_query_panel(user, message_id=message_id)
    if data in ("q_go", "q_year_go"):
        return _run_query(user, message_id=message_id)

    if data.startswith("m_toggle:"):
        try:
            mid = int(data.split(":", 1)[1])
        except Exception:
            return
        return _toggle_monitor(user, mid, message_id=message_id)
    if data.startswith("m_delete:"):
        try:
            mid = int(data.split(":", 1)[1])
        except Exception:
            return
        return _delete_monitor(user, mid, message_id=message_id)
