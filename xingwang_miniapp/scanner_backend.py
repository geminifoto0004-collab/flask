# -*- coding: utf-8 -*-
"""Mobile QR scanner for stock/sample inspection.

Separate, authenticated operator interface. Existing Telegram, Xiaozhi and
public /stock endpoints remain unchanged. Never writes Access; TiDB is optional.
"""
import asyncio
import hashlib
import hmac
import os
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from xingwang_miniapp import scanner_tidb

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()
COOKIE = "xw_scanner_session"
TTL = 30 * 86400
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()/-]{1,39}$")
LOGIN_ATTEMPTS = {}
REQUEST_TIMES = []
LOCK = asyncio.Lock()
PENDING_SCANS = {}  # random scan_id => (time, signed-in device, series, real SKUs)
PAGE = Path(__file__).with_name("scanner.html").read_text(encoding="utf-8")


def _passcode():
    return os.environ.get("XW_SCANNER_PASSCODE", "")


def _key():
    password = _passcode()
    # A 6-digit operator PIN is supported. Login attempts are rate-limited.
    if len(password) < 6:
        return None
    return hmac.new(os.environ["BRIDGE_SHARED_SECRET"].encode("utf-8"),
                    ("xw-scanner-cookie-v1:" + password).encode("utf-8"),
                    hashlib.sha256).digest()


def _sign(data):
    return hmac.new(_key(), data.encode("ascii"), hashlib.sha256).hexdigest()


def _authorized(request):
    if _key() is None:
        return False
    token = request.cookies.get(COOKIE, "")
    if len(token) > 200:
        return False
    try:
        exp, nonce, mac = token.split(".")
        if not exp.isdecimal() or not re.fullmatch(r"[a-f0-9]{24}", nonce):
            return False
        if not re.fullmatch(r"[a-f0-9]{64}", mac):
            return False
        now = time.time()
        if not now < int(exp) <= now + TTL + 60:
            return False
        return hmac.compare_digest(mac, _sign(exp + "." + nonce))
    except (ValueError, TypeError):
        return False


def _check_origin(request):
    # The UI only calls same-origin POSTs. Prevent cross-site cookie abuse.
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    if not origin or origin not in ("https://" + host, "http://localhost:" + host.split(":")[-1]):
        raise HTTPException(403, "Invalid origin")


def _require(request):
    if not _authorized(request):
        raise HTTPException(401, "請先登入掃描器")


@router.get("/scanner", response_class=HTMLResponse)
async def scanner_page():
    return HTMLResponse(PAGE, headers={
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'",
    })


@router.get("/scanner/api/session")
async def session(request: Request):
    return {"ok": True, "signed_in": _authorized(request),
            "configured": _key() is not None,
            "db_configured": scanner_tidb.configured()}


@router.post("/scanner/api/db/setup")
async def scanner_db_setup(request: Request):
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "請先在 Render Environment 設定 XW_SCANNER_TIDB_URL")
    try:
        result = await asyncio.to_thread(scanner_tidb.check_and_initialize)
        logging.getLogger("uvicorn.error").info(
            "SCANNER_TIDB_READY tables=%d",len(result["tables"])
        )
        return {"ok":True, **result}
    except Exception:
        logging.getLogger("uvicorn.error").exception("SCANNER_TIDB_SETUP_FAILED")
        raise HTTPException(503, "TiDB 連線或建表失敗，請檢查 Render 日誌")



# Manual Access -> Render -> TiDB snapshot. Uses the authenticated V33 bridge
# and the existing Flask /search endpoint; never executes arbitrary SQL.
_INVENTORY_LOCK = asyncio.Lock()
_INVENTORY_JOB = {"state": "idle"}
_INVENTORY_TASK = None


async def _inventory_run(job_id):
    global _INVENTORY_JOB
    from xingwang_miniapp import miniapp_server as relay
    from xingwang_miniapp import stock_sync_api
    import base64
    import zlib
    import json

    request_id = uuid4().hex
    future = asyncio.get_running_loop().create_future()
    try:
        async with relay.bridge_lock:
            if relay.active_bridge is None or relay.active_role is None:
                raise RuntimeError("V33 is not online; please start the updated V33 bridge")
            if len(relay.waiting) >= relay.MAX_INFLIGHT:
                raise RuntimeError("V33 bridge is busy")
            ws = relay.active_bridge
            relay.waiting[request_id] = (future, ws)
            try:
                await relay.send_peer(relay.active_role, {
                    "type": "query", "id": request_id, "source": "scanner_admin",
                    "action": "stock_snapshot", "q": "@"
                })
            except Exception:
                relay.waiting.pop(request_id, None)
                raise RuntimeError("Failed to send stock sync command to V33")
        try:
            response = await asyncio.wait_for(future, timeout=220)
        finally:
            relay.waiting.pop(request_id, None)

        if not isinstance(response, dict) or response.get("ok") is not True:
            code = response.get("code", "UNAVAILABLE") if isinstance(response, dict) else "INVALID"
            if code == "ACCESS_DENIED":
                raise RuntimeError("V33 does not support the new sync command; install V33 Sync")
            raise RuntimeError("V33 inventory query failed (" + str(code)[:30] + ")")
        data = response.get("data")
        if not isinstance(data, dict) or data.get("encoding") != "zlib-base64":
            raise RuntimeError("Invalid inventory transfer format from V33")
        encoded = data.get("payload")
        if not isinstance(encoded, str) or len(encoded) > 16 * 1024 * 1024:
            raise RuntimeError("Compressed inventory exceeds allowed size")
        compressed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, 20 * 1024 * 1024 + 1)
        if (len(raw) > 20 * 1024 * 1024 or not decoder.eof
                or decoder.unconsumed_tail or decoder.unused_data
                or len(raw) != data.get("original_bytes")
                or hashlib.sha256(raw).hexdigest() != data.get("sha256")):
            raise RuntimeError("Corrupted or oversized stock snapshot")
        snapshot = stock_sync_api._validate(json.loads(raw))
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"writing", "id":job_id,
                                  "started_at":_INVENTORY_JOB["started_at"]}
        result = await asyncio.to_thread(stock_sync_api._sync_blocking, snapshot)
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"success", "id":job_id, "result":result}
        logging.getLogger("uvicorn.error").info(
            "STOCK_SYNC_OK total=%d inserted=%d updated=%d deactivated=%d",
            result["sku_count"], result["inserted"],
            result["updated"], result["deactivated"])
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Never include host/credential details from arbitrary DB exceptions.
        if isinstance(exc, RuntimeError):
            safe = str(exc)[:180]
        elif isinstance(exc, ValueError):
            safe = "Inventory validation failed; previous TiDB snapshot retained"
        else:
            safe = "Stock sync failed; see Render logs"
        logging.getLogger("uvicorn.error").error(
            "STOCK_SYNC_TASK_FAILED kind=%s", type(exc).__name__)
        async with _INVENTORY_LOCK:
            if _INVENTORY_JOB.get("id") == job_id:
                _INVENTORY_JOB = {"state":"failed", "id":job_id, "error":safe}


@router.post("/scanner/api/inventory/start")
async def inventory_start(request: Request):
    global _INVENTORY_TASK, _INVENTORY_JOB
    _check_origin(request)
    _require(request)
    if not scanner_tidb.configured():
        raise HTTPException(503, "TiDB is not configured in Render")
    from xingwang_miniapp import miniapp_server as relay
    async with _INVENTORY_LOCK:
        if _INVENTORY_JOB.get("state") in ("reading", "writing"):
            raise HTTPException(409, "Stock sync already in progress")
        if relay.active_bridge is None or relay.active_role is None:
            raise HTTPException(503, "V33 is not online. Open local Flask and the updated V33.")
        job_id = uuid4().hex
        _INVENTORY_JOB = {
            "state":"reading", "id":job_id,
            "started_at":datetime.now(timezone.utc).isoformat(timespec="seconds")
        }
        _INVENTORY_TASK = asyncio.create_task(_inventory_run(job_id),
                                              name="manual-access-stock-sync")
    return {"ok":True, "state":"reading", "job_id":job_id}


@router.get("/scanner/api/inventory/status")
async def inventory_status(request: Request):
    _require(request)
    from xingwang_miniapp import stock_sync_api
    try:
        last = await asyncio.to_thread(stock_sync_api._status_blocking)
    except Exception:
        last = {"success":False, "has_synced":False}
    return {"ok":True, "job":dict(_INVENTORY_JOB), "last_success":last}


@router.post("/scanner/api/login")
async def login(request: Request):
    _check_origin(request)
    if _key() is None:
        raise HTTPException(503, "請先在 Render 設定掃描器登入碼")
    async with LOCK:
        now = time.monotonic()
        # Both per-client and global limits; no password in error responses/logs.
        for key, values in list(LOGIN_ATTEMPTS.items()):
            LOGIN_ATTEMPTS[key] = [v for v in values if now - v < 900]
            if not LOGIN_ATTEMPTS[key]:
                del LOGIN_ATTEMPTS[key]
        ip = request.client.host if request.client else "unknown"
        values = LOGIN_ATTEMPTS.setdefault(ip, [])
        total = sum(len(v) for v in LOGIN_ATTEMPTS.values())
        if len(values) >= 8 or total >= 80:
            raise HTTPException(429, "登入嘗試過多，請稍後再試")
        values.append(now)
    if int(request.headers.get("content-length", "0") or 0) > 256:
        raise HTTPException(413, "Request too large")
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    code = body.get("passcode") if isinstance(body, dict) else None
    if not isinstance(code, str) or not hmac.compare_digest(code, _passcode()):
        raise HTTPException(401, "登入碼錯誤")
    expires = str(int(time.time()) + TTL)
    nonce = secrets.token_hex(12)
    data = expires + "." + nonce
    resp = JSONResponse({"ok": True, "signed_in": True})
    resp.set_cookie(COOKIE, data + "." + _sign(data),
                    max_age=TTL, httponly=True, secure=True, samesite="lax",
                    path="/scanner")
    return resp


@router.post("/scanner/api/logout")
async def logout(request: Request):
    _check_origin(request)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/scanner", secure=True, httponly=True, samesite="lax")
    return resp


def attach_stock_lookup(stock_lookup):
    """Bind the existing read-only V33 stock bridge, without modifying it."""
    @router.post("/scanner/api/stock")
    async def scanner_stock(request: Request):
        _check_origin(request)
        _require(request)
        if int(request.headers.get("content-length", "0") or 0) > 512:
            raise HTTPException(413, "Request too large")
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
            raise HTTPException(400, "Invalid product code")
        code = code.strip()
        async with LOCK:
            now = time.monotonic()
            REQUEST_TIMES[:] = [v for v in REQUEST_TIMES if now - v < 60]
            if len(REQUEST_TIMES) >= 35:
                raise HTTPException(429, "查詢太頻繁，請稍後重試")
            REQUEST_TIMES.append(now)
        from xingwang_miniapp.stock_mcp import normalize_stock, stock_variant_breakdown
        raw = await stock_lookup(code)
        clean = normalize_stock(raw, code)
        if not clean.get("ok"):
            err = clean.get("code") or "STOCK_UNAVAILABLE"
            status = 404 if err == "NOT_FOUND" else 429 if err == "BUSY" else 503
            return JSONResponse({"ok": False, "code": err,
                "error": "庫存不存在" if status == 404 else
                         "本機 V33 離線或庫存暫時無法查詢，請確認 V33 已開啟"}, status_code=status)
        variants = stock_variant_breakdown(clean)
        skus = [v["code"] for v in variants]
        can_save = scanner_tidb.configured() and 0 < len(skus) <= 500
        status_map = {}
        db_error = False
        if can_save:
            try:
                status_map = await asyncio.to_thread(scanner_tidb.read_status, code, skus)
            except Exception:
                # Keep stock lookup usable but explicitly disable sample writes.
                logging.getLogger("uvicorn.error").exception(
                    "SCANNER_TIDB_READ_FAILED series=%r", code
                )
                db_error = True
        scan_id = None
        if can_save and not db_error:
            scan_id = uuid4().hex
            device_id = hashlib.sha256(request.cookies.get(COOKIE,"").encode()).hexdigest()[:16]
            now = time.monotonic()
            for token,entry in list(PENDING_SCANS.items()):
                if now - entry[0] > 1800:
                    PENDING_SCANS.pop(token,None)
            if len(PENDING_SCANS) >= 500:
                PENDING_SCANS.pop(next(iter(PENDING_SCANS)))
            PENDING_SCANS[scan_id] = (now, device_id, code, tuple(skus))
        return JSONResponse({"ok": True, "product_code": code,
            "stock_rolls": clean.get("stock_rolls"),
            "stock_meters": clean.get("stock_meters"),
            "variants": variants,
            "source": clean.get("source"), "as_of": clean.get("as_of"),
            "db_connected": bool(scan_id), "db_error": db_error,
            "scan_id": scan_id, "previous_status": status_map})

    @router.post("/scanner/api/save")
    async def scanner_save(request: Request):
        _check_origin(request)
        _require(request)
        if not scanner_tidb.configured():
            raise HTTPException(503, "TiDB 尚未設定，無法保存")
        if int(request.headers.get("content-length", "0") or 0) > 6000:
            raise HTTPException(413, "Request too large")
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise HTTPException(400, "Invalid request")
        scan_id = data.get("scan_id")
        missed = data.get("missing")
        if (not isinstance(scan_id,str) or
            not re.fullmatch(r"[a-f0-9]{32}",scan_id) or
            not isinstance(missed,list) or len(missed)>500 or
            any(not isinstance(s,str) for s in missed) or
            len(set(missed)) != len(missed)):
            raise HTTPException(400, "Invalid scan submission")
        session = PENDING_SCANS.get(scan_id)
        if not session or time.monotonic()-session[0]>1800:
            raise HTTPException(409, "這次掃描已過期，請重新查詢")
        started, owner, series, skus = session
        device_id = hashlib.sha256(request.cookies.get(COOKIE,"").encode()).hexdigest()[:16]
        if not hmac.compare_digest(owner,device_id) or not set(missed).issubset(skus):
            raise HTTPException(403, "Invalid scan authorization")
        try:
            result=await asyncio.to_thread(
                scanner_tidb.save_scan, scan_id, series, skus, missed, device_id
            )
        except Exception:
            logging.getLogger("uvicorn.error").exception(
                "SCANNER_TIDB_SAVE_FAILED series=%r",series
            )
            raise HTTPException(503, "TiDB 無法寫入，這次盤點未成功保存")
        return JSONResponse({"ok":True,"scan_id":scan_id,**result})
