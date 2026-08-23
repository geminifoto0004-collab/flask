"""Multi-B2 storage adapter for ORDER customer-share assets.

Primary credentials keep the existing B2_* environment variable names. An optional
secondary Backblaze B2 account/bucket uses B2_SECONDARY_* variables. TiDB records the
backend selected for each cloud_assets row so public reads can use the correct store.

This module is deliberately additive: existing rows without storage_backend are
migrated to b2_primary and existing primary configuration continues to work unchanged.
"""
from __future__ import annotations

import os

import boto3

from database import check_column_exists, get_cursor, get_db_connection, get_row_dict
from services import order_cloud_asset_service as asset_service

PRIMARY = 'b2_primary'
SECONDARY = 'b2_secondary'
_ALLOWED = {PRIMARY, SECONDARY}


def _env_first(*names):
    for name in names:
        value = (os.environ.get(name) or '').strip()
        if value:
            return value
    return ''


def config_for_backend(backend, required=True):
    backend = str(backend or PRIMARY).strip().lower()
    if backend not in _ALLOWED:
        backend = PRIMARY
    if backend == SECONDARY:
        cfg = {
            'backend': SECONDARY,
            'key_id': _env_first('B2_SECONDARY_KEY_ID', 'B2_2_KEY_ID'),
            'application_key': _env_first('B2_SECONDARY_APPLICATION_KEY', 'B2_2_APPLICATION_KEY'),
            'bucket_name': _env_first('B2_SECONDARY_BUCKET_NAME', 'B2_2_BUCKET_NAME'),
            'endpoint': _env_first('B2_SECONDARY_ENDPOINT', 'B2_2_ENDPOINT').rstrip('/'),
        }
    else:
        cfg = {
            'backend': PRIMARY,
            'key_id': _env_first('B2_KEY_ID'),
            'application_key': _env_first('B2_APPLICATION_KEY'),
            'bucket_name': _env_first('B2_BUCKET_NAME'),
            'endpoint': _env_first('B2_ENDPOINT').rstrip('/'),
        }
    if required:
        missing = [k for k in ('key_id', 'application_key', 'bucket_name', 'endpoint') if not cfg[k]]
        if missing:
            raise RuntimeError(f'Missing {backend} configuration: ' + ', '.join(missing))
    return cfg


def backend_ready(backend):
    cfg = config_for_backend(backend, required=False)
    return all(cfg.get(k) for k in ('key_id', 'application_key', 'bucket_name', 'endpoint'))


def client_for_backend(backend):
    cfg = config_for_backend(backend, required=True)
    return boto3.client(
        's3',
        endpoint_url=cfg['endpoint'],
        aws_access_key_id=cfg['key_id'],
        aws_secret_access_key=cfg['application_key'],
    )


def preferred_backend():
    value = (os.environ.get('ORDER_B2_PREFERRED_BACKEND') or PRIMARY).strip().lower()
    if value not in _ALLOWED:
        value = PRIMARY
    if value == SECONDARY and not backend_ready(SECONDARY):
        return PRIMARY
    return value


def _backend_order(prefer=None):
    first = str(prefer or preferred_backend()).strip().lower()
    if first not in _ALLOWED:
        first = PRIMARY
    second = SECONDARY if first == PRIMARY else PRIMARY
    order = [first]
    if backend_ready(second):
        order.append(second)
    return order


def put_to_backend(backend, object_key, data, content_type, metadata=None, cache_control=None):
    cfg = config_for_backend(backend, required=True)
    kwargs = {
        'Bucket': cfg['bucket_name'],
        'Key': object_key,
        'Body': data,
        'ContentType': content_type,
    }
    if metadata:
        kwargs['Metadata'] = metadata
    if cache_control:
        kwargs['CacheControl'] = cache_control
    client_for_backend(backend).put_object(**kwargs)
    return backend


def put_with_failover(object_key, data, content_type, metadata=None, cache_control=None, prefer=None):
    errors = []
    for backend in _backend_order(prefer):
        try:
            put_to_backend(backend, object_key, data, content_type, metadata=metadata, cache_control=cache_control)
            return backend
        except Exception as exc:
            errors.append(f'{backend}: {type(exc).__name__}: {exc}')
    raise RuntimeError('All configured B2 backends failed: ' + ' | '.join(errors))


def _ensure_storage_backend_column():
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        if not check_column_exists(cur, 'cloud_assets', 'storage_backend'):
            cur.execute("ALTER TABLE cloud_assets ADD COLUMN storage_backend VARCHAR(32) NULL")
        cur.execute("UPDATE cloud_assets SET storage_backend=? WHERE storage_backend IS NULL OR storage_backend=''", (PRIMARY,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_asset_metadata_multi(order_number, workflow_key, sha256_hex, object_key,
                                content_type, file_size, source_site=None,
                                storage_backend=PRIMARY):
    _ensure_storage_backend_column()
    storage_backend = str(storage_backend or PRIMARY).strip().lower()
    if storage_backend not in _ALLOWED:
        storage_backend = PRIMARY

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        order_number, customer_key, workflow_key = asset_service._resolve_order_and_workflow(cur, order_number, workflow_key)
        asset_key = asset_service._asset_key(order_number, workflow_key, sha256_hex)
        display_name = f'Imagen {order_number}'
        source_site = str(source_site or '').strip().upper()[:16] or None

        cur.execute('SELECT asset_key FROM cloud_assets WHERE asset_key=?', (asset_key,))
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_assets
                   SET customer_key=?, order_number=?, workflow_key=?, asset_type='IMAGE',
                       sha256=?, object_key=?, content_type=?, file_size=?, display_name=?,
                       source_site=?, storage_backend=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                   WHERE asset_key=?""",
                (customer_key, order_number, workflow_key, sha256_hex, object_key,
                 content_type, int(file_size), display_name, source_site,
                 storage_backend, asset_key),
            )
        else:
            cur.execute(
                """INSERT INTO cloud_assets
                   (customer_key, order_number, workflow_key, asset_type, sha256,
                    object_key, content_type, file_size, display_name, source_site,
                    storage_backend, asset_key)
                   VALUES (?, ?, ?, 'IMAGE', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (customer_key, order_number, workflow_key, sha256_hex, object_key,
                 content_type, int(file_size), display_name, source_site,
                 storage_backend, asset_key),
            )
        conn.commit()
        return {
            'asset_key': asset_key,
            'customer_key': customer_key,
            'order_number': order_number,
            'workflow_key': workflow_key,
            'asset_type': 'IMAGE',
            'sha256': sha256_hex,
            'content_type': content_type,
            'file_size': int(file_size),
            'display_name': display_name,
            'source_site': source_site,
            'storage_backend': storage_backend,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_customer_assets_multi(customer_key):
    _ensure_storage_backend_column()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, content_type, file_size, display_name, source_site,
                      storage_backend, updated_at
               FROM cloud_assets WHERE customer_key=? AND active=TRUE
               ORDER BY order_number, created_at, asset_key""",
            (customer_key,),
        )
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def get_asset_multi(asset_key):
    asset_key = str(asset_key or '').strip().lower()
    if not asset_service.re.fullmatch(r'[0-9a-f]{64}', asset_key):
        return None
    _ensure_storage_backend_column()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT asset_key, customer_key, order_number, workflow_key, asset_type,
                      sha256, object_key, content_type, file_size, display_name, source_site,
                      storage_backend
               FROM cloud_assets WHERE asset_key=? AND active=TRUE""",
            (asset_key,),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None
    finally:
        conn.close()


def storage_backend_for_sha(sha256_hex):
    _ensure_storage_backend_column()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT storage_backend FROM cloud_assets
               WHERE sha256=? AND active=TRUE
               ORDER BY updated_at DESC LIMIT 1""",
            (sha256_hex,),
        )
        row = cur.fetchone()
        data = get_row_dict(row, cur) if row else None
        backend = str((data or {}).get('storage_backend') or PRIMARY).strip().lower()
        return backend if backend in _ALLOWED else PRIMARY
    finally:
        conn.close()


def presigned_get_for_asset(asset, seconds=900, object_key=None):
    backend = str((asset or {}).get('storage_backend') or PRIMARY).strip().lower()
    if backend not in _ALLOWED:
        backend = PRIMARY
    cfg = config_for_backend(backend, required=True)
    key = object_key or asset['object_key']
    return client_for_backend(backend).generate_presigned_url(
        'get_object', Params={'Bucket': cfg['bucket_name'], 'Key': key}, ExpiresIn=int(seconds)
    )


def read_private_asset_multi(asset):
    if not asset or not asset.get('object_key'):
        raise ValueError('asset not found')
    backend = str(asset.get('storage_backend') or PRIMARY).strip().lower()
    cfg = config_for_backend(backend, required=True)
    obj = client_for_backend(backend).get_object(Bucket=cfg['bucket_name'], Key=asset['object_key'])
    return obj['Body'].read(), (obj.get('ContentType') or asset.get('content_type') or 'application/octet-stream')


# Runtime compatibility layer for code that dynamically imports these functions.
asset_service._upsert_asset_metadata = upsert_asset_metadata_multi
asset_service.list_customer_assets = list_customer_assets_multi
asset_service.get_asset = get_asset_multi
asset_service.read_private_asset = read_private_asset_multi
