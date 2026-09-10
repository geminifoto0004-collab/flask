# -*- coding: utf-8 -*-
"""Small plugin registry for Telegram update dispatch."""
from __future__ import annotations

import importlib
from threading import RLock

_LOCK = RLock()
_PLUGINS = {}


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


def dispatch(key: str, update: dict):
    normalized = str(key or "").strip().upper()
    with _LOCK:
        spec = dict(_PLUGINS.get(normalized) or {})
    if not spec:
        raise KeyError(f"Unknown automation plugin: {normalized}")
    module = importlib.import_module(spec["module"])
    handler = getattr(module, spec["handler_name"])
    return handler(update)
