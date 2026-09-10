# -*- coding: utf-8 -*-
"""Telegram mobile entry point for Aduana Monitor.

The normal bot workflow is reused, but manual consultation skips the redundant
RUT-selection screen when the user has exactly one saved RUT.  This keeps the
first screen useful: RUT + Aduana + period + Buscar.
"""
from __future__ import annotations

from . import bot, permissions, storage, telegram

_ORIGINAL_START_QUERY = bot._start_query


def _start_query_mobile(user):
    """Open the query panel directly when there is only one possible RUT."""
    try:
        permissions.assert_can_query(user)
    except permissions.PermissionDenied as exc:
        return bot._show_panel(
            user,
            telegram.escape_html(str(exc)),
            rows=[[("🧹 Limpiar", "ui_clear")]],
        )

    ruts = storage.distinct_ruts(user["id"])

    # Main mobile case: the saved RUT is already known, so asking the user to
    # select it again only adds one unnecessary screen/tap.
    if len(ruts) == 1:
        return bot._prepare_query(user, ruts[0])

    # With zero or several saved RUTs the original workflow is still needed:
    # OWNER can type another RUT and multiple saved RUTs require a choice.
    return _ORIGINAL_START_QUERY(user)


# bot.handle_update and its callback handlers resolve _start_query from the bot
# module at runtime, so replacing this one workflow function keeps every other
# behavior unchanged (monitor setup, clear screen, query engine, permissions).
bot._start_query = _start_query_mobile


def handle_update(update):
    return bot.handle_update(update)
