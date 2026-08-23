"""Small Render-proxy thumbnail upload for ORDER customer sharing.

The thumbnail is written to the same B2 backend recorded for its WEB image. No HEAD
preflight is used, so bulk publishing does not consume Backblaze Class-B transactions.
"""
from __future__ import annotations

import hashlib

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from services.order_cloud_asset_service import _validate_sha256
from services.order_cloud_direct_b2 import _thumb_object_key
from services.order_cloud_multi_b2 import put_to_backend, storage_backend_for_sha

MAX_THUMB_BYTES = 3 * 1024 * 1024


@b2_test_bp.route('/api/order-cloud/assets/upload-thumb', methods=['POST'])
def order_cloud_asset_upload_thumb():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        asset_sha256 = _validate_sha256(request.form.get('asset_sha256'))
        expected_sha = str(request.form.get('sha256') or '').strip().lower()
        if expected_sha:
            expected_sha = _validate_sha256(expected_sha)

        image = request.files.get('file')
        if image is None:
            return jsonify({'ok': False, 'error': "multipart field 'file' is required"}), 400
        data = image.read(MAX_THUMB_BYTES + 1)
        if not data:
            return jsonify({'ok': False, 'error': 'thumbnail is empty'}), 400
        if len(data) > MAX_THUMB_BYTES:
            return jsonify({'ok': False, 'error': 'thumbnail exceeds 3 MB limit'}), 413
        if str(image.mimetype or '').strip().lower() != 'image/jpeg':
            return jsonify({'ok': False, 'error': 'thumbnail must be JPEG'}), 400

        actual_sha = hashlib.sha256(data).hexdigest()
        if expected_sha and actual_sha != expected_sha:
            return jsonify({'ok': False, 'error': 'thumbnail sha256 does not match uploaded bytes'}), 400

        backend = storage_backend_for_sha(asset_sha256)
        object_key = _thumb_object_key(asset_sha256)
        put_to_backend(
            backend,
            object_key,
            data,
            'image/jpeg',
            metadata={'sha256': actual_sha, 'asset-sha256': asset_sha256},
            cache_control='private, max-age=2592000',
        )

        return jsonify({'ok': True, 'result': {
            'asset_sha256': asset_sha256,
            'sha256': actual_sha,
            'object_key': object_key,
            'file_size': len(data),
            'uploaded_to_b2': True,
            'deduplicated': False,
            'upload_mode': 'render_proxy_thumb_nohead_multi_b2',
            'storage_backend': backend,
            'b2_head_calls': 0,
        }})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


# Register additive protected/public extensions while this module is imported by
# services.__init__.py. The direct multi-B2 share-page hook is registered before the
# legacy public-share hook imported later by services.__init__.py.
from . import order_b2_diagnostic as _order_b2_diagnostic  # noqa: E402,F401
from . import order_b2_classb_probe as _order_b2_classb_probe  # noqa: E402,F401
from . import order_cloud_multi_b2 as _order_cloud_multi_b2  # noqa: E402,F401
from . import order_cloud_multi_b2_public as _order_cloud_multi_b2_public  # noqa: E402,F401
from . import order_public_share_multi_b2_page as _order_public_share_multi_b2_page  # noqa: E402,F401
from . import order_cloud_nohead_upload as _order_cloud_nohead_upload  # noqa: E402,F401
from . import order_cloud_direct_multi_b2 as _order_cloud_direct_multi_b2  # noqa: E402,F401
from . import order_cloud_sigv4_patch as _order_cloud_sigv4_patch  # noqa: E402,F401
from . import order_cloud_direct_reuse_health as _order_cloud_direct_reuse_health  # noqa: E402,F401
from . import order_cloud_backend_health as _order_cloud_backend_health  # noqa: E402,F401
from . import order_share_live_refresh as _order_share_live_refresh  # noqa: E402,F401
