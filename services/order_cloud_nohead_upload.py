"""Protected ORDER image upload with multi-B2 failover and no Class-B HEAD calls."""
from __future__ import annotations

import hashlib

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from services.order_cloud_asset_service import MAX_IMAGE_BYTES, _object_key, _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import put_with_failover, upsert_asset_metadata_multi


@b2_test_bp.route('/api/order-cloud/assets/upload-nohead', methods=['POST'])
def order_cloud_asset_upload_nohead():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        order_number = str(request.form.get('order_number') or '').strip()
        workflow_key = str(request.form.get('workflow_key') or '').strip() or None
        expected_sha = _validate_sha256(request.form.get('sha256'))
        if not order_number:
            return jsonify({'ok': False, 'error': 'order_number is required'}), 400

        image = request.files.get('file')
        if image is None:
            return jsonify({'ok': False, 'error': "multipart field 'file' is required"}), 400
        content_type = _validate_content_type(image.mimetype)
        data = image.read(MAX_IMAGE_BYTES + 1)
        if not data:
            return jsonify({'ok': False, 'error': 'image is empty'}), 400
        if len(data) > MAX_IMAGE_BYTES:
            return jsonify({'ok': False, 'error': 'image exceeds 15 MB limit'}), 413

        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            return jsonify({'ok': False, 'error': 'client sha256 does not match uploaded bytes'}), 400

        object_key = _object_key(actual_sha, content_type)
        backend = put_with_failover(
            object_key,
            data,
            content_type,
            metadata={'sha256': actual_sha},
            cache_control='private, max-age=2592000',
        )
        result = upsert_asset_metadata_multi(
            order_number,
            workflow_key,
            actual_sha,
            object_key,
            content_type,
            len(data),
            source_site=source_site,
            storage_backend=backend,
        )
        result['uploaded_to_b2'] = True
        result['deduplicated'] = False
        result['upload_mode'] = 'render_proxy_nohead_multi_b2'
        result['b2_head_calls'] = 0
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
