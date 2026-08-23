"""Standalone Render entry point for CUSTOMS AGENT TOWN.

Start command for the dedicated Render service:
    gunicorn town_app:app

This process intentionally loads only the AI-town stack. It does not mount the
main authorization app, ORDER, crawler jobs, B2 helpers, container services or
other production blueprints.
"""

import os

# blueprints/__init__.py checks this before importing any unrelated main-service
# modules. It must be set before the first blueprints.* import below.
os.environ["TOWN_STANDALONE_SERVICE"] = "1"

from flask import Flask, jsonify, redirect

from blueprints import town_ai_bp as _town_ai_module
from blueprints.town_ai_action_runtime import install_latest_action_runtime
from blueprints.town_ai_visibility_runtime import install_visibility_runtime
from blueprints.town_ai_history_runtime import install_history_runtime
from blueprints.town_ai_profile_runtime import install_profile_runtime
from blueprints.town_ai_bilingual_runtime import install_bilingual_runtime
from blueprints.town_world_map_runtime import install_world_map_runtime
from blueprints.town_ai_sea_runtime import install_sea_runtime
from blueprints.town_ai_shift_runtime import install_shift_runtime
from blueprints.town_world_object_runtime import install_world_object_runtime
from blueprints.town_generic_entity_runtime import install_generic_entity_runtime
from blueprints.town_relationship_runtime import install_relationship_runtime
from blueprints.town_officer_scene_runtime import install_officer_scene_runtime
from blueprints.town_generic_scene_runtime import install_generic_scene_runtime
from blueprints.town_world_tidb_runtime import install_tidb_world_runtime
from blueprints.town_dialogue_tidb_runtime import install_tidb_dialogue_runtime

# Import side effect: allow longer composed tool-call sequences before admin and
# language runtimes bind the action parser.
from blueprints import town_ai_toolcall_limit_patch as _town_ai_toolcall_limit_patch  # noqa: F401

from blueprints.town_admin_runtime import install_town_admin_runtime
from blueprints.town_admin_scene_runtime import install_admin_scene_runtime
from blueprints.town_officer_scene_admin_patch import install_officer_scene_admin_patch
from blueprints.town_ai_grounded_director import grounded_model_decision

from blueprints import town_page_bp as _town_page_module
from blueprints.town_latest_page_runtime import latest_town_html
from blueprints.town_render_visibility_patch import patch_render_visibility
from blueprints.town_render_action_patch import patch_render_actions
from blueprints.town_render_depth_patch import patch_render_depth
from blueprints.town_render_fishing_patch import patch_render_fishing
from blueprints.town_render_chat_timing_patch import patch_render_chat_timing
from blueprints.town_render_profile_patch import patch_render_profiles
from blueprints.town_render_dialogue_panel_patch import patch_render_dialogue_panel
from blueprints.town_render_dialogue_fix_patch import patch_render_dialogue_fix
from blueprints.town_render_panel_alignment_patch import patch_render_panel_alignment
from blueprints.town_render_shared_dialogue_patch import patch_render_shared_dialogue
from blueprints.town_render_admin_world_patch import patch_render_admin_world
from blueprints.town_render_world_object_patch import patch_render_world_objects
from blueprints.town_render_generic_entity_patch import patch_render_generic_entities
from blueprints.town_render_admin_action_feedback_patch import patch_render_admin_action_feedback


app = Flask(__name__)
app.secret_key = (
    os.environ.get("TOWN_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or "customs-town-local-development-only"
)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_NAME")),
)


# Keep the currently stable town runtime chain isolated from the main service.
# Experimental universal-action modules stay in the repository but are not
# enabled here until they have been tested independently.
install_latest_action_runtime()
install_visibility_runtime()
install_history_runtime()
install_profile_runtime()
install_bilingual_runtime()
install_world_map_runtime()
install_sea_runtime()
install_shift_runtime()
install_world_object_runtime()
install_generic_entity_runtime()
install_relationship_runtime()
install_officer_scene_runtime()
install_generic_scene_runtime()
install_tidb_world_runtime()
install_tidb_dialogue_runtime()
install_admin_scene_runtime()
install_officer_scene_admin_patch()
install_town_admin_runtime()

# /api/town/think uses the grounded director after all validation/persistence
# wrappers are installed.
_town_ai_module._model_decision = grounded_model_decision
town_ai_bp = _town_ai_module.town_ai_bp

# Build the same known-good browser composition that previously lived on the
# main Render service.
town_page_bp = _town_page_module.town_page_bp
_town_page_module._patched_town_html = lambda: patch_render_admin_action_feedback(
    patch_render_generic_entities(
        patch_render_world_objects(
            patch_render_admin_world(
                patch_render_shared_dialogue(
                    patch_render_panel_alignment(
                        patch_render_dialogue_fix(
                            patch_render_dialogue_panel(
                                patch_render_profiles(
                                    patch_render_chat_timing(
                                        patch_render_fishing(
                                            patch_render_depth(
                                                patch_render_actions(
                                                    patch_render_visibility(latest_town_html())
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
    )
)

app.register_blueprint(town_ai_bp)
app.register_blueprint(town_page_bp)


@app.get("/")
def town_root():
    return redirect("/customs-town")


@app.get("/health")
def town_health():
    return jsonify(
        {
            "ok": True,
            "service": "customs-agent-town",
            "town_page": "/customs-town",
            "deepseek_configured": bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip()),
            "admin_configured": bool((os.environ.get("TOWN_ADMIN_PASSWORD") or "").strip()),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
