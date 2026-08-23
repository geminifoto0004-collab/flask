"""Small Render-proxy thumbnail upload for ORDER customer sharing.

The stable production upload path remains office PC -> Render -> private B2.  The
2560px WEB image continues to use the existing authenticated /assets/upload route.
This module adds only the small 480px thumbnail companion so public share pages do
not need to generate thumbnails on first view.

No B2 credential leaves Render.  Thumbnail objects are content companions keyed by
the registered WEB image SHA and have no separate cloud_assets row.
"""
from __future__ import annotations

import hashlib

from flask import jsonify, request
from botocore.exceptions import ClientError

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from services.order_cloud_asset_service import _b2_client, _b2_config, _is_not_found, _validate_sha256
from services.order_cloud_direct_b2 import _thumb_object_key

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

        cfg = _b2_config()
        s3 = _b2_client(cfg)
        object_key = _thumb_object_key(asset_sha256)
        uploaded = False
        try:
            info = s3.head_object(Bucket=cfg['bucket_name'], Key=object_key)
            existing_size = int(info.get('ContentLength') or 0)
            if existing_size <= 0:
                raise RuntimeError('existing thumbnail has invalid size')
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            s3.put_object(
                Bucket=cfg['bucket_name'],
                Key=object_key,
                Body=data,
                ContentType='image/jpeg',
                CacheControl='private, max-age=2592000',
                Metadata={'sha256': actual_sha, 'asset-sha256': asset_sha256},
            )
            uploaded = True

        return jsonify({'ok': True, 'result': {
            'asset_sha256': asset_sha256,
            'sha256': actual_sha,
            'object_key': object_key,
            'file_size': len(data),
            'uploaded_to_b2': uploaded,
            'deduplicated': not uploaded,
            'upload_mode': 'render_proxy_thumb',
        }})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
