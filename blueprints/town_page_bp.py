"""Standalone browser page for CUSTOMS AGENT TOWN."""

import os

from flask import Blueprint, Response, current_app, jsonify


town_page_bp = Blueprint("town_page", __name__)


def _town_page_path():
    return os.path.join(current_app.root_path, "templates", "customs_agent_town.html")


def _patched_town_html():
    """Serve the standalone town with the newest autonomous AI behavior."""
    page_path = _town_page_path()
    with open(page_path, "r", encoding="utf-8") as fh:
        html = fh.read()

    # AI decisions must drive the real character target instead of being overwritten
    # by the next random idle decision.
    html = html.replace(
        "a.idle=action.action;a.timer=0;a.decisionTimer=rand(1.5,4.5);\n          chooseIdleTarget(a);",
        "a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=rand(4.5,8.5);\n          chooseIdleTarget(a,action.action);",
    )
    html = html.replace("function chooseIdleTarget(a){", "function chooseIdleTarget(a,forcedMode=''){")
    html = html.replace("const mode=randIdle(a);", "const mode=forcedMode||randIdle(a);")
    html = html.replace("coffee:[{x:120,y:180},{x:262,y:180}],", "coffee:[{x:500,y:130},{x:486,y:146}],")
    html = html.replace("files:[{x:a.homeX-54,y:146},{x:a.homeX+48,y:146}],", "files:[{x:112,y:126},{x:120,y:146}],")
    html = html.replace("lookSea:[{x:438,y:258},{x:410,y:258}],", "lookSea:[{x:300,y:246},{x:340,y:246}],")

    # Comfortable desktop overview size.
    html = html.replace(
        "  padding:18px;\n  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
        "  padding:10px;\n  max-width:1180px;\n  margin:0 auto;\n  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
    )
    html = html.replace(
        "#customs-sim .game-wrap{background:#090d13;padding:8px;border:3px solid #080a0d;box-shadow:0 0 0 3px light-dark(#696153,#344052);overflow:hidden}",
        "#customs-sim .game-wrap{background:#090d13;padding:6px;border:3px solid #080a0d;box-shadow:0 0 0 3px light-dark(#696153,#344052);overflow:hidden;display:flex;justify-content:center}",
    )
    html = html.replace(
        "#customs-sim canvas{display:block;width:100%;height:auto;aspect-ratio:8/5;image-rendering:pixelated;image-rendering:crisp-edges;background:#173344}",
        "#customs-sim canvas{display:block;width:min(100%,960px);height:auto;aspect-ratio:8/5;image-rendering:pixelated;image-rendering:crisp-edges;background:#173344}",
    )
    html = html.replace(
        "@media(max-width:600px){#customs-sim.app-root{padding:10px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
        "@media(max-width:600px){#customs-sim.app-root{padding:8px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
    )

    # Auto-AI UI and state.
    html = html.replace(
        '<button id="aiTestBtn" type="button">🧠 AI 小鎮想一下</button>',
        '<button id="aiTestBtn" type="button">🧠 AI 立即想一下</button>\n    <button id="aiAutoBtn" type="button">⚡ AI 自動：開</button>',
    )
    html = html.replace(
        "start:root.querySelector('#startBtn'), add:root.querySelector('#addBtn'), finish:root.querySelector('#finishBtn'), aiTest:root.querySelector('#aiTestBtn'), aiBase:root.querySelector('#aiBaseInput'), aiSave:root.querySelector('#aiSaveBtn'), reset:root.querySelector('#resetBtn'), speed:root.querySelector('#speedSelect')",
        "start:root.querySelector('#startBtn'), add:root.querySelector('#addBtn'), finish:root.querySelector('#finishBtn'), aiTest:root.querySelector('#aiTestBtn'), aiAuto:root.querySelector('#aiAutoBtn'), aiBase:root.querySelector('#aiBaseInput'), aiSave:root.querySelector('#aiSaveBtn'), reset:root.querySelector('#resetBtn'), speed:root.querySelector('#speedSelect')",
    )
    html = html.replace(
        "  let vessels=[];",
        "  let vessels=[];\n  let aiAuto=localStorage.getItem('customs-town-ai-auto')!=='0';\n  let aiAutoTimer=rand(35,75);\n  let aiBusy=false;\n  let decorVariant=Math.floor(rand(0,4));\n  let serverStateTimer=12;\n  let serverPlanTimer=6;\n  let lastServerPlanVersion=Number(localStorage.getItem('customs-town-plan-version')||0);",
    )

    # DeepSeek may now trigger a safe decorative layout shuffle.
    html = html.replace(
        "      }else if(action.type==='dog_visit'&&dogVisitors.length<2){\n        spawnDog(action.kind==='female'?'female':'male',Math.random()<.5);\n        addLog('AI 觸發了一隻過路狗');\n      }",
        "      }else if(action.type==='dog_visit'&&dogVisitors.length<2){\n        spawnDog(action.kind==='female'?'female':'male',Math.random()<.5);\n        addLog('AI 觸發了一隻過路狗');\n      }else if(action.type==='layout_shuffle'){\n        decorVariant=(decorVariant+1+Math.floor(Math.random()*3))%4;\n        const live=plantStates.filter(p=>p.alive);\n        live.forEach(p=>{const slot=chooseFreePlantSlot(p.id);p.x=slot.x;p.y=slot.y;});\n        addLog('AI 重新整理了辦公室的生活佈局');\n      }",
    )
    html = html.replace(
        "  async function testDeepSeek(){\n    if(!ui.aiTest)return;",
        "  async function testDeepSeek(){\n    if(!ui.aiTest)return;\n    if(aiBusy)return;",
    )
    html = html.replace(
        "    ui.aiTest.disabled=true;",
        "    aiBusy=true;\n    ui.aiTest.disabled=true;",
    )
    html = html.replace(
        "    }finally{\n      ui.aiTest.disabled=false;",
        "    }finally{\n      aiBusy=false;\n      ui.aiTest.disabled=false;",
    )

    # Browser periodically saves the world snapshot and consumes plans generated by
    # cron-job.org while the page was closed.
    html = html.replace(
        "  function sync(){",
        "  async function pushTownState(){\n    if(!TOWN_AI_BASE)return;\n    try{await fetch(TOWN_AI_BASE+'/api/town/state',{method:'POST',headers:{'Accept':'application/json'},body:JSON.stringify({world:compactTownSnapshot()})});}catch(_e){}\n  }\n  async function pullTownPlan(){\n    if(!TOWN_AI_BASE||aiBusy)return;\n    try{\n      const r=await fetch(TOWN_AI_BASE+'/api/town/plan',{headers:{'Accept':'application/json'}});\n      if(!r.ok)return;\n      const data=await r.json();\n      const version=Number(data?.version||0);\n      if(version<=lastServerPlanVersion)return;\n      lastServerPlanVersion=version;\n      localStorage.setItem('customs-town-plan-version',String(version));\n      applyAiTownActions(data?.actions||[]);\n      if(data?.thought)addLog('遠端 AI 演化：'+String(data.thought).slice(0,120));\n    }catch(_e){}\n  }\n  function sync(){",
    )
    html = html.replace(
        "    updateDogs(dt);",
        "    updateDogs(dt);\n    serverStateTimer-=dt;serverPlanTimer-=dt;\n    if(serverStateTimer<=0){serverStateTimer=45;pushTownState();}\n    if(serverPlanTimer<=0){serverPlanTimer=35;pullTownPlan();}\n    if(aiAuto&&!aiBusy){aiAutoTimer-=dt;if(aiAutoTimer<=0){aiAutoTimer=rand(300,900);testDeepSeek();}}",
    )

    # Visible decor variants make repeat visits feel less static without allowing AI
    # to break collision geometry or block the doorway.
    html = html.replace(
        "    drawWallFrame(412,42,'#6c8f8b');\n    drawWallFrame(472,42,'#b07d58');",
        "    drawWallFrame(412,42,['#6c8f8b','#7b86a0','#7d9465','#9b786d'][decorVariant]);\n    drawWallFrame(472,42,['#b07d58','#8e6f91','#6f8c85','#aa8a58'][decorVariant]);",
    )
    html = html.replace("    drawBreakTable(520,216);", "    drawBreakTable(decorVariant%2===0?520:500,216);")

    html = html.replace(
        "  ui.aiTest.addEventListener('click',testDeepSeek);",
        "  ui.aiTest.addEventListener('click',testDeepSeek);\n  ui.aiAuto.addEventListener('click',()=>{\n    aiAuto=!aiAuto;localStorage.setItem('customs-town-ai-auto',aiAuto?'1':'0');\n    aiAutoTimer=aiAuto?rand(15,35):999999;\n    ui.aiAuto.textContent=aiAuto?'⚡ AI 自動：開':'⚡ AI 自動：關';\n    addLog(aiAuto?'AI 自動導演已開啟，之後會自己觀察與改變小鎮':'AI 自動導演已關閉');\n  });",
    )
    html = html.replace(
        "    agents.forEach((a,i)=>{a.x=a.homeX+(i-1)*16;a.y=a.homeY-34-i*5;a.decisionTimer=rand(.5,2.0);chooseIdleTarget(a);a.walkPhase=i*1.7;});",
        "    agents.forEach((a,i)=>{a.x=a.homeX+(i-1)*16;a.y=a.homeY-34-i*5;a.decisionTimer=rand(.5,2.0);chooseIdleTarget(a);a.walkPhase=i*1.7;});\n    if(ui.aiAuto)ui.aiAuto.textContent=aiAuto?'⚡ AI 自動：開':'⚡ AI 自動：關';\n    if(aiAuto)aiAutoTimer=rand(8,22);\n    setTimeout(()=>{pushTownState();pullTownPlan();},900);",
    )
    return html


@town_page_bp.route("/customs-town", methods=["GET"])
@town_page_bp.route("/customs-town/", methods=["GET"])
def customs_town_page():
    return Response(_patched_town_html(), mimetype="text/html")


@town_page_bp.route("/api/town/page-health", methods=["GET"])
def customs_town_page_health():
    page_path = _town_page_path()
    return jsonify({
        "ok": True,
        "page": "customs-town",
        "file_exists": os.path.isfile(page_path),
        "file_size": os.path.getsize(page_path) if os.path.isfile(page_path) else 0,
        "ai_action_patch": True,
        "compact_layout": True,
        "auto_ai": True,
        "cron_plan_sync": True,
    })
