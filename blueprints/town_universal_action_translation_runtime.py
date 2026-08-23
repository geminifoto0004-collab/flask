"""Translate the single universal AI verb into existing engine primitives.

DeepSeek sees one generic world_action function. The browser/backend can keep
using mature low-level primitives while stories no longer require bespoke tools.
"""

from . import town_ai_bp as _base

_OFFICERS = {"MIA", "ANA", "LIA"}


def install_universal_action_translation_runtime():
    previous_validate = _base._validate_actions

    def validate_actions(raw_actions):
        if not isinstance(raw_actions, list):
            return []
        translated = []
        for raw in raw_actions[:20]:
            if not isinstance(raw, dict) or str(raw.get("type") or "") != "world_action":
                translated.append(raw)
                continue
            op = str(raw.get("operation") or "").lower()
            entity = str(raw.get("entity") or raw.get("id") or "")
            upper = entity.upper()
            if op == "spawn":
                translated.append({
                    "type": "spawn_entity", "id": raw.get("id") or entity, "name": raw.get("name") or entity,
                    "entityType": raw.get("entityType") or "human", "zone": raw.get("zone") or "harbor_walkway",
                    "x": raw.get("x"), "y": raw.get("y"), "bodyColor": raw.get("bodyColor"),
                    "accentColor": raw.get("accentColor"), "carrying": raw.get("carrying") or [],
                })
            elif op == "move":
                translated.append({"type": "move_entity", "entity": entity, "target": raw.get("target"), "zone": raw.get("zone"), "x": raw.get("x"), "y": raw.get("y"), "speed": raw.get("speed")})
            elif op == "say":
                if upper in _OFFICERS:
                    translated.append({"type": "agent_say", "agent": upper, "text": raw.get("text"), "text_zh": raw.get("text_zh")})
                else:
                    translated.append({"type": "say", "entity": entity, "text": raw.get("text"), "text_zh": raw.get("text_zh")})
            elif op == "wait":
                if upper not in _OFFICERS:
                    translated.append({"type": "wait", "entity": entity, "seconds": raw.get("seconds")})
            elif op == "give":
                if upper not in _OFFICERS:
                    translated.append({"type": "give", "entity": entity, "target": raw.get("target"), "item": raw.get("item")})
            elif op == "leave":
                translated.append({"type": "agent_shift", "agent": upper, "mode": "off"} if upper in _OFFICERS else {"type": "leave", "entity": entity})
            elif op == "remove":
                if upper in _OFFICERS:
                    translated.append({"type": "agent_shift", "agent": upper, "mode": "off"})
                else:
                    translated.append({"type": "remove_entity", "entity": entity})
            elif op == "set_presence":
                if upper in _OFFICERS:
                    translated.append({"type": "agent_shift", "agent": upper, "mode": "on" if raw.get("present") is not False else "off"})
                elif raw.get("present") is False:
                    translated.append({"type": "remove_entity", "entity": entity})
            elif op == "set_state":
                key = str(raw.get("key") or "")
                if upper in _OFFICERS and key == "onDuty":
                    translated.append({"type": "agent_shift", "agent": upper, "mode": "on" if bool(raw.get("value")) else "off"})
                elif upper in _OFFICERS and key in {"mood", "energy"}:
                    # Existing trait engine is delta-based. Keep absolute state
                    # changes server-side only instead of fabricating a delta.
                    translated.append(raw)
                else:
                    translated.append(raw)
            elif op == "set_relationship":
                translated.append({"type": "set_relationship", "actor": entity, "target": raw.get("target"), "status": raw.get("status"), "intensity": raw.get("intensity"), "note": raw.get("note")})
            elif op == "interact":
                # Interaction is semantic; movement/speech are separate explicit
                # calls. No fake browser animation is invented here.
                continue
        return previous_validate(translated)

    _base._validate_actions = validate_actions
