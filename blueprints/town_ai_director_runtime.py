"""AI world director for the persistent Iquique customs-office town.

DeepSeek chooses real executable town functions through native tool calling.
The model never edits JavaScript or SQL; browser physics and backend validation
remain authoritative.
"""

import json
import os
import time
import xml.etree.ElementTree as ET

import requests


_NEWS_CACHE = {"at": 0.0, "items": []}
_AGENT_ENUM = ["MIA", "ANA", "LIA"]
_ACTION_ENUM = [
    "coffee", "files", "desk", "plant", "waterPlant", "lookSea",
    "stretch", "radio", "checkCoworker", "fishing", "wander",
]
_TRAIT_ENUM = [
    "workBias", "energy", "mood", "curiosity", "social", "focus",
    "restlessness", "coffeeLove", "flowerLove", "fishLove", "cleanliness", "dogLove",
]
_FURNITURE_ENUM = [
    "file_box", "chair", "plant_shelf", "dog_bowl", "side_table",
    "wall_frame", "floor_lamp", "small_cabinet", "rug", "notice_board",
]
_PERSONA_ENUM = ["lazy", "busybody", "restless"]


def _fn(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


DIRECTOR_TOOLS = [
    _fn(
        "agent_action",
        "Make one on-duty idle officer perform one supported visible action. Choose from the character/world state, not a fixed routine.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "action": {"type": "string", "enum": _ACTION_ENUM},
        },
        ["agent", "action"],
    ),
    _fn(
        "agent_chat",
        "Start a real multi-turn conversation between two DIFFERENT on-duty officers. Write every line yourself; topics may come from their personalities, recent events, dogs, work or supplied news.",
        {
            "from": {"type": "string", "enum": _AGENT_ENUM},
            "to": {"type": "string", "enum": _AGENT_ENUM},
            "turns": {
                "type": "array",
                "minItems": 2,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string", "enum": _AGENT_ENUM},
                        "text": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            },
        },
        ["from", "to", "turns"],
    ),
    _fn(
        "agent_say",
        "Make one on-duty officer say one spontaneous sentence. Write the exact words; silence is also possible by choosing another tool instead.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "text": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        ["agent", "text"],
    ),
    _fn(
        "agent_outfit",
        "Choose today's outfit colors/style for one officer. Use sparingly, normally once per Iquique day per person.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "shirt": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "vest": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "badge": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "style": {"type": "string", "maxLength": 24},
            "day": {"type": "string", "maxLength": 10},
        },
        ["agent", "shirt", "vest", "badge", "style", "day"],
    ),
    _fn(
        "agent_evolve",
        "Apply a small persistent RPG-like trait change only when current/recent experience supports it.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "trait": {"type": "string", "enum": _TRAIT_ENUM},
            "delta": {"type": "number", "minimum": -0.18, "maximum": 0.18},
        },
        ["agent", "trait", "delta"],
    ),
    _fn(
        "agent_life",
        "Rare long-term life event for an officer.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "event": {"type": "string", "enum": ["marry", "divorce"]},
            "partnerName": {"type": "string", "maxLength": 18},
        },
        ["agent", "event", "partnerName"],
    ),
    _fn(
        "replace_agent",
        "Very rare personnel change: one slot gets a new colleague. Do not use as ordinary variety.",
        {
            "agent": {"type": "string", "enum": _AGENT_ENUM},
            "newName": {"type": "string", "minLength": 1, "maxLength": 18},
            "persona": {"type": "string", "enum": _PERSONA_ENUM},
            "reason": {"type": "string", "maxLength": 50},
            "traits": {
                "type": "object",
                "properties": {key: {"type": "number", "minimum": 0.05, "maximum": 1.0} for key in _TRAIT_ENUM},
                "additionalProperties": False,
            },
        },
        ["agent", "newName", "persona", "reason", "traits"],
    ),
    _fn(
        "former_visit",
        "Invite a known former colleague to visit, using an id that exists in formerAgents.",
        {"formerId": {"type": "string", "minLength": 1, "maxLength": 80}},
        ["formerId"],
    ),
    _fn("plant_spawn", "Add one new plant when the office plausibly needs/wants one."),
    _fn(
        "dog_visit",
        "Let a passing dog visit the office/harbor area.",
        {"kind": {"type": "string", "enum": ["male", "female"]}},
        ["kind"],
    ),
    _fn("layout_shuffle", "Reorganize the safe office layout. This is a meaningful occasional change, not a routine action."),
    _fn(
        "furniture_add",
        "Add one supported furniture object at a proposed office position. The engine may reject unsafe placement.",
        {
            "furniture": {"type": "string", "enum": _FURNITURE_ENUM},
            "x": {"type": "number", "minimum": 50, "maximum": 590},
            "y": {"type": "number", "minimum": 40, "maximum": 250},
            "w": {"type": "number", "minimum": 8, "maximum": 72},
            "h": {"type": "number", "minimum": 8, "maximum": 60},
            "label": {"type": "string", "maxLength": 24},
        },
        ["furniture", "x", "y", "w", "h", "label"],
    ),
    _fn(
        "furniture_move",
        "Move an existing furniture object by its world id. Prefer this to adding duplicates.",
        {
            "id": {"type": "string", "minLength": 1, "maxLength": 80},
            "x": {"type": "number", "minimum": 50, "maximum": 590},
            "y": {"type": "number", "minimum": 40, "maximum": 250},
        },
        ["id", "x", "y"],
    ),
    _fn(
        "furniture_remove",
        "Remove an existing AI furniture object by id when it is clutter/unwanted.",
        {"id": {"type": "string", "minLength": 1, "maxLength": 80}},
        ["id"],
    ),
    _fn(
        "object_add",
        "Invent a small new pixel object from safe rectangles when something outside the furniture catalog genuinely improves the world.",
        {
            "x": {"type": "number", "minimum": 60, "maximum": 570},
            "y": {"type": "number", "minimum": 104, "maximum": 242},
            "label": {"type": "string", "minLength": 1, "maxLength": 24},
            "parts": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "properties": {
                        "shape": {"type": "string", "enum": ["rect"]},
                        "x": {"type": "number", "minimum": -40, "maximum": 40},
                        "y": {"type": "number", "minimum": -40, "maximum": 40},
                        "w": {"type": "number", "minimum": 2, "maximum": 72},
                        "h": {"type": "number", "minimum": 2, "maximum": 60},
                        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                    },
                    "required": ["shape", "x", "y", "w", "h", "color"],
                    "additionalProperties": False,
                },
            },
        },
        ["x", "y", "label", "parts"],
    ),
]


def _recent_news():
    now = time.time()
    if _NEWS_CACHE["items"] and now - _NEWS_CACHE["at"] < 900:
        return list(_NEWS_CACHE["items"])
    items = []
    try:
        response = requests.get(
            "https://news.google.com/rss/search",
            params={"q": "Iquique OR Tarapacá OR Chile", "hl": "es-419", "gl": "CL", "ceid": "CL:es-419"},
            headers={"User-Agent": "Mozilla/5.0 CUSTOMS-AGENT-TOWN/1.0"},
            timeout=10,
        )
        if response.ok:
            root = ET.fromstring(response.content)
            for node in root.findall("./channel/item")[:8]:
                title = (node.findtext("title") or "").strip()
                published = (node.findtext("pubDate") or "").strip()
                if title:
                    items.append({"title": title[:180], "published": published[:50]})
    except Exception:
        items = []
    _NEWS_CACHE["at"] = now
    _NEWS_CACHE["items"] = items[:8]
    return list(_NEWS_CACHE["items"])


def _tool_calls_to_actions(message):
    actions = []
    for call in (message.get("tool_calls") or [])[:6]:
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


def _call_model(world, evolution, retry_note=""):
    from .town_ai_bp import _iquique_context

    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _iquique_context()
    news = _recent_news()
    mode = (
        "This is an approximately five-minute world-director tick."
        if evolution else
        "This is a MANUAL TEST tick. You MUST choose at least one executable tool so the user can visibly test the director."
    )
    entropy = int(time.time() * 1000) % 1000000

    system_prompt = f"""You are the autonomous WORLD DIRECTOR of a persistent pixel-art customs office in IQUIQUE, Chile.
{mode}

IMPORTANT: You do not write an imaginary story and you do not return action JSON in prose. You DIRECT THE WORLD BY CALLING THE PROVIDED TOOLS. Every physical/social change you want must be a real tool call.

DIRECTOR RULES:
- MIA, ANA, LIA are literal IDs. Never translate or respell them.
- Ship/customs work is the main story. Never interrupt an active ship task for leisure.
- Characters are persistent RPG people. Read numeric traits, mood, energy, relationships, outfit, recent stimuli, dogs, plants and current states.
- Do NOT fall into the coffee/files/lookSea loop. Those are only 3 possibilities among many tools. Vary choices naturally across calls.
- You may combine 1-3 coherent tools in one manual test, e.g. move one person, let two others converse, change an outfit, invite a dog, alter the room, or evolve a trait if justified.
- Dialogue must use agent_chat or agent_say and contain the exact words. Never call agent_action with chat.
- Recent news is optional conversation material. Use only supplied headline facts, never invented article details.
- Outfit changes normally happen once per Iquique day per person.
- Furniture/layout/object changes are occasional, not constant decoration spam.
- Long-term life/personnel changes are rare.
- Never invent unsupported actions. If a desired action has no tool, choose another real capability instead.
- Preserve believable causality: characters can react differently to the same dog/plant/event because their traits differ.
- Manual-test diversity seed: {entropy}. Use it only to avoid repeating the same safe choice; world state still matters more than randomness.
{retry_note}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "server_context": context,
                "recent_news": news,
                "world": world,
            }, ensure_ascii=False, separators=(",", ":"))},
        ],
        "tools": DIRECTOR_TOOLS,
        "tool_choice": "auto" if evolution else "required",
        "temperature": 1.25,
        "max_tokens": 1600,
    }
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if not response.ok:
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {response.text[:260]}")
    raw = response.json()
    message = ((raw.get("choices") or [{}])[0].get("message") or {})
    actions = _tool_calls_to_actions(message)
    # Keep the old caller contract: it expects JSON text and then runs the
    # authoritative validator. The content itself is no longer trusted/needed.
    text = json.dumps({"thought": "", "actions": actions}, ensure_ascii=False)
    return text, model, context, news


def director_model_decision(world, evolution=False):
    from .town_ai_bp import _extract_json, _validate_actions

    text, model, context, news = _call_model(world, evolution)
    decision = _extract_json(text)
    actions = _validate_actions(decision.get("actions"))

    if not actions and not evolution:
        text, model, context, news = _call_model(
            world,
            evolution,
            retry_note="Your previous tool calls were rejected by validation. Call 1-3 different valid tools using only ids/items that exist in the supplied world.",
        )
        decision = _extract_json(text)
        actions = _validate_actions(decision.get("actions"))

    return {
        "ok": True,
        "thought": "",
        "actions": actions,
        "model": model,
        "context": context,
        "news_context_count": len(news),
        "director_tools": True,
        "native_tool_calls": True,
    }
