"""Make ordinary AI actions visually obvious and feed recent action history back to the director."""


def patch_render_actions(html: str) -> str:
    # Remember only actions that the browser actually received. The next AI
    # tick sees this tiny history and can avoid repeating the same safe choice.
    html = html.replace(
        "function applyAiTownActions(actions=[]){\n    if(!Array.isArray(actions))return;",
        "function applyAiTownActions(actions=[]){\n"
        "    if(!Array.isArray(actions))return;\n"
        "    const visibleActions=actions.filter(a=>a&&typeof a==='object');\n"
        "    if(visibleActions.length){window.__townDirectorHistory=Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[];visibleActions.forEach(a=>window.__townDirectorHistory.push({at:Date.now(),type:String(a.type||''),agent:String(a.agent||a.from||''),target:String(a.to||''),action:String(a.action||''),label:String(a.label||a.furniture||'')}));window.__townDirectorHistory=window.__townDirectorHistory.slice(-12);}",
    )
    html = html.replace(
        "furniture:aiFurniture.map(f=>({id:f.id,type:f.type,x:f.x,y:f.y,w:f.w,h:f.h,label:f.label||''}))\n    };",
        "furniture:aiFurniture.map(f=>({id:f.id,type:f.type,x:f.x,y:f.y,w:f.w,h:f.h,label:f.label||''})),\n"
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12)\n"
        "    };",
    )

    # Give every AI movement a protected execution window. Random idle logic may
    # resume only after the visible action has actually played, while ship work
    # can still pre-empt it through the existing queue/task logic.
    html = html.replace(
        "a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=rand(4.5,8.5);chooseIdleTarget(a,action.action);\n    addLog('AI 決定：'+agentLabel(a)+' → '+action.action);",
        "const labels={coffee:'去沖咖啡',files:'去整理文件',desk:'回工位工作',plant:'去看看植物',waterPlant:'去澆花',lookSea:'去窗邊看海',stretch:'伸展一下',radio:'去用海事電台',checkCoworker:'去找同事',fishing:'去釣魚',wander:'走一走'};\n"
        "    a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=999;a.intentLabel=labels[action.action]||action.action;a.intentUntil=Date.now()+30000;a.intentStarted=false;a.directorAction=action.action;a.directorCompleted=false;a.directorLockUntil=Date.now()+30000;chooseIdleTarget(a,action.action);\n"
        "    addLog('AI 指派：'+agentLabel(a)+' '+a.intentLabel);",
    )

    html = html.replace(
        "if(a.state==='idle'){\n        a.timer-=dt;a.decisionTimer-=dt;",
        "if(a.state==='idle'){\n        a.timer-=dt;a.decisionTimer-=dt;\n        const directorLocked=Date.now()<(a.directorLockUntil||0)&&!!a.directorAction;",
    )
    html = html.replace(
        "if(a.timer<=0)chooseIdleTarget(a);",
        "if(a.timer<=0){if(directorLocked){a.timer=.6;}else{chooseIdleTarget(a);}}",
    )

    # Hold ordinary AI actions on screen long enough to be unmistakable.
    timing_replacements = {
        "if(a.idle==='coffee'){a.timer=rand(1.4,5.5);": "if(a.idle==='coffee'){a.timer=rand(5.5,8.5);",
        "if(a.idle==='lookSea')a.timer=rand(1.2,5.4);": "if(a.idle==='lookSea')a.timer=rand(5.0,8.0);",
        "if(a.idle==='files')a.timer=rand(1.0,4.6);": "if(a.idle==='files')a.timer=rand(5.0,8.0);",
        "if(a.idle==='fishing'){a.timer=rand(4.5,12);": "if(a.idle==='fishing'){a.timer=rand(7.0,12);",
    }
    for old, new in timing_replacements.items():
        html = html.replace(old, new)

    # Mark a protected action complete only after it reached the destination and
    # visibly ran. This makes the log reflect execution rather than intent.
    html = html.replace(
        "    // 不再把所有空閒關員強制抓去工作；每個人各自有工作意願與隨機決策時間。",
        "      if(a.state==='idle'&&a.directorAction&&Date.now()<(a.directorLockUntil||0)&&a.intentStarted&&a.timer<=.65&&a.directorAction!=='chat'){addLog('AI 動作完成：'+agentLabel(a)+' '+(a.intentLabel||a.directorAction));a.directorCompleted=true;a.directorAction='';a.directorLockUntil=0;a.intentLabel='';a.intentUntil=0;a.decisionTimer=rand(1.5,4);a.timer=rand(.8,2.2);}\n"
        "    });\n"
        "    // 不再把所有空閒關員強制抓去工作；每個人各自有工作意願與隨機決策時間。",
        1,
    )

    # The embedded snapshot already closes agents.forEach immediately before the
    # comment above. If the previous replacement inserted an extra close, fix it.
    html = html.replace("    });\n      if(a.state==='idle'&&a.directorAction", "      if(a.state==='idle'&&a.directorAction")

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
