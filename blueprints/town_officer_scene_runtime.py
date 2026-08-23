"""Atomic scenes for existing on-duty officers.

This is deliberately generic: the model composes ordinary officer speech/action
plus validated world-group effects. It is not a dog-specific story function.
"""

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS, _fn

_OFFICERS = ["MIA", "ANA", "LIA"]
_EXTRA_AGENT_ACTIONS = ["cleanPoop"]
_WORLD_GROUPS = ["dogs", "dogPoops"]


def _tool_name(tool):
    return str((tool.get("function") or {}).get("name") or "")


def _ensure_tools():
    # Extend the already-existing low-level agent_action capability instead of
    # creating one bespoke cleanup function.
    for tool in DIRECTOR_TOOLS:
        if _tool_name(tool) != "agent_action":
            continue
        props = (((tool.get("function") or {}).get("parameters") or {}).get("properties") or {})
        action_schema = props.get("action") if isinstance(props, dict) else None
        enum = action_schema.get("enum") if isinstance(action_schema, dict) else None
        if isinstance(enum, list):
            for action in _EXTRA_AGENT_ACTIONS:
                if action not in enum:
                    enum.append(action)

    if not any(_tool_name(tool) == "world_group_action" for tool in DIRECTOR_TOOLS):
        DIRECTOR_TOOLS.append(_fn(
            "world_group_action",
            "Apply one validated low-level effect to a category already present in the shared world. Use dismiss for actors that leave, clear for debris/items that are cleaned away.",
            {
                "operation": {"type": "string", "enum": ["dismiss", "clear"]},
                "group": {"type": "string", "enum": _WORLD_GROUPS},
                "actor": {"type": "string", "enum": _OFFICERS},
                "reason": {"type": "string", "maxLength": 100},
            },
            ["operation", "group", "actor"],
        ))

    if not any(_tool_name(tool) == "officer_scene" for tool in DIRECTOR_TOOLS):
        DIRECTOR_TOOLS.append(_fn(
            "officer_scene",
            (
                "Direct one COMPLETE scene performed by an existing officer. Use this when the administrator asks an officer to react, "
                "complain/speak, perform a supported physical action and/or change a world group. Preserve explicit requested beats but "
                "choose natural wording and staging yourself. Do not add speech unless it fits the request/character."
            ),
            {
                "agent": {"type": "string", "enum": _OFFICERS},
                "intentSummary": {"type": "string", "minLength": 1, "maxLength": 140},
                "directorNote": {"type": "string", "minLength": 1, "maxLength": 180},
                "steps": {
                    "type": "array", "minItems": 1, "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["say", "action", "world_group"]},
                            "text": {"type": "string", "maxLength": 160},
                            "text_zh": {"type": "string", "maxLength": 160},
                            "action": {"type": "string", "enum": [
                                "coffee", "files", "desk", "plant", "waterPlant", "lookSea",
                                "stretch", "radio", "checkCoworker", "fishing", "wander", "cleanPoop"
                            ]},
                            "operation": {"type": "string", "enum": ["dismiss", "clear"]},
                            "group": {"type": "string", "enum": _WORLD_GROUPS},
                            "reason": {"type": "string", "maxLength": 100},
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                },
            },
            ["agent", "intentSummary", "directorNote", "steps"],
        ))


def install_officer_scene_runtime():
    _ensure_tools()
    previous_validate = _base._validate_actions
    previous_apply = _base._apply_persistent_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        expanded = []
        direct_group_actions = []
        for raw in raw_actions[:18]:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type") or "")
            if kind == "officer_scene":
                agent = str(raw.get("agent") or "").upper()
                if agent not in _OFFICERS:
                    continue
                for step in raw.get("steps") if isinstance(raw.get("steps"), list) else []:
                    if not isinstance(step, dict):
                        continue
                    step_type = str(step.get("type") or "")
                    if step_type == "say":
                        expanded.append({
                            "type": "agent_say", "agent": agent,
                            "text": step.get("text"), "text_zh": step.get("text_zh"),
                        })
                    elif step_type == "action":
                        expanded.append({"type": "agent_action", "agent": agent, "action": step.get("action")})
                    elif step_type == "world_group":
                        direct_group_actions.append({
                            "type": "world_group_action", "actor": agent,
                            "operation": step.get("operation"), "group": step.get("group"),
                            "reason": step.get("reason"),
                        })
            elif kind == "world_group_action":
                direct_group_actions.append(raw)
            elif kind == "agent_action" and str(raw.get("action") or "") in _EXTRA_AGENT_ACTIONS:
                agent = str(raw.get("agent") or "").upper()
                if agent in _OFFICERS:
                    expanded.append({"type": "agent_action", "agent": agent, "action": str(raw.get("action"))})
            else:
                expanded.append(raw)

        validated = previous_validate(expanded)
        for raw in direct_group_actions:
            actor = str(raw.get("actor") or "").upper()
            operation = str(raw.get("operation") or "")
            group = str(raw.get("group") or "")
            if actor in _OFFICERS and operation in {"dismiss", "clear"} and group in _WORLD_GROUPS:
                validated.append({
                    "type": "world_group_action", "actor": actor,
                    "operation": operation, "group": group,
                    "reason": str(raw.get("reason") or "")[:100],
                })
            if len(validated) >= 16:
                break
        return validated[:16]

    def apply_persistent_actions(world, actions):
        actions = actions or []
        group_actions = [a for a in actions if str(a.get("type") or "") == "world_group_action"]
        evolved = previous_apply(world, [a for a in actions if str(a.get("type") or "") != "world_group_action"])
        for action in group_actions:
            group = str(action.get("group") or "")
            operation = str(action.get("operation") or "")
            if group == "dogs" and operation in {"dismiss", "clear"}:
                evolved["dogs"] = []
            elif group == "dogPoops" and operation == "clear":
                current = evolved.get("dogPoops")
                evolved["dogPoops"] = [] if isinstance(current, list) else 0
        return evolved

    _base._validate_actions = validate_actions
    _base._apply_persistent_actions = apply_persistent_actions
