# -*- coding: utf-8 -*-
"""Configuration for the Aduana Telegram monitor blueprint.

The module reuses the parent FLASK database and parent /login admin session.
Telegram may come from the shared Automation Hub; ADUANA_* token variables remain
only as a backwards-compatible fallback.
"""
from __future__ import annotations

import hashlib
import hmac
import os

# The legacy Consulta Denuncias Oracle APEX endpoint is served over HTTP.
# HTTPS connections from Render time out on port 443, while HTTP responds
# immediately (Render currently receives 403 on that path). Keep an override
# for diagnostics/alternate collectors, but use the real legacy endpoint by
# default so local/allowed-network collectors continue to work.
BASE_URL = (
    os.environ.get("ADUANA_BASE_URL")
    or "http://sistemas.aduana.cl/pls/htmldb/f?p=114:1"
).strip()
ADUANA_PUBLIC_QUERY_PAGE = "https://www.aduana.cl/consulta-denuncias/aduana/2007-02-27/182803.html"

# Keep an individual upstream request comfortably below the web worker's
# timeout. If Aduana is blocked/hanging from Render we need to return a useful
# diagnostic instead of letting Gunicorn kill the whole worker first.
REQUEST_TIMEOUT = max(3, min(int(os.environ.get("ADUANA_REQUEST_TIMEOUT", "8") or 8), 20))
PERIOD_WORKERS = max(1, min(int(os.environ.get("ADUANA_PERIOD_WORKERS", "4") or 4), 6))
TARGET_WORKERS = max(1, min(int(os.environ.get("ADUANA_TARGET_WORKERS", "4") or 4), 6))
CRON_LOOKBACK_DAYS = max(7, min(int(os.environ.get("ADUANA_CRON_LOOKBACK_DAYS", "31") or 31), 62))
RUN_LOCK_STALE_MINUTES = max(10, int(os.environ.get("ADUANA_RUN_LOCK_STALE_MINUTES", "120") or 120))

# Residential/ISP pull worker.
# Keep Render's environment simple: AUTOMATION_MASTER_KEY remains the single
# master secret. We derive a purpose-specific worker credential with HMAC and
# expose only that derived credential to the Windows/Raspberry Pi worker.
# The master key itself never leaves Render.
_AUTOMATION_MASTER_KEY = (os.environ.get("AUTOMATION_MASTER_KEY") or "").strip()
if _AUTOMATION_MASTER_KEY:
    WORKER_TOKEN = hmac.new(
        _AUTOMATION_MASTER_KEY.encode("utf-8"),
        b"aduana-residential-worker-v1",
        hashlib.sha256,
    ).hexdigest()
else:
    WORKER_TOKEN = ""

# Pull-worker is now the only production Aduana query path whenever the Hub
# master key exists.  Do not let an old ADUANA_USE_REMOTE_WORKER environment
# value silently send queries back through Render's blocked datacenter egress.
WORKER_ENABLED = bool(WORKER_TOKEN)

# Telegram/cron run in background threads and can wait longer. A normal web
# request gets a shorter ceiling to stay below common Gunicorn request limits.
WORKER_WAIT_SECONDS = max(30, min(int(os.environ.get("ADUANA_WORKER_WAIT_SECONDS", "180") or 180), 600))
WORKER_WEB_WAIT_SECONDS = max(5, min(int(os.environ.get("ADUANA_WORKER_WEB_WAIT_SECONDS", "25") or 25), 28))

# Legacy fallback only. New bots should be added from /admin/automation.
TELEGRAM_BOT_TOKEN = (os.environ.get("ADUANA_TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_WEBHOOK_SECRET = (os.environ.get("ADUANA_TELEGRAM_WEBHOOK_SECRET") or "").strip()
OWNER_TELEGRAM_ID_RAW = (os.environ.get("ADUANA_OWNER_TELEGRAM_ID") or "").strip()
try:
    OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID_RAW) if OWNER_TELEGRAM_ID_RAW else 0
except ValueError:
    OWNER_TELEGRAM_ID = 0

CRON_SECRET = (os.environ.get("ADUANA_CRON_SECRET") or "").strip()
ADMIN_PREFIX = "/admin/automation/aduana"
PUBLIC_BASE_URL = (
    os.environ.get("ADUANA_PUBLIC_BASE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or os.environ.get("PUBLIC_BASE_URL")
    or ""
).strip().rstrip("/")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    # Normal browser navigation path from Aduana's own public Consulta page.
    "Referer": ADUANA_PUBLIC_QUERY_PAGE,
}

ADUANAS = [
    ("3", "ARICA"),
    ("7", "IQUIQUE"),
    ("10", "TOCOPILLA"),
    ("14", "ANTOFAGASTA"),
    ("17", "CHANARAL"),
    ("25", "COQUIMBO"),
    ("33", "LOS ANDES"),
    ("34", "VALPARAISO"),
    ("39", "SAN ANTONIO"),
    ("48", "METROPOLITANA"),
    ("55", "TALCAHUANO"),
    ("56", "ARAUCANIA"),
    ("67", "OSORNO"),
    ("69", "PUERTO MONTT"),
    ("83", "COYHAIQUE"),
    ("90", "PUERTO AYSEN"),
    ("92", "PUNTA ARENAS"),
    ("98", "DIRECCION NACIONAL"),
]
ADUANA_LABELS = dict(ADUANAS)
ADUANA_CODES = [code for code, _ in ADUANAS]

COLUMNS = [
    "n_denuncia",
    "emision",
    "notificacion",
    "doc_aduanero",
    "art_infraccion",
    "infractor",
    "multa_max_legal",
    "multa_c_allan",
    "multa_s_allan",
    "venc_allan",
    "venc_recl_junta",
    "audiencia",
    "n_despacho",
    "aduana_nombre",
]

PERMISSION_LEVELS = ("MONTH", "THREE_MONTHS", "YEAR")
OWNER_PERMISSION = "UNLIMITED"
UNLIMITED_START_YEAR = 2011
DEFAULT_PERMISSION = "THREE_MONTHS"
DEFAULT_MAX_RUTS = 3
