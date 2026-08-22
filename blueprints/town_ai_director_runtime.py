"""AI world director for the persistent Iquique customs-office town.

The model sees world facts and a small recent-news context, then chooses from a
strict catalog of executable capabilities. Dialogue and reactions are generated
by the model; the browser owns rendering/physics and the backend owns validation.
"""

import json
import os
import time
import xml.etree.ElementTree as ET

import requests


_NEWS_CACHE = {"at": 0.0, "items": []}

DIRECTOR_TOOL_CATALOG = """
EXECUTABLE DIRECTOR FUNCTIONS
1. agent_action(agent, action)
   action: coffee|files|desk|plant|waterPlant|lookSea|stretch|radio|chat|checkCoworker|fishing|wander
2. agent_chat(from, to, turns)
   turns: [{speaker:"ANA", text:"..."}, ...] up to 8 turns. YOU write every line.
3. agent_outfit(agent, shirt, vest, badge, style, day)
   Colors are #RRGGBB. Use when today's outfit has not yet been chosen or there is a believable reason to change.
4. agent_evolve(agent, trait, delta)
   trait: workBias|energy|mood|curiosity|social|focus|restlessness|coffeeLove|flowerLove|fishLove|cleanliness|dogLove
5. agent_life(agent, event, partnerName)
   event: marry|divorce
6. replace_agent(agent, newName, persona, reason, traits)
7. former_visit(formerId)
8. plant_spawn()
9. dog_visit(kind)
10. layout_shuffle()
11. furniture_add(furniture, x, y, w, h, label)
    furniture: file_box|chair|plant_shelf|dog_bowl|side_table|wall_frame|floor_lamp|small_cabinet|rug|notice_board
12. furniture_move(id, x, y)
13. furniture_remove(id)
14. object_add(x, y, label, parts)
    parts: safe pixel rectangles [{shape:"rect",x,y,w,h,color:"#RRGGBB"}, ...]

You never edit JavaScript and never write SQL. The browser/server execute only
validated actions from this catalog.
"""


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


def _call_model(world, evolution, retry_note=""):
    from .town_ai_bp import _iquique_context

    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = (os.environ.get("TOWN_AI_MODEL") or "deepseek-chat").strip()
    context = _iquique_context()
    news = _recent_news()
    mode = (
        "This is the approximately five-minute world-director tick. Decide a small coherent slice of life for the coming minutes."
        if evolution else
        "This is a manual world-director tick. Decide naturally what should happen from the current state."
    )

    system_prompt = f"""You are the autonomous director of a persistent pixel-art customs office in IQUIQUE, Chile.
{mode}

{DIRECTOR_TOOL_CATALOG}

DIRECTOR PRINCIPLES:
- The ship/customs workflow is the MAIN STORY. If ships are waiting/being inspected, work takes priority over leisure and decoration.
- People are persistent RPG-like characters. Read their numeric traits, mood, energy, relationships, current action, cleanliness/dogLove and recent reaction cues. Do not reduce a person to one stereotype.
- Do not hard-code a repetitive routine. Coffee, radio, fishing, cleaning, plants and chatting are possibilities, not mandatory loops.
- Dialogue is YOUR job. If people talk, generate natural multi-turn `agent_chat.turns`; the browser will not invent fallback lines.
- Recent news is optional conversation context, not a forced topic. Use only supplied headline facts; never invent article details. People may ignore news entirely.
- Outfit is YOUR decision. If an on-duty character's `outfitDay` is not today's Iquique date, you may choose a plausible different outfit. Avoid changing clothes repeatedly during one day without a reason.
- Furniture/layout changes are rare life events, not a visibility gimmick. Do not repeatedly add side tables or lamps. Prefer moving/reusing/removing existing objects over buying duplicates.
- `layout_shuffle` is currently a safe coarse-layout capability; use it only when a believable reorganization is warranted. More free-form layout control will be added later.
- `object_add` lets you invent a small object from safe pixel rectangles when the world genuinely needs something not in the furniture catalog.
- Dog poop is a world fact. A character with high cleanliness may be bothered and the browser may clean it; use reactionCue/traits to decide whether they SAY something. Do not force a complaint.
- Long-term trait changes, marriage/divorce, colleague replacement and former visits are uncommon. They should emerge slowly.
- Return 1-4 coherent actions, normally ordinary life/work. It is okay to return subtle actions.
- Never narrate a change in `thought` unless a matching executable action is actually returned.
- Use server Iquique time/weather. Do not contradict it.
- Never touch business records, security data, scraper results, walls, the only doorway, or harbor geometry.
{retry_note}

Return ONLY JSON:
{{"thought":"Traditional Chinese, <=100 chars","actions":[...]}}
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
        "temperature": 1.15,
        "max_tokens": 1200,
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
    return text, model, context, news


def director_model_decision(world, evolution=False):
    from .town_ai_bp import _extract_json, _validate_actions

    text, model, context, news = _call_model(world, evolution)
    decision = _extract_json(text)
    actions = _validate_actions(decision.get("actions"))

    if not actions:
        text, model, context, news = _call_model(
            world,
            evolution,
            retry_note="Your previous answer had no executable action after validation. Return 1-3 valid catalog actions; choose natural behavior, not decoration for decoration's sake.",
        )
        decision = _extract_json(text)
        actions = _validate_actions(decision.get("actions"))

    thought = str(decision.get("thought") or "AI 觀察了 IQUIQUE 辦公室並安排了一小段自然生活。")[:180]
    return {
        "ok": True,
        "thought": thought,
        "actions": actions,
        "model": model,
        "context": context,
        "news_context_count": len(news),
        "director_tools": True,
    }
