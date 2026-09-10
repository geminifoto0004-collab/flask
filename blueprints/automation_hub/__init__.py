# -*- coding: utf-8 -*-
"""Shared Automation / Telegram Bot Hub blueprint.

This package is deliberately isolated from existing business blueprints. It owns
reusable Telegram-bot registration/webhook plumbing while every crawler keeps
its own business logic.
"""
from flask import Blueprint

automation_hub_bp = Blueprint(
    "automation_hub",
    __name__,
    template_folder="templates",
)

from .registry import register_lazy  # noqa: E402

# Current plugin. Future crawlers register another lazy handler and optional
# admin_path; the parent XINGWANG login/admin console remains the single入口.
register_lazy(
    "ADUANA",
    "Aduana Monitor",
    "blueprints.aduana_monitor.bot",
    "handle_update",
    admin_path="/admin/automation/aduana",
)

from . import routes as _routes  # noqa: E402,F401

__all__ = ["automation_hub_bp"]
