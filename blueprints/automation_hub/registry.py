# -*- coding: utf-8 -*-
"""Small plugin registry for Telegram update dispatch."""
from __future__ import annotations

import importlib
from contextvars import ContextVar
from threading import RLock

_LOCK = RLock()
_PLUGINS = {}
_CURRENT_BOT_KEY = ContextVar("automation_hub_current_bot_key", default=None)


def register_lazy(key: str, label: str, module: str, handler_name: str) -> None:
    normalized = str(key or "").strip().upper()
    if not normalized:
        raise ValueError("plugin key required")
    with _LOCK:
        _PLUGINS[normalized] = {
            "key": normalized,
            "label": label or normalized,
            "module": module,
            "handler_name": handler_name,
        }


def list_plugins():
    with _LOCK:
        return [dict(v) for _, v in sorted(_PLUGINS.items())]


def has_plugin(key: str) -> bool:
    with _LOCK:
        return str(key or "").strip().upper() in _PLUGINS


def current_bot_key():
    return _CURRENT_BOT_KEY.get()


def dispatch(key: str, update: dict, bot_key: str | None = None):
    normalized = str(key or "").strip().upper()
    with _LOCK:
        spec = dict(_PLUGINS.get(normalized) or {})
    if not spec:
        raise KeyError(f"Unknown automation plugin: {normalized}")
    module = importlib.import_module(spec["module"])
    handler = getattr(module, spec["handler_name"])
    token = _CURRENT_BOT_KEY.set(bot_key) if bot_key else None
    try:
        return handler(update)
    finally:
        if token is not None:
            _CURRENT_BOT_KEY.reset(token)
