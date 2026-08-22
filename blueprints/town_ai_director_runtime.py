"""Strict AI director used while validating the town before TiDB persistence.

The model receives a catalog of executable front-end functions and must return
only actions that the browser can actually perform. This keeps narration and
visible world changes in sync during manual testing.
"""

import json
import os

import requests


DIRECTOR_TOOL_CATALOG = """
EXECUTABLE DIRECTOR FUNCTIONS
1. agent_action(agent, action)
   action: coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander
2. agent_evolve(agent, trait, delta)
   trait: workBias|energy|mood|curiosity|social|focus|restlessness|coffeeLove|flowerLove|fishLove
3. agent_life(agent, event, partnerName)
   event: marry|divorce
4. replace_agent(agent, newName, persona, reason, traits)
5. former_visit(formerId)
6. plant_spawn()
7. dog_visit(kind)
8. layout_shuffle()
9. furniture_add(furniture, x, y, w, h, label)
   furniture: file_box|chair|plant_shelf|dog_bowl|side_table|wall_frame|floor_lamp|small_cabinet|rug|notice_board
10. furniture_move(id, x, y)
11. furniture_remove(id)

The browser is the executor. You do not edit JavaScript source and you do not
write SQL. You direct the world only by returning calls to these functions.
"""

_VISIBLE_TYPES = {
    "plant_spawn", "dog_visit", "layout_shuffle", "furniture_add",
    "furniture_move", "furniture_remove", "replace_agent", "former_visit",
    "agent_life",
}


def _call_model(world, evolution, retry_note=""):
    # Imported lazily so this module can be installed as a runtime override after
    # town_ai_bp has already been imported and its helper functions are available.
    from .town_ai_bp import _iquique_context

    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _iquique_context()
    mode = (
        "This is a scheduled evolution tick."
        if evolution else
        "This is a MANUAL VALIDATION click. The owner must be able to SEE that your function call really changed the front end."
    )

    system_prompt = f"""You are the autonomous director of a persistent pixel-art office world in IQUIQUE, Chile.
{mode}

{DIRECTOR_TOOL_CATALOG}

STRICT RULES:
- The `thought` is only a short explanation of actions you ACTUALLY return.
- NEVER say you added/moved/removed/changed something unless a matching executable action is present in `actions`.
- For example, if thought says a chair was added, actions MUST contain furniture_add with furniture='chair'.
- Do not describe imaginary changes that the front end cannot execute.
- During manual validation, include at least ONE clearly visible executable action when safe: prefer furniture_add, plant_spawn, layout_shuffle, dog_visit, former_visit, or a coherent life event.
- Use current IQUIQUE time/weather from server_context. Do not invent contradictory weather.
- Do not touch core desks, walls, the only doorway, harbor geometry, ship results, security data, or business records.
- Furniture coordinates are suggestions; the browser may relocate unsafe placements.
- Keep actions coherent; maximum 7.
{retry_note}

Return ONLY JSON:
{{"thought":"Traditional Chinese, max 80 chars","actions":[...]}}

Action JSON examples:
{{"type":"furniture_add","furniture":"chair","x":520,"y":220,"w":22,"h":22,"label":"午後休息椅"}}
{{"type":"agent_action","agent":"ANA","action":"coffee"}}
{{"type":"agent_evolve","agent":"LIA","trait":"fishLove","delta":0.04}}
{{"type":"agent_life","agent":"ANA","event":"marry","partnerName":"Carlos"}}
{{"type":"replace_agent","agent":"MIA","newName":"SOFIA","persona":"busybody","reason":"退休","traits":{{"workBias":0.72,"social":0.65}}}}
{{"type":"plant_spawn"}}
{{"type":"layout_shuffle"}}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"server_context": context, "world": world}, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 1.05,
        "max_tokens": 720,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if not response.ok:
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}: {response.text[:220]}")
    raw = response.json()
    text = (((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    return text, model, context


def director_model_decision(world, evolution=False):
    from .town_ai_bp import _extract_json, _validate_actions

    text, model, context = _call_model(world, evolution)
    decision = _extract_json(text)
    actions = _validate_actions(decision.get("actions"))

    # One retry during manual testing when the model only narrates or returns an
    # invisible no-op. This makes the "AI think now" button useful for validation.
    if not evolution and not any(a.get("type") in _VISIBLE_TYPES for a in actions):
        text, model, context = _call_model(
            world,
            evolution,
            retry_note="Your previous answer did not contain a clearly visible executable world change. Return at least one visible function call now; do not merely narrate it.",
        )
        decision = _extract_json(text)
        actions = _validate_actions(decision.get("actions"))

    thought = str(decision.get("thought") or "AI 觀察了 IQUIQUE 小鎮並完成一次導演決策。")[:160]
    return {
        "ok": True,
        "thought": thought,
        "actions": actions,
        "model": model,
        "context": context,
        "director_tools": True,
    }
