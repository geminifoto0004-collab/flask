"""Invitation-only staff access to the ORDER share Telegram bot.

Employees join a private Telegram group, where the bot is an administrator.
Telegram's getChatMember verifies group membership on every private lookup,
so leaving or being removed removes access without requiring an ID list.
No passcodes, no private customer data in the group.
"""
from __future__ import annotations

import os
import re

import requests

_GROUP_ID_RE = re.compile(r"-[1-9][0-9]{3,20}")


def group_id():
    value = (os.environ.get("ORDER_SHARE_TELEGRAM_GROUP_ID") or "").strip()
    return int(value) if _GROUP_ID_RE.fullmatch(value) else None


def configured():
    return group_id() is not None


def is_authorized(bot_key, user_id, bot_token):
    """Check a real Telegram member. Errors fail closed, never reveal bot token."""
    if group_id() is None or type(user_id) is not int or user_id <= 0 or not bot_token:
        return False
    try:
        response = requests.post(
            "https://api.telegram.org/bot" + bot_token + "/getChatMember",
            json={"chat_id": group_id(), "user_id": user_id},
            timeout=8,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        if not payload.get("ok"):
            return False
        member = payload.get("result") or {}
        status = member.get("status")
        return status in {"creator", "administrator", "member"} or (
            status == "restricted" and member.get("is_member") is True
        )
    except Exception:
        # Any requests exception may contain the token-bearing URL; fail closed.
        return False
