"""Small admin integration for generic existing-officer scenes."""

from . import town_admin_runtime as _admin


def install_officer_scene_admin_patch():
    previous_metadata = _admin._scene_metadata
    previous_slim_world = _admin._slim_world

    def scene_metadata(raw_actions):
        for action in raw_actions or []:
            if not isinstance(action, dict) or str(action.get("type") or "") != "officer_scene":
                continue
            return {
                "intent_summary": str(action.get("intentSummary") or "").strip()[:140],
                "must_keep": [],
                "creative_freedom": [],
                "director_note": str(action.get("directorNote") or "").strip()[:180],
            }
        return previous_metadata(raw_actions)

    def slim_world(world):
        result = previous_slim_world(world)
        if isinstance(world, dict):
            result["dogPoops"] = world.get("dogPoops", 0)
        return result

    _admin._scene_metadata = scene_metadata
    _admin._slim_world = slim_world
