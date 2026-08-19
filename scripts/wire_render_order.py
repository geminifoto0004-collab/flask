#!/usr/bin/env python3
"""Wire the vendored ORDER UI into Render safely and idempotently.

This changes only the Render repository's app.py. It never edits the sibling/local
production order_tracking source or tracking.db.
"""
from __future__ import annotations

import argparse
import py_compile
import subprocess
from pathlib import Path

MOUNT_MARKER = "# ========== Render ORDER（TiDB 唯讀） =========="

MOUNT_BLOCK = '''# ========== Render ORDER（TiDB 唯讀） ==========
# Render 直接掛載同一份 vendored order_tracking UI。
# 本機正式 ORDER 不會走到這裡；只有 Render（或明確開啟環境變數）才啟用。
import os as _os

def _env_true(name, default=False):
    raw = _os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}

_RENDER_ORDER_ENABLED = _env_true(
    'TRACKING_RENDER_ORDER_ENABLED',
    bool(_os.environ.get('RENDER') or _os.environ.get('RENDER_SERVICE_NAME'))
)

if _RENDER_ORDER_ENABLED:
    # ORDER on Render is always cloud + read-only. Official writes stay in local SQLite.
    app.config['TRACKING_CLOUD_MODE'] = True
    app.config['TRACKING_CLOUD_READ_ONLY'] = True
    app.config['TRACKING_TIDB_PROVIDER_ENABLED'] = True
    app.config['TRACKING_PUBLIC_SHARE_BACKGROUND_SYNC_ENABLED'] = False

    from order_tracking import init_app as init_order_tracking_app, register_cloud_db_connection_factory
    from services.order_tracking_render_provider import RenderOrderDataProvider

    # Raw ORDER cloud DB calls, when needed, use the same TiDB connection wrapper as Render.
    # Cloud mode never falls back to a Render-local SQLite file.
    register_cloud_db_connection_factory(app, get_db_connection)
    init_order_tracking_app(app, data_provider=RenderOrderDataProvider())
    print('✅ Render ORDER mounted at /tracking (TiDB read-only)')

    @app.before_request
    def _render_order_parent_login_gate():
        # ORDER reuses the existing Render login/session. Do not maintain a second cloud password store.
        if request.path.startswith('/tracking'):
            if not session.get('logged_in') or not session.get('user_id'):
                target = request.full_path if request.query_string else request.path
                if not target.startswith('/') or target.startswith('//'):
                    target = '/tracking'
                session['post_login_next'] = target
                return redirect(url_for('login'))
        return None

'''


def patch_app(path: Path) -> bool:
    text = path.read_text('utf-8')
    changed = False

    if MOUNT_MARKER not in text:
        anchor = "app.register_blueprint(email_proxy_bp)\n\n# ========== 自動初始化資料庫 =========="
        if anchor not in text:
            raise RuntimeError('app.py mount anchor not found; refusing unsafe patch')
        text = text.replace(
            anchor,
            "app.register_blueprint(email_proxy_bp)\n\n" + MOUNT_BLOCK + "# ========== 自動初始化資料庫 ==========",
            1,
        )
        changed = True

    login_anchor = '''def login():\n    """統一登入入口"""\n    if request.method == 'POST':\n'''
    if "session['post_login_next'] = next_url" not in text:
        replacement = '''def login():\n    """統一登入入口"""\n    if request.method == 'GET':\n        next_url = (request.args.get('next') or '').strip()\n        if next_url.startswith('/') and not next_url.startswith('//'):\n            session['post_login_next'] = next_url\n\n    if request.method == 'POST':\n'''
        if login_anchor not in text:
            raise RuntimeError('app.py login anchor not found; refusing unsafe patch')
        text = text.replace(login_anchor, replacement, 1)
        changed = True

    old_admin = "            return redirect(url_for('admin_dashboard'))\n        else:\n            print(\"Super Admin登入失敗，嘗試普通用戶驗證\")"
    if old_admin in text:
        text = text.replace(
            old_admin,
            "            return redirect(session.pop('post_login_next', None) or url_for('admin_dashboard'))\n        else:\n            print(\"Super Admin登入失敗，嘗試普通用戶驗證\")",
            1,
        )
        changed = True

    old_regular = '''            # 根據角色重定向到不同頁面\n            if result['role'] == 'admin':\n                return redirect(url_for('admin_dashboard'))\n            else:\n                return redirect(url_for('user_auth.user_portal'))\n'''
    if old_regular in text:
        new_regular = '''            # 如果是從 ORDER 進來，登入後回到 ORDER；否則維持原本角色首頁。\n            post_login_next = session.pop('post_login_next', None)\n            if post_login_next:\n                return redirect(post_login_next)\n            if result['role'] == 'admin':\n                return redirect(url_for('admin_dashboard'))\n            else:\n                return redirect(url_for('user_auth.user_portal'))\n'''
        text = text.replace(old_regular, new_regular, 1)
        changed = True

    if "def order_entry():" not in text:
        anchor = "\n\n@app.route('/logout')\ndef logout():\n"
        if anchor not in text:
            raise RuntimeError('app.py logout anchor not found; refusing unsafe patch')
        entry = '''\n\n@app.route('/order')\ndef order_entry():\n    """Stable entry point for the Render-hosted read-only ORDER UI."""\n    if not _RENDER_ORDER_ENABLED:\n        return jsonify({'success': False, 'error': 'Render ORDER is disabled'}), 404\n    if not session.get('logged_in') or not session.get('user_id'):\n        session['post_login_next'] = '/order'\n        return redirect(url_for('login'))\n    return redirect('/tracking')\n\n\n@app.route('/logout')\ndef logout():\n'''
        text = text.replace(anchor, entry, 1)
        changed = True

    if changed:
        path.write_text(text, 'utf-8')
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--push', action='store_true')
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    app_py = repo / 'app.py'
    provider = repo / 'services' / 'order_tracking_render_provider.py'
    order_init = repo / 'order_tracking' / '__init__.py'

    for required in (app_py, provider, order_init):
        if not required.is_file():
            raise SystemExit(f'missing required file: {required}')

    changed = patch_app(app_py)
    py_compile.compile(str(app_py), doraise=True)
    py_compile.compile(str(provider), doraise=True)

    if not changed:
        print('Render ORDER wiring already present')
        return 0

    print('Render ORDER wiring applied safely')
    subprocess.run(['git', 'add', 'app.py'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'Mount read-only ORDER UI on Render'], cwd=repo, check=True)
    if args.push:
        subprocess.run(['git', 'push'], cwd=repo, check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
