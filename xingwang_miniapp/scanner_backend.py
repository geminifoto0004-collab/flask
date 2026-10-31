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
    if len(password) < 12:
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
