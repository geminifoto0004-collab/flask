"""Dialogue-focused DeepSeek runtime for CUSTOMS AGENT TOWN.

Keeps native tool calling, but gives the model stricter language, topic-memory and
life-profile rules so conversations feel like persistent coworkers in Iquique.
"""

import json
import os
import time

import requests

from .town_ai_director_runtime import DIRECTOR_TOOLS, _recent_news, _tool_calls_to_actions


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
    dialogue_policy = world.get("dialoguePolicy") if isinstance(world, dict) else None
    profiles = world.get("characterProfiles") if isinstance(world, dict) else None
    recent_dialogue = world.get("recentDialogue") if isinstance(world, dict) else None

    system_prompt = f"""You are the autonomous WORLD DIRECTOR of a persistent pixel-art customs office in IQUIQUE, Chile.
{mode}

You DIRECT THE WORLD ONLY by calling the provided tools. Do not narrate imaginary physical actions that have no tool call.

CHARACTERS AND WORLD:
- MIA, ANA and LIA are literal IDs. Never translate or respell them.
- Ship/customs work is the main story and active ship work has priority.
- Read character traits, mood, energy, relationships, recent stimuli, dogs, plants, current actions, recentDirectorActions, characterProfiles and recentDialogue.
- Avoid repeating the same safe action if recentDirectorActions shows it happened recently.
- Manual-test diversity seed: {entropy}. Use it only to avoid repetitive choices; world state matters more than randomness.

PERSISTENT LIFE PROFILES:
- Each officer may have persistent life facts: age, gender, zodiac, marital status, children, likes, dislikes and interests.
- If a profile is still empty, you may use agent_profile to create a believable profile. Once established, do NOT randomly overwrite it every tick.
- Profiles are conversation context, NOT deterministic stereotypes. A zodiac sign or gender never forces behavior.
- Use profiles together with current mood, traits, relationships, recent events and time of day to decide whether they talk and what feels natural to mention.
- Examples of possible sources of conversation include family logistics, children, partner, hobbies, food, music, football, pets, weekend plans, shopping, fishing, plants, coworkers, work annoyances, memories, local life and occasional news. These are possibilities, not a fixed menu.
- Do not mechanically mention profile facts. Real coworkers often change subject, tease each other, say one sentence, or stay quiet.

DIALOGUE MEMORY AND VARIETY — CRITICAL:
- Read recentDialogue before writing a new conversation.
- Do NOT repeat the same headline, rain/disaster topic, port-delay topic, aid story, weather observation or conversational theme if it was already discussed recently.
- If a subject was just discussed, choose a genuinely different topic or choose a non-dialogue action instead.
- News is only an occasional source of conversation, never the default. The presence of recent_news does NOT mean anyone must discuss it.
- Prefer personal/contextual continuity over repeatedly summarizing public news.

DIALOGUE QUALITY — IMPORTANT:
- All character dialogue must sound like natural everyday CHILEAN SPANISH between coworkers in Iquique, not translated Chinese/English and not a television news script.
- Prefer short, conversational sentences with normal Chilean/neutral vocabulary. Mild local expressions are fine, but do not overuse slang.
- Each person can doubt, joke, disagree, ignore the topic, change subject, or say very little.
- If a supplied headline is mentioned, use ONLY facts literally present in that headline. Never invent ships, rescue cargo, schedules, port closures, causes, official plans, arrival times, casualty details, or article content that was not supplied.
- If the headline itself is ambiguous, hedge naturally: "parece que...", "dicen que...", "vi un titular sobre...", "no sé bien los detalles".
- Never claim "lo dijeron por la radio" unless the world state actually supports a radio-related action/context.
- Avoid awkward literal constructions such as "ni piernas quietas tendré" or unnatural noun phrases such as "cargueros de socorro".
- If agent_chat is used, every turn must belong to one of the two participants and the two participants must be different people.
- If agent_say is used, write the exact natural sentence the character says.

TOOL USE:
- Do not fall into a coffee/files/lookSea loop. Those are only some possibilities.
- You may combine 1-3 coherent tools in one manual test.
- Dialogue requires agent_chat or agent_say; never fake dialogue through prose.
- Outfit changes normally happen once per Iquique day per person.
- Furniture/layout/object changes are occasional, not decoration spam.
- Long-term trait/life/personnel changes are rare and should have a believable reason.
- Never invent unsupported actions. If a desired action has no tool, choose another real capability.

Current characterProfiles: {json.dumps(profiles, ensure_ascii=False)}
Recent dialogue memory: {json.dumps(recent_dialogue, ensure_ascii=False)}
Browser-supplied dialogue policy, if any: {json.dumps(dialogue_policy, ensure_ascii=False)}
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
        "temperature": 1.18,
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
    text = json.dumps({"thought": "", "actions": actions}, ensure_ascii=False)
    return text, model, context, news
