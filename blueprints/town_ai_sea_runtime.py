"""Sea-life director capability for CUSTOMS AGENT TOWN."""

import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn


def _ensure_tool():
    if any((item.get("function") or {}).get("name") == "sea_creature_spawn" for item in DIRECTOR_TOOLS):
        return
    DIRECTOR_TOOLS.append(_fn(
        "sea_creature_spawn",
        "Spawn a small visible sea creature in the harbor water. Currently supported creature: seal. Use only when the user's instruction or world story calls for it.",
        {
            "kind": {"type": "string", "enum": ["seal"]},
            "x": {"type": "number", "minimum": 70, "maximum": 570},
            "y": {"type": "number", "minimum": 326, "maximum": 374},
            "direction": {"type": "integer", "enum": [-1, 1]},
        },
        ["kind"],
    ))


def install_sea_runtime():
    _ensure_tool()
    previous_validate = _base._validate_actions
    previous_clean = _base._clean_world
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for item in raw_actions[:12]:
            if not isinstance(item, dict) or str(item.get("type") or "") != "sea_creature_spawn":
                output.extend(previous_validate([item]))
                continue
            if str(item.get("kind") or "seal").lower() != "seal":
                continue
            try:
                x = max(70.0, min(570.0, float(item.get("x", 320))))
            except Exception:
                x = 320.0
            try:
                y = max(326.0, min(374.0, float(item.get("y", 350))))
            except Exception:
                y = 350.0
            direction = -1 if int(item.get("direction", 1) or 1) < 0 else 1
            output.append({
                "type": "sea_creature_spawn",
                "id": str(item.get("id") or f"seal-{int(time.time()*1000)}")[:80],
                "kind": "seal",
                "x": round(x, 1),
                "y": round(y, 1),
                "direction": direction,
            })
        return output[:10]

    def clean_world(world):
        cleaned = previous_clean(world)
        if not isinstance(world, dict):
            return cleaned
        creatures = []
        for item in world.get("seaCreatures") if isinstance(world.get("seaCreatures"), list) else []:
            if not isinstance(item, dict) or str(item.get("kind") or "").lower() != "seal":
                continue
            creatures.append({
                "id": str(item.get("id") or "")[:80],
                "kind": "seal",
                "x": item.get("x"),
                "y": item.get("y"),
                "direction": -1 if int(item.get("direction", 1) or 1) < 0 else 1,
                "createdAt": item.get("createdAt") or item.get("created_at") or 0,
            })
        if creatures:
            cleaned["seaCreatures"] = creatures[-12:]
        return cleaned

    def apply_persistent_actions(world, actions):
        actions = actions or []
        sea_actions = [a for a in actions if a.get("type") == "sea_creature_spawn"]
        evolved = previous_apply(world, [a for a in actions if a.get("type") != "sea_creature_spawn"])
        creatures = [dict(c) for c in evolved.get("seaCreatures", []) if isinstance(c, dict)]
        for action in sea_actions:
            creature_id = str(action.get("id") or f"seal-{int(time.time()*1000)}")[:80]
            if any(str(c.get("id")) == creature_id for c in creatures):
                continue
            creatures.append({
                "id": creature_id,
                "kind": "seal",
                "x": action.get("x", 320),
                "y": action.get("y", 350),
                "direction": action.get("direction", 1),
                "createdAt": int(time.time() * 1000),
            })
        evolved["seaCreatures"] = creatures[-12:]
        return clean_world(evolved)

    _base._validate_actions = validate_actions
    _base._clean_world = clean_world
    _base._apply_persistent_actions = apply_persistent_actions
