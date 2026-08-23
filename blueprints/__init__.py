# ========== blueprints/__init__.py ==========
"""
Blueprints package bootstrap.

The main Render keeps its existing lightweight shared blueprints and does not
load AI-town runtimes. A future dedicated town_app.py sets
TOWN_STANDALONE_SERVICE=1 before importing this package, which skips unrelated
main-service blueprints entirely.
"""

import os as _os
import sys as _sys

_TOWN_STANDALONE = str(_os.environ.get('TOWN_STANDALONE_SERVICE') or '').strip().lower() in {
    '1', 'true', 'yes', 'on', 'y'
}

if not _TOWN_STANDALONE:
    # Main Render must never run the full schema bootstrap inside a user's first
    # HTTP request. app.py imports init_database before importing this package,
    # so replace only app.py's bound reference while the app module is importing.
    if _os.environ.get('RENDER') or _os.environ.get('RENDER_SERVICE_NAME'):
        _app_module = _sys.modules.get('app')
        if _app_module is not None and hasattr(_app_module, 'init_database'):
            def _skip_render_request_database_init():
                return None
            _app_module.init_database = _skip_render_request_database_init
            print('✅ Render request-time database bootstrap disabled')

    from .user_auth_bp import user_auth_bp
    from .b2_test_bp import b2_test_bp

    # AI town is intentionally NOT imported on the main Render service.
    print('✅ AI town disabled on main Render service')
    __all__ = ['user_auth_bp', 'b2_test_bp']
else:
    # Dedicated AI-town service: importing blueprints.* must not drag in ORDER,
    # crawler/B2 helpers, auth pages or other main-service modules.
    print('✅ Standalone AI town blueprint mode')
    __all__ = []
