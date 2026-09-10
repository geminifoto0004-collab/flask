# -*- coding: utf-8 -*-
from __future__ import annotations

import os

MASTER_KEY = (os.environ.get("AUTOMATION_MASTER_KEY") or "").strip()
ADMIN_PASSWORD = (
    os.environ.get("AUTOMATION_ADMIN_PASSWORD")
    or os.environ.get("ADUANA_ADMIN_PASSWORD")
    or ""
).strip()
ADMIN_PREFIX = (os.environ.get("AUTOMATION_ADMIN_PREFIX") or "/automation-hub-x7k9").strip()
if not ADMIN_PREFIX.startswith("/"):
    ADMIN_PREFIX = "/" + ADMIN_PREFIX
ADMIN_PREFIX = ADMIN_PREFIX.rstrip("/") or "/automation-hub-x7k9"

PUBLIC_BASE_URL = (
    os.environ.get("AUTOMATION_PUBLIC_BASE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or os.environ.get("PUBLIC_BASE_URL")
    or ""
).strip().rstrip("/")

TELEGRAM_TIMEOUT = max(5, min(int(os.environ.get("AUTOMATION_TELEGRAM_TIMEOUT", "20") or 20), 60))
