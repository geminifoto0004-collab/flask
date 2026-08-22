# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from . import town_ai_bp as _town_ai_module
from .town_ai_director_runtime import director_model_decision
from . import town_page_bp as _town_page_module
from .town_world_runtime_patch import patch_town_world

# During validation, /api/town/think uses the strict director runtime. DeepSeek
# receives the executable function catalog and must return actions the front end
# can really execute instead of narration-only ideas.
_town_ai_module._model_decision = director_model_decision
town_ai_bp = _town_ai_module.town_ai_bp

# Keep the existing page blueprint, but wrap its HTML renderer with the newest
# autonomous-world layer so the large base template does not need to be copied.
town_page_bp = _town_page_module.town_page_bp
_town_page_base_renderer = _town_page_module._patched_town_html


def _render_town_with_world_patch():
    html = patch_town_world(_town_page_base_renderer())
    # Manual validation phase: do not let the page call DeepSeek by itself yet.
    html = html.replace(
        "let aiAuto=localStorage.getItem('customs-town-ai-auto')!=='0';",
        "let aiAuto=false;",
    )
    # Visual details requested for the IQUIQUE office.
    html = html.replace(
        "txt('ADUANA · IQUIQUE',320,41,'#efe5c7',7,'center');",
        "txt('IQUIQUE',320,44,'#efe5c7',12,'center');",
    )
    html = html.replace(
        "txt('IQUIQUE '+String(c.hour).padStart(2,'0')+':'+String(c.minute).padStart(2,'0'),74,390,'#d5e6e8',6,'left');\n    if(Number.isFinite(Number(townWeather.temperature)))txt(Math.round(Number(townWeather.temperature))+'°C',156,390,'#d5e6e8',6,'left');",
        "",
    )
    return html


_town_page_module._patched_town_html = _render_town_with_world_patch

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']
