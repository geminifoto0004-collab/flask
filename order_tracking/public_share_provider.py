"""Public customer-share provider interface.

The shared package deliberately contains no B2/TiDB credentials and no concrete cloud
client. The overseas parent Flask app registers a provider only when deployment security
flags permit it. Credentials stay outside this source tree and can be revoked externally.
"""
from __future__ import annotations
import sys
from flask import current_app
from .config import (
    PUBLIC_SHARE_PROVIDER_READY,
    RENDER_PUBLIC_GUEST_ENABLED,
    PERMANENT_PUBLIC_GUEST_ENABLED,
)

_KEY = 'order_tracking_public_share_provider'


def _sync_runtime_feature_flags(app):
    """Keep the already-imported order_tracking package in sync with parent Flask flags.

    ``order_tracking.__init__`` imports the deployment flags at module import time.  An
    overseas parent Flask (for example FlaskApp2025) intentionally enables cloud sharing
    later, when it registers its external Render provider.  Mirror those runtime values
    into the package globals so the admin share UI immediately reflects the provider that
    is actually registered, without forcing China/local standalone ORDER deployments on.
    """
    package = sys.modules.get(__package__)
    if package is None:
        return
    package.RENDER_PUBLIC_GUEST_ENABLED = bool(
        app.config.get('TRACKING_RENDER_PUBLIC_GUEST_ENABLED', RENDER_PUBLIC_GUEST_ENABLED)
    )
    package.PERMANENT_PUBLIC_GUEST_ENABLED = bool(
        app.config.get('TRACKING_PERMANENT_PUBLIC_GUEST_ENABLED', PERMANENT_PUBLIC_GUEST_ENABLED)
    )
    package.PUBLIC_SHARE_PROVIDER_READY = bool(
        app.config.get('TRACKING_PUBLIC_SHARE_PROVIDER_READY', PUBLIC_SHARE_PROVIDER_READY)
    )


def register_public_share_provider(app, provider):
    allowed = bool(app.config.get('TRACKING_PUBLIC_SHARE_PROVIDER_READY', PUBLIC_SHARE_PROVIDER_READY))
    if not allowed:
        raise RuntimeError('Public share provider is disabled by deployment security policy')
    secret = str(getattr(app, 'secret_key', '') or '')
    if not secret or secret.startswith('your-secret-key-change-in-production'):
        raise RuntimeError('Public share provider requires a non-default Flask SECRET_KEY from the deployment secret store')
    app.extensions[_KEY] = provider
    _sync_runtime_feature_flags(app)


def get_public_share_provider():
    return current_app.extensions.get(_KEY)


def public_share_provider_ready():
    return get_public_share_provider() is not None


def create_public_share(payload, creator):
    provider = get_public_share_provider()
    fn = getattr(provider, 'create_share', None) if provider is not None else None
    if not callable(fn):
        raise RuntimeError('Public share provider does not implement create_share')
    return fn(dict(payload or {}), dict(creator or {}))


def list_public_shares():
    provider = get_public_share_provider()
    fn = getattr(provider, 'list_active_shares', None) if provider is not None else None
    if not callable(fn):
        return []
    value = fn()
    return list(value or [])


def update_public_share(share_id, payload):
    """Update mutable settings on an existing public share.

    The concrete Render/provider implementation may expose ``update_share``.  Keeping
    the wrapper optional preserves compatibility with older deployments while letting
    the admin UI change password protection without recreating a link.
    """
    provider = get_public_share_provider()
    fn = getattr(provider, 'update_share', None) if provider is not None else None
    if not callable(fn):
        raise RuntimeError('Public share provider does not implement update_share')
    return fn(share_id, dict(payload or {}))


def revoke_public_share(share_id):
    provider = get_public_share_provider()
    fn = getattr(provider, 'revoke_share', None) if provider is not None else None
    if not callable(fn):
        raise RuntimeError('Public share provider does not implement revoke_share')
    return fn(share_id)


def sync_due_public_shares():
    provider = get_public_share_provider()
    fn = getattr(provider, 'sync_due_permanent_shares', None) if provider is not None else None
    if not callable(fn):
        return {'synced': 0, 'skipped': True}
    return fn()
