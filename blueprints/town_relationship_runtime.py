"""Generic persistent relationship state for CUSTOMS AGENT TOWN.

Relationships are semantic world memory, not hard-coded stories. DeepSeek may
update a directional relationship when a scene genuinely changes it, and future
director calls can read that shared memory.
"""

import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn


def _tool_name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def _short(value, limit):
    return str(value or "").strip()[:limit]


def _ensure_tool():
    if any(_tool_name(tool) == "set_relationship" for tool in DIRECTOR_TOOLS):
        return
    DIRECTOR_TOOLS.append(_fn(
        "set_relationship",
        (
            "Persist one directional social relationship only when the story actually changes it. "
            "Use for friendship, attraction, dating, ex-partner, distrust, acquaintance, rejection, etc. "
            "Do not force reciprocal feelings: ANA can reject Oscar even if Oscar likes ANA."
        ),
        {
            "actor": {"type": "string", "minLength": 1, "maxLength": 64},
            "target": {"type": "string", "minLength": 1, "maxLength": 64},
            "status": {"type": "string", "minLength": 1, "maxLength": 40},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1},
            "note": {"type": "string", "maxLength": 140},
        },
        ["actor", "target", "status"],
    ))


def install_relationship_runtime():
    _ensure_tool()
    previous_validate = _base._validate_actions
    previous_clean = _base._clean_world
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for item in raw_actions[:18]:
            if not isinstance(item, dict) or str(item.get("type") or "") != "set_relationship":
                output.extend(previous_validate([item]))
                continue
            actor = _short(item.get("actor") or item.get("from"), 64)
            target = _short(item.get("target") or item.get("to"), 64)
            status = _short(item.get("status") or item.get("relation"), 40)
            if not actor or not target or not status or actor.upper() == target.upper():
                continue
            try:
                intensity = max(0.0, min(1.0, float(item.get("intensity", 0.5))))
            except Exception:
                intensity = 0.5
            output.append({
                "type": "set_relationship",
                "actor": actor,
                "target": target,
                "status": status,
                "intensity": round(intensity, 2),
                "note": _short(item.get("note"), 140),
            })
            if len(output) >= 16:
                break
        return output[:16]

    def clean_world(world):
        cleaned = previous_clean(world)
        source = world if isinstance(world, dict) else {}
        relationships = []
        for raw in source.get("relationships") if isinstance(source.get("relationships"), list) else []:
            if not isinstance(raw, dict):
                continue
            actor = _short(raw.get("actor") or raw.get("from"), 64)
            target = _short(raw.get("target") or raw.get("to"), 64)
            status = _short(raw.get("status") or raw.get("relation"), 40)
            if not actor or not target or not status or actor.upper() == target.upper():
                continue
            try:
                intensity = max(0.0, min(1.0, float(raw.get("intensity", 0.5))))
            except Exception:
                intensity = 0.5
            relationships.append({
                "actor": actor,
                "target": target,
                "status": status,
                "intensity": round(intensity, 2),
                "note": _short(raw.get("note"), 140),
                "updatedAt": int(raw.get("updatedAt") or 0),
            })
        cleaned["relationships"] = relationships[-100:]
        return cleaned

    def apply_persistent_actions(world, actions):
        actions = actions or []
        relation_actions = [a for a in actions if str(a.get("type") or "") == "set_relationship"]
        evolved = previous_apply(world, [a for a in actions if str(a.get("type") or "") != "set_relationship"])
        relationships = [dict(r) for r in evolved.get("relationships", []) if isinstance(r, dict)]
        stamp = int(time.time() * 1000)
        for action in relation_actions:
            actor = _short(action.get("actor"), 64)
            target = _short(action.get("target"), 64)
            if not actor or not target:
                continue
            relationships = [r for r in relationships if not (
                str(r.get("actor") or "").lower() == actor.lower() and
                str(r.get("target") or "").lower() == target.lower()
            )]
            relationships.append({
                "actor": actor,
                "target": target,
                "status": _short(action.get("status"), 40),
                "intensity": action.get("intensity", 0.5),
                "note": _short(action.get("note"), 140),
                "updatedAt": stamp,
            })
        evolved["relationships"] = relationships[-100:]
        return clean_world(evolved)

    _base._validate_actions = validate_actions
    _base._clean_world = clean_world
    _base._apply_persistent_actions = apply_persistent_actions
