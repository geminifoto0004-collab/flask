# -*- coding: utf-8 -*-
from __future__ import annotations

import requests

from . import settings


def _call(token: str, method: str, *, data=None):
    token = str(token or "").strip()
    if not token:
        raise ValueError("Bot token requerido")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data or {},
        timeout=settings.TELEGRAM_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or f"Telegram {method} failed")
    return payload


def test_bot(token: str):
    payload = _call(token, "getMe")
    return payload.get("result") or {}


def set_webhook(token: str, url: str, secret: str):
    data = {"url": url, "drop_pending_updates": "false"}
    if secret:
        data["secret_token"] = secret
    return _call(token, "setWebhook", data=data)


def get_webhook_info(token: str):
    return _call(token, "getWebhookInfo")


def delete_webhook(token: str):
    return _call(token, "deleteWebhook", data={"drop_pending_updates": "false"})
