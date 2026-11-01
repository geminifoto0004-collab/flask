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
import threading
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
_LOCAL_SYNC_LOCK = threading.Lock()
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
    """Stage a complete stock snapshot, atomically swap tables after validation.

    The original stock table remains online throughout loading. Each staging
    INSERT batch is committed separately; no giant DELETE+INSERT transaction.
    All xw_sample_* tables are untouched. No TRUNCATE of a live table.
    """
    started = time.perf_counter()
    if not snapshot or len(snapshot) > _MAX_SKUS:
        raise ValueError("Invalid inventory size")
    if len(set(x.casefold() for x in snapshot)) != len(snapshot):
        raise ValueError("Duplicate SKU in inventory")

    def report(stage, done=0, total=0):
        if progress is not None:
            try:
                progress(stage, done, total)
            except Exception:
                LOGGER.warning("STOCK_SYNC_PROGRESS_CALLBACK_FAILED")

    # One Render worker today; serialize the signed upload and scanner job.
    if not _LOCAL_SYNC_LOCK.acquire(blocking=False):
        raise RuntimeError("Stock snapshot synchronization already running")
    conn = None
    stage = "xw_stock_stage_" + secrets.token_hex(6)
    backup = "xw_stock_old_" + secrets.token_hex(6)
    stage_exists = False
    swapped = False
    committed = False
    try:
        report("connecting")
        conn = scanner_tidb._connect(read_timeout=90, write_timeout=90)
        scanner_tidb._ensure(conn)
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        report("comparing")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM xw_stock_snapshot WHERE is_active=1")
            old_active = int(cur.fetchone()[0])
        conn.commit()

        # Reject a clearly truncated future snapshot, but allow the first
        # upgrade from the earlier positive-only 3,980 records to full stock.
        if (old_active >= 100 and len(snapshot) < old_active * 0.8
                and not allow_large_deactivation):
            raise ValueError(
                "STOCK_SNAPSHOT_TOO_SMALL: previous=%d incoming=%d" %
                (old_active, len(snapshot))
            )

        LOGGER.info("STOCK_STAGE_BEGIN old_active=%d incoming=%d", old_active, len(snapshot))
        with conn.cursor() as cur:
            # TiDB CREATE TABLE LIKE copies schema/indexes, no rows.
            cur.execute("CREATE TABLE " + stage + " LIKE xw_stock_snapshot")
        conn.commit()
        stage_exists = True

        insert_sql = (
            "INSERT INTO " + stage + " "
            "(sku,series,stock_rolls,stock_meters,is_active,changed_at) "
            "VALUES (%s,%s,%s,%s,1,%s)"
        )
        rows = [(sku, *vals, ts) for sku, vals in snapshot.items()]
        total = len(rows)
        report("writing", 0, total)
        for i in range(0, total, 250):
            chunk = rows[i:i + 250]
            t0 = time.perf_counter()
            with conn.cursor() as cur:
                cur.executemany(insert_sql, chunk)
            # This is safe: no reader uses the staging table before swap.
            conn.commit()
            done = i + len(chunk)
            report("writing", done, total)
            LOGGER.info(
                "STOCK_STAGE_BATCH done=%d total=%d batch_ms=%d total_ms=%d",
                done, total, round((time.perf_counter() - t0) * 1000),
                round((time.perf_counter() - started) * 1000),
            )

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM " + stage)
            persisted = int(cur.fetchone()[0])
            if persisted != total:
                raise ValueError("Inventory row count mismatch")
            cur.execute(
                "SELECT "
                "COALESCE(SUM(CASE WHEN stock_rolls>0 THEN 1 ELSE 0 END),0),"
                "COALESCE(SUM(CASE WHEN stock_rolls=0 THEN 1 ELSE 0 END),0),"
                "COALESCE(SUM(CASE WHEN stock_rolls<0 THEN 1 ELSE 0 END),0),"
                "COALESCE(SUM(CASE WHEN stock_rolls IS NULL THEN 1 ELSE 0 END),0) "
                "FROM " + stage
            )
            actual_groups = tuple(int(v) for v in cur.fetchone())
        expected_groups = (
            sum(v[1] is not None and v[1] > 0 for v in snapshot.values()),
            sum(v[1] is not None and v[1] == 0 for v in snapshot.values()),
            sum(v[1] is not None and v[1] < 0 for v in snapshot.values()),
            sum(v[1] is None for v in snapshot.values()),
        )
        if actual_groups != expected_groups or sum(actual_groups) != total:
            raise ValueError("Inventory category count mismatch")
        conn.commit()

        # TiDB supports multi-table atomic RENAME. No moment with no
        # xw_stock_snapshot; readers see either old or complete new table.
        report("committing", total, total)
        LOGGER.info("STOCK_STAGE_VERIFIED total=%d counts=%s", total, actual_groups)
        with conn.cursor() as cur:
            cur.execute(
                "RENAME TABLE xw_stock_snapshot TO " + backup +
                ", " + stage + " TO xw_stock_snapshot"
            )
        swapped = True
        stage_exists = False
        # RENAME is DDL, not part of a transaction with this status UPDATE.
        # If status update fails, best-effort swap back to old stock below.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO xw_stock_sync_state "
                "(id,last_success_utc,sku_count,inserted,updated,deactivated) "
                "VALUES (1,%s,%s,%s,0,0) "
                "ON DUPLICATE KEY UPDATE last_success_utc=VALUES(last_success_utc),"
                "sku_count=VALUES(sku_count),inserted=VALUES(inserted),"
                "updated=0,deactivated=0",
                (ts, total, total)
            )
        conn.commit()
        committed = True
        LOGGER.info(
            "STOCK_SYNC_DB_FINISHED mode=stage_swap total=%d old=%d duration_ms=%d",
            total, old_active, round((time.perf_counter()-started)*1000),
        )
        # Old data is kept until the new table AND status are committed.
        # A cleanup failure never changes the successful result.
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE " + backup)
            conn.commit()
        except Exception:
            LOGGER.warning("STOCK_OLD_SNAPSHOT_CLEANUP_FAILED")
        report("finished", total, total)
        return {
            "success": True, "mode": "replace",
            "synced_at_utc": ts.isoformat(timespec="seconds") + "Z",
            "sku_count": total, "inserted": total, "updated": 0,
            "deactivated": 0, "unchanged": 0, "replaced_old": old_active,
        }
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            # If a failure occurred after the atomic swap, restore the
            # previous snapshot using the still-present backup table.
            if swapped and not committed:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "RENAME TABLE xw_stock_snapshot TO " + stage +
                            ", " + backup + " TO xw_stock_snapshot"
                        )
                    conn.commit()
                    stage_exists = True
                    LOGGER.warning("STOCK_STAGE_SWAP_ROLLED_BACK")
                except Exception:
                    LOGGER.critical(
                        "STOCK_STAGE_SWAP_RECOVERY_REQUIRED prior_table=%s", backup
                    )
            if stage_exists:
                try:
                    with conn.cursor() as cur:
                        cur.execute("DROP TABLE IF EXISTS " + stage)
                    conn.commit()
                except Exception:
                    LOGGER.warning("STOCK_STAGE_CLEANUP_FAILED")
        raise
    finally:
        if conn is not None:
            conn.close()
        _LOCAL_SYNC_LOCK.release()


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
