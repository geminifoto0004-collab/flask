"""Atomic multi-step scene tool for CUSTOMS AGENT TOWN.

DeepSeek is good at inventing a scene, but native tool calling may legally return
only the first call (for example spawn_entity).  entity_scene lets the model send
one complete ordered scene in a single tool call.  The runtime expands that one
call into the existing generic world verbs, so the browser/server engine stays
generic rather than gaining story-specific functions.
"""

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn


def _tool_name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def _ensure_scene_tool():
    if any(_tool_name(tool) == "entity_scene" for tool in DIRECTOR_TOOLS):
        return
    DIRECTOR_TOOLS.append(_fn(
        "entity_scene",
        (
            "Create ONE COMPLETE multi-step scene for a generic actor in a single call. "
            "Use this instead of returning spawn_entity alone when a visitor/person/animal/vehicle must arrive, move, "
            "speak, give something, wait, and/or leave. Read onDutyAgents before planning: never spawn an absent MIA/ANA/LIA. "
            "If the requested officer is absent, let the actor notice and improvise a believable alternative with an officer "
            "who is actually present (for example ask them, leave/hand over the item, or depart). Include the whole ordered scene "
            "through its natural ending. This is a generic scene transaction, not a story-specific function."
        ),
        {
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "name": {"type": "string", "minLength": 1, "maxLength": 28},
            "entityType": {"type": "string", "enum": ["human", "vehicle", "animal", "item", "decoration"]},
            "zone": {"type": "string", "enum": ["office", "office_door", "harbor_walkway", "pier", "sea"]},
            "bodyColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "accentColor": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "carrying": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "minLength": 1, "maxLength": 24},
            },
            "steps": {
                "type": "array", "minItems": 2, "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["move", "say", "give", "wait", "leave"]},
                        "target": {"type": "string", "maxLength": 64},
                        "zone": {"type": "string", "enum": ["office", "office_door", "harbor_walkway", "pier", "sea"]},
                        "x": {"type": "number", "minimum": 12, "maximum": 628},
                        "y": {"type": "number", "minimum": 60, "maximum": 390},
                        "speed": {"type": "number", "minimum": 12, "maximum": 80},
                        "text": {"type": "string", "maxLength": 160},
                        "text_zh": {"type": "string", "maxLength": 160},
                        "item": {"type": "string", "maxLength": 24},
                        "seconds": {"type": "number", "minimum": 0.5, "maximum": 120},
                    },
                    "required": ["type"],
                    "additionalProperties": False,
                },
            },
        },
        ["id", "name", "entityType", "zone", "steps"],
    ))


def install_generic_scene_runtime():
    _ensure_scene_tool()
    previous_validate = _base._validate_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        expanded = []
        for raw in raw_actions[:18]:
            if not isinstance(raw, dict) or str(raw.get("type") or "") != "entity_scene":
                expanded.append(raw)
                continue

            entity_id = str(raw.get("id") or "").strip()[:64]
            if not entity_id:
                continue
            expanded.append({
                "type": "spawn_entity",
                "id": entity_id,
                "name": raw.get("name"),
                "entityType": raw.get("entityType"),
                "zone": raw.get("zone"),
                "bodyColor": raw.get("bodyColor"),
                "accentColor": raw.get("accentColor"),
                "carrying": raw.get("carrying") if isinstance(raw.get("carrying"), list) else [],
            })

            for step in raw.get("steps") if isinstance(raw.get("steps"), list) else []:
                if not isinstance(step, dict):
                    continue
                kind = str(step.get("type") or "").strip().lower()
                if kind == "move":
                    expanded.append({
                        "type": "move_entity", "entity": entity_id,
                        "target": step.get("target"), "zone": step.get("zone"),
                        "x": step.get("x"), "y": step.get("y"), "speed": step.get("speed"),
                    })
                elif kind == "say":
                    expanded.append({
                        "type": "say", "entity": entity_id,
                        "text": step.get("text"), "text_zh": step.get("text_zh"),
                    })
                elif kind == "give":
                    expanded.append({
                        "type": "give", "entity": entity_id,
                        "target": step.get("target"), "item": step.get("item"),
                    })
                elif kind == "wait":
                    expanded.append({"type": "wait", "entity": entity_id, "seconds": step.get("seconds")})
                elif kind == "leave":
                    expanded.append({"type": "leave", "entity": entity_id})
                if len(expanded) >= 16:
                    break
            if len(expanded) >= 16:
                break
        return previous_validate(expanded[:16])

    _base._validate_actions = validate_actions
