# -*- coding: utf-8 -*-
"""OWNER assignment helpers for Aduana Monitor.

OWNER is persisted in the Aduana users table so the parent XINGWANG admin can
assign it without adding another Render environment variable.
"""
from __future__ import annotations

from . import settings, storage


def get_owner():
    storage.ensure_schema()
    with storage.transaction() as (_conn, cur):
        cur.execute(
            "SELECT * FROM aduana_users WHERE role='OWNER' ORDER BY approved_at DESC, id ASC LIMIT 1"
        )
        return storage._row_dict(cur.fetchone())


def promote_to_owner(user_id):
    """Promote one existing Telegram user to the single Aduana OWNER role.

    Refuses to replace an existing different OWNER silently. This avoids an
    accidental click transferring unrestricted access.
    """
    storage.ensure_schema()
    user = storage.get_user(user_id)
    if not user:
        return None

    existing = get_owner()
    if existing and int(existing.get("id")) != int(user_id):
        raise ValueError(
            f"Ya existe un OWNER: {existing.get('first_name') or existing.get('telegram_user_id')}"
        )

    current = storage.now()
    with storage.transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE aduana_users
            SET role='OWNER', status='ACTIVE', permission_level=?, max_ruts=999999,
                can_query=1, can_monitor=1,
                approved_at=COALESCE(approved_at, ?),
                pending_action=NULL, pending_data=NULL,
                last_activity_at=?
            WHERE id=?
            """,
            (settings.OWNER_PERMISSION, current, current, int(user_id)),
        )
        cur.execute("SELECT * FROM aduana_users WHERE id=?", (int(user_id),))
        return storage._row_dict(cur.fetchone())
