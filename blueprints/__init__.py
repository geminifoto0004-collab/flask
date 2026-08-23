# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from . import town_ai_bp as _town_ai_module
from .town_ai_action_runtime import install_latest_action_runtime
from .town_ai_visibility_runtime import install_visibility_runtime
from .town_ai_history_runtime import install_history_runtime
from .town_ai_profile_runtime import install_profile_runtime
from .town_ai_bilingual_runtime import install_bilingual_runtime
from .town_world_map_runtime import install_world_map_runtime
from .town_ai_sea_runtime import install_sea_runtime
from .town_ai_shift_runtime import install_shift_runtime
from .town_world_object_runtime import install_world_object_runtime
from .town_world_tidb_runtime import install_tidb_world_runtime
from .town_dialogue_tidb_runtime import install_tidb_dialogue_runtime
from .town_admin_runtime import install_town_admin_runtime
from .town_ai_grounded_director import grounded_model_decision
from . import town_page_bp as _town_page_module
from .town_latest_page_runtime import latest_town_html
from .town_render_visibility_patch import patch_render_visibility
from .town_render_action_patch import patch_render_actions
from .town_render_depth_patch import patch_render_depth
from .town_render_fishing_patch import patch_render_fishing
from .town_render_chat_timing_patch import patch_render_chat_timing
from .town_render_profile_patch import patch_render_profiles
from .town_render_dialogue_panel_patch import patch_render_dialogue_panel
from .town_render_dialogue_fix_patch import patch_render_dialogue_fix
from .town_render_panel_alignment_patch import patch_render_panel_alignment
from .town_render_shared_dialogue_patch import patch_render_shared_dialogue
from .town_render_admin_world_patch import patch_render_admin_world
from .town_render_world_object_patch import patch_render_world_objects

# Install validation/persistence for the current browser capabilities before the
# blueprint is registered on the Flask app. The server map is authoritative,
# while browser physics remains the final collision/safety boundary.
install_latest_action_runtime()
install_visibility_runtime()
install_history_runtime()
install_profile_runtime()
install_bilingual_runtime()
install_world_map_runtime()
install_sea_runtime()
install_shift_runtime()
install_world_object_runtime()
install_tidb_world_runtime()
install_tidb_dialogue_runtime()
install_town_admin_runtime()

# Render /api/town/think uses the grounded AI world director. User-visible
# narration is rebuilt from validated executable actions, so the log cannot
# claim a physical event that was never actually sent to the browser.
_town_ai_module._model_decision = grounded_model_decision
town_ai_bp = _town_ai_module.town_ai_bp

# Keep the known-good game composition. Generic objects are a transparent safe
# overlay; the existing game animation loop remains untouched.
town_page_bp = _town_page_module.town_page_bp
_town_page_module._patched_town_html = lambda: patch_render_world_objects(patch_render_admin_world(patch_render_shared_dialogue(patch_render_panel_alignment(patch_render_dialogue_fix(patch_render_dialogue_panel(patch_render_profiles(patch_render_chat_timing(patch_render_fishing(patch_render_depth(patch_render_actions(patch_render_visibility(latest_town_html()))))))))))))

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']
