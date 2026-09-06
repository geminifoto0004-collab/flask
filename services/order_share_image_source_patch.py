"""Source-level image visibility for ORDER public shares.

`show_images` means supervisor/order reference images (workflow_key is empty).
`show_workflow_images` controls salesperson/workflow images (workflow_key is set).
Existing links default salesperson images to visible.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time

from flask import Response, jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _ensure_order_cloud_tables, _order_cloud_auth_source
from database import check_column_exists, get_cursor, get_db_connection, get_row_dict
from services import order_public_share_fast as _fast
from services import order_public_share_multi_b2_page as _page
from services.order_share_image_policy import (
    asset_allowed as _asset_allowed,
    bool_default as _bool_default,
    filter_assets_in_space as _filter_assets_in_space,
)

try:
    from services import order_share_visibility_live_patch as _visibility
except Exception:
    _visibility = None
try:
    from services import order_share_render_cache as _html_cache
except Exception:
    _html_cache = None
try:
    from services import order_customer_share_hot_cache as _hot
except Exception:
    _hot = None

_LOCK = threading.RLock()
_CACHE = {}
_TTL = 60.0

_BASE_LOAD = getattr(_visibility, '_ORIG_LOAD', _page._load_page_data)
_BASE_RESOLVE = getattr(_visibility, '_ORIG_RESOLVE', _fast._resolve_share)
_BASE_FILTER = getattr(_visibility, '_ORIG_FILTER', _fast._filter_space)
_BASE_ASSET = getattr(_visibility, '_ORIG_ASSET', _fast._asset_for_share)
_BASE_RENDER = _page.render_template


def _ensure_columns():
    _ensure_order_cloud_tables()
    try:
        _fast._ensure_share_columns()
    except Exception:
        pass
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        if not check_column_exists(cur, 'cloud_share_tokens', 'show_workflow_images'):
            cur.execute("ALTER TABLE cloud_share_tokens ADD COLUMN show_workflow_images BOOLEAN NOT NULL DEFAULT TRUE")
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def _scope(value):
    return _fast._scope(value)


def _mode(value):
    return _fast._status_filter_mode(value)


def _settings(token):
    token = str(token or '').strip()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(token_hash)
        if item and item[0] > now:
            return dict(item[1])
    _ensure_columns()
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT history_scope, status_filter_mode, show_pdf_pages,
                      allow_report_pdf_download, show_images, show_workflow_images,
                      include_cancelled
               FROM cloud_share_tokens WHERE token_hash=? LIMIT 1""",
            (token_hash,),
        )
        row = cur.fetchone(); data = get_row_dict(row, cur) if row else {}
    finally:
        conn.close()
    result = {
        'history_scope': _scope(data.get('history_scope')),
        'status_filter_mode': _mode(data.get('status_filter_mode')),
        'show_pdf_pages': _bool_default(data.get('show_pdf_pages'), True),
        'allow_report_pdf_download': _bool_default(data.get('allow_report_pdf_download'), False),
        'show_images': _bool_default(data.get('show_images'), True),
        'show_workflow_images': _bool_default(data.get('show_workflow_images'), True),
        'include_cancelled': False,
    }
    with _LOCK:
        _CACHE[token_hash] = (now + _TTL, dict(result))
    return result


def _drop_caches(token):
    token = str(token or '').strip()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with _LOCK:
        _CACHE.pop(token_hash, None)
    try:
        if _visibility is not None:
            with _visibility._LOCK:
                _visibility._SETTINGS.pop(token_hash, None)
    except Exception:
        pass
    try:
        with _fast._cache_lock:
            _fast._share_cache.pop(token, None)
    except Exception:
        pass
    try:
        with _page._cache_lock:
            _page._token_cache.pop(token, None)
            if _hot is not None:
                _hot._HASH_TOKEN_CACHE.pop(token_hash, None)
    except Exception:
        pass
    try:
        if _html_cache is not None:
            with _html_cache._LOCK:
                _html_cache._TOKEN_HTML.pop(token_hash, None)
    except Exception:
        pass


def _load_page(token):
    share, bundle, error = _BASE_LOAD(token)
    if error or not share:
        return share, bundle, error
    try:
        settings = _settings(token)
        share = dict(share); share.update(settings)
        if bundle:
            bundle = copy.deepcopy(bundle)
            space = bundle.get('space') if isinstance(bundle, dict) and isinstance(bundle.get('space'), dict) else bundle
            _filter_assets_in_space(space, settings)
    except Exception as exc:
        print(f'[WARN] ORDER image-source settings unavailable: {type(exc).__name__}: {exc}')
        return share, None, Response('Servicio temporalmente no disponible.', 503, mimetype='text/plain')
    return share, bundle, error


def _resolve_share(token):
    share, state = _BASE_RESOLVE(token)
    if share:
        share = dict(share); share.update(_settings(token))
    return share, state


def _filter_space(space, share):
    result = _BASE_FILTER(space, share)
    target = result if isinstance(result, dict) else space
    settings = {
        'show_pdf_pages': _bool_default((share or {}).get('show_pdf_pages'), True),
        'show_images': _bool_default((share or {}).get('show_images'), True),
        'show_workflow_images': _bool_default((share or {}).get('show_workflow_images'), True),
    }
    _filter_assets_in_space(target, settings)
    return result


def _asset_for_share(token, asset_key):
    share, asset, error = _BASE_ASSET(token, asset_key)
    if error or not share:
        return share, asset, error
    try:
        settings = _settings(token)
        share = dict(share); share.update(settings)
        if not _asset_allowed(asset, settings):
            return share, None, Response('Archivo no encontrado.', 404, mimetype='text/plain')
    except Exception:
        pass
    return share, asset, error


def _create_scoped_share():
    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_columns()
        payload = request.get_json(silent=True) or {}
        from services.order_cloud_service import create_live_share
        scope = _scope(payload.get('history_scope'))
        mode = _mode(payload.get('status_filter_mode'))
        show_pdf = _bool_default(payload.get('show_pdf_pages'), True)
        allow_report = _bool_default(payload.get('allow_report_pdf_download'), False)
        show_supervisor = _bool_default(payload.get('show_images'), True)
        show_workflow = _bool_default(payload.get('show_workflow_images'), True)
        result = create_live_share(
            payload.get('customer_key'), source_site=source_site,
            expires_hours=payload.get('expires_hours', 24),
            permanent=bool(payload.get('permanent', False)),
            history_scope=scope, include_cancelled=False, status_filter_mode=mode,
            show_pdf_pages=show_pdf, allow_report_pdf_download=allow_report,
            show_images=show_supervisor,
        )
        token = result.pop('token')
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        conn = get_db_connection(); cur = get_cursor(conn)
        try:
            cur.execute(
                """UPDATE cloud_share_tokens
                   SET history_scope=?, status_filter_mode=?, show_pdf_pages=?,
                       allow_report_pdf_download=?, show_images=?, show_workflow_images=?,
                       include_cancelled=FALSE
                   WHERE token_hash=?""",
                (scope, mode, show_pdf, allow_report, show_supervisor, show_workflow, token_hash),
            )
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
        expiry = result.get('expires_at')
        result['expires_at'] = expiry.isoformat() if hasattr(expiry, 'isoformat') else expiry
        result.update({
            'history_scope': scope, 'status_filter_mode': mode,
            'show_pdf_pages': show_pdf,
            'allow_report_pdf_download': allow_report,
            'show_images': show_supervisor,
            'show_workflow_images': show_workflow,
            'include_cancelled': False,
            'share_url': request.host_url.rstrip('/') + '/share/' + token,
        })
        _drop_caches(token)
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def _update_share_settings():
    _source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        _ensure_columns()
        payload = request.get_json(silent=True) or {}
        token = str(payload.get('token') or '').strip()
        if not token:
            return jsonify({'ok': False, 'error': 'token is required'}), 400
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        scope = _scope(payload.get('history_scope'))
        mode = _mode(payload.get('status_filter_mode'))
        show_pdf = _bool_default(payload.get('show_pdf_pages'), True)
        allow_report = _bool_default(payload.get('allow_report_pdf_download'), False)
        show_supervisor = _bool_default(payload.get('show_images'), True)
        show_workflow = _bool_default(payload.get('show_workflow_images'), True)
        conn = get_db_connection(); cur = get_cursor(conn)
        try:
            cur.execute("SELECT customer_key FROM cloud_share_tokens WHERE token_hash=? AND status='active' LIMIT 1", (token_hash,))
            row = cur.fetchone()
            if not row:
                return jsonify({'ok': False, 'error': 'active share not found'}), 404
            customer_key = str((get_row_dict(row, cur) or {}).get('customer_key') or '')
            cur.execute(
                """UPDATE cloud_share_tokens
                   SET history_scope=?, status_filter_mode=?, show_pdf_pages=?,
                       allow_report_pdf_download=?, show_images=?, show_workflow_images=?,
                       include_cancelled=FALSE
                   WHERE token_hash=? AND status='active'""",
                (scope, mode, show_pdf, allow_report, show_supervisor, show_workflow, token_hash),
            )
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
        _drop_caches(token)
        return jsonify({'ok': True, 'result': {
            'share_id': token_hash, 'customer_key': customer_key,
            'history_scope': scope, 'status_filter_mode': mode,
            'show_pdf_pages': show_pdf,
            'allow_report_pdf_download': allow_report,
            'show_images': show_supervisor,
            'show_workflow_images': show_workflow,
            'include_cancelled': False,
        }})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def _render_template(template_name, *args, **kwargs):
    if template_name == 'customer_share_live_fast.html':
        share = kwargs.get('share') or {}
        # Render from a filtered copy even when an older renderer was captured
        # before the source-specific visibility patch was installed.
        kwargs['space'] = _filter_assets_in_space(copy.deepcopy(kwargs.get('space') or {}), share)
        show_supervisor = _bool_default(share.get('show_images'), True)
        show_workflow = _bool_default(share.get('show_workflow_images'), True)
        if not (show_supervisor and show_workflow) and _html_cache is not None:
            try:
                return _html_cache._ORIGINAL_RENDER_TEMPLATE(template_name, *args, **kwargs)
            except Exception:
                pass
    return _BASE_RENDER(template_name, *args, **kwargs)


_fast._create_scoped_share = _create_scoped_share
_fast._update_share_settings = _update_share_settings
_fast._resolve_share = _resolve_share
_fast._filter_space = _filter_space
_fast._asset_for_share = _asset_for_share
_page._load_page_data = _load_page
_page.render_template = _render_template


@b2_test_bp.record_once
def _order_share_image_source_startup(state):
    try:
        with state.app.app_context():
            _ensure_columns()
        print('[ORDER] share image-source visibility ready')
    except Exception as exc:
        print(f'[WARN] share image-source migration skipped: {type(exc).__name__}: {exc}')
