"""Signed URLs for existing shares whose original bearer token was not retained.

A link resolves to the same token row; all expiry, visibility and asset ownership
checks continue to run against that row. No token rows or images are created.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading


_KEY = None
_KEY_LOCK = threading.Lock()
_PREFIX = 'm1_'
_FORMAT = re.compile(r'm1_([0-9a-f]{64})_([A-Za-z0-9_-]{43})\Z')


def _signing_key():
    global _KEY
    if _KEY is not None:
        return _KEY
    with _KEY_LOCK:
        if _KEY is not None:
            return _KEY
        from database import get_db_connection, get_cursor, get_row_dict
        conn = get_db_connection()
        cur = get_cursor(conn)
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS cloud_share_link_keys (key_id INTEGER PRIMARY KEY, signing_key VARCHAR(64) NOT NULL)")
            cur.execute("INSERT IGNORE INTO cloud_share_link_keys (key_id, signing_key) VALUES (1, ?)", (secrets.token_hex(32),))
            conn.commit()
            cur.execute("SELECT signing_key FROM cloud_share_link_keys WHERE key_id=1")
            row = get_row_dict(cur.fetchone(), cur) or {}
            value = str(row.get('signing_key') or '')
            if not re.fullmatch(r'[0-9a-f]{64}', value):
                raise RuntimeError('Share link signing key is unavailable')
            _KEY = bytes.fromhex(value)
            return _KEY
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _signature(token_hash):
    digest = hmac.new(_signing_key(), ('order-share-directory:v1:' + token_hash).encode('ascii'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def share_link_token(token_hash):
    token_hash = str(token_hash or '')
    if not re.fullmatch(r'[0-9a-f]{64}', token_hash):
        raise ValueError('valid token_hash is required')
    return _PREFIX + token_hash + '_' + _signature(token_hash)


def share_token_hash(token):
    token = str(token or '')
    if token.startswith(_PREFIX):
        match = _FORMAT.fullmatch(token)
        if match:
            try:
                if hmac.compare_digest(match[2], _signature(match[1])):
                    return match[1]
            except RuntimeError:
                pass
    # Legacy tokens and invalid signatures use the original lookup behavior.
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
