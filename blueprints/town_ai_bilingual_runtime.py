"""Bilingual dialogue/runtime support for CUSTOMS AGENT TOWN.

Adds optional Traditional Chinese translations to dialogue tool payloads so the
browser can switch between Spanish and Chinese without losing the original
Spanish conversation.
"""

from . import town_ai_bp as _base
from .town_ai_director_runtime import DIRECTOR_TOOLS



def _tool_named(name: str):
    for item in DIRECTOR_TOOLS:
        fn = item.get("function") or {}
        if fn.get("name") == name:
            return item
    return None



def _ensure_bilingual_schema():
    chat_tool = _tool_named("agent_chat")
    if chat_tool:
        props = (((chat_tool.get("function") or {}).get("parameters") or {}).get("properties") or {})
        turns = (props.get("turns") or {})
        items = (turns.get("items") or {})
        item_props = items.get("properties") or {}
        if "text_zh" not in item_props:
            item_props["text_zh"] = {"type": "string", "minLength": 1, "maxLength": 120}
            items["properties"] = item_props
            turns["items"] = items
            props["turns"] = turns
            ((chat_tool.get("function") or {}).get("parameters") or {})["properties"] = props

    say_tool = _tool_named("agent_say")
    if say_tool:
        props = (((say_tool.get("function") or {}).get("parameters") or {}).get("properties") or {})
        if "text_zh" not in props:
            props["text_zh"] = {"type": "string", "minLength": 1, "maxLength": 120}
            ((say_tool.get("function") or {}).get("parameters") or {})["properties"] = props



def install_bilingual_runtime():
    _ensure_bilingual_schema()
    previous_validate = _base._validate_actions
    previous_clean = _base._clean_world

    def validate_actions(raw_actions):
        valid = []
        if not isinstance(raw_actions, list):
            return valid
        for item in raw_actions[:12]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if kind == "agent_chat":
                from_agent = str(item.get("from") or item.get("agent") or "").upper()
                to_agent = str(item.get("to") or item.get("target") or "").upper()
                if from_agent in {"MIA", "ANA", "LIA"} and to_agent in {"MIA", "ANA", "LIA"} and from_agent != to_agent:
                    turns = []
                    raw_turns = item.get("turns") if isinstance(item.get("turns"), list) else []
                    for index, turn in enumerate(raw_turns[:8]):
                        if not isinstance(turn, dict):
                            continue
                        speaker = str(turn.get("speaker") or turn.get("from") or (from_agent if index % 2 == 0 else to_agent)).upper()
                        text = str(turn.get("text") or turn.get("message") or "").strip()[:120]
                        text_zh = str(turn.get("text_zh") or turn.get("textZh") or turn.get("translation_zh") or "").strip()[:120]
                        if speaker in {from_agent, to_agent} and text:
                            payload = {"speaker": speaker, "text": text}
                            if text_zh:
                                payload["text_zh"] = text_zh
                            turns.append(payload)
                    if turns:
                        valid.append({"type": "agent_chat", "from": from_agent, "to": to_agent, "turns": turns})
                continue
            if kind == "agent_say":
                agent = str(item.get("agent") or "").upper()
                text = str(item.get("text") or item.get("message") or "").strip()[:120]
                text_zh = str(item.get("text_zh") or item.get("textZh") or turn.get("translation_zh") or "").strip()[:120] if False else str(item.get("text_zh") or item.get("textZh") or item.get("translation_zh") or "").strip()[:120]
                if agent in {"MIA", "ANA", "LIA"} and text:
                    payload = {"type": "agent_say", "agent": agent, "text": text}
                    if text_zh:
                        payload["text_zh"] = text_zh
                    valid.append(payload)
                continue
            valid.extend(previous_validate([item]))
            if len(valid) >= 10:
                break
        return valid[:10]

    def clean_world(world):
        cleaned = previous_clean(world)
        if not isinstance(world, dict):
            return cleaned
        recent_dialogue = world.get("recentDialogue") if isinstance(world.get("recentDialogue"), list) else []
        if recent_dialogue:
            safe = []
            for item in recent_dialogue[-8:]:
                if not isinstance(item, dict):
                    continue
                turns = []
                for turn in item.get("turns") if isinstance(item.get("turns"), list) else []:
                    if not isinstance(turn, dict):
                        continue
                    payload = {
                        "speaker": str(turn.get("speaker") or "")[:18],
                        "text": str(turn.get("text") or "")[:120],
                    }
                    if turn.get("text_zh"):
                        payload["text_zh"] = str(turn.get("text_zh") or "")[:120]
                    turns.append(payload)
                safe.append({
                    "at": item.get("at"),
                    "members": [str(v or "")[:18] for v in (item.get("members") or [])[:2]],
                    "text": str(item.get("text") or "")[:520],
                    "turns": turns[:8],
                })
            cleaned["recentDialogue"] = safe
        return cleaned

    _base._validate_actions = validate_actions
    _base._clean_world = clean_world
