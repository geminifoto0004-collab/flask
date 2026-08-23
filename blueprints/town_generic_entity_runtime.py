"""Generic entity/action engine for CUSTOMS AGENT TOWN.

DeepSeek composes a small set of world verbs instead of needing one bespoke
function per story. The server validates and persists entity scripts in the
shared world; browsers animate the same semantic script independently.
"""

import re
import time

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn
from .town_world_map_runtime import zone_by_id

_ENTITY_TYPES = {"human", "vehicle", "animal", "item", "decoration"}
_ZONES = {"office", "office_door", "harbor_walkway", "pier", "sea"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _tool_names():
    return {(item.get("function") or {}).get("name") for item in DIRECTOR_TOOLS}


def _ensure_tools():
    names = _tool_names()
    if "spawn_entity" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "spawn_entity",
            "Create a persistent world entity such as a visitor/person, vehicle, animal, item or decoration. Use this for characters or actors that may participate in a multi-step scene. Give it a short stable id so later tool calls in the same plan can move/speak/interact with it.",
            {
                "id": {"type": "string", "minLength": 1, "maxLength": 64},
                "name": {"type": "string", "minLength": 1, "maxLength": 28},
                "entityType": {"type": "string", "enum": sorted(_ENTITY_TYPES)},
                "zone": {"type": "string", "enum": sorted(_ZONES)},
                "x": {"type": "number", "minimum": 12, "maximum": 628},
                "y": {"type": "number", "minimum": 60, "maximum": 390},
                "bodyColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "accentColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "carrying": {
                    "type": "array", "maxItems": 6,
                    "items": {"type": "string", "minLength": 1, "maxLength": 24},
                },
            },
            ["id", "name", "entityType", "zone"],
        ))
    if "move_entity" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "move_entity",
            "Move a previously spawned generic entity toward another entity/officer or to a semantic zone/coordinate. The browser enforces the office door and safe movement path.",
            {
                "entity": {"type": "string", "minLength": 1, "maxLength": 64},
                "target": {"type": "string", "maxLength": 64},
                "zone": {"type": "string", "enum": sorted(_ZONES)},
                "x": {"type": "number", "minimum": 12, "maximum": 628},
                "y": {"type": "number", "minimum": 60, "maximum": 390},
                "speed": {"type": "number", "minimum": 12, "maximum": 80},
            },
            ["entity"],
        ))
    if "say" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "say",
            "Make a spawned generic human/visitor say an exact sentence. Use text for natural Spanish and text_zh for Traditional Chinese translation when useful.",
            {
                "entity": {"type": "string", "minLength": 1, "maxLength": 64},
                "text": {"type": "string", "minLength": 1, "maxLength": 160},
                "text_zh": {"type": "string", "maxLength": 160},
            },
            ["entity", "text"],
        ))
    if "give" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "give",
            "Give an item carried by a spawned entity to another entity or an officer. Move near the recipient first when appropriate.",
            {
                "entity": {"type": "string", "minLength": 1, "maxLength": 64},
                "target": {"type": "string", "minLength": 1, "maxLength": 64},
                "item": {"type": "string", "minLength": 1, "maxLength": 24},
            },
            ["entity", "target", "item"],
        ))
    if "wait" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "wait",
            "Keep a spawned entity in place for a short time before its next scripted action.",
            {
                "entity": {"type": "string", "minLength": 1, "maxLength": 64},
                "seconds": {"type": "number", "minimum": 0.5, "maximum": 120},
            },
            ["entity", "seconds"],
        ))
    if "leave" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "leave",
            "Make a spawned entity leave the scene through the proper office door/walkway route. Use near the end of a visit/story.",
            {"entity": {"type": "string", "minLength": 1, "maxLength": 64}},
            ["entity"],
        ))
    if "remove_entity" not in names:
        DIRECTOR_TOOLS.append(_fn(
            "remove_entity",
            "Remove a generic entity from the persistent world immediately when it should no longer exist.",
            {"entity": {"type": "string", "minLength": 1, "maxLength": 64}},
            ["entity"],
        ))


def _text(value, limit=64):
    return str(value or "").strip()[:limit]


def _number(value, low, high, default=None):
    try:
        value = float(value)
    except Exception:
        return default
    return round(max(low, min(high, value)), 1)


def _safe_color(value, default):
    value = str(value or "")
    return value if _HEX.match(value) else default


def _zone_position(zone_id, x=None, y=None):
    if zone_id == "office_door":
        return 320.0, 278.0
    zone = zone_by_id(zone_id)
    if not zone:
        defaults = {
            "office": (320.0, 238.0), "harbor_walkway": (320.0, 292.0),
            "pier": (320.0, 306.0), "sea": (520.0, 350.0),
        }
        return defaults.get(zone_id)
    pad = 10.0
    x0 = float(zone.get("x") or 0) + pad
    y0 = float(zone.get("y") or 0) + pad
    x1 = float(zone.get("x") or 0) + max(pad, float(zone.get("w") or 0) - pad)
    y1 = float(zone.get("y") or 0) + max(pad, float(zone.get("h") or 0) - pad)
    return (
        _number(x, x0, x1, (x0 + x1) / 2),
        _number(y, y0, y1, (y0 + y1) / 2),
    )


def _clean_step(step):
    if not isinstance(step, dict):
        return None
    kind = _text(step.get("type"), 24)
    step_id = _text(step.get("stepId") or step.get("id"), 80)
    base = {"stepId": step_id, "type": kind}
    if kind == "move_entity":
        base.update({
            "target": _text(step.get("target"), 64),
            "zone": _text(step.get("zone"), 24),
            "x": _number(step.get("x"), 12, 628),
            "y": _number(step.get("y"), 60, 390),
            "speed": _number(step.get("speed"), 12, 80, 38),
        })
    elif kind == "say":
        base.update({"text": _text(step.get("text"), 160), "text_zh": _text(step.get("text_zh"), 160)})
    elif kind == "give":
        base.update({"target": _text(step.get("target"), 64), "item": _text(step.get("item"), 24)})
    elif kind == "wait":
        base["seconds"] = _number(step.get("seconds"), 0.5, 120, 1)
    elif kind == "leave":
        pass
    else:
        return None
    return base


def install_generic_entity_runtime():
    _ensure_tools()
    previous_validate = _base._validate_actions
    previous_clean = _base._clean_world
    previous_apply = _base._apply_persistent_actions

    generic_types = {"spawn_entity", "move_entity", "say", "give", "wait", "leave", "remove_entity"}

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        output = []
        for index, item in enumerate(raw_actions[:18]):
            if not isinstance(item, dict):
                continue
            kind = _text(item.get("type"), 32)
            if kind not in generic_types:
                output.extend(previous_validate([item]))
                continue
            if kind == "spawn_entity":
                entity_id = _text(item.get("id"), 64)
                name = _text(item.get("name"), 28)
                entity_type = _text(item.get("entityType") or item.get("entity_type"), 24).lower()
                zone = _text(item.get("zone"), 24)
                pos = _zone_position(zone, item.get("x"), item.get("y")) if zone in _ZONES else None
                if not entity_id or not name or entity_type not in _ENTITY_TYPES or not pos:
                    continue
                carrying = []
                for value in item.get("carrying") if isinstance(item.get("carrying"), list) else []:
                    value = _text(value, 24)
                    if value and value not in carrying:
                        carrying.append(value)
                    if len(carrying) >= 6:
                        break
                output.append({
                    "type": kind, "id": entity_id, "name": name,
                    "entityType": entity_type, "zone": zone,
                    "x": pos[0], "y": pos[1],
                    "bodyColor": _safe_color(item.get("bodyColor"), "#b7a58e"),
                    "accentColor": _safe_color(item.get("accentColor"), "#8670a0"),
                    "carrying": carrying,
                })
            elif kind == "move_entity":
                entity = _text(item.get("entity") or item.get("id"), 64)
                if not entity:
                    continue
                zone = _text(item.get("zone"), 24)
                pos = _zone_position(zone, item.get("x"), item.get("y")) if zone in _ZONES else None
                action = {"type": kind, "entity": entity, "target": _text(item.get("target"), 64), "speed": _number(item.get("speed"), 12, 80, 38)}
                if pos:
                    action.update({"zone": zone, "x": pos[0], "y": pos[1]})
                output.append(action)
            elif kind == "say":
                entity = _text(item.get("entity") or item.get("id"), 64)
                text = _text(item.get("text"), 160)
                if entity and text:
                    output.append({"type": kind, "entity": entity, "text": text, "text_zh": _text(item.get("text_zh"), 160)})
            elif kind == "give":
                entity = _text(item.get("entity") or item.get("id"), 64)
                target = _text(item.get("target"), 64)
                item_name = _text(item.get("item"), 24)
                if entity and target and item_name:
                    output.append({"type": kind, "entity": entity, "target": target, "item": item_name})
            elif kind == "wait":
                entity = _text(item.get("entity") or item.get("id"), 64)
                if entity:
                    output.append({"type": kind, "entity": entity, "seconds": _number(item.get("seconds"), 0.5, 120, 1)})
            elif kind in {"leave", "remove_entity"}:
                entity = _text(item.get("entity") or item.get("id"), 64)
                if entity:
                    output.append({"type": kind, "entity": entity})
            if len(output) >= 16:
                break
        return output[:16]

    def clean_world(world):
        cleaned = previous_clean(world)
        source = world if isinstance(world, dict) else {}
        entities = []
        for raw in source.get("genericEntities") if isinstance(source.get("genericEntities"), list) else []:
            if not isinstance(raw, dict):
                continue
            entity_id = _text(raw.get("id"), 64)
            name = _text(raw.get("name"), 28)
            entity_type = _text(raw.get("entityType") or raw.get("entity_type"), 24).lower()
            zone = _text(raw.get("zone"), 24)
            pos = _zone_position(zone, raw.get("x"), raw.get("y")) if zone in _ZONES else None
            if not entity_id or not name or entity_type not in _ENTITY_TYPES or not pos:
                continue
            carrying = [_text(v, 24) for v in (raw.get("carrying") if isinstance(raw.get("carrying"), list) else []) if _text(v, 24)][:6]
            script = []
            for step in raw.get("script") if isinstance(raw.get("script"), list) else []:
                step = _clean_step(step)
                if step:
                    script.append(step)
                if len(script) >= 24:
                    break
            entities.append({
                "id": entity_id, "name": name, "entityType": entity_type,
                "zone": zone, "x": pos[0], "y": pos[1],
                "bodyColor": _safe_color(raw.get("bodyColor"), "#b7a58e"),
                "accentColor": _safe_color(raw.get("accentColor"), "#8670a0"),
                "carrying": carrying, "script": script,
                "createdAt": int(raw.get("createdAt") or 0),
                "updatedAt": int(raw.get("updatedAt") or 0),
            })
        cleaned["genericEntities"] = entities[-40:]
        return cleaned

    def apply_persistent_actions(world, actions):
        actions = actions or []
        generic_actions = [a for a in actions if str(a.get("type") or "") in generic_types]
        evolved = previous_apply(world, [a for a in actions if str(a.get("type") or "") not in generic_types])
        entities = [dict(e) for e in evolved.get("genericEntities", []) if isinstance(e, dict)]
        by_id = {str(e.get("id") or ""): e for e in entities}
        stamp = int(time.time() * 1000)
        sequence = 0

        def append_step(entity, action):
            nonlocal sequence
            sequence += 1
            script = [dict(s) for s in entity.get("script", []) if isinstance(s, dict)][-20:]
            step = {"stepId": f"{stamp}-{sequence}", **action}
            script.append(step)
            entity["script"] = script[-24:]
            entity["updatedAt"] = stamp

        for action in generic_actions:
            kind = str(action.get("type") or "")
            if kind == "spawn_entity":
                entity_id = str(action.get("id") or "")[:64]
                if entity_id in by_id:
                    continue
                entity = {
                    "id": entity_id, "name": action.get("name") or entity_id,
                    "entityType": action.get("entityType") or "human",
                    "zone": action.get("zone") or "harbor_walkway",
                    "x": action.get("x"), "y": action.get("y"),
                    "bodyColor": action.get("bodyColor") or "#b7a58e",
                    "accentColor": action.get("accentColor") or "#8670a0",
                    "carrying": list(action.get("carrying") or [])[:6],
                    "script": [], "createdAt": stamp, "updatedAt": stamp,
                }
                entities.append(entity); by_id[entity_id] = entity
                continue
            entity_id = str(action.get("entity") or "")[:64]
            entity = by_id.get(entity_id)
            if not entity:
                continue
            if kind == "remove_entity":
                entities = [e for e in entities if str(e.get("id")) != entity_id]
                by_id.pop(entity_id, None)
            elif kind == "move_entity":
                append_step(entity, {"type": kind, "target": action.get("target") or "", "zone": action.get("zone") or "", "x": action.get("x"), "y": action.get("y"), "speed": action.get("speed") or 38})
            elif kind == "say":
                append_step(entity, {"type": kind, "text": action.get("text") or "", "text_zh": action.get("text_zh") or ""})
            elif kind == "give":
                append_step(entity, {"type": kind, "target": action.get("target") or "", "item": action.get("item") or ""})
            elif kind == "wait":
                append_step(entity, {"type": kind, "seconds": action.get("seconds") or 1})
            elif kind == "leave":
                append_step(entity, {"type": kind})
        evolved["genericEntities"] = entities[-40:]
        return clean_world(evolved)

    _base._validate_actions = validate_actions
    _base._clean_world = clean_world
    _base._apply_persistent_actions = apply_persistent_actions
