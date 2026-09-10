# -*- coding: utf-8 -*-
"""Configuration for the Aduana Telegram monitor blueprint.

Sensitive values stay in Render environment variables.  This module deliberately
reuses the parent Flask application's database connection instead of defining a
second database URL.
"""
from __future__ import annotations

import os

BASE_URL = "http://sistemas.aduana.cl/pls/htmldb/f?p=114:1"
REQUEST_TIMEOUT = int(os.environ.get("ADUANA_REQUEST_TIMEOUT", "45") or 45)
PERIOD_WORKERS = max(1, min(int(os.environ.get("ADUANA_PERIOD_WORKERS", "4") or 4), 6))
TARGET_WORKERS = max(1, min(int(os.environ.get("ADUANA_TARGET_WORKERS", "4") or 4), 6))
CRON_LOOKBACK_DAYS = max(7, min(int(os.environ.get("ADUANA_CRON_LOOKBACK_DAYS", "31") or 31), 62))
RUN_LOCK_STALE_MINUTES = max(10, int(os.environ.get("ADUANA_RUN_LOCK_STALE_MINUTES", "120") or 120))

TELEGRAM_BOT_TOKEN = (os.environ.get("ADUANA_TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_WEBHOOK_SECRET = (os.environ.get("ADUANA_TELEGRAM_WEBHOOK_SECRET") or "").strip()
OWNER_TELEGRAM_ID_RAW = (os.environ.get("ADUANA_OWNER_TELEGRAM_ID") or "").strip()
try:
    OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID_RAW) if OWNER_TELEGRAM_ID_RAW else 0
except ValueError:
    OWNER_TELEGRAM_ID = 0

CRON_SECRET = (os.environ.get("ADUANA_CRON_SECRET") or "").strip()
ADMIN_PASSWORD = (os.environ.get("ADUANA_ADMIN_PASSWORD") or "").strip()
ADMIN_PREFIX = (os.environ.get("ADUANA_ADMIN_PREFIX") or "/aduana-admin-x7k9").strip()
if not ADMIN_PREFIX.startswith("/"):
    ADMIN_PREFIX = "/" + ADMIN_PREFIX
ADMIN_PREFIX = ADMIN_PREFIX.rstrip("/") or "/aduana-admin-x7k9"
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
