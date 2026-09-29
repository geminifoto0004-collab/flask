"""Direct PC -> B2 upload signer for ORDER customer-share images.

Formal image policy:
- one local source image -> one optimized WEB object + one 480px thumbnail object;
- image bytes always travel PC -> B2, never through Render;
- new object keys are scoped by stable TiDB customer/order/workflow ownership, never
  by a share token, so changing/revoking a share link never changes image ownership;
- an existing cloud_assets row is reused without a B2 HEAD request.

WEB images and 480px thumbnails are both presigned control-plane objects. New clients
generate both locally and PUT both directly PC -> B2; Render never sees their bytes.
"""
from __future__ import annotations

import hashlib
import re
import threading

from flask import jsonify, request

from blueprints.b2_test_bp import (
    b2_test_bp,
    _ensure_order_cloud_tables,
    _order_cloud_auth_source,
)
from database import get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service
from services.order_cloud_asset_service import (
    ALLOWED_IMAGE_TYPES,
    _object_key,
    _validate_content_type,
    _validate_sha256,
)
from services.order_cloud_direct_b2 import _thumb_object_key
from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    config_for_backend,
)
from services.order_cloud_multi_b2_auto import select_readable_backend

_ALLOWED_BACKENDS = {PRIMARY, SECONDARY}
_NEW_IMAGE_MAX_BYTES = 1_000_000
_LEGACY_MAX_BYTES = 15 * 1024 * 1024
_CLIENTS = {}
_CLIENTS_LOCK = threading.Lock()


def _client_for_backend(backend):
    """Reuse one boto3 client per backend instead of rebuilding it per image."""
    import boto3

    backend = str(backend or PRIMARY).strip().lower()
    cfg = config_for_backend(backend, required=True)
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(backend)
        if client is None:
            client = boto3.client(
                's3',
                endpoint_url=cfg['endpoint'],
                aws_access_key_id=cfg['key_id'],
                aws_secret_access_key=cfg['application_key'],
            )
            _CLIENTS[backend] = client
        return client


def _presigned_put(backend, object_key, content_type, seconds=600):
    cfg = config_for_backend(backend, required=True)
    return _client_for_backend(backend).generate_presigned_url(
        ClientMethod='put_object',
        Params={
            'Bucket': cfg['bucket_name'],
            'Key': object_key,
            'ContentType': content_type,
        },
        ExpiresIn=int(seconds),
        HttpMethod='PUT',
    )


def _safe_component(value, fallback):
    raw = str(value or '').strip()
    if not raw:
        return fallback
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', raw).strip('-.') or fallback
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]
    return f'{slug[:72]}-{digest}'


def _customer_namespace(customer_key):
    """Stable, non-human-readable folder derived from TiDB customer_key, never token."""
    value = str(customer_key or '').strip()
    if not value:
        raise ValueError('customer_key is required')
    return 'c_' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def _scoped_object_key(customer_key, order_number, workflow_key, sha256_hex, content_type):
    content_type = _validate_content_type(content_type)
    sha256_hex = _validate_sha256(sha256_hex)
    extension = ALLOWED_IMAGE_TYPES[content_type]
    customer = _customer_namespace(customer_key)
    order = _safe_component(order_number, 'order')
    workflow = _safe_component(workflow_key, '_order') if workflow_key else '_order'
    return (
        f'customers/{customer}/orders/{order}/workflows/{workflow}/images/'
        f'{sha256_hex}{extension}'
    )


def _resolve_owner(order_number, workflow_key, conn=None):
    """Resolve canonical ownership, optionally reusing one DB connection for a batch."""
    own_conn = conn is None
    conn = conn or get_db_connection()
    cur = get_cursor(conn)
    try:
        order_number, customer_key, workflow_key = asset_service._resolve_order_and_workflow(
            cur, order_number, workflow_key
        )
        return order_number, str(customer_key or '').strip(), workflow_key
    finally:
        if own_conn:
            conn.close()


def _existing_asset(order_number, workflow_key, sha256_hex, conn=None):
    """Trust registered metadata for reuse; deliberately do not HEAD B2 per image."""
    asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
    own_conn = conn is None
    conn = conn or get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                      object_key, content_type, file_size, storage_backend
               FROM cloud_assets
               WHERE asset_key=? AND active=TRUE LIMIT 1""",
            (asset_key,),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        if own_conn:
            conn.close()


def _b2_existing_object(object_keys, expected_size=0):
    """Probe B2 only after TiDB lost its asset row (for example after failover).

    A missing TiDB row does not mean that the image bytes need uploading again.
    Probe both configured B2 stores and both scoped/legacy key conventions. A
    read error is not a 404: do not overwrite an object we could not check.
    """
    from botocore.exceptions import ClientError

    checked = 0
    errors = []
    for backend in (PRIMARY, SECONDARY):
        if not backend_ready(backend):
            continue
        cfg = config_for_backend(backend, required=True)
        client = _client_for_backend(backend)
        for object_key in dict.fromkeys(object_keys):
            try:
                info = client.head_object(Bucket=cfg['bucket_name'], Key=object_key)
            except ClientError as exc:
                code = str((exc.response.get('Error') or {}).get('Code') or '')
                status = (exc.response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
                if code in {'404', 'NoSuchKey', 'NotFound'} or status == 404:
                    checked += 1
                    continue
                errors.append(exc)
                continue
            except Exception as exc:
                errors.append(exc)
                continue
            size = int(info.get('ContentLength') or 0)
            if size <= 0 or (expected_size and size != expected_size):
                raise RuntimeError('existing B2 image has an unexpected size')
            return backend, object_key, size
    if errors:
        raise RuntimeError('cannot confirm whether image already exists in B2') from errors[0]
    if not checked:
        raise RuntimeError('no readable B2 backend is configured')
    return None


def _upsert_registered_asset(order_number, customer_key, workflow_key, sha256_hex,
                             object_key, content_type, file_size, source_site,
                             storage_backend, thumb_object_key=None, thumb_sha256=None,
                             thumb_content_type=None, thumb_file_size=None, conn=None):
    """Fast metadata upsert; a batch may reuse one DB connection across many items."""
    asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
    display_name = f'Imagen {order_number}'
    source_site = str(source_site or '').strip().upper()[:16] or None

    own_conn = conn is None
    conn = conn or get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute('SELECT asset_key FROM cloud_assets WHERE asset_key=?', (asset_key,))
        values = (
            customer_key, order_number, workflow_key, sha256_hex, object_key,
            content_type, int(file_size), display_name, source_site, storage_backend,
            thumb_object_key, thumb_sha256, thumb_content_type,
            int(thumb_file_size or 0) if thumb_file_size else None, asset_key,
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_assets
                   SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                       sha256=?, object_key=?, content_type=?, file_size=?, display_name=?,
                       source_site=?, storage_backend=?, thumb_object_key=?, thumb_sha256=?,
                       thumb_content_type=?, thumb_file_size=?, active=TRUE,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE asset_key=?""",
                values,
            )
        else:
            cur.execute(
                """INSERT INTO cloud_assets
                   (customer_key, order_number, workflow_key, asset_type, sha256,
                    object_key, content_type, file_size, display_name, source_site,
                    storage_backend, thumb_object_key, thumb_sha256, thumb_content_type,
                    thumb_file_size, asset_key)
                   VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    return {
        'asset_key': asset_key,
        'customer_key': customer_key,
        'order_number': order_number,
        'workflow_key': workflow_key,
        'asset_type': 'IMAGE',
        'sha256': sha256_hex,
        'object_key': object_key,
        'content_type': content_type,
        'file_size': int(file_size),
        'display_name': display_name,
        'source_site': source_site,
        'storage_backend': storage_backend,
        'thumb_object_key': thumb_object_key,
        'thumb_sha256': thumb_sha256,
        'thumb_content_type': thumb_content_type,
        'thumb_file_size': int(thumb_file_size or 0) if thumb_file_size else None,
    }


def _choose_upload_backend(avoid_backend=''):
    """Choose one configured/readable backend. Avoid is used only for direct-B2 failover."""
    backend, selection = select_readable_backend(force_probe=False)
    avoid_backend = str(avoid_backend or '').strip().lower()
    if avoid_backend and backend == avoid_backend:
        alternate = SECONDARY if backend == PRIMARY else PRIMARY
        if alternate in _ALLOWED_BACKENDS and backend_ready(alternate):
            backend = alternate
    return backend, selection


def _direct_presign_result(payload, *, conn=None, owner_cache=None, selected_backend=None,
                           selection=None, expires_seconds=1800):
    variant = str(payload.get('variant') or 'image').strip().lower()
    if variant not in {'image', 'web', 'thumb'}:
        raise ValueError('variant must be image, web or thumb')

    byte_sha256 = _validate_sha256(payload.get('sha256'))
    if variant == 'thumb':
        asset_sha256 = _validate_sha256(payload.get('asset_sha256'))
        content_type = 'image/jpeg'
        object_key = _thumb_object_key(asset_sha256)
        try:
            thumb_size = int(payload.get('file_size') or 0)
        except Exception:
            thumb_size = 0
        if thumb_size <= 0 or thumb_size > 2_000_000:
            raise ValueError('thumbnail file_size is outside the allowed range')
        requested_backend = str(payload.get('storage_backend') or '').strip().lower()
        backend = requested_backend or selected_backend
        if not backend:
            from services.order_cloud_multi_b2 import storage_backend_for_sha
            backend = storage_backend_for_sha(asset_sha256)
        if backend not in _ALLOWED_BACKENDS or not backend_ready(backend):
            raise RuntimeError('thumbnail B2 backend is not configured')
        upload_url = _presigned_put(backend, object_key, content_type, seconds=expires_seconds)
        return {
            'exists': False, 'variant': variant, 'sha256': byte_sha256,
            'asset_sha256': asset_sha256, 'content_type': content_type,
            'file_size': thumb_size, 'object_key': object_key, 'storage_backend': backend,
            'upload_url': upload_url, 'expires_seconds': expires_seconds,
            'upload_mode': 'pc_direct_b2_prebuilt_thumb',
            'render_receives_image_bytes': False, 'b2_head_calls_per_image': 0,
        }

    asset_sha256 = byte_sha256
    content_type = _validate_content_type(payload.get('content_type'))
    order_number = str(payload.get('order_number') or '').strip()
    workflow_key = str(payload.get('workflow_key') or '').strip() or None
    customer_key = ''

    if order_number:
        cache_key = (order_number, workflow_key or '')
        resolved = (owner_cache or {}).get(cache_key) if owner_cache is not None else None
        if not resolved:
            resolved = _resolve_owner(order_number, workflow_key, conn=conn)
            if owner_cache is not None:
                owner_cache[cache_key] = resolved
        order_number, customer_key, workflow_key = resolved
        existing = _existing_asset(order_number, workflow_key, asset_sha256, conn=conn)
        if existing:
            backend = str(existing.get('storage_backend') or PRIMARY).strip().lower()
            if backend in _ALLOWED_BACKENDS and backend_ready(backend) and existing.get('object_key'):
                return {
                    'exists': True, 'reused': True, 'variant': 'image',
                    'sha256': asset_sha256, 'asset_sha256': asset_sha256,
                    'content_type': existing.get('content_type') or content_type,
                    'file_size': int(existing.get('file_size') or 0),
                    'object_key': existing.get('object_key'), 'storage_backend': backend,
                    'asset_key': existing.get('asset_key'),
                    'upload_mode': 'tidb_metadata_reuse_no_b2_head',
                    'render_receives_image_bytes': False, 'b2_head_calls_per_image': 0,
                }
        object_key = _scoped_object_key(customer_key, order_number, workflow_key, asset_sha256, content_type)
        try:
            file_size = int(payload.get('file_size') or 0)
        except Exception:
            file_size = 0
        if file_size > _LEGACY_MAX_BYTES:
            raise ValueError('file_size is outside the allowed range')

        # A newly selected TiDB can lack cloud_assets even though B2 already has
        # the image. Restore its metadata without another PC -> B2 upload. This
        # path runs only for a signed, authenticated publication request; public
        # page reads never guess visibility from the mere presence of a B2 file.
        # Customer-pinned uploads use a stable customer/SHA object path. Older
        # batches only probed order-scoped and legacy paths, so a TiDB switch
        # could miss the existing B2 bytes and report every cached item failed.
        from services.order_cloud_customer_storage import stable_object_key, find_customer_sha_asset
        physical = find_customer_sha_asset(customer_key, asset_sha256)
        if physical and physical.get('object_key'):
            linked = _upsert_registered_asset(
                order_number, customer_key, workflow_key, asset_sha256,
                physical['object_key'], physical.get('content_type') or content_type,
                int(physical.get('file_size') or file_size), None,
                physical.get('storage_backend') or PRIMARY, conn=conn,
            )
            return {
                'exists': True, 'reused': True, 'variant': 'image',
                'sha256': asset_sha256, 'asset_sha256': asset_sha256,
                'content_type': physical.get('content_type') or content_type,
                'file_size': int(physical.get('file_size') or file_size),
                'object_key': physical['object_key'],
                'storage_backend': physical.get('storage_backend') or PRIMARY,
                'asset_key': linked['asset_key'],
                'upload_mode': 'customer_sha_relinked_without_upload',
            }
        found = _b2_existing_object(
            (stable_object_key(customer_key, asset_sha256, content_type),
             object_key, _object_key(asset_sha256, content_type)), file_size,
        )
        if found:
            backend, found_key, found_size = found
            thumb_key = _thumb_object_key(asset_sha256)
            try:
                thumb = _b2_existing_object((thumb_key,))
            except RuntimeError:
                # A thumbnail is optional; losing its backend must not cause a
                # second upload of a confirmed existing WEB image.
                thumb = None
            thumb_size = thumb[2] if thumb and thumb[0] == backend else None
            registered = _upsert_registered_asset(
                order_number, customer_key, workflow_key, asset_sha256,
                found_key, content_type, found_size, None, backend,
                thumb_object_key=thumb_key if thumb_size else None,
                thumb_content_type='image/jpeg' if thumb_size else None,
                thumb_file_size=thumb_size, conn=conn,
            )
            return {
                'exists': True, 'reused': True, 'variant': 'image',
                'sha256': asset_sha256, 'asset_sha256': asset_sha256,
                'content_type': content_type, 'file_size': found_size,
                'object_key': found_key, 'storage_backend': backend,
                'asset_key': registered['asset_key'],
                'upload_mode': 'b2_existing_object_tidb_metadata_repair',
                'render_receives_image_bytes': False,
                'b2_head_calls_per_image': 1,
            }
        # Historical images may be larger than the current upload policy. They
        # can be linked only after confirming their bytes already exist in B2;
        # never issue a new PUT URL for an oversized image.
        if file_size > _NEW_IMAGE_MAX_BYTES:
            raise ValueError('optimized image exceeds 1,000,000-byte policy')
    else:
        object_key = _object_key(asset_sha256, content_type)

    backend = selected_backend
    if not backend:
        backend, selection = _choose_upload_backend(payload.get('avoid_backend'))
    elif str(payload.get('avoid_backend') or '').strip().lower() == backend:
        alt = SECONDARY if backend == PRIMARY else PRIMARY
        if backend_ready(alt):
            backend = alt

    upload_url = _presigned_put(backend, object_key, content_type, seconds=expires_seconds)
    result = {
        'exists': False, 'reused': False, 'variant': 'image',
        'sha256': byte_sha256, 'asset_sha256': asset_sha256,
        'content_type': content_type, 'object_key': object_key,
        'storage_backend': backend, 'upload_url': upload_url,
        'expires_seconds': expires_seconds,
        'upload_mode': 'pc_direct_b2_batch_ready',
        'render_receives_image_bytes': False, 'b2_head_calls_per_image': 0,
    }
    if customer_key:
        result['customer_namespace'] = _customer_namespace(customer_key)
    if selection:
        result['backend_selection'] = {
            'selected': selection.get('selected'),
            'primary_status': (selection.get('primary') or {}).get('status'),
            'primary_cached': (selection.get('primary') or {}).get('cached'),
            'secondary_status': (selection.get('secondary') or {}).get('status') if selection.get('secondary') else None,
            'secondary_cached': (selection.get('secondary') or {}).get('cached') if selection.get('secondary') else None,
        }
    return result


def _validate_register_item(payload, *, conn=None, owner_cache=None):
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
    if file_size <= 0 or file_size > _LEGACY_MAX_BYTES:
        raise ValueError('file_size is outside the allowed range')

    cache_key = (order_number, workflow_key or '')
    resolved = (owner_cache or {}).get(cache_key) if owner_cache is not None else None
    if not resolved:
        resolved = _resolve_owner(order_number, workflow_key, conn=conn)
        if owner_cache is not None:
            owner_cache[cache_key] = resolved
    order_number, customer_key, workflow_key = resolved
    scoped_object_key = _scoped_object_key(customer_key, order_number, workflow_key, sha256_hex, content_type)
    legacy_object_key = _object_key(sha256_hex, content_type)
    supplied_object_key = str(payload.get('object_key') or '').strip()
    object_key = supplied_object_key or scoped_object_key
    if object_key not in {scoped_object_key, legacy_object_key}:
        raise ValueError('object_key does not match canonical owner/sha256/content_type')
    if object_key == scoped_object_key and file_size > _NEW_IMAGE_MAX_BYTES:
        raise ValueError('optimized image exceeds 1,000,000-byte policy')

    thumb_object_key = str(payload.get('thumb_object_key') or '').strip() or None
    thumb_sha256 = str(payload.get('thumb_sha256') or '').strip().lower() or None
    thumb_content_type = str(payload.get('thumb_content_type') or '').strip().lower() or None
    try:
        thumb_file_size = int(payload.get('thumb_file_size') or 0) or None
    except Exception:
        raise ValueError('thumb_file_size must be an integer')
    if any((thumb_object_key, thumb_sha256, thumb_content_type, thumb_file_size)):
        expected_thumb_key = _thumb_object_key(sha256_hex)
        if thumb_object_key != expected_thumb_key:
            raise ValueError('thumb_object_key does not match asset sha256')
        thumb_sha256 = _validate_sha256(thumb_sha256)
        if thumb_content_type != 'image/jpeg':
            raise ValueError('thumb_content_type must be image/jpeg')
        if not thumb_file_size or thumb_file_size <= 0 or thumb_file_size > 2_000_000:
            raise ValueError('thumb_file_size is outside the allowed range')
    return (order_number, customer_key, workflow_key, sha256_hex, object_key, content_type,
            file_size, backend, scoped_object_key, thumb_object_key, thumb_sha256,
            thumb_content_type, thumb_file_size)


@b2_test_bp.route('/api/order-cloud/assets/direct-presign', methods=['POST'])
def order_cloud_asset_direct_presign():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        result = _direct_presign_result(payload, expires_seconds=1800)
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/direct-presign-batch', methods=['POST'])
def order_cloud_asset_direct_presign_batch():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        items = payload.get('items') or []
        if not isinstance(items, list) or not items:
            raise ValueError('items must be a non-empty list')
        if len(items) > 50:
            raise ValueError('batch presign supports at most 50 items')
        try:
            expires_seconds = int(payload.get('expires_seconds') or 1800)
        except Exception:
            expires_seconds = 1800
        expires_seconds = max(600, min(expires_seconds, 3600))

        # Select the normal upload backend once per request. Existing registered assets
        # retain their own recorded backend. No image bytes ever reach this endpoint.
        # A missing upload backend must not block an already registered asset;
        # individual new uploads still fail closed in _direct_presign_result.
        try:
            selected_backend, selection = _choose_upload_backend(payload.get('avoid_backend'))
        except Exception as exc:
            print(f'[ORDER Cloud] presign batch backend probe unavailable: {type(exc).__name__}: {exc}')
            selected_backend, selection = None, None
        conn = get_db_connection()
        owner_cache = {}
        results = []
        repaired_customers = set()
        try:
            for index, raw in enumerate(items):
                item = dict(raw or {})
                client_id = str(item.pop('client_id', index))
                try:
                    result = _direct_presign_result(
                        item, conn=conn, owner_cache=owner_cache,
                        selected_backend=selected_backend, selection=selection,
                        expires_seconds=expires_seconds,
                    )
                    results.append({'client_id': client_id, 'ok': True, 'result': result})
                    if result.get('upload_mode') in {
                        'customer_sha_relinked_without_upload',
                        'b2_existing_object_tidb_metadata_repair',
                    }:
                        resolved = owner_cache.get((str(item.get('order_number') or '').strip(),
                                                    str(item.get('workflow_key') or '').strip()))
                        if resolved and resolved[1]:
                            repaired_customers.add(str(resolved[1]))
                except Exception as exc:
                    results.append({
                        'client_id': client_id, 'ok': False, 'error': str(exc),
                        'error_type': type(exc).__name__,
                    })
        finally:
            conn.close()
        if repaired_customers:
            from services.order_customer_share_snapshot import queue_snapshot_refresh
            for customer_key in repaired_customers:
                queue_snapshot_refresh(customer_key)
        return jsonify({'ok': True, 'result': {
            'items': results, 'count': len(results),
            'selected_backend': selected_backend, 'expires_seconds': expires_seconds,
            'render_receives_image_bytes': False,
        }})
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
        values = _validate_register_item(payload)
        (order_number, customer_key, workflow_key, sha256_hex, object_key, content_type,
         file_size, backend, scoped_object_key, thumb_object_key, thumb_sha256,
         thumb_content_type, thumb_file_size) = values
        result = _upsert_registered_asset(
            order_number, customer_key, workflow_key, sha256_hex, object_key,
            content_type, file_size, source_site, backend,
            thumb_object_key=thumb_object_key, thumb_sha256=thumb_sha256,
            thumb_content_type=thumb_content_type, thumb_file_size=thumb_file_size,
        )
        result['upload_mode'] = 'pc_direct_b2_single_image_registered' if object_key == scoped_object_key else 'pc_direct_b2_legacy_registered'
        result['render_received_image_bytes'] = False
        result['b2_head_calls'] = 0
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500


@b2_test_bp.route('/api/order-cloud/assets/direct-register-batch', methods=['POST'])
def order_cloud_asset_direct_register_batch():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_order_cloud_tables()
        payload = request.get_json(silent=True) or {}
        items = payload.get('items') or []
        if not isinstance(items, list) or not items:
            raise ValueError('items must be a non-empty list')
        if len(items) > 50:
            raise ValueError('batch register supports at most 50 items')

        conn = get_db_connection()
        owner_cache = {}
        results = []
        try:
            for index, raw in enumerate(items):
                item = dict(raw or {})
                client_id = str(item.pop('client_id', index))
                try:
                    values = _validate_register_item(item, conn=conn, owner_cache=owner_cache)
                    (order_number, customer_key, workflow_key, sha256_hex, object_key, content_type,
                     file_size, backend, scoped_object_key, thumb_object_key, thumb_sha256,
                     thumb_content_type, thumb_file_size) = values
                    result = _upsert_registered_asset(
                        order_number, customer_key, workflow_key, sha256_hex, object_key,
                        content_type, file_size, source_site, backend,
                        thumb_object_key=thumb_object_key, thumb_sha256=thumb_sha256,
                        thumb_content_type=thumb_content_type, thumb_file_size=thumb_file_size,
                        conn=conn,
                    )
                    result['upload_mode'] = 'pc_direct_b2_batch_registered' if object_key == scoped_object_key else 'pc_direct_b2_legacy_registered'
                    result['render_received_image_bytes'] = False
                    result['b2_head_calls'] = 0
                    results.append({'client_id': client_id, 'ok': True, 'result': result})
                except Exception as exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    results.append({
                        'client_id': client_id, 'ok': False, 'error': str(exc),
                        'error_type': type(exc).__name__,
                    })
        finally:
            conn.close()
        return jsonify({'ok': True, 'result': {
            'items': results, 'count': len(results), 'render_received_image_bytes': False,
        }})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
