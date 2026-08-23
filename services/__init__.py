"""Service package exports for Flask application.

Keep imports lightweight; optional ORDER runtime patches are registered explicitly by
services/order_cloud_proxy_thumb.py so importing services itself remains safe.
"""

# This package intentionally exposes modules through normal Python imports.  Do not
# eagerly import optional runtime patches here because several of them register Flask
# hooks as a side effect and their ordering is controlled elsewhere.
