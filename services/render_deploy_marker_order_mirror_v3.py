"""No-op deploy marker for Render ORDER mirror v3.

This module is intentionally not imported. Its only purpose is to create a source-tree
commit so Render auto-deploy can pick up the latest ORDER mirror transport changes.
"""
ORDER_MIRROR_DEPLOY_MARKER = "v3-per-table-staging"
