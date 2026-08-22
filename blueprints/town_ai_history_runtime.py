"""Preserve a small safe history of recent browser-executed director actions.

This gives the model memory of what it just did so it can avoid repeatedly
choosing coffee/files/lookSea without hard-coding a replacement routine.
"""

from . import town_ai_bp as _base


def install_history_runtime():
    previous = _base._clean_world

    def clean(world):
        cleaned = previous(world)
        if not isinstance(world, dict):
            return cleaned
        raw = world.get("recentDirectorActions")
        if not isinstance(raw, list):
            return cleaned
        history = []
        for item in raw[-12:]:
            if not isinstance(item, dict):
                continue
            history.append({
                "at": item.get("at"),
                "type": str(item.get("type") or "")[:40],
                "agent": str(item.get("agent") or "")[:18],
                "target": str(item.get("target") or "")[:18],
                "action": str(item.get("action") or "")[:40],
                "label": str(item.get("label") or "")[:32],
            })
        cleaned["recentDirectorActions"] = history
        return cleaned

    _base._clean_world = clean
