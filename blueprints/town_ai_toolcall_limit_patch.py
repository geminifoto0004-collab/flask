"""Raise the native DeepSeek tool-call sequence cap for composed town scenes."""

import json

from . import town_ai_director_runtime as _director


def _expanded_tool_calls_to_actions(message):
    actions = []
    for call in (message.get("tool_calls") or [])[:12]:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        raw_args = fn.get("arguments")
        if isinstance(raw_args, dict):
            args = dict(raw_args)
        else:
            try:
                args = json.loads(raw_args or "{}")
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        actions.append({"type": name, **args})
    return actions


_director._tool_calls_to_actions = _expanded_tool_calls_to_actions
