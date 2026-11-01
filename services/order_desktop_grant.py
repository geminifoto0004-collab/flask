"""A cloud admin may pair a desktop for read-only link refresh, once per device."""
from flask import current_app, request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import secrets

SALT = 'order-desktop-read-share-links-v1'


def issue():
    return URLSafeTimedSerializer(current_app.secret_key, salt=SALT).dumps(
        {'scope': 'share-links:read', 'device': secrets.token_hex(16)})


def authorized():
    token = str(request.headers.get('X-Order-Desktop-Grant') or '')
    if not token or len(token) > 2048:
        return False
    try:
        value = URLSafeTimedSerializer(current_app.secret_key, salt=SALT).loads(token, max_age=365*86400)
    except (BadSignature, SignatureExpired):
        return False
    return isinstance(value, dict) and value.get('scope') == 'share-links:read' and bool(value.get('device'))


def install(blueprint):
    from flask import jsonify
    from blueprints.b2_test_bp import _order_cloud_auth_source
    @blueprint.route('/api/order-cloud/desktop/share-links', methods=['GET'])
    def desktop_share_links():
        _, error = _order_cloud_auth_source()
        if error: return error
        if not authorized():
            return jsonify({'ok': False, 'error': 'desktop_pairing_required'}), 401
        from services.order_share_admin_runtime_patch import _cloud_admin_share_rows
        rows = [{'id': row['id'], 'share_url': row['share_url']}
                for row in _cloud_admin_share_rows(active_only=True) if row.get('share_url')]
        response = jsonify({'ok': True, 'result': {'shares': rows}})
        response.headers['Cache-Control'] = 'no-store, private'
        return response
