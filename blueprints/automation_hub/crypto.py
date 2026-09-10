# -*- coding: utf-8 -*-
"""Authenticated encryption for bot tokens.

Only one Render secret (AUTOMATION_MASTER_KEY) is needed no matter how many
Telegram bots are registered. Bot tokens stored in TiDB are never plaintext.
"""
from __future__ import annotations

import base64
import hashlib

from . import settings


def _fernet():
    if not settings.MASTER_KEY:
        raise RuntimeError("AUTOMATION_MASTER_KEY no está configurado")
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia 'cryptography'") from exc
    digest = hashlib.sha256(settings.MASTER_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("secret vacío")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
