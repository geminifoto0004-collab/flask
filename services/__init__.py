# Service package bootstrap.
#
# ORDER public share hot-path interception must be imported before the legacy/multi-B2
# public media hooks so /share/<token> and /share/<token>/(image|asset|thumb)/... use
# the cached token/customer/asset lookups first.  Remaining modules keep their own
# fallback routes and upload/health logic.

try:
    from . import order_public_share_fast  # noqa: F401
except Exception as exc:
    print(f'[WARN] ORDER public share fast bootstrap failed: {exc}')

# Preserve the repository's optional service patch imports.  Each module is isolated
# so a missing optional dependency cannot prevent the parent Flask app from starting.
_OPTIONAL_ORDER_MODULES = (
    'order_cloud_sigv4_patch',
    'order_cloud_multi_b2_auto',
    'order_cloud_direct_reuse_health',
    'order_cloud_backend_health',
    'order_cloud_nohead_upload',
    'order_cloud_proxy_thumb',
    'order_cloud_multi_b2_public',
    'order_public_share_multi_b2_page',
    'order_share_live_refresh',
    'order_cloud_wan_storage_summary',
    'order_wan_compat_diagnostics',
)

import importlib as _importlib
for _name in _OPTIONAL_ORDER_MODULES:
    try:
        _importlib.import_module(f'{__name__}.{_name}')
    except Exception as _exc:
        print(f'[WARN] optional service {_name} bootstrap failed: {_exc}')
