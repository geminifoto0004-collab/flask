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
    extra = {}
    if action == "nota":
        span = payload.get("date_span","2y")
        if not isinstance(span,str) or span not in ("1y","2y","all"):
            raise HTTPException(400,"Invalid Nota date range")
        extra = {"date_span":span}
    if action == "history_more":
        cursor = payload.get("cursor")
        include_older = payload.get("include_older")
        if type(cursor) is not int or not (0<=cursor<=5000) or type(include_older) is not bool:
            raise HTTPException(400,"Invalid history pagination")
        extra = {"cursor":cursor,"include_older":include_older}
    if action in ("nota_media","nota_details"):
        customer=payload.get("customer","")
        if not q.isdecimal() or not 2<=len(q)<=12 or not isinstance(customer,str) or len(customer)>130:
            raise HTTPException(400,"Invalid Nota image request")
        extra = {"customer":customer}
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
    return {"ok":True,"data":response.get("data")}

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

if os.environ.get("XW_STOCK_MCP_ENABLED", "") == "1":
    from xingwang_miniapp.stock_mcp import create_stock_mcp
    stock_mcp_service, stock_mcp_asgi = create_stock_mcp(relay_stock_mcp)
    # Mount LAST so /api/query, /bridge and the Mini App remain unchanged.
    app.mount("/", stock_mcp_asgi, name="xingwang-stock-mcp")
