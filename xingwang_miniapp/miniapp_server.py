# -*- coding: utf-8 -*-
"""XINGWANG Mini App relay: no business database or Telegram bot token on Render.
Only a paired local worker can respond. The worker validates Telegram initData and group membership.
Run exactly one worker.
"""
import asyncio
import hmac
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager

SECRET = os.environ.get("BRIDGE_SHARED_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("BRIDGE_SHARED_SECRET must be at least 32 characters")
stock_mcp_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # A mounted SDK sub-app does not run its own lifespan automatically.
    if stock_mcp_service is None:
        yield
    else:
        async with stock_mcp_service.session_manager.run():
            yield

app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None, lifespan=lifespan)
PAGE = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
active_bridge = None
active_role = None
bridge_lock = asyncio.Lock()
peers = {}
waiting = {}  # id -> (future, owner socket)
MAX_INFLIGHT = 20
# The old host's 12-sec local lease and in-flight requests must expire.
HANDOVER_SECONDS = 32
HEARTBEAT_SECONDS = 3
PEER_TIMEOUT_SECONDS = 10
handover_task = None
handover_version = 0
# This pilot is OFF unless enabled with a separate, revocable 32+ char ticket.
# No time-based expiry: operator can disable the flag or rotate the ticket.
pilot_recent_calls = []
pilot_rate_lock = asyncio.Lock()

# Public read-only stock URL for ChatGPT voice / browser URL reads.
# Intentionally has NO token. It exposes only stock quantities and incoming
# quantities, never prices, customers, orders, notes, or raw Flask payloads.
public_stock_recent_calls = []
public_stock_rate_lock = asyncio.Lock()

@app.middleware("http")
async def nocache(request:Request,call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(PAGE)

@app.get("/admin", response_class=HTMLResponse)
async def admin():
    return HTMLResponse(PAGE)

@app.get("/healthz")
async def healthz():
    return {"service":"xingwang-miniapp","local_online":active_bridge is not None,"active_site":active_role,"home_online":"home" in peers,"company_online":"company" in peers}


async def send_peer(role, payload):
    peer=peers.get(role)
    if peer is not None:
        async with peer["send_lock"]:
            await peer["ws"].send_json(payload)

def best_role():
    return "company" if "company" in peers else "home" if "home" in peers else None

def cancel_owner(ws):
    for future,owner in waiting.values():
        if owner is ws and not future.done():
            future.set_result({"ok":False,"code":"SWITCHING",
                               "error":"正在切换公司／家里的电脑，请稍后重新查询"})

async def promote_after(version):
    global active_bridge,active_role
    await asyncio.sleep(HANDOVER_SECONDS)
    async with bridge_lock:
        if version!=handover_version or active_bridge is not None:return
        role=best_role()
        if role is None:return
        target=peers[role]["ws"]
        try:
            await send_peer(role,{"type":"active","epoch":version})
        except (RuntimeError,WebSocketDisconnect,OSError):
            return
        active_bridge=target
        active_role=role

async def rebalance():
    """Must hold bridge_lock. Old lease expires before promotion."""
    global active_bridge,active_role,handover_task,handover_version
    selected=best_role()
    if active_bridge is not None and active_role==selected:
        for role in peers:
            if role!=active_role:
                try:await send_peer(role,{"type":"standby"})
                except (RuntimeError,WebSocketDisconnect,OSError):pass
        return
    former=active_bridge
    active_bridge=None
    active_role=None
    if former is not None:cancel_owner(former)
    handover_version+=1
    if handover_task is not None:handover_task.cancel()
    for role in peers:
        try:await send_peer(role,{"type":"standby"})
        except (RuntimeError,WebSocketDisconnect,OSError):pass
    if selected is not None:
        handover_task=asyncio.create_task(promote_after(handover_version))

async def peer_heartbeat(role,ws):
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        entry=peers.get(role)
        if entry is None or entry["ws"] is not ws:return
        if time.monotonic()-entry["last_pong"]>PEER_TIMEOUT_SECONDS:
            try:await ws.close(code=1011,reason="Heartbeat timeout")
            except (RuntimeError,WebSocketDisconnect,OSError):pass
            return
        try:await send_peer(role,{"type":"ping"})
        except (RuntimeError,WebSocketDisconnect,OSError):return

@app.post("/api/query")
async def query(request:Request):
    try:
        raw = await request.body()
        if len(raw)>6000:raise HTTPException(413,"Request too large")
        payload = json.loads(raw)
    except HTTPException:raise
    except (ValueError,UnicodeError):raise HTTPException(400,"Invalid JSON")
    if not isinstance(payload,dict):raise HTTPException(400,"Invalid query")
    alias,action,q,init_data = (payload.get(k) for k in ("bot","action","q","init_data"))
    if alias not in ("STOCK","ADMIN") or action not in ("stock","camino","orders","nota","history_more","nota_media","nota_details"):
        raise HTTPException(400,"Unsupported action")
    if not isinstance(q,str) or not ((q=="@" and action=="nota") or (action=="nota" and len(q)==1 and q.isdecimal()) or 2<=len(q)<=40) or not isinstance(init_data,str) or not (1<=len(init_data)<=4096):
        raise HTTPException(400,"Invalid input")
    session = payload.get("miniapp_session", "")
    if not isinstance(session, str) or len(session) > 100:
        raise HTTPException(400, "Invalid Mini App session")
    extra = {"miniapp_session": session}
    if action == "nota":
        span = payload.get("date_span","2y")
        if not isinstance(span,str) or span not in ("1y","2y","all"):
            raise HTTPException(400,"Invalid Nota date range")
        extra.update({"date_span":span})
    if action == "history_more":
        cursor = payload.get("cursor")
        include_older = payload.get("include_older")
        if type(cursor) is not int or not (0<=cursor<=5000) or type(include_older) is not bool:
            raise HTTPException(400,"Invalid history pagination")
        extra.update({"cursor":cursor,"include_older":include_older})
    if action in ("nota_media","nota_details"):
        customer=payload.get("customer","")
        if not q.isdecimal() or not 2<=len(q)<=12 or not isinstance(customer,str) or len(customer)>130:
            raise HTTPException(400,"Invalid Nota image request")
        extra.update({"customer":customer})
    async with bridge_lock:
        ws=active_bridge
        role=active_role
        if ws is None or role is None:raise HTTPException(503,"本机切换中或未连线，请稍后重试")
        if len(waiting)>=MAX_INFLIGHT:raise HTTPException(429,"查詢過多")
        req_id=uuid4().hex
        future=asyncio.get_running_loop().create_future()
        waiting[req_id]=(future,ws)
        try:
            await send_peer(role,{"type":"query","id":req_id,"bot":alias,"action":action,"q":q,"init_data":init_data,**extra})
        except (RuntimeError,WebSocketDisconnect):
            waiting.pop(req_id,None)
            raise HTTPException(503,"連線中斷")
    try:
        response=await asyncio.wait_for(future,45)
    except asyncio.TimeoutError:
        raise HTTPException(504,"查詢逾時")
    finally:
        waiting.pop(req_id,None)
    if not response.get("ok"):
        # Authorization problems are 403; local API failures are 502, never "zero inventory".
        code = response.get("code") or "ACCESS_DENIED"
        status = 503 if code in ("SWITCHING","STANDBY") else 502 if code in ("LOCAL_API", "INTERNAL") else 409 if code == "HISTORY_EXPIRED" else 400 if code == "INPUT" else 403
        return JSONResponse({"ok":False, "code":code,
                             "error":str(response.get("error") or "查詢未完成")[:150]},
                            status_code=status)
    result = {"ok":True,"data":response.get("data")}
    session_return = response.get("miniapp_session", "")
    if isinstance(session_return, str) and len(session_return) <= 100 and session_return.startswith("xw_"):
        result["miniapp_session"] = session_return
    return result

@app.websocket("/bridge")
async def bridge(ws:WebSocket):
    role=ws.query_params.get("role","")
    proto=ws.query_params.get("protocol","")
    if (not hmac.compare_digest(ws.headers.get("authorization",""),"Bearer "+SECRET)
        or role not in ("home","company") or proto!="v20"):
        await ws.close(code=1008)
        return
    await ws.accept()
    async with bridge_lock:
        if role in peers:
            await ws.close(code=1008)
            return
        peers[role]={"ws":ws,"last_pong":time.monotonic(),"send_lock":asyncio.Lock()}
        await rebalance()
    heartbeat=asyncio.create_task(peer_heartbeat(role,ws))
    try:
        while True:
            msg=await ws.receive_json()
            if not isinstance(msg,dict):continue
            if msg.get("type")=="pong":
                entry=peers.get(role)
                if entry is not None and entry["ws"] is ws:
                    entry["last_pong"]=time.monotonic()
            elif msg.get("type")=="response" and active_bridge is ws:
                record=waiting.get(msg.get("id"))
                if record is not None:
                    future,owner=record
                    if owner is ws and not future.done():
                        future.set_result(msg)
    except (WebSocketDisconnect,RuntimeError,ValueError):
        pass
    finally:
        heartbeat.cancel()
        async with bridge_lock:
            if peers.get(role,{}).get("ws") is ws:
                peers.pop(role,None)
                cancel_owner(ws)
                await rebalance()

# ----------------------- XINGWANG STOCK MCP -----------------------
# Completely separate from Telegram init_data. Disabled by default.
# No public MCP endpoint exists until XW_STOCK_MCP_ENABLED=1 AND the
# OAuth identity provider, audience and approved subjects are configured.
async def relay_stock_mcp(product_code: str) -> dict:
    async with bridge_lock:
        ws = active_bridge
        role = active_role
        if ws is None or role is None:
            return {"ok": False, "code": "LOCAL_OFFLINE"}
        if len(waiting) >= MAX_INFLIGHT:
            return {"ok": False, "code": "BUSY"}
        req_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        waiting[req_id] = (future, ws)
        try:
            # Distinct worker action; existing Telegram action='stock' cannot
            # be called with missing or fabricated Telegram credentials.
            await send_peer(role, {
                "type": "query",
                "id": req_id,
                "source": "chatgpt_oauth",
                "bot": "STOCK",
                "action": "stock_mcp",
                "q": product_code,
            })
        except (RuntimeError, WebSocketDisconnect, OSError):
            waiting.pop(req_id, None)
            return {"ok": False, "code": "LOCAL_OFFLINE"}
    try:
        reply = await asyncio.wait_for(future, timeout=35)
    except asyncio.TimeoutError:
        return {"ok": False, "code": "TIMEOUT"}
    finally:
        waiting.pop(req_id, None)
    if not isinstance(reply, dict):
        return {"ok": False, "code": "INVALID_RESPONSE"}
    if reply.get("ok") is not True:
        return {"ok": False, "code": reply.get("code", "LOCAL_API")}
    return {"ok": True, "data": reply.get("data"), "source": role}


def _render_stock_variant_table(variants: list[dict]) -> str:
    """HTML contains only already-allowlisted product codes and quantities."""
    from html import escape
    def safe(value):
        return escape(str(value if value is not None else "未提供"), quote=True)
    if not variants:
        return "<h2>各商品庫存明細</h2><p>沒有可列出的子商品明細</p>"
    lines = [
        "<h2>各商品編號庫存明細</h2>",
        "<table border='1' cellspacing='0' cellpadding='6'>",
        "<thead><tr><th>商品編號</th><th>庫存匹數</th>"
        "<th>庫存米數</th><th>待到貨箱數</th></tr></thead><tbody>",
    ]
    for row in variants:
        lines.append(
            "<tr>"
            f"<td>{safe(row['code'])}</td>"
            f"<td>{safe(row['stock_rolls'])}</td>"
            f"<td>{safe(row['stock_meters'])}</td>"
            f"<td>{safe(row['incoming_boxes'])}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    lines.append("<p>「未提供」不等於 0。負數庫存保留 ERP 原始數字；"
                 "待到貨單位是箱，不換算成匹或米。</p>")
    return "".join(lines)


# ---------------- Public read-only stock URL ----------------
# Example:
#   /stock?code=1314
#   /stock?code=120-07&format=html
# This endpoint is deliberately token-free so ordinary ChatGPT voice can
# construct and read the URL directly. Keep the response strictly allowlisted.
@app.get("/stock")
async def stock_public(request: Request, code: str = ""):
    from xingwang_miniapp.stock_mcp import CODE_PATTERN, normalize_stock, stock_variant_breakdown

    code = (code or "").strip()
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(400, "Invalid product code")

    # Global abuse guard. This is intentionally simple because the endpoint is
    # public; it prevents the public URL from flooding the local Windows bridge.
    async with public_stock_rate_lock:
        now = time.monotonic()
        public_stock_recent_calls[:] = [
            t for t in public_stock_recent_calls if now - t < 60
        ]
        if len(public_stock_recent_calls) >= 30:
            raise HTTPException(429, "Public stock query limit reached")
        public_stock_recent_calls.append(now)

    raw = await relay_stock_mcp(code)
    normalized = normalize_stock(raw, code)

    noindex_headers = {
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "Access-Control-Allow-Origin": "*",
    }

    if not normalized.get("ok"):
        upstream_code = str(normalized.get("code") or "STOCK_UNAVAILABLE")
        status = 404 if upstream_code == "NOT_FOUND" else 503
        return JSONResponse(
            {
                "ok": False,
                "product_code": code,
                "code": upstream_code,
                "error": "STOCK_UNAVAILABLE",
            },
            status_code=status,
            headers=noindex_headers,
        )

    clean = {
        "ok": True,
        "product_code": code,
        "stock_rolls": normalized["stock_rolls"],
        "stock_meters": normalized["stock_meters"],
        "stock_rolls_missing": normalized.get("stock_rolls_missing", 0),
        "stock_meters_missing": normalized.get("stock_meters_missing", 0),
        "variants": stock_variant_breakdown(normalized),
        "incoming_rolls": normalized.get("incoming_rolls"),
        "incoming_meters": normalized.get("incoming_meters"),
        "incoming_boxes": normalized.get("incoming_boxes"),
        "source": normalized.get("source"),
        "as_of": normalized.get("as_of"),
    }

    if request.query_params.get("format") == "html":
        from html import escape

        def safe(value):
            return escape(
                str(value if value is not None else "未提供"),
                quote=True,
            )

        contents = (
            "<!doctype html><html lang='zh-Hant'><head>"
            "<meta charset='utf-8'>"
            "<meta name='robots' content='noindex,nofollow,noarchive'>"
            f"<title>XINGWANG STOCK {safe(code)}</title></head><body>"
            f"<main><h1>商品系列 {safe(code)}</h1>"
            "<h2>系列合計</h2>"
            f"<p>庫存匹數：<strong>{safe(clean['stock_rolls'])}</strong> 匹</p>"
            f"<p>庫存米數：<strong>{safe(clean['stock_meters'])}</strong> 米</p>"
            f"<p>匹數缺失筆數：{safe(clean['stock_rolls_missing'])}；"
            f"米數缺失筆數：{safe(clean['stock_meters_missing'])}</p>"
            f"<p>待到貨箱數：<strong>{safe(clean['incoming_boxes'])}</strong> 箱</p>"
            f"<p>待到貨匹數：{safe(clean['incoming_rolls'])}</p>"
            f"<p>待到貨米數：{safe(clean['incoming_meters'])}</p>"
            f"<p>資料來源：{safe(clean['source'])}</p>"
            f"<p>查詢時間：{safe(clean['as_of'])}</p>"
            + _render_stock_variant_table(clean["variants"])
            + "</main></body></html>"
        )
        return HTMLResponse(contents, headers=noindex_headers)

    return JSONResponse(clean, headers=noindex_headers)


# ---------------- Temporary REAL STOCK URL pilot ----------------
# GET is needed for ordinary ChatGPT URL-reading experiments.
# Never remove the ticket check; never expose prices or other Flask outputs.
# This is not the long-term username/password login flow.
@app.get("/stock-test")
async def stock_test(request: Request, code: str = "", ticket: str = ""):
    from xingwang_miniapp.stock_mcp import (
        normalize_stock, pilot_access_allowed, pilot_stock_view
    )
    if not pilot_access_allowed(
        code=code,
        ticket=ticket,
        enabled=os.environ.get("XW_STOCK_TEST_ENABLED", ""),
        server_secret=os.environ.get("XW_STOCK_TEST_TICKET", ""),
    ):
        # Do not reveal whether a real stock service is running.
        raise HTTPException(404, "Not Found")

    async with pilot_rate_lock:
        now = time.monotonic()
        pilot_recent_calls[:] = [t for t in pilot_recent_calls if now - t < 60]
        if len(pilot_recent_calls) >= 8:
            raise HTTPException(429, "Temporary test query limit reached")
        pilot_recent_calls.append(now)

    raw = await relay_stock_mcp(code)
    normalized = normalize_stock(raw, code)
    clean = pilot_stock_view(normalized, code)
    # No zero-stock fabrication on upstream failure.
    if not clean.get("ok"):
        return JSONResponse(
            {"ok": False, "test_only": True, "error": "本機庫存暫時無法取得"},
            status_code=503,
            headers={"X-Robots-Tag": "noindex, nofollow, noarchive"},
        )
    noindex_headers = {"X-Robots-Tag": "noindex, nofollow, noarchive"}
    if request.query_params.get("format") == "html":
        # Render only the already-allowlisted stock fields; never forward
        # raw Flask results, pricing, customers, or user-supplied HTML.
        from html import escape
        def safe(value):
            return escape(str(value if value is not None else "未提供"), quote=True)
        contents = (
            "<!doctype html><html lang='zh-Hant'><head>"
            "<meta charset='utf-8'><meta name='robots' content='noindex,nofollow,noarchive'>"
            f"<title>XINGWANG STOCK {safe(code)} 即時庫存</title></head><body>"
            f"<main><h1>XINGWANG STOCK：商品 {safe(code)}</h1>"
            "<p>這是現有 Windows Flask 的即時查詢結果，僅供授權測試；不是模擬資料。</p>"
            f"<p>庫存匹數：<strong>{safe(clean['stock_rolls'])}</strong> 匹</p>"
            f"<p>庫存米數：<strong>{safe(clean['stock_meters'])}</strong> 米</p>"
            f"<p>匹數缺失筆數：{safe(clean['stock_rolls_missing'])}；"
            f"米數缺失筆數：{safe(clean['stock_meters_missing'])}</p>"
            f"<p>待到貨箱數：<strong>{safe(clean['incoming_boxes'])}</strong> 箱</p>"
            f"<p>待到貨匹數：{safe(clean['incoming_rolls'])}；"
            f"待到貨米數：{safe(clean['incoming_meters'])}</p>"
            f"<p>資料來源：{safe(clean['source'])}；查詢時間：{safe(clean['as_of'])}</p>"
            "<p>本頁不提供售價、成本、客戶或訂單資料。</p>"
            "</main></body></html>"
        )
        return HTMLResponse(contents, headers=noindex_headers)
    return JSONResponse(clean, headers=noindex_headers)

if os.environ.get("XW_STOCK_MCP_ENABLED", "") == "1":
    from xingwang_miniapp.stock_mcp import create_stock_mcp
    stock_mcp_service, stock_mcp_asgi = create_stock_mcp(relay_stock_mcp)
    # Mount LAST so /api/query, /bridge and the Mini App remain unchanged.
    app.mount("/", stock_mcp_asgi, name="xingwang-stock-mcp")
