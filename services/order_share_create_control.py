"""Create one public token in a short transaction, safely repeatable by token hash."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import re
import secrets
import threading

from database import get_cursor, get_db_connection, get_row_dict

_LOCK = threading.Lock()


class ShareCreateConflict(ValueError):
    pass


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
        raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    site = str(source_site or '').upper()[:16] or None
    history_scope = str(history_scope or 'current')
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

    def existing(cur):
        cur.execute('SELECT token_hash, customer_key, source_site, status, expires_at, history_scope, '
                    'status_filter_mode, show_pdf_pages, allow_report_pdf_download, show_images, '
                    'show_workflow_images FROM cloud_share_tokens WHERE token_hash=? LIMIT 1', (token_hash,))
        row = cur.fetchone()
        return get_row_dict(row, cur) if row else None

    def response(row, repeated=False):
        if str(row.get('customer_key') or '') != customer_key:
            raise ShareCreateConflict('requested token belongs to another customer')
        if site not in {None, 'LEGACY', 'ORDER'} and row.get('source_site') not in {None, site}:
            raise ShareCreateConflict('requested token belongs to another source')
        expiry = row.get('expires_at')
        if expiry and isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00')).replace(tzinfo=None)
        if str(row.get('status') or '') != 'active' or (expiry and expiry <= datetime.utcnow()):
            raise ShareCreateConflict('requested token is revoked or expired')
        return {'token': raw_token, 'share_id': token_hash, 'customer_key': customer_key,
                'expires_at': expiry, 'history_scope': row.get('history_scope') or 'current',
                'status_filter_mode': row.get('status_filter_mode') or 'simple',
                'show_pdf_pages': bool(row.get('show_pdf_pages')),
                'allow_report_pdf_download': bool(row.get('allow_report_pdf_download')),
                'show_images': bool(row.get('show_images')),
                'show_workflow_images': bool(row.get('show_workflow_images')),
                'include_cancelled': False, 'idempotent_create': True, 'reused_token': repeated}

    # A unique token_hash remains the cross-process guard. The local lock avoids
    # contention between threads in one worker; duplicate INSERTs elsewhere are read back.
    with _LOCK:
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            row = existing(cur)
            if row:
                return response(row, True)
            cur.execute('SELECT customer_key FROM cloud_customers WHERE customer_key=? AND active=TRUE LIMIT 1',
                        (customer_key,))
            if not cur.fetchone():
                raise ValueError('customer not found')
            row = {'customer_key': customer_key, 'source_site': site, 'status': 'active',
                   'expires_at': expires_at, 'history_scope': history_scope, 'status_filter_mode': mode,
                   'show_pdf_pages': show_pdf_pages, 'allow_report_pdf_download': allow_report_pdf_download,
                   'show_images': show_images, 'show_workflow_images': show_workflow_images}
            try:
                cur.execute('INSERT INTO cloud_share_tokens '
                            '(token_hash, customer_key, mode, status, source_site, history_scope, status_filter_mode, '
                            'show_pdf_pages, allow_report_pdf_download, show_images, show_workflow_images, include_cancelled, expires_at) '
                            "VALUES (?, ?, 'LIVE', 'active', ?, ?, ?, ?, ?, ?, ?, FALSE, ?)",
                            (token_hash, customer_key, site, history_scope, mode, bool(show_pdf_pages),
                             bool(allow_report_pdf_download), bool(show_images), bool(show_workflow_images), expires_at))
                conn.commit()
            except Exception:
                conn.rollback()
                recovered = existing(cur)
                if recovered:
                    return response(recovered, True)
                raise
            return response(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
