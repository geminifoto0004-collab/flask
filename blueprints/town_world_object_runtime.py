"""Generic AI-authored pixel objects for CUSTOMS AGENT TOWN.

DeepSeek chooses what should exist in the world. Common objects use a curated
pixel preset so they stay readable and attractive; uncommon objects can still
fall back to model-authored safe rectangle parts. The browser only renders
validated data and never executes model code.
"""

import re
import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn
from .town_world_map_runtime import zone_by_id

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ZONES = {"office", "harbor_walkway", "pier", "sea"}
_BEHAVIORS = {
    "static", "bob", "float", "drift", "swim_left", "swim_right",
    "drive_left", "drive_right",
}
_PRESETS = {"car", "christmas_tree", "octopus", "seal"}

_PRESET_PARTS = {
    "car": [
        {"shape": "rect", "x": -18, "y": -6, "w": 36, "h": 11, "color": "#c94f45"},
        {"shape": "rect", "x": -9, "y": -13, "w": 18, "h": 8, "color": "#e4ecee"},
        {"shape": "rect", "x": -7, "y": -11, "w": 6, "h": 5, "color": "#7798a5"},
        {"shape": "rect", "x": 2, "y": -11, "w": 6, "h": 5, "color": "#7798a5"},
        {"shape": "rect", "x": -13, "y": 4, "w": 7, "h": 7, "color": "#20272d"},
        {"shape": "rect", "x": 7, "y": 4, "w": 7, "h": 7, "color": "#20272d"},
        {"shape": "rect", "x": -11, "y": 5, "w": 3, "h": 3, "color": "#8f9699"},
        {"shape": "rect", "x": 9, "y": 5, "w": 3, "h": 3, "color": "#8f9699"},
        {"shape": "rect", "x": 14, "y": -4, "w": 4, "h": 3, "color": "#f0d26a"},
        {"shape": "rect", "x": -18, "y": -4, "w": 4, "h": 3, "color": "#d86760"},
    ],
    "christmas_tree": [
        {"shape": "rect", "x": -3, "y": 12, "w": 6, "h": 12, "color": "#6b472f"},
        {"shape": "rect", "x": -18, "y": -5, "w": 36, "h": 13, "color": "#2e7448"},
        {"shape": "rect", "x": -14, "y": -16, "w": 28, "h": 13, "color": "#388a54"},
        {"shape": "rect", "x": -10, "y": -26, "w": 20, "h": 12, "color": "#46a061"},
        {"shape": "rect", "x": -3, "y": -33, "w": 6, "h": 8, "color": "#f1c94f"},
        {"shape": "rect", "x": -12, "y": -10, "w": 4, "h": 4, "color": "#dc5f58"},
        {"shape": "rect", "x": 8, "y": -12, "w": 4, "h": 4, "color": "#e3b84e"},
        {"shape": "rect", "x": -3, "y": -20, "w": 4, "h": 4, "color": "#79a8d5"},
        {"shape": "rect", "x": 5, "y": 0, "w": 4, "h": 4, "color": "#d77dc1"},
    ],
    "octopus": [
        {"shape": "rect", "x": -11, "y": -12, "w": 22, "h": 16, "color": "#895bb1"},
        {"shape": "rect", "x": -7, "y": -17, "w": 14, "h": 7, "color": "#a170c8"},
        {"shape": "rect", "x": -10, "y": 2, "w": 4, "h": 14, "color": "#744b9c"},
        {"shape": "rect", "x": -4, "y": 3, "w": 4, "h": 16, "color": "#744b9c"},
        {"shape": "rect", "x": 2, "y": 3, "w": 4, "h": 15, "color": "#744b9c"},
        {"shape": "rect", "x": 8, "y": 2, "w": 4, "h": 13, "color": "#744b9c"},
        {"shape": "rect", "x": -6, "y": -9, "w": 4, "h": 4, "color": "#f2f0eb"},
        {"shape": "rect", "x": 3, "y": -9, "w": 4, "h": 4, "color": "#f2f0eb"},
        {"shape": "rect", "x": -5, "y": -8, "w": 2, "h": 2, "color": "#1d2430"},
        {"shape": "rect", "x": 4, "y": -8, "w": 2, "h": 2, "color": "#1d2430"},
    ],
    "seal": [
        {"shape": "rect", "x": -14, "y": -4, "w": 28, "h": 9, "color": "#718388"},
        {"shape": "rect", "x": -10, "y": -8, "w": 20, "h": 5, "color": "#829398"},
        {"shape": "rect", "x": 10, "y": -10, "w": 10, "h": 10, "color": "#8d9ca0"},
        {"shape": "rect", "x": 17, "y": -7, "w": 5, "h": 4, "color": "#a8b4b6"},
        {"shape": "rect", "x": -10, "y": 4, "w": 8, "h": 5, "color": "#5d6d72"},
        {"shape": "rect", "x": 2, "y": 4, "w": 8, "h": 5, "color": "#5d6d72"},
        {"shape": "rect", "x": 15, "y": -8, "w": 2, "h": 2, "color": "#172126"},
        {"shape": "rect", "x": 20, "y": -5, "w": 2, "h": 2, "color": "#263237"},
    ],
}


def _guess_preset(name):
    text = str(name or "").strip().lower()
    if any(token in text for token in ("car", "auto", "coche", "車", "车")):
        return "car"
    if any(token in text for token in ("christmas", "navidad", "聖誕樹", "圣诞树")):
        return "christmas_tree"
    if any(token in text for token in ("octopus", "pulpo", "章魚", "章鱼")):
        return "octopus"
    if any(token in text for token in ("seal", "foca", "海豹")):
        return "seal"
    return ""


def _ensure_tools():
    names = {(item.get("function") or {}).get("name") for item in DIRECTOR_TOOLS}
    if "world_object_spawn" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "world_object_spawn",
            "Create a visible pixel-art world object. Prefer preset=car/christmas_tree/octopus/seal for those common objects so the shared renderer uses a polished sprite. For other objects, provide safe rectangle parts. Put cars on harbor_walkway, Christmas trees in office, and sea life in sea.",
            {
                "name": {"type": "string", "minLength": 1, "maxLength": 32},
                "label": {"type": "string", "maxLength": 32},
                "preset": {"type": "string", "enum": sorted(_PRESETS)},
                "zone": {"type": "string", "enum": sorted(_ZONES)},
                "x": {"type": "number", "minimum": 12, "maximum": 628},
                "y": {"type": "number", "minimum": 64, "maximum": 388},
                "behavior": {"type": "string", "enum": sorted(_BEHAVIORS)},
                "direction": {"type": "integer", "enum": [-1, 1]},
                "parts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 24,
                    "items": {
                        "type": "object",
                        "properties": {
                            "shape": {"type": "string", "enum": ["rect"]},
                            "x": {"type": "number", "minimum": -48, "maximum": 48},
                            "y": {"type": "number", "minimum": -48, "maximum": 48},
                            "w": {"type": "number", "minimum": 2, "maximum": 96},
                            "h": {"type": "number", "minimum": 2, "maximum": 80},
                            "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                        },
                        "required": ["shape", "x", "y", "w", "h", "color"],
                        "additionalProperties": False,
                    },
                },
            },
            ["name", "zone", "behavior"],
        ))
    if "world_object_move" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "world_object_move",
            "Move or change the behavior of an existing generic world object by id.",
            {
                "id": {"type": "string", "minLength": 1, "maxLength": 80},
                "zone": {"type": "string", "enum": sorted(_ZONES)},
                "x": {"type": "number", "minimum": 12, "maximum": 628},
                "y": {"type": "number", "minimum": 64, "maximum": 388},
                "behavior": {"type": "string", "enum": sorted(_BEHAVIORS)},
            },
            ["id"],
        ))
    if "world_object_remove" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "world_object_remove",
            "Remove an existing generic world object by id.",
            {"id": {"type": "string", "minLength": 1, "maxLength": 80}},
            ["id"],
        ))


def _number(value, low, high, default):
    try:
        value = float(value)
    except Exception:
        value = default
    return round(max(low, min(high, value)), 1)


def _zone_position(zone_id, x=None, y=None):
    zone = zone_by_id(zone_id)
    if not zone:
        return None
    pad = 12.0
    x0 = float(zone.get("x") or 0) + pad
    y0 = float(zone.get("y") or 0) + pad
    x1 = float(zone.get("x") or 0) + max(pad, float(zone.get("w") or 0) - pad)
    y1 = float(zone.get("y") or 0) + max(pad, float(zone.get("h") or 0) - pad)
    return (
        _number(x, x0, x1, (x0 + x1) / 2),
        _number(y, y0, y1, (y0 + y1) / 2),
    )


def _parts(raw):
    result = []
    for part in raw if isinstance(raw, list) else []:
        if not isinstance(part, dict) or str(part.get("shape") or "rect") != "rect":
            continue
        color = str(part.get("color") or "#7b8790")
        if not _HEX.match(color):
            continue
        result.append({
            "shape": "rect",
            "x": _number(part.get("x"), -48, 48, 0),
            "y": _number(part.get("y"), -48, 48, 0),
            "w": _number(part.get("w"), 2, 96, 8),
            "h": _number(part.get("h"), 2, 80, 8),
            "color": color,
        })
        if len(result) >= 24:
            break
    return result


def _resolved_parts(item):
    preset = str(item.get("preset") or "").strip().lower()
    if preset not in _PRESETS:
        preset = _guess_preset(item.get("name") or item.get("label"))
    if preset in _PRESETS:
        return preset, [dict(part) for part in _PRESET_PARTS[preset]]
    return "", _parts(item.get("parts"))


def install_world_object_runtime():
    _ensure_tools()
    previous_validate = _base._validate_actions
    previous_clean = _base._clean_world
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for index, item in enumerate(raw_actions[:12]):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if kind == "world_object_spawn":
                zone = str(item.get("zone") or "")
                behavior = str(item.get("behavior") or "static")
                preset, parts = _resolved_parts(item)
                pos = _zone_position(zone, item.get("x"), item.get("y")) if zone in _ZONES else None
                if not parts or not pos or behavior not in _BEHAVIORS:
                    continue
                if preset == "car" and zone != "harbor_walkway":
                    zone = "harbor_walkway"; pos = _zone_position(zone, item.get("x"), item.get("y"))
                elif preset in {"octopus", "seal"} and zone != "sea":
                    zone = "sea"; pos = _zone_position(zone, item.get("x"), item.get("y"))
                elif preset == "christmas_tree" and zone != "office":
                    zone = "office"; pos = _zone_position(zone, item.get("x"), item.get("y"))
                if zone != "sea" and behavior.startswith("swim_"):
                    behavior = "static"
                if zone != "harbor_walkway" and behavior.startswith("drive_"):
                    behavior = "static"
                if preset == "car" and not behavior.startswith("drive_"):
                    behavior = "drive_right" if int(item.get("direction", 1) or 1) >= 0 else "drive_left"
                if preset == "octopus" and not behavior.startswith("swim_"):
                    behavior = "swim_left" if int(item.get("direction", 1) or 1) < 0 else "swim_right"
                object_id = str(item.get("id") or item.get("action_id") or f"world-{int(time.time()*1000)}-{index}")[:80]
                output.append({
                    "type": "world_object_spawn",
                    "id": object_id,
                    "preset": preset,
                    "name": str(item.get("name") or item.get("label") or preset or "AI object")[:32],
                    "label": str(item.get("label") or item.get("name") or "")[:32],
                    "zone": zone,
                    "x": pos[0], "y": pos[1],
                    "behavior": behavior,
                    "direction": -1 if int(item.get("direction", 1) or 1) < 0 else 1,
                    "parts": parts,
                })
            elif kind == "world_object_move":
                object_id = str(item.get("id") or "")[:80]
                if not object_id:
                    continue
                action = {"type": "world_object_move", "id": object_id}
                zone = str(item.get("zone") or "")
                if zone in _ZONES:
                    action["zone"] = zone
                    pos = _zone_position(zone, item.get("x"), item.get("y"))
                    if pos:
                        action["x"], action["y"] = pos
                behavior = str(item.get("behavior") or "")
                if behavior in _BEHAVIORS:
                    action["behavior"] = behavior
                output.append(action)
            elif kind == "world_object_remove":
                object_id = str(item.get("id") or "")[:80]
                if object_id:
                    output.append({"type": "world_object_remove", "id": object_id})
            else:
                output.extend(previous_validate([item]))
            if len(output) >= 10:
                break
        return output[:10]

    def clean_world(world):
        cleaned = previous_clean(world)
        source = world if isinstance(world, dict) else {}
        objects = []
        for item in source.get("worldObjects") if isinstance(source.get("worldObjects"), list) else []:
            if not isinstance(item, dict):
                continue
            zone = str(item.get("zone") or "")
            preset, parts = _resolved_parts(item)
            pos = _zone_position(zone, item.get("x"), item.get("y")) if zone in _ZONES else None
            if not parts or not pos:
                continue
            behavior = str(item.get("behavior") or "static")
            if behavior not in _BEHAVIORS:
                behavior = "static"
            objects.append({
                "id": str(item.get("id") or "")[:80],
                "preset": preset,
                "name": str(item.get("name") or item.get("label") or preset or "AI object")[:32],
                "label": str(item.get("label") or item.get("name") or "")[:32],
                "zone": zone,
                "x": pos[0], "y": pos[1],
                "behavior": behavior,
                "direction": -1 if int(item.get("direction", 1) or 1) < 0 else 1,
                "parts": parts,
                "createdAt": int(item.get("createdAt") or item.get("created_at") or 0),
            })
        cleaned["worldObjects"] = objects[-40:]
        return cleaned

    def apply_persistent_actions(world, actions):
        actions = actions or []
        object_actions = [a for a in actions if str(a.get("type") or "").startswith("world_object_")]
        evolved = previous_apply(world, [a for a in actions if not str(a.get("type") or "").startswith("world_object_")])
        objects = [dict(o) for o in evolved.get("worldObjects", []) if isinstance(o, dict)]
        for action in object_actions:
            kind = action.get("type")
            if kind == "world_object_spawn":
                object_id = str(action.get("id") or "")[:80]
                if object_id and not any(str(o.get("id")) == object_id for o in objects):
                    objects.append({
                        "id": object_id,
                        "preset": action.get("preset") or "",
                        "name": action.get("name") or "AI object",
                        "label": action.get("label") or action.get("name") or "",
                        "zone": action.get("zone"),
                        "x": action.get("x"), "y": action.get("y"),
                        "behavior": action.get("behavior") or "static",
                        "direction": action.get("direction", 1),
                        "parts": action.get("parts") or [],
                        "createdAt": int(time.time() * 1000),
                    })
            elif kind == "world_object_move":
                for obj in objects:
                    if str(obj.get("id")) != str(action.get("id")):
                        continue
                    zone = str(action.get("zone") or obj.get("zone") or "")
                    pos = _zone_position(zone, action.get("x", obj.get("x")), action.get("y", obj.get("y")))
                    if pos:
                        obj["zone"] = zone; obj["x"], obj["y"] = pos
                    if action.get("behavior") in _BEHAVIORS:
                        obj["behavior"] = action.get("behavior")
                    break
            elif kind == "world_object_remove":
                objects = [o for o in objects if str(o.get("id")) != str(action.get("id"))]
        evolved["worldObjects"] = objects[-40:]
        return clean_world(evolved)

    _base._validate_actions = validate_actions
    _base._clean_world = clean_world
    _base._apply_persistent_actions = apply_persistent_actions
