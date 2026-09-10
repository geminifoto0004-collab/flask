# -*- coding: utf-8 -*-
from __future__ import annotations

import os

# One server-side encryption key protects all Telegram Bot tokens stored by the Hub.
# Authentication is NOT duplicated here: the Hub reuses the parent FLASK /login session.
MASTER_KEY = (os.environ.get("AUTOMATION_MASTER_KEY") or "").strip()

# Keep the Automation Hub inside the existing XINGWANG admin console.
# This path is intentionally fixed so a normal /login -> /admin workflow can reach it.
ADMIN_PREFIX = "/admin/automation"

PUBLIC_BASE_URL = (
    os.environ.get("AUTOMATION_PUBLIC_BASE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or os.environ.get("PUBLIC_BASE_URL")
    or ""
).strip().rstrip("/")

TELEGRAM_TIMEOUT = max(5, min(int(os.environ.get("AUTOMATION_TELEGRAM_TIMEOUT", "20") or 20), 60))
