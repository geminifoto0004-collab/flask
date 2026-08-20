"""External order-data provider hook used by the legacy Render cloud mode.

Unified LAN/WAN ORDER no longer needs this provider path: the exact LAN routes run
against SQLite locally and the TiDB mirror remotely through db_backend/db_compat.
The legacy provider registration is kept temporarily so existing deployments can
roll back safely.
"""
from __future__ import annotations

from typing import Any, Optional

from flask import current_app

from .config import TIDB_PROVIDER_ENABLED
from .runtime_mode import unified_remote_db_enabled

_EXTENSION_KEY = "order_tracking_data_provider"


class OrderDataProvider:
    def load_home_orders(self, role: str, user_id: Any):  # pragma: no cover
        raise NotImplementedError

    def get_workflows_for_order(self, order_number: str, role: str = 'viewer', user_id: Any = None):  # pragma: no cover
        raise NotImplementedError

    def get_order_detail(self, order_number: str):  # pragma: no cover
        raise NotImplementedError

    def get_workflow_detail(self, workflow_number: str):  # pragma: no cover
        raise NotImplementedError

    def search_customers(self, query: str, limit: int = 10):  # pragma: no cover
        raise NotImplementedError

    def get_customer_history(self, customer_name: str, history_scope: str = 'current',
                             include_cancelled: bool = False, role: str = 'viewer',
                             user_id: Any = None):  # pragma: no cover
        raise NotImplementedError

    def get_last_synced_at(self) -> Optional[str]:
        return None


def register_order_data_provider(app, provider: Any) -> None:
    allowed = bool(app.config.get("TRACKING_TIDB_PROVIDER_ENABLED", TIDB_PROVIDER_ENABLED))
    if not allowed:
        raise RuntimeError("TiDB/order cloud provider is disabled by deployment security policy")
    app.extensions[_EXTENSION_KEY] = provider


def get_order_data_provider() -> Any:
    # In unified WAN mode, deliberately ignore any legacy provider that the parent
    # Flask app may still register. This sends every ORDER GET route down the same
    # code path used on LAN.
    if unified_remote_db_enabled():
        return None
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
