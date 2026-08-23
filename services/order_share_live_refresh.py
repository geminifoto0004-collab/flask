"""Compatibility module: ORDER share live polling is intentionally retired.

The formal share page is a one-shot TiDB render.  It does not poll asset-state every
five seconds and does not perform request-time storage/schema maintenance.  Images are
lazy-loaded individually through the token-authorized /image/<asset_key> redirect.

This module remains importable so older service registration code does not break.
"""
