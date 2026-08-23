"""Public ORDER media routing for assets stored across multiple B2 backends.

This hook is registered before the legacy public-share hook. It intercepts only media
URLs, authorizes them through the existing share-token logic, then generates a signed
GET URL from the backend recorded in TiDB. No B2 HEAD request is performed.
"""
from flask import redirect, request

from blueprints.b2_test_bp import b2_test_bp
from services.order_cloud_multi_b2 import presigned_get_for_asset


@b2_test_bp.before_app_request
def _multi_b2_public_media_interceptor():
    path = request.path or ''
    if not path.startswith('/share/') or request.method != 'GET':
        return None
    parts = path.strip('/').split('/')
    if len(parts) != 4 or parts[2] not in ('asset', 'thumb'):
        return None

    # Imported lazily because order_public_share_fast is registered later during app
    # startup. Reuse its token/customer authorization instead of duplicating policy.
    from services.order_public_share_fast import _asset_for_share

    token = parts[1]
    _share, asset, error = _asset_for_share(token, parts[3])
    if error:
        return error

    if parts[2] == 'thumb':
        sha = str(asset.get('sha256') or '')
        key = f'order-cloud/thumbs/{sha[:2]}/{sha}.jpg'
        url = presigned_get_for_asset(asset, seconds=3600, object_key=key)
        resp = redirect(url, code=302)
        resp.headers['Cache-Control'] = 'private, max-age=1800'
        return resp

    url = presigned_get_for_asset(asset, seconds=900)
    resp = redirect(url, code=302)
    resp.headers['Cache-Control'] = 'private, max-age=300'
    return resp
