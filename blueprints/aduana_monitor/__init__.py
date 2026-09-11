# -*- coding: utf-8 -*-
"""Aduana Monitor child blueprint.

This package is intentionally self-contained. The main FLASK application only
needs to register this blueprint; no existing business/service code is changed.
"""
from flask import Blueprint

aduana_bp = Blueprint(
    "aduana",
    __name__,
    template_folder="templates",
)

from . import routes as _routes  # noqa: E402,F401
from . import web_query as _web_query  # noqa: E402,F401
from . import collector_queue as _collector_queue  # noqa: E402,F401
from . import collector_bridge as _collector_bridge  # noqa: E402,F401
from . import telegram_ui_patch as _telegram_ui_patch  # noqa: E402,F401
from . import telegram_result_patch as _telegram_result_patch  # noqa: E402,F401
from . import telegram_anchor_patch as _telegram_anchor_patch  # noqa: E402,F401
from . import telegram_native_menu_patch as _telegram_native_menu_patch  # noqa: E402,F401

__all__ = ["aduana_bp"]
