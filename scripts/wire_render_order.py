#!/usr/bin/env python3
"""Wire the vendored ORDER UI into Render safely and idempotently.

This changes only the Render repository's app.py. It never edits the sibling/local
production order_tracking source or tracking.db.

Render ORDER intentionally uses the native ORDER login screen/session semantics,
backed by the isolated TiDB cloud_order_users mirror. It does not use the parent
Flask authorization-system login.
"""
from __future__ import annotations

import argparse
import py_compile
import subprocess
from pathlib import Path

MOUNT_MARKER = "# ========== Render ORDER（TiDB 唯讀） =========="
NEXT_MARKER = "# ========== 自動初始化資料庫 =========="

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

    from blueprints.order_tracking_cloud_auth_bp import order_tracking_cloud_auth_bp
    from order_tracking import init_app as init_order_tracking_app, register_cloud_db_connection_factory
    from services.order_tracking_render_provider import RenderOrderDataProvider
    from services.order_tracking_cloud_auth import authenticate_order_user

    # Small protected endpoint used only by the local ORDER text-sync process to keep
    # the native ORDER username/password-hash/role mirror current.
    app.register_blueprint(order_tracking_cloud_auth_bp)

    # Raw ORDER cloud DB calls, when needed, use the same TiDB connection wrapper as Render.
    # Cloud mode never falls back to a Render-local SQLite file.
    register_cloud_db_connection_factory(app, get_db_connection)
    init_order_tracking_app(app, data_provider=RenderOrderDataProvider())
    print('✅ Render ORDER mounted at /tracking (TiDB read-only, native ORDER login)')

    @app.before_request
    def _render_order_native_login_gate():
        """Keep ORDER authentication separate from the parent Flask authorization login."""
        path = request.path or ''
        if not path.startswith('/tracking'):
            return None
        if path.startswith('/tracking/static/'):
            return None

        # Intercept native ORDER login so it authenticates against cloud_order_users,
        # not the parent Flask app's unrelated users table.
        if path.rstrip('/') == '/tracking/login':
            if request.method == 'GET':
                if session.get('order_tracking_authenticated'):
                    return redirect('/tracking')
                return render_template('tracking/login.html')

            data = request.get_json(silent=True) if request.is_json else request.form
            data = data or {}
            username = str(data.get('username') or '').strip()
            password = str(data.get('password') or '')

            if not username:
                error_msg = '請輸入用戶名'
                if request.is_json:
                    return jsonify({'success': False, 'error': error_msg, 'code': 'MISSING_USERNAME'}), 400
                return render_template('tracking/login.html', error=error_msg, username=username)
            if not password:
                error_msg = '請輸入密碼'
                if request.is_json:
                    return jsonify({'success': False, 'error': error_msg, 'code': 'MISSING_PASSWORD'}), 400
                return render_template('tracking/login.html', error=error_msg, username=username)

            user, auth_state = authenticate_order_user(username, password)
            state_errors = {
                'pending': ('您的帳號正在等待主管審核，請稍後再試', 'PENDING_APPROVAL', 403),
                'rejected': ('您的註冊申請已被拒絕，請聯繫主管', 'REJECTED', 403),
                'suspended': ('您的帳號已被停權，請聯繫主管', 'SUSPENDED', 403),
                'needs_password_reset': ('請先在公司 ORDER 完成密碼重置，再登入雲端 ORDER', 'NEEDS_PASSWORD_RESET', 403),
            }
            if not user:
                error_msg, code, status = state_errors.get(
                    auth_state,
                    ('用戶名或密碼錯誤', 'INVALID_CREDENTIALS', 401),
                )
                if request.is_json:
                    return jsonify({'success': False, 'error': error_msg, 'code': code}), status
                return render_template('tracking/login.html', error=error_msg, username=username)

            # Same session keys used by the local ORDER application. Parent Flask
            # login stays separate because its protected pages require logged_in=True.
            session['order_tracking_authenticated'] = True
            session['user_id'] = user.get('id')
            session['username'] = user.get('username')
            session['display_name'] = user.get('display_name')
            session['role'] = user.get('role') or 'viewer'

            if request.is_json:
                try:
                    import jwt as _jwt
                    from order_tracking.config import JWT_SECRET_KEY as _jwt_secret, JWT_EXPIRATION_DELTA as _jwt_exp
                    from datetime import datetime as _dt
                    token = _jwt.encode({
                        'user_id': user.get('id'),
                        'username': user.get('username'),
                        'role': user.get('role') or 'viewer',
                        'exp': _dt.utcnow().timestamp() + _jwt_exp,
                    }, _jwt_secret, algorithm='HS256')
                except Exception:
                    token = None
                return jsonify({
                    'success': True,
                    'token': token,
                    'user': {
                        'id': user.get('id'),
                        'username': user.get('username'),
                        'display_name': user.get('display_name'),
                        'role': user.get('role') or 'viewer',
                    },
                })
            return redirect('/tracking')

        if not session.get('order_tracking_authenticated'):
            return redirect('/tracking/login')
        return None

'''


def _replace_mount_block(text: str) -> tuple[str, bool]:
    start = text.find(MOUNT_MARKER)
    end = text.find(NEXT_MARKER)
    if start < 0:
        anchor = "app.register_blueprint(email_proxy_bp)\n\n" + NEXT_MARKER
        if anchor not in text:
            raise RuntimeError('app.py mount anchor not found; refusing unsafe patch')
        return text.replace(
            anchor,
            "app.register_blueprint(email_proxy_bp)\n\n" + MOUNT_BLOCK + NEXT_MARKER,
            1,
        ), True
    if end < 0 or end <= start:
        raise RuntimeError('app.py ORDER block boundary not found; refusing unsafe patch')
    current = text[start:end]
    if current == MOUNT_BLOCK:
        return text, False
    return text[:start] + MOUNT_BLOCK + text[end:], True


def patch_app(path: Path) -> bool:
    text = path.read_text('utf-8')
    changed = False

    text, block_changed = _replace_mount_block(text)
    changed = changed or block_changed

    # /order is a stable shortcut into native ORDER auth, never parent /login.
    old_entry = '''@app.route('/order')\ndef order_entry():\n    """Stable entry point for the Render-hosted read-only ORDER UI."""\n    if not _RENDER_ORDER_ENABLED:\n        return jsonify({'success': False, 'error': 'Render ORDER is disabled'}), 404\n    if not session.get('logged_in') or not session.get('user_id'):\n        session['post_login_next'] = '/order'\n        return redirect(url_for('login'))\n    return redirect('/tracking')\n'''
    new_entry = '''@app.route('/order')\ndef order_entry():\n    """Stable entry point for the Render-hosted read-only ORDER UI."""\n    if not _RENDER_ORDER_ENABLED:\n        return jsonify({'success': False, 'error': 'Render ORDER is disabled'}), 404\n    return redirect('/tracking')\n'''
    if old_entry in text:
        text = text.replace(old_entry, new_entry, 1)
        changed = True
    elif "def order_entry():" in text and new_entry not in text:
        raise RuntimeError('existing /order route has an unexpected layout; refusing unsafe patch')

    # Never log plaintext passwords or configured admin passwords.
    secret_log_lines = [
        "        print(f\"登入嘗試: 郵箱='{email}', 密碼='{password}'\")\n",
        "        print(f\"Super Admin配置: 郵箱='{admin_config.SUPER_ADMIN_EMAIL}', 密碼='{admin_config.SUPER_ADMIN_PASSWORD}'\")\n",
    ]
    for line in secret_log_lines:
        if line in text:
            text = text.replace(line, '')
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
    auth_service = repo / 'services' / 'order_tracking_cloud_auth.py'
    auth_bp = repo / 'blueprints' / 'order_tracking_cloud_auth_bp.py'
    order_init = repo / 'order_tracking' / '__init__.py'

    for required in (app_py, provider, auth_service, auth_bp, order_init):
        if not required.is_file():
            raise SystemExit(f'missing required file: {required}')

    changed = patch_app(app_py)
    for target in (app_py, provider, auth_service, auth_bp):
        py_compile.compile(str(target), doraise=True)

    if not changed:
        print('Render ORDER native-login wiring already present')
        return 0

    print('Render ORDER native-login wiring applied safely')
    subprocess.run(['git', 'add', 'app.py'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'Use native ORDER login on Render'], cwd=repo, check=True)
    if args.push:
        subprocess.run(['git', 'push'], cwd=repo, check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
