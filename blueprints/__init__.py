# ========== blueprints/__init__.py ==========
"""
Blueprints 包初始化
"""

from .user_auth_bp import user_auth_bp
from .b2_test_bp import b2_test_bp
from .town_ai_bp import town_ai_bp
from .town_page_bp import town_page_bp

# b2_test_bp has no url_prefix and is already registered by app.py.
# Nest the town blueprints under it so both the browser page and /api/town/*
# become available without changing the large app.py entry point.
b2_test_bp.register_blueprint(town_ai_bp)
b2_test_bp.register_blueprint(town_page_bp)

__all__ = ['user_auth_bp', 'town_ai_bp', 'town_page_bp']