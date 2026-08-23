"""Automatic readable-B2 selection for ORDER uploads.

Rules:
- Prefer primary while its Class-B HEAD probe is healthy.
- If primary is unreadable (403/cap/config/network), use secondary automatically.
- Cache probe results so bulk uploads do NOT spend one Class-B request per image.
- The image upload itself still uses PUT only; TiDB stores the selected backend.
"""
from __future__ import annotations

import threading
import time
import uuid

from botocore.exceptions import ClientError

from services.order_cloud_multi_b2 import (
    PRIMARY,
    SECONDARY,
    backend_ready,
    client_for_backend,
    config_for_backend,
    put_to_backend,
)

# One never-created object name per Render process. HEAD should return 404 when
# read/Class-B access is healthy.
_PROBE_KEY = f"order-cloud/images/__auto_health__/{uuid.uuid4().hex}.probe"

# Healthy status is refreshed occasionally; blocked/error status is kept longer so a
# large publication cannot hammer an already-exhausted B2 account.
_HEALTHY_TTL_SECONDS = 300
_BLOCKED_TTL_SECONDS = 1800
_ERROR_TTL_SECONDS = 300

_cache = {}
_lock = threading.Lock()


def _client_error_fields(exc):
    response = getattr(exc, 'response', None) or {}
    err = response.get('Error') or {}
    meta = response.get('ResponseMetadata') or {}
    return (
        meta.get('HTTPStatusCode'),
        str(err.get('Code') or ''),
        str(err.get('Message') or ''),
    )


def invalidate_backend_health(backend):
    with _lock:
        _cache.pop(str(backend or ''), None)


def _cached(backend):
    now = time.monotonic()
    with _lock:
        item = _cache.get(backend)
        if item and float(item.get('expires_at') or 0) > now:
            result = dict(item)
            result['cached'] = True
            result.pop('expires_at', None)
            return result
    return None


def _store(backend, result, ttl):
    item = dict(result)
    item['expires_at'] = time.monotonic() + max(1, int(ttl))
    with _lock:
        _cache[backend] = item
    result = dict(result)
    result['cached'] = False
    return result


def probe_backend_class_b(backend, force=False):
    """Use exactly one HEAD when a fresh probe is required.

    404/NoSuchKey means Class-B read access is healthy. 403 or any other error means
    this backend is not suitable for NEW customer-share images because a successful
    PUT could still leave the image unreadable to customers.
    """
    backend = str(backend or '').strip().lower()
    if backend not in (PRIMARY, SECONDARY):
        return {'backend': backend, 'configured': False, 'class_b_ok': False, 'status': 'invalid_backend'}

    if not backend_ready(backend):
        return {'backend': backend, 'configured': False, 'class_b_ok': False, 'status': 'not_configured'}

    if not force:
        cached = _cached(backend)
        if cached is not None:
            return cached

    cfg = config_for_backend(backend, required=True)
    try:
        client_for_backend(backend).head_object(Bucket=cfg['bucket_name'], Key=_PROBE_KEY)
        # Extremely unlikely (the random probe key is never PUT), but readable is what
        # matters, so treat a successful HEAD as healthy too.
        return _store(backend, {
            'backend': backend,
            'configured': True,
            'class_b_ok': True,
            'status': 'ok',
            'http_status': 200,
        }, _HEALTHY_TTL_SECONDS)
    except ClientError as exc:
        http_status, aws_code, aws_message = _client_error_fields(exc)
        if http_status == 404 or aws_code in ('404', 'NoSuchKey', 'NotFound'):
            return _store(backend, {
                'backend': backend,
                'configured': True,
                'class_b_ok': True,
                'status': 'ok',
                'http_status': http_status,
                'aws_code': aws_code,
                'note': '404 on missing probe key means Class-B access works',
            }, _HEALTHY_TTL_SECONDS)

        # Backblaze sometimes returns only generic 403 for HEAD after the Class-B cap
        # is exceeded. Treat every non-404 HEAD failure as unreadable and hold it for
        # 30 minutes before trying that backend again.
        return _store(backend, {
            'backend': backend,
            'configured': True,
            'class_b_ok': False,
            'status': 'blocked',
            'http_status': http_status,
            'aws_code': aws_code,
            'aws_message': aws_message,
        }, _BLOCKED_TTL_SECONDS)
    except Exception as exc:
        return _store(backend, {
            'backend': backend,
            'configured': True,
            'class_b_ok': False,
            'status': 'error',
            'error_type': type(exc).__name__,
            'error': str(exc),
        }, _ERROR_TTL_SECONDS)


def select_readable_backend(force_probe=False):
    """Primary first; secondary only when primary is not readable."""
    primary = probe_backend_class_b(PRIMARY, force=force_probe)
    if primary.get('class_b_ok'):
        return PRIMARY, {'primary': primary, 'secondary': None, 'selected': PRIMARY}

    secondary = probe_backend_class_b(SECONDARY, force=force_probe)
    if secondary.get('class_b_ok'):
        return SECONDARY, {'primary': primary, 'secondary': secondary, 'selected': SECONDARY}

    def _short(item):
        if not item:
            return 'unknown'
        return f"{item.get('status')} HTTP={item.get('http_status')} AWS={item.get('aws_code')}"

    raise RuntimeError(
        'No readable B2 backend is available for ORDER images. '
        f"primary={_short(primary)}; secondary={_short(secondary)}"
    )


def put_auto(object_key, data, content_type, metadata=None, cache_control=None):
    """Select a readable backend, PUT there, and fail over on write failure.

    Class-B status is checked/cached before choosing a store. This prevents the case
    where primary PUT succeeds while primary GET/HEAD is capped and customers cannot
    read the newly uploaded image.
    """
    selected, selection = select_readable_backend(force_probe=False)
    try:
        put_to_backend(
            selected,
            object_key,
            data,
            content_type,
            metadata=metadata,
            cache_control=cache_control,
        )
        return selected, selection
    except Exception as first_exc:
        # A write/config failure can happen independently of Class-B health. Mark this
        # selection stale and try the other readable backend once.
        invalidate_backend_health(selected)
        other = SECONDARY if selected == PRIMARY else PRIMARY
        other_health = probe_backend_class_b(other, force=False)
        if other_health.get('class_b_ok'):
            try:
                put_to_backend(
                    other,
                    object_key,
                    data,
                    content_type,
                    metadata=metadata,
                    cache_control=cache_control,
                )
                selection['selected'] = other
                selection['write_failover_from'] = selected
                selection['write_failover_error'] = f'{type(first_exc).__name__}: {first_exc}'
                if other == PRIMARY:
                    selection['primary'] = other_health
                else:
                    selection['secondary'] = other_health
                return other, selection
            except Exception as second_exc:
                raise RuntimeError(
                    'Both readable B2 upload attempts failed: '
                    f'{selected}: {type(first_exc).__name__}: {first_exc} | '
                    f'{other}: {type(second_exc).__name__}: {second_exc}'
                ) from second_exc
        raise RuntimeError(
            f'Selected B2 upload failed and alternate backend is not readable: '
            f'{selected}: {type(first_exc).__name__}: {first_exc}'
        ) from first_exc
