"""Legacy compatibility shim for ORDER direct-upload backend recovery.

Cross-backend retry is intentionally retired. The active production policy lives in
``order_cloud_customer_storage`` and pins every new image to one customer-assigned B2.
An existing TiDB asset is reused as-is even if that backend is temporarily unreadable;
timeout/403 therefore never means "upload the same bytes to the other B2".

This module remains importable so older service-registration code does not break.
"""
