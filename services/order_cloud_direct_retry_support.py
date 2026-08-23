"""Retry/failover support for ORDER direct PC -> B2 uploads.

A direct-presign retry may ask Render to avoid the B2 backend that just failed a PUT.
The request stays authenticated and owner-scoped; Render still returns only a
short-lived one-object PUT URL and never receives image bytes.
"""
from __future__ import annotations

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from services.order_cloud_asset_service import _validate_content_type, _validate_sha256
from services.order_cloud_multi_b2 import PRIMARY, SECONDARY, backend_ready
from services.order_cloud_multi_b2_auto import probe_backend_class_b
from services import order_cloud_direct_multi_b2 as direct

_ALLOWED = {PRIMARY, SECONDARY}


@b2_test_bp.before_app_request
def _direct_presign_retry_failover():
    if request.method != 'POST' or request.path != '/api/order-cloud/assets/direct-presign':
        return None

    payload = request.get_json(silent=True) or {}
    variant = str(payload.get('variant') or 'image').strip().lower()
    avoid_backend = str(payload.get('avoid_backend') or '').strip().lower()
    if variant != 'image' or avoid_backend not in _ALLOWED:
        return None

    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error

    try:
        _ensure_order_cloud_tables()
        sha256_hex = _validate_sha256(payload.get('sha256'))
        content_type = _validate_content_type(payload.get('content_type'))
        order_number = str(payload.get('order_number') or '').strip()
        workflow_key = str(payload.get('workflow_key') or '').strip() or None
        if not order_number:
            raise ValueError('order_number is required for retry failover')
        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            file_size = 0
        if file_size and file_size > direct._NEW_IMAGE_MAX_BYTES:
            raise ValueError('optimized image exceeds 1,000,000-byte policy')

        order_number, customer_key, workflow_key = direct._resolve_owner(order_number, workflow_key)

        # If another concurrent/retry request already registered this exact logical
        # image, reuse it instead of uploading again.
        existing = direct._existing_asset(order_number, workflow_key, sha256_hex)
        if existing:
            existing_backend = str(existing.get('storage_backend') or PRIMARY).strip().lower()
            if existing_backend in _ALLOWED and backend_ready(existing_backend) and existing.get('object_key'):
                health = probe_backend_class_b(existing_backend, force=False)
                if health.get('class_b_ok'):
                    return jsonify({'ok': True, 'result': {
                        'exists': True,
                        'reused': True,
                        'variant': 'image',
                        'sha256': sha256_hex,
                        'asset_sha256': sha256_hex,
                        'content_type': existing.get('content_type') or content_type,
                        'file_size': int(existing.get('file_size') or 0),
                        'object_key': existing.get('object_key'),
                        'storage_backend': existing_backend,
                        'asset_key': existing.get('asset_key'),
                        'upload_mode': 'retry_found_registered_asset',
                        'render_receives_image_bytes': False,
                    }})

        preferred = SECONDARY if avoid_backend == PRIMARY else PRIMARY
        health_by_backend = {}
        selected = None
        for backend in (preferred, avoid_backend):
            if not backend_ready(backend):
                health_by_backend[backend] = {'status': 'not_configured', 'class_b_ok': False}
                continue
            health = probe_backend_class_b(backend, force=False)
            health_by_backend[backend] = health
            if health.get('class_b_ok'):
                selected = backend
                break
        if not selected:
            raise RuntimeError(
                'No readable B2 backend available for retry: '
                f'{PRIMARY}={health_by_backend.get(PRIMARY, {}).get("status")}; '
                f'{SECONDARY}={health_by_backend.get(SECONDARY, {}).get("status")}'
            )

        object_key = direct._scoped_object_key(
            customer_key, order_number, workflow_key, sha256_hex, content_type
        )
        upload_url = direct._presigned_put(selected, object_key, content_type, seconds=600)
        return jsonify({'ok': True, 'result': {
            'exists': False,
            'reused': False,
            'variant': 'image',
            'sha256': sha256_hex,
            'asset_sha256': sha256_hex,
            'content_type': content_type,
            'object_key': object_key,
            'storage_backend': selected,
            'upload_url': upload_url,
            'expires_seconds': 600,
            'upload_mode': 'pc_direct_b2_retry_failover',
            'render_receives_image_bytes': False,
            'customer_namespace': direct._customer_namespace(customer_key),
            'avoid_backend': avoid_backend,
        }})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
