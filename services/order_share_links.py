"""Signed URLs for existing shares whose original bearer token was not retained.

A link resolves to the same token row; all expiry, visibility and asset ownership
checks continue to run against that row. No token rows or images are created.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re

from flask import current_app, has_app_context

_PREFIX = 'm1_'
_FORMAT = re.compile(r'm1_([0-9a-f]{64})_([A-Za-z0-9_-]{43})\Z')


def _signature(token_hash):
    secret = current_app.secret_key
    if not secret or secret == 'dev-secret-key-change-in-production':
        raise RuntimeError('Configured SECRET_KEY is required for share links')
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    digest = hmac.new(secret, ('order-share-directory:v1:' + token_hash).encode('ascii'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def share_link_token(token_hash):
    token_hash = str(token_hash or '')
    if not re.fullmatch(r'[0-9a-f]{64}', token_hash):
        raise ValueError('valid token_hash is required')
    return _PREFIX + token_hash + '_' + _signature(token_hash)


def share_token_hash(token):
    token = str(token or '')
    if token.startswith(_PREFIX) and has_app_context():
        match = _FORMAT.fullmatch(token)
        if match:
            try:
                if hmac.compare_digest(match[2], _signature(match[1])):
                    return match[1]
            except RuntimeError:
                pass
    # Legacy tokens and invalid signatures use the original lookup behavior.
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
