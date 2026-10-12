# -*- coding: utf-8 -*-
"""XINGWANG Mini App relay: no business database or Telegram bot token on Render.
Only a paired local worker can respond. The worker validates Telegram initData and group membership.
Run exactly one worker.
"""
import asyncio
import hmac
import json
import os
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

SECRET = os.environ.get("BRIDGE_SHARED_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("BRIDGE_SHARED_SECRET must be at least 32 characters")
app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
PAGE = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
active_bridge = None
bridge_lock = asyncio.Lock()
waiting = {}
MAX_INFLIGHT = 20

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
    return {"service":"xingwang-miniapp","local_online":active_bridge is not None}

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
    if alias not in ("STOCK","ADMIN") or action not in ("stock","camino","orders","nota"):
        raise HTTPException(400,"Unsupported action")
    if not isinstance(q,str) or not ((q=="@" and action=="nota") or (action=="nota" and len(q)==1 and q.isdecimal()) or 2<=len(q)<=40) or not isinstance(init_data,str) or not (1<=len(init_data)<=4096):
        raise HTTPException(400,"Invalid input")
    async with bridge_lock:
        ws=active_bridge
        if ws is None:raise HTTPException(503,"本機未連線")
        if len(waiting)>=MAX_INFLIGHT:raise HTTPException(429,"查詢過多")
        req_id=uuid4().hex
        future=asyncio.get_running_loop().create_future()
        waiting[req_id]=future
        try:
            await ws.send_json({"type":"query","id":req_id,"bot":alias,"action":action,"q":q,"init_data":init_data})
        except (RuntimeError,WebSocketDisconnect):
            waiting.pop(req_id,None)
            raise HTTPException(503,"連線中斷")
    try:
        response=await asyncio.wait_for(future,25)
    except asyncio.TimeoutError:
        raise HTTPException(504,"查詢逾時")
    finally:
        waiting.pop(req_id,None)
    if not response.get("ok"):
        # Authorization problems are 403; local API failures are 502, never "zero inventory".
        code = response.get("code") or "ACCESS_DENIED"
        status = 502 if code in ("LOCAL_API", "INTERNAL") else 400 if code == "INPUT" else 403
        return JSONResponse({"ok":False, "code":code,
                             "error":str(response.get("error") or "查詢未完成")[:150]},
                            status_code=status)
    return {"ok":True,"data":response.get("data")}

@app.websocket("/bridge")
async def bridge(ws:WebSocket):
    global active_bridge
    if not hmac.compare_digest(ws.headers.get("authorization",""),"Bearer "+SECRET):
        await ws.close(code=1008)
        return
    await ws.accept()
    async with bridge_lock:
        if active_bridge is not None:
            await ws.close(code=1008)
            return
        active_bridge=ws
    try:
        while True:
            try:
                incoming=await asyncio.wait_for(ws.receive_json(),timeout=20)
            except asyncio.TimeoutError:
                await ws.send_json({"type":"ping"})
                continue
            if isinstance(incoming,dict) and incoming.get("type")=="response":
                future=waiting.get(incoming.get("id"))
                if future is not None and not future.done():
                    future.set_result(incoming)
    except (WebSocketDisconnect,RuntimeError,ValueError):
        pass
    finally:
        async with bridge_lock:
            if active_bridge is ws:active_bridge=None
            for future in list(waiting.values()):
                if not future.done():future.set_result({"ok":False,"error":"本機斷線，請重試"})
