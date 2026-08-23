# Services package
# Keep this file intentionally small: service modules are imported explicitly by app/blueprints.
# ORDER hot-path patches register themselves through services/order_cloud_proxy_thumb.py and
# the normal b2_test blueprint bootstrap; do not replace the package API here.
