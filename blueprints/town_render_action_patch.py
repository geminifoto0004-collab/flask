"""Make ordinary AI actions visually obvious on the Render town page."""


def patch_render_actions(html: str) -> str:
    html = html.replace(
        "a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=rand(4.5,8.5);chooseIdleTarget(a,action.action);\n    addLog('AI 決定：'+agentLabel(a)+' → '+action.action);",
        "const labels={coffee:'去沖咖啡',files:'去整理文件',desk:'回工位工作',plant:'去看看植物',waterPlant:'去澆花',lookSea:'去窗邊看海',stretch:'伸展一下',radio:'去用海事電台',checkCoworker:'去找同事',fishing:'去釣魚',wander:'走一走'};\n"
        "    a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=rand(10,16);a.intentLabel=labels[action.action]||action.action;a.intentUntil=Date.now()+16000;chooseIdleTarget(a,action.action);\n"
        "    addLog('AI 指派：'+agentLabel(a)+' '+a.intentLabel);",
    )

    # Show what a moving character is on the way to do, and already carry the
    # relevant prop while walking instead of looking like a generic walk cycle.
    html = html.replace(
        "// 隨機摸魚／日常動作：不顯示文字，直接用道具和姿勢表達。\n    if(a.state==='idle'||(a.state==='idleWalk'&&a.idle==='sweep')){",
        "if(a.intentLabel&&Date.now()<(a.intentUntil||0)){const intent=String(a.intentLabel).slice(0,9),iw=Math.max(58,intent.length*10+14);rect(x-iw/2,y+20,iw,14,'rgba(15,24,32,.9)');txt(intent,x,y+31,'#ffffff',8,'center');}\n"
        "    // 行走途中就顯示對應道具，避免 AI 已下令但畫面只像普通散步。\n"
        "    if(a.state==='idle'||a.state==='idleWalk'){const visibleIdleAction=a.state==='idleWalk'?a.idle:a.idleAction;",
    )
    replacements = {
        "if(a.idleAction==='coffee')": "if(visibleIdleAction==='coffee')",
        "else if(a.idleAction==='files')": "else if(visibleIdleAction==='files')",
        "else if(a.idleAction==='window'||a.idleAction==='lookSea')": "else if(visibleIdleAction==='window'||visibleIdleAction==='lookSea')",
        "else if(a.idleAction==='plant')": "else if(visibleIdleAction==='plant')",
        "else if(a.idleAction==='waterPlant')": "else if(visibleIdleAction==='waterPlant')",
        "else if(a.idleAction==='desk')": "else if(visibleIdleAction==='desk')",
        "else if(a.idleAction==='stretch')": "else if(visibleIdleAction==='stretch')",
        "else if(a.idleAction==='radio')": "else if(visibleIdleAction==='radio')",
        "else if(a.idleAction==='chat')": "else if(visibleIdleAction==='chat')",
        "else if(a.idleAction==='checkCoworker')": "else if(visibleIdleAction==='checkCoworker')",
        "else if(a.idleAction==='fishing')": "else if(visibleIdleAction==='fishing')",
        "else if(a.idleAction==='cleanPoop')": "else if(visibleIdleAction==='cleanPoop')",
        "else if(a.idleAction==='sweep')": "else if(visibleIdleAction==='sweep')",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html
