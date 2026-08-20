"""External order-data provider hook used by Render cloud mode.

This module intentionally contains no TiDB/MySQL imports. The parent Flask app
owns any cloud database client and registers a provider object with this package.
That keeps the China/local shared order_tracking package storage-agnostic.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from flask import current_app

from .config import TIDB_PROVIDER_ENABLED

_EXTENSION_KEY = "order_tracking_data_provider"


class OrderDataProvider:
    """Minimal interface for a cloud order summary provider.

    A provider should implement ``load_home_orders(role, user_id)`` and may
    implement ``get_last_synced_at()``. The provider is responsible for enforcing
    visibility mapping that is specific to its deployment (for example mapping a
    Render sales account to a local salesperson identity).
    """

    def load_home_orders(self, role: str, user_id: Any):  # pragma: no cover - interface only
        raise NotImplementedError

    # The methods below let the exact same ORDER routes/UI run against a cloud
    # mirror. Local/LAN deployments do not register a provider, so they keep
    # using the original SQLite code paths unchanged.
    def get_workflows_for_order(self, order_number: str, role: str = 'viewer',
                                user_id: Any = None):  # pragma: no cover - interface only
        raise NotImplementedError

    def get_order_detail(self, order_number: str):  # pragma: no cover - interface only
        raise NotImplementedError

    def get_workflow_detail(self, workflow_number: str):  # pragma: no cover - interface only
        raise NotImplementedError

    def search_customers(self, query: str, limit: int = 10):  # pragma: no cover - interface only
        raise NotImplementedError

    def get_customer_history(self, customer_name: str, history_scope: str = 'current',
                             include_cancelled: bool = False, role: str = 'viewer',
                             user_id: Any = None):  # pragma: no cover - interface only
        raise NotImplementedError

    def get_last_synced_at(self) -> Optional[str]:
        return None


def register_order_data_provider(app, provider: Any) -> None:
    """Register an external provider only when this deployment is authorized.

    Source code alone never enables TiDB access. The overseas/Render deployment must
    explicitly opt in through an environment-backed config flag, and the concrete
    provider still needs its own external credentials.
    """
    allowed = bool(app.config.get("TRACKING_TIDB_PROVIDER_ENABLED", TIDB_PROVIDER_ENABLED))
    if not allowed:
        raise RuntimeError("TiDB/order cloud provider is disabled by deployment security policy")
    app.extensions[_EXTENSION_KEY] = provider


def get_order_data_provider() -> Any:
    return current_app.extensions.get(_EXTENSION_KEY)


def provider_ready() -> bool:
    return get_order_data_provider() is not None


def provider_last_synced_at() -> Optional[str]:
    provider = get_order_data_provider()
    if provider is None:
        return None
    getter = getattr(provider, "get_last_synced_at", None)
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception:
        return None
    return None if value is None else str(value)
