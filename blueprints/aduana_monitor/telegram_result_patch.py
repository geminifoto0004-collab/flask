# -*- coding: utf-8 -*-
"""Readable Telegram formatting for Aduana manual-query results.

Keep the single-screen UI from telegram_ui_patch, but present records as
mobile-friendly blocks instead of dense pipe-separated lines.
"""
from __future__ import annotations

import csv
import io
import re

from . import bot, settings, storage, telegram

_INLINE_LIMIT = 6


def _value(row, key):
    return str((row or {}).get(key) or "").strip()


def _money(value):
    text = str(value or "").strip()
    compact = re.sub(r"\s+", "", text)
    if compact.isdigit():
        try:
            return f"{int(compact):,}".replace(",", ".")
        except Exception:
            pass
    return text


def _send_csv(chat_id, rows, rut, aduana):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=settings.COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    label = settings.ADUANA_LABELS.get(aduana, aduana)
    telegram.send_document(
        chat_id,
        f"ADUANA_{label}_{rut}.csv",
        buf.getvalue().encode("utf-8-sig"),
        f"{len(rows)} resultado(s)",
    )


def _send_results(user_id, chat_id, message_id, rows, rut, aduana, all_ok):
    user = storage.get_user(user_id)
    if not user:
        return

    bot._set_state(user_id, "IDLE", {}, panel_id=message_id or None)
    user = storage.get_user(user_id)

    if not rows and not all_ok:
        return bot._show_panel(
            user,
            "⚠️ <b>Consulta incompleta</b>\n\n"
            "Aduana no respondió correctamente en uno o más períodos. "
            "No podemos afirmar que no existan resultados.",
            rows=[[("🔄 Intentar otra consulta", "ui_query")]],
            message_id=message_id or None,
        )

    warning = "⚠️ Algunos períodos tuvieron error.\n\n" if not all_ok else ""
    if not rows:
        return bot._show_panel(
            user,
            "Sin resultados para ese período.",
            rows=[[("🔄 Otra consulta", "ui_query")]],
            message_id=message_id or None,
        )

    # Large result sets are much easier to read as a file than as one giant
    # Telegram message. Keep the chat panel short and useful.
    if len(rows) > _INLINE_LIMIT:
        _send_csv(chat_id, rows, rut, aduana)
        label = settings.ADUANA_LABELS.get(aduana, aduana)
        return bot._show_panel(
            user,
            warning
            + f"✅ <b>{len(rows)} resultados</b>\n\n"
            + f"RUT: <code>{telegram.escape_html(rut)}</code>\n"
            + f"Aduana: <b>{telegram.escape_html(label)}</b>\n\n"
            + "Se envió un archivo CSV para ver todos los registros con claridad.",
            rows=[[("🔄 Otra consulta", "ui_query")]],
            message_id=message_id or None,
        )

    label = settings.ADUANA_LABELS.get(aduana, aduana)
    infractors = []
    for row in rows:
        name = _value(row, "infractor")
        if name and name not in infractors:
            infractors.append(name)

    lines = [
        warning + f"✅ <b>{len(rows)} resultado(s)</b>",
        f"RUT: <code>{telegram.escape_html(rut)}</code>",
        f"Aduana: <b>{telegram.escape_html(label)}</b>",
    ]
    if len(infractors) == 1:
        lines.append(f"👤 {telegram.escape_html(infractors[0])}")

    for index, row in enumerate(rows, start=1):
        denuncia = _value(row, "n_denuncia") or "—"
        emision = _value(row, "emision") or "—"
        notificacion = _value(row, "notificacion")
        documento = _value(row, "doc_aduanero") or "—"
        multa = _money(_value(row, "multa_max_legal")) or "—"

        lines.extend([
            "",
            "────────────",
            f"<b>{index}. Denuncia N° {telegram.escape_html(denuncia)}</b>",
            f"📅 Emisión: <b>{telegram.escape_html(emision)}</b>",
        ])
        if notificacion:
            lines.append(f"🔔 Notificación: {telegram.escape_html(notificacion)}")
        if len(infractors) != 1:
            infractor = _value(row, "infractor")
            if infractor:
                lines.append(f"👤 {telegram.escape_html(infractor)}")
        lines.extend([
            "📄 Documento:",
            f"{telegram.escape_html(documento)}",
            f"💰 Multa máx.: <b>{telegram.escape_html(multa)}</b>",
        ])

    text = "\n".join(lines)
    if len(text) > 3900:
        _send_csv(chat_id, rows, rut, aduana)
        text = (
            warning
            + f"✅ <b>{len(rows)} resultados</b>\n\n"
            + "Los datos son demasiado largos para mostrarlos claramente en una sola pantalla. "
            + "Se envió el CSV completo."
        )

    return bot._show_panel(
        user,
        text,
        rows=[[("🔄 Otra consulta", "ui_query")]],
        message_id=message_id or None,
    )


def install():
    if getattr(bot, "_telegram_result_patch_installed", False):
        return
    bot._send_results = _send_results
    bot._telegram_result_patch_installed = True


install()
