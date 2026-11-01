# -*- coding: utf-8 -*-
"""Access stock snapshot upload, authenticated by the EXISTING V33 bridge secret.

V33 sends one *complete* read-only Access aggregate on user request.
Render atomically replaces ONLY the TiDB stock table and timestamps success.
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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
    # SQL SUM() may return NULL; keep it distinct from zero.
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("Invalid inventory quantity")
    try:
        amount = Decimal(str(raw))
        if not amount.is_finite() or abs(amount) > _AMOUNT:
            raise ValueError("Out-of-range inventory quantity")
        # Access SUM(UNT * PN) may return binary floating-point tails.
        # TiDB DECIMAL(18,3) already stores millesimal precision: round once,
        # explicitly and consistently, rather than rejecting valid totals.
        return amount.quantize(_UNIT, rounding=ROUND_HALF_UP)
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
        if "stock_rolls" not in item or "stock_meters" not in item:
            raise ValueError("Missing stock quantity field")
        values[code] = (_series(code), _value(item["stock_rolls"]),
                         _value(item["stock_meters"]))
    return values


def _sync_blocking(snapshot, allow_large_deactivation=False, progress=None):
    """Replace ONLY the inventory snapshot atomically; never touch sample records.

    TiDB/InnoDB DELETE + INSERT within one transaction: a failed batch rolls
    back the DELETE, inserts, and success marker together. TRUNCATE is forbidden.
    """
    started = time.perf_counter()
    def report(stage, done=0, total=0):
        if progress is not None:
            try:
                progress(stage, done, total)
            except Exception:
                LOGGER.warning("STOCK_SYNC_PROGRESS_CALLBACK_FAILED")

    if not snapshot or len(snapshot) > _MAX_SKUS:
        raise ValueError("Invalid inventory size")
    # Refuse to destroy good data if the snapshot bypasses the API validator.
    if len({key.casefold() for key in snapshot}) != len(snapshot):
        raise ValueError("Duplicate SKU in inventory")
    report("connecting")
    conn = scanner_tidb._connect(read_timeout=90, write_timeout=90)
    try:
        scanner_tidb._ensure(conn)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        report("comparing")
        with conn.cursor() as cur:
            # One serialized writer, including uploads through the signed API.
            cur.execute(
                "INSERT IGNORE INTO xw_stock_sync_state "
                "(id,last_success_utc,sku_count,inserted,updated,deactivated) "
                "VALUES (1,%s,0,0,0,0)", (now,)
            )
            cur.execute("SELECT id FROM xw_stock_sync_state WHERE id=1 FOR UPDATE")
            cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM xw_stock_snapshot WHERE is_active=1")
            old_active = int(cur.fetchone()[0])

            # The former /search import had only 3,980 positive records.
            # A verified full Access snapshot can replace it outright.
            # Future unexpectedly truncated snapshots still need approval.
            if (old_active >= 100
                    and len(snapshot) < int(old_active * 0.80)
                    and not allow_large_deactivation):
                LOGGER.warning(
                    "STOCK_REPLACE_REJECTED old_active=%d incoming=%d reason=shrink",
                    old_active, len(snapshot),
                )
                raise ValueError(
                    "STOCK_SNAPSHOT_TOO_SMALL: previous=%d incoming=%d" %
                    (old_active, len(snapshot))
                )

            LOGGER.info(
                "STOCK_REPLACE_START old_active=%d incoming=%d",
                old_active, len(snapshot),
            )
            report("writing", 0, len(snapshot))
            # DELETE and every INSERT remain uncommitted until the final
            # validation and state update are all successful.
            cur.execute("DELETE FROM xw_stock_snapshot")
            query = (
                "INSERT INTO xw_stock_snapshot "
                "(sku,series,stock_rolls,stock_meters,is_active,changed_at) "
                "VALUES (%s,%s,%s,%s,1,%s)"
            )
            rows = [(sku, *values, now) for sku, values in snapshot.items()]
            for j in range(0, len(rows), 400):
                batch = rows[j:j + 400]
                cur.executemany(query, batch)
                report("writing", min(j + len(batch), len(rows)), len(rows))

            # Check the table's actual row count BEFORE committing.
            cur.execute("SELECT COUNT(*) FROM xw_stock_snapshot")
            actual_count = int(cur.fetchone()[0])
            if actual_count != len(snapshot):
                raise ValueError("Inventory row count mismatch")

            # Keep state in the same database transaction.
            cur.execute(
                "UPDATE xw_stock_sync_state "
                "SET last_success_utc=%s,sku_count=%s,inserted=%s,"
                "updated=0,deactivated=0 WHERE id=1",
                (now, len(snapshot), len(snapshot))
            )

        report("committing", len(snapshot), len(snapshot))
        conn.commit()
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        LOGGER.info(
            "STOCK_SYNC_DB_FINISHED mode=replace total=%d old_replaced=%d duration_ms=%d",
            len(snapshot), old_active, elapsed_ms,
        )
        report("finished", len(snapshot), len(snapshot))
        return {
            "success": True,
            "mode": "replace",
            "synced_at_utc": now.isoformat(timespec="seconds") + "Z",
            "sku_count": len(snapshot),
            "inserted": len(snapshot), "updated": 0, "deactivated": 0,
            "unchanged": 0, "replaced_old": old_active
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
        breakdown = scanner_tidb.stock_breakdown(conn)
        return {
            "success": True, "has_synced": True,
            "stock_breakdown":breakdown,
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
