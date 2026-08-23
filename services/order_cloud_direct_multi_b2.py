"""Direct PC -> B2 upload signer for ORDER customer-share images.

Render never returns B2 credentials.  It returns short-lived presigned PUT URLs only.
Image bytes therefore bypass Render completely:

PC -> Render (small JSON presign request)
PC -> selected B2 (image bytes)
PC -> Render (small metadata register request)

Backend selection uses the cached Class-B health policy.  No per-image HEAD is used.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from services.order_cloud_asset_service import (
    _object_key,
    _validate_content_type,
    _validate_sha256,
)
from services.order_cloud_direct_b2 import _thumb_object_key
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    client_for_backend,
    config_for_backend,
    storage_backend_for_sha,
    upsert_asset_metadata_multi,
)
from services.order_cloud_multi_b2_auto import select_readable_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}


def _presigned_put(backend, object_key, content_type, seconds=600):
    cfg = config_for_backend(backend, required=True)
    return client_for_backend(backend).generate_presigned_url(
        ClientMethod='put_object',
        Params={
            'Bucket': cfg['bucket_name'],
            'Key': object_key,
            'ContentType': content_type,
        },
        ExpiresIn=int(seconds),
        HttpMethod='PUT',
    )


@b2_test_bp.route('/api/order-cloud/assets/direct-presign', methods=['POST'])
def order_cloud_asset_direct_presign():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        variant = str(payload.get('variant') or 'web').strip().lower()
        if variant not in {'web', 'thumb'}:
            raise ValueError('variant must be web or thumb')

        byte_sha256 = _validate_sha256(payload.get('sha256'))
        selection = None

        if variant == 'thumb':
            asset_sha256 = _validate_sha256(payload.get('asset_sha256'))
            content_type = 'image/jpeg'
            object_key = _thumb_object_key(asset_sha256)
            backend = storage_backend_for_sha(asset_sha256)
            if backend not in _ALLOWED_BACKENDS or not backend_ready(backend):
                raise RuntimeError('thumbnail B2 backend is not configured')
        else:
            asset_sha256 = byte_sha256
            content_type = _validate_content_type(payload.get('content_type'))
            object_key = _object_key(asset_sha256, content_type)
            backend, selection = select_readable_backend(force_probe=False)

        upload_url = _presigned_put(backend, object_key, content_type, seconds=600)
        result = {
            'variant': variant,
            'sha256': byte_sha256,
            'asset_sha256': asset_sha256,
            'content_type': content_type,
            'object_key': object_key,
            'storage_backend': backend,
            'upload_url': upload_url,
            'expires_seconds': 600,
            'upload_mode': 'pc_direct_b2_presigned',
            'render_receives_image_bytes': False,
            'b2_head_calls_per_image': 0,
        }
        if selection:
            result['backend_selection'] = {
                'selected': selection.get('selected'),
                'primary_status': (selection.get('primary') or {}).get('status'),
                'primary_cached': (selection.get('primary') or {}).get('cached'),
                'secondary_status': (selection.get('secondary') or {}).get('status') if selection.get('secondary') else None,
                'secondary_cached': (selection.get('secondary') or {}).get('cached') if selection.get('secondary') else None,
            }
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/direct-register', methods=['POST'])
def order_cloud_asset_direct_register():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        order_number = str(payload.get('order_number') or '').strip()
        workflow_key = str(payload.get('workflow_key') or '').strip() or None
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        backend = str(payload.get('storage_backend') or '').strip().lower()
        if backend not in _ALLOWED_BACKENDS or not backend_ready(backend):
            raise ValueError('storage_backend is invalid or not configured')
        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            raise ValueError('file_size must be an integer')
        if file_size <= 0 or file_size > 15 * 1024 * 1024:
            raise ValueError('file_size is outside the allowed range')

        expected_object_key = _object_key(sha256_hex, content_type)
        supplied_object_key = str(payload.get('object_key') or '').strip()
        if supplied_object_key and supplied_object_key != expected_object_key:
            raise ValueError('object_key does not match sha256/content_type')

        result = upsert_asset_metadata_multi(
            order_number,
            workflow_key,
            sha256_hex,
            expected_object_key,
            content_type,
            file_size,
            source_site=source_site,
            storage_backend=backend,
        )
        result['upload_mode'] = 'pc_direct_b2_registered'
        result['render_received_image_bytes'] = False
        result['b2_head_calls'] = 0
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
