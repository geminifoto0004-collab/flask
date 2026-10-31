# -*- coding: utf-8 -*-
"""Access stock snapshot upload, authenticated by the EXISTING V33 bridge secret.

V33 sends one *complete* read-only Access aggregate on user request.
Render performs a transactional TiDB delta update and timestamps success.
No stock payload, passwords or bridge secrets are stored in application logs.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from xingwang_miniapp import scanner_tidb

router = APIRouter()
LOGGER = logging.getLogger("uvicorn.error")
_MAX_BODY = 8 * 1024 * 1024
_MAX_SKUS = 80000
_NONCES = {}
_AUTH_LOCK = asyncio.Lock()
_WRITE_LOCK = asyncio.Lock()
_CODE = re.compile(r"^[^\x00-\x1f\x7f]{1,127}$")
_AMOUNT = Decimal("999999999999999.999")
_UNIT = Decimal("0.001")


def sign_request(shared_secret, timestamp, nonce, body):
    """Reusable signature contract for the V33 client's existing credential."""
    message = (
        "xw-stock-sync-v1\n" + str(timestamp) + "\n" + nonce + "\n" +
        hashlib.sha256(body).hexdigest()
    ).encode("ascii")
    derived = hmac.new(shared_secret.encode("utf-8"), b"stock-sync-v1", hashlib.sha256).digest()
    return hmac.new(derived, message, hashlib.sha256).hexdigest()


async def _verify(request, body):
    try:
        ts = int(request.headers.get("x-xw-time", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid authorization")
    nonce = request.headers.get("x-xw-nonce", "")
    signature = request.headers.get("x-xw-signature", "")
    if (abs(time.time() - ts) > 300 or
        not re.fullmatch(r"[a-f0-9]{32}", nonce) or
        not re.fullmatch(r"[a-f0-9]{64}", signature)):
        raise HTTPException(401, "Invalid authorization")
    secret = os.environ.get("BRIDGE_SHARED_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(503, "Bridge authentication unavailable")
    expected = sign_request(secret, ts, nonce, body)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid authorization")
    async with _AUTH_LOCK:
        current = time.monotonic()
        for item, deadline in list(_NONCES.items()):
            if deadline < current:
                _NONCES.pop(item, None)
        if len(_NONCES) > 2000:
            raise HTTPException(429, "Too many requests")
        if nonce in _NONCES:
            raise HTTPException(409, "Duplicate request")
        _NONCES[nonce] = current + 330


def _value(raw):
    if isinstance(raw, bool) or raw is None:
        raise ValueError("Missing or invalid inventory quantity")
    try:
        amount = Decimal(str(raw))
        if not amount.is_finite() or abs(amount) > _AMOUNT:
            raise ValueError("Out-of-range inventory quantity")
        if amount != amount.quantize(_UNIT):
            raise ValueError("Inventory quantity has too many decimal places")
        return amount
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid inventory quantity")


def _series(sku):
    # Strict series relationship: 12-225-3 -> 12-225, 12-225 -> 12-225
    found = re.fullmatch(r"(.+-[0-9]+)-[0-9]+", sku)
    return found.group(1) if found else sku


def _validate(payload):
    if not isinstance(payload, dict) or payload.get("schema") != "xw-stock-v1":
        raise ValueError("Unsupported payload format")
    if payload.get("complete_snapshot") is not True:
        raise ValueError("Full snapshot required")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not 0 < len(rows) <= _MAX_SKUS:
        raise ValueError("Invalid inventory size")
    if payload.get("expected_count") != len(rows):
        raise ValueError("Inventory row count mismatch")
    values = {}
    folded_codes = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Invalid inventory row")
        code = item.get("sku")
        if not isinstance(code, str) or not _CODE.fullmatch(code) or code != code.strip():
            raise ValueError("Invalid SKU in inventory")
        key = code.casefold()
        if key in folded_codes:
            raise ValueError("Duplicate SKU in inventory")
        folded_codes.add(key)
        values[code] = (_series(code), _value(item.get("stock_rolls")),
                         _value(item.get("stock_meters")))
    return values


def _sync_blocking(snapshot, allow_large_deactivation=False):
    conn = scanner_tidb._connect()
    try:
        scanner_tidb._ensure(conn)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with conn.cursor() as cur:
            # Serialize across Render processes and concurrent local senders.
            cur.execute("INSERT IGNORE INTO xw_stock_sync_state "
                        "(id,last_success_utc,sku_count,inserted,updated,deactivated)"
                        " VALUES (1,%s,0,0,0,0)", (now,))
            cur.execute("SELECT id FROM xw_stock_sync_state WHERE id=1 FOR UPDATE")
            cur.fetchone()
            cur.execute("SELECT sku, series, stock_rolls, stock_meters, is_active "
                        "FROM xw_stock_snapshot")
            old = {
                sku: (series, rolls, meters, int(active))
                for sku, series, rolls, meters, active in cur.fetchall()
            }
            inserted = []
            updated = []
            for sku, values in snapshot.items():
                current = old.get(sku)
                if current is None:
                    inserted.append((sku, *values, now))
                elif (current[0] != values[0] or
                      current[1] != values[1] or
                      current[2] != values[2] or current[3] != 1):
                    updated.append((sku, *values, now))
            gone = [sku for sku, current in old.items()
                    if current[3] and sku not in snapshot]
            # Strong protection against accidental truncated Access reads.
            active_count = sum(1 for item in old.values() if item[3])
            if (active_count >= 100 and
                len(gone) > max(25, int(active_count * 0.20)) and
                not allow_large_deactivation):
                raise ValueError(
                    "More than 20% of SKUs disappeared; no inventory changes saved. "
                    "Confirm the Access query is complete before retrying."
                )
            query = (
                "INSERT INTO xw_stock_snapshot "
                "(sku,series,stock_rolls,stock_meters,is_active,changed_at) "
                "VALUES (%s,%s,%s,%s,1,%s) "
                "ON DUPLICATE KEY UPDATE series=VALUES(series),"
                "stock_rolls=VALUES(stock_rolls),stock_meters=VALUES(stock_meters),"
                "is_active=1,changed_at=VALUES(changed_at)"
            )
            for group in (inserted, updated):
                for j in range(0, len(group), 400):
                    cur.executemany(query, group[j:j + 400])
            for j in range(0, len(gone), 400):
                batch = gone[j:j + 400]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    "UPDATE xw_stock_snapshot SET is_active=0,changed_at=%s "
                    "WHERE sku IN (" + placeholders + ")",
                    [now, *batch]
                )
            cur.execute(
                "UPDATE xw_stock_sync_state "
                "SET last_success_utc=%s,sku_count=%s,inserted=%s,updated=%s,deactivated=%s WHERE id=1",
                (now, len(snapshot), len(inserted), len(updated), len(gone))
            )
        conn.commit()
        return {
            "success": True, "synced_at_utc": now.isoformat(timespec="seconds") + "Z",
            "sku_count": len(snapshot), "inserted": len(inserted),
            "updated": len(updated), "deactivated": len(gone),
            "unchanged": len(snapshot) - len(inserted) - len(updated)
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _status_blocking():
    conn = scanner_tidb._connect()
    try:
        scanner_tidb._ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT last_success_utc,sku_count,inserted,updated,deactivated "
                        "FROM xw_stock_sync_state WHERE id=1")
            row = cur.fetchone()
        if not row:
            return {"success": True, "has_synced": False}
        return {
            "success": True, "has_synced": True,
            "synced_at_utc": row[0].isoformat(timespec="seconds") + "Z",
            "sku_count": row[1], "inserted": row[2], "updated": row[3],
            "deactivated": row[4],
        }
    finally:
        conn.close()


@router.post("/scanner/api/stock-sync")
async def upload_stock(request: Request):
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB not configured")
    if int(request.headers.get("content-length", "0") or 0) > _MAX_BODY:
        raise HTTPException(413, "Snapshot too large")
    body = await request.body()
    if len(body) > _MAX_BODY:
        raise HTTPException(413, "Snapshot too large")
    await _verify(request, body)
    try:
        payload = json.loads(body)
        snapshot = _validate(payload)
    except (UnicodeDecodeError, ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    async with _WRITE_LOCK:
        try:
            result = await asyncio.to_thread(
                _sync_blocking, snapshot, payload.get("allow_large_deactivation") is True
            )
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            LOGGER.error("STOCK_SYNC_FAILED kind=%s", type(e).__name__)
            raise HTTPException(503, "TiDB sync failed; previous snapshot retained")
    LOGGER.info(
        "STOCK_SYNC_OK count=%d inserted=%d updated=%d deactivated=%d",
        result["sku_count"], result["inserted"],
        result["updated"], result["deactivated"],
    )
    return JSONResponse(result)


@router.get("/scanner/api/stock-sync/status")
async def stock_status(request: Request):
    await _verify(request, b"")
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB not configured")
    try:
        return await asyncio.to_thread(_status_blocking)
    except Exception as e:
        LOGGER.error("STOCK_SYNC_STATUS_FAILED kind=%s", type(e).__name__)
        raise HTTPException(503, "TiDB sync status unavailable")
