"""Create one public token per customer, safely reusing the active share."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import threading

from database import get_cursor, get_db_connection, get_row_dict
from services.order_share_links import share_link_token

_LOCK = threading.Lock()


class ShareCreateConflict(ValueError):
    pass


def _connection_driver(connection):
    """Find the raw DB-API driver behind ORDER and DBUtils connection wrappers."""
    current = connection
    # Render may return CloudMirroredConnection -> AdaptedConnection ->
    # DBUtils.PooledDedicatedDBConnection -> pymysql.Connection. The pool
    # wrapper exposes the actual driver connection as _con; stopping at
    # DBUtils.PooledDB would skip TiDB's SELECT ... FOR UPDATE guard.
    for _ in range(8):
        next_connection = None
        for attribute in ('_active', '_conn', '_con'):
            try:
                candidate = getattr(current, attribute, None)
            except Exception:
                candidate = None
            if candidate is not None and candidate is not current:
                next_connection = candidate
                break
        if next_connection is None:
            break
        current = next_connection
    return str(current.__class__.__module__ or '')


def _as_naive_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def create_live_share(customer_key, source_site=None, expires_hours=24, permanent=False,
                      history_scope='current', include_cancelled=False, status_filter_mode='simple',
                      show_pdf_pages=True, allow_report_pdf_download=False, show_images=True,
                      show_workflow_images=True, requested_token=None):
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        raise ValueError('customer_key is required')

    if requested_token is not None:
        if not isinstance(requested_token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', requested_token):
            raise ValueError('requested_token must contain 32..128 URL-safe characters')
        raw_token = requested_token
    else:
        raw_token = None

    site = str(source_site or '').upper()[:16] or None
    scope = str(history_scope or 'current').strip().lower()
    if scope not in {'current', '3m', '6m', '12m', 'all'}:
        scope = 'current'
    mode = 'full' if str(status_filter_mode or '').strip().lower() == 'full' else 'simple'
    if permanent:
        expires_at = None
    else:
        try:
            hours = int(expires_hours or 24)
        except (TypeError, ValueError):
            raise ValueError('expires_hours must be an integer')
        if hours < 1 or hours > 8760:
            raise ValueError('expires_hours must be between 1 and 8760')
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    def existing_by_token(cur, token_hash):
        cur.execute(
            'SELECT token_hash, customer_key, source_site, status, expires_at, history_scope, '
            'status_filter_mode, show_pdf_pages, allow_report_pdf_download, show_images, '
            'show_workflow_images FROM cloud_share_tokens WHERE token_hash=? LIMIT 1',
            (token_hash,),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None

    def existing_active_customer(cur, now):
        cur.execute(
            """SELECT token_hash, customer_key, source_site, status, expires_at, history_scope,
                      status_filter_mode, show_pdf_pages, allow_report_pdf_download, show_images,
                      show_workflow_images
               FROM cloud_share_tokens
               WHERE customer_key=? AND status='active'
                 AND (expires_at IS NULL OR expires_at>?)
               ORDER BY created_at ASC, token_hash ASC
               LIMIT 1""",
            (customer_key, now),
        )
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None

    def response(row, token_value, repeated=False, reused_customer=False):
        if str(row.get('customer_key') or '') != customer_key:
            raise ShareCreateConflict('requested token belongs to another customer')
        if site not in {None, 'LEGACY', 'ORDER'} and row.get('source_site') not in {None, site}:
            raise ShareCreateConflict('requested token belongs to another source')
        expiry = _as_naive_utc(row.get('expires_at'))
        if str(row.get('status') or '') != 'active' or (expiry and expiry <= datetime.utcnow()):
            raise ShareCreateConflict('requested token is revoked or expired')
        return {
            'token': token_value,
            'share_id': str(row.get('token_hash') or ''),
            'customer_key': customer_key,
            'expires_at': expiry,
            'history_scope': row.get('history_scope') or 'current',
            'status_filter_mode': row.get('status_filter_mode') or 'simple',
            'show_pdf_pages': True if row.get('show_pdf_pages') is None else bool(row.get('show_pdf_pages')),
            'allow_report_pdf_download': bool(row.get('allow_report_pdf_download')),
            'show_images': True if row.get('show_images') is None else bool(row.get('show_images')),
            'show_workflow_images': True if row.get('show_workflow_images') is None else bool(row.get('show_workflow_images')),
            'include_cancelled': False,
            'idempotent_create': True,
            'reused_token': bool(repeated or reused_customer),
            'reused_customer_share': bool(reused_customer),
        }

    with _LOCK:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            # SQLite gets a write reservation before checking; TiDB locks the
            # canonical customer row. This closes the check-then-insert race.
            driver = _connection_driver(conn)
            if driver.startswith('sqlite3'):
                conn.execute('BEGIN IMMEDIATE')

            if raw_token is not None:
                token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
                row = existing_by_token(cur, token_hash)
                if row:
                    result = response(row, raw_token, True, False)
                    conn.commit()
                    return result

            if driver.startswith(('pymysql', 'mysql')):
                cur.execute(
                    'SELECT customer_key FROM cloud_customers '
                    'WHERE customer_key=? AND active=TRUE LIMIT 1 FOR UPDATE',
                    (customer_key,),
                )
            else:
                cur.execute(
                    'SELECT customer_key FROM cloud_customers '
                    'WHERE customer_key=? AND active=TRUE LIMIT 1',
                    (customer_key,),
                )
            if not cur.fetchone():
                raise ValueError('customer not found')

            now = datetime.utcnow()
            row = existing_active_customer(cur, now)
            if row:
                # Raw tokens are intentionally not stored. A signed directory URL
                # deterministically resolves to the same token row and keeps the
                # original customer URL working.
                signed_token = share_link_token(str(row.get('token_hash') or ''))
                result = response(row, signed_token, True, True)
                conn.commit()
                return result

            if raw_token is None:
                raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
            row = {
                'customer_key': customer_key,
                'source_site': site,
                'status': 'active',
                'expires_at': expires_at,
                'history_scope': scope,
                'status_filter_mode': mode,
                'show_pdf_pages': show_pdf_pages,
                'allow_report_pdf_download': allow_report_pdf_download,
                'show_images': show_images,
                'show_workflow_images': show_workflow_images,
            }
            try:
                cur.execute(
                    'INSERT INTO cloud_share_tokens '
                    '(token_hash, customer_key, mode, status, source_site, history_scope, status_filter_mode, '
                    'show_pdf_pages, allow_report_pdf_download, show_images, show_workflow_images, include_cancelled, expires_at) '
                    "VALUES (?, ?, 'LIVE', 'active', ?, ?, ?, ?, ?, ?, ?, FALSE, ?)",
                    (token_hash, customer_key, site, scope, mode, bool(show_pdf_pages),
                     bool(allow_report_pdf_download), bool(show_images), bool(show_workflow_images), expires_at),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                recovered = existing_by_token(cur, token_hash)
                if recovered:
                    return response(recovered, raw_token, True, False)
                # A concurrent request from another worker may have created the
                # customer's active share using a different token.
                recovered_customer = existing_active_customer(cur, datetime.utcnow())
                if recovered_customer:
                    signed_token = share_link_token(str(recovered_customer.get('token_hash') or ''))
                    return response(recovered_customer, signed_token, True, True)
                raise
            return response(row | {'token_hash': token_hash}, raw_token, False, False)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
