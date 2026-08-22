"""Small runtime patch for the Render-served town snapshot.

The App Block moves faster than the embedded snapshot. This patch fixes the
important visibility contract without another full HTML snapshot upload:
AI dialogue waits until both characters meet, stays on screen long enough, and
manual AI calls show the exact validated commands rather than narration alone.
"""


def patch_render_visibility(html: str) -> str:
    # Preserve complete model dialogue instead of clipping Spanish/Chinese lines.
    html = html.replace(
        "text:String(turn?.text||turn?.message||'').slice(0,48)",
        "text:String(turn?.text||turn?.message||'').slice(0,140)",
    )
    html = html.replace(
        "const x=a.x,y=a.y-54,text=String(s||'').slice(0,48);\n    const maxChars=8,lines=[];",
        "const x=a.x,y=a.y-54,text=String(s||'').slice(0,140);\n    const maxChars=12,lines=[];",
    )
    html = html.replace(
        "const w=Math.max(132,Math.min(190,Math.max(...lines.map(line=>line.length),4)*15+28));",
        "const w=Math.max(150,Math.min(224,Math.max(...lines.map(line=>line.length),4)*13+30));",
    )

    # A conversation is not allowed to disappear while characters are still
    # walking. Give it a visible intent, then force the meeting after 8 seconds
    # if pathfinding cannot complete, so a validated AI chat always gets played.
    html = html.replace(
        "activeChats.push({members:[from.name,to.name],turns,index:0,timer:1.2,done:false});\n    addLog(agentLabel(from)+' 和 '+agentLabel(to)+' 開始一段多輪對話');",
        "activeChats.push({members:[from.name,to.name],turns,index:0,timer:.4,started:false,done:false,waited:0});\n    addLog(agentLabel(from)+' 和 '+agentLabel(to)+' 正在走到一起準備聊天');",
    )
    html = html.replace(
        "activeChats.push({members:[from.name,to.name],turns,index:0,timer:.4,started:false,done:false});",
        "activeChats.push({members:[from.name,to.name],turns,index:0,timer:.4,started:false,done:false,waited:0});",
    )
    html = html.replace(
        "[from,to].forEach(a=>{a.path=[];a.pathTarget='';a.state='idleWalk';a.idle='chat';a.idleAction='walk';a.decisionTimer=36;a.timer=28;a.chatText='';a.chatTimer=0;});",
        "[from,to].forEach(a=>{a.path=[];a.pathTarget='';a.state='idleWalk';a.idle='chat';a.idleAction='walk';a.decisionTimer=60;a.timer=60;a.chatText='';a.chatTimer=0;a.intentLabel='去和 '+agentLabel(a===from?to:from)+' 聊天';a.intentUntil=Date.now()+60000;});",
    )
    html = html.replace(
        "if(!first||!second||first.task||second.task){chat.done=true;return;}\n      chat.timer-=dt;",
        "if(!first||!second||first.task||second.task){chat.done=true;return;}\n"
        "      chat.waited=(chat.waited||0)+dt;\n"
        "      const together=Math.hypot(first.x-second.x,first.y-second.y)<=70;\n"
        "      const arrived=first.idle==='chat'&&second.idle==='chat'&&first.state!=='idleWalk'&&second.state!=='idleWalk';\n"
        "      if(!chat.started){\n"
        "        if((!together||!arrived)&&chat.waited<8)return;\n"
        "        if(!together||!arrived){const midX=Math.max(210,Math.min(430,(first.homeX+second.homeX)/2));first.x=midX-22;first.y=232;second.x=midX+22;second.y=232;first.path=[];second.path=[];first.pathTarget='';second.pathTarget='';first.state='idle';second.state='idle';first.idle='chat';second.idle='chat';}\n"
        "        chat.started=true;chat.timer=.5;first.timer=999;second.timer=999;first.decisionTimer=999;second.decisionTimer=999;first.idleAction='chat';second.idleAction='chat';first.intentLabel='正在和 '+agentLabel(second)+' 聊天';second.intentLabel='正在和 '+agentLabel(first)+' 聊天';first.intentUntil=Date.now()+120000;second.intentUntil=Date.now()+120000;addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 已走到一起，開始聊天');\n"
        "      }\n"
        "      chat.timer-=dt;",
    )
    html = html.replace(
        "const together=Math.hypot(first.x-second.x,first.y-second.y)<=70;\n      const arrived=first.state==='idle'&&second.state==='idle'&&first.idle==='chat'&&second.idle==='chat';\n      if(!chat.started){if(!together||!arrived)return;chat.started=true;chat.timer=.5;first.timer=999;second.timer=999;first.idleAction='chat';second.idleAction='chat';addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 已走到一起，開始聊天');}\n      chat.timer-=dt;",
        "chat.waited=(chat.waited||0)+dt;\n      const together=Math.hypot(first.x-second.x,first.y-second.y)<=70;\n      const arrived=first.idle==='chat'&&second.idle==='chat'&&first.state!=='idleWalk'&&second.state!=='idleWalk';\n      if(!chat.started){if((!together||!arrived)&&chat.waited<8)return;if(!together||!arrived){const midX=Math.max(210,Math.min(430,(first.homeX+second.homeX)/2));first.x=midX-22;first.y=232;second.x=midX+22;second.y=232;first.path=[];second.path=[];first.pathTarget='';second.pathTarget='';first.state='idle';second.state='idle';first.idle='chat';second.idle='chat';}chat.started=true;chat.timer=.5;first.timer=999;second.timer=999;first.decisionTimer=999;second.decisionTimer=999;first.idleAction='chat';second.idleAction='chat';first.intentLabel='正在和 '+agentLabel(second)+' 聊天';second.intentLabel='正在和 '+agentLabel(first)+' 聊天';first.intentUntil=Date.now()+120000;second.intentUntil=Date.now()+120000;addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 已走到一起，開始聊天');}\n      chat.timer-=dt;",
    )
    html = html.replace(
        "first.chatText='';second.chatText='';first.chatTimer=0;second.chatTimer=0;chat.done=true;return;",
        "first.chatText='';second.chatText='';first.chatTimer=0;second.chatTimer=0;[first,second].forEach(a=>{a.idle='wander';a.idleAction='stand';a.timer=rand(.8,2.2);a.decisionTimer=rand(1.5,4);a.chatPartner='';a.intentLabel='';a.intentUntil=0;});chat.done=true;addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 聊完了');return;",
    )
    html = html.replace(
        "[first,second].forEach(a=>{a.idle='wander';a.idleAction='stand';a.timer=rand(.8,2.2);a.decisionTimer=rand(1.5,4);a.chatPartner='';});chat.done=true;addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 聊完了');return;",
        "[first,second].forEach(a=>{a.idle='wander';a.idleAction='stand';a.timer=rand(.8,2.2);a.decisionTimer=rand(1.5,4);a.chatPartner='';a.intentLabel='';a.intentUntil=0;});chat.done=true;addLog(agentLabel(first)+' 和 '+agentLabel(second)+' 聊完了');return;",
    )
    html = html.replace(
        "speaker.chatText=turn.text;speaker.chatTimer=4.6;\n      listener.chatText='';listener.chatTimer=0;\n      addLog('💬 '+agentLabel(speaker)+'：'+turn.text);\n      chat.timer=4.8;",
        "speaker.chatText=turn.text;speaker.chatTimer=Math.max(5.5,Math.min(10,3.5+turn.text.length*.055));\n      listener.chatText='';listener.chatTimer=0;\n      addLog('💬 '+agentLabel(speaker)+'：'+turn.text);\n      chat.timer=speaker.chatTimer+.35;",
    )

    # A one-line AI remark must also be visibly rendered and must explain why
    # it failed if the named person is unavailable.
    html = html.replace(
        "const a=agents.find(x=>x.name===String(action.agent||'').toUpperCase());if(!a||a.task||!isAgentOnDuty(a))return;\n    const text=String(action.text||action.message||'').trim().slice(0,72);if(!text)return;\n    a.chatText=text;a.chatTimer=Math.max(5,Math.min(14,3+text.length*.16));\n    addLog(agentLabel(a)+'：'+text);",
        "const a=agents.find(x=>x.name===String(action.agent||'').toUpperCase());if(!a){addLog('AI 說話未執行：找不到 '+String(action.agent||'')+' 這個角色');return;}if(a.task){addLog('AI 說話未執行：'+agentLabel(a)+' 正在處理船務');return;}if(!isAgentOnDuty(a)){addLog('AI 說話未執行：'+agentLabel(a)+' 現在不在班');return;}\n    const text=String(action.text||action.message||'').trim().slice(0,160);if(!text){addLog('AI 說話未執行：沒有台詞');return;}\n    a.chatText=text;a.chatTimer=Math.max(7,Math.min(18,4+text.length*.13));a.intentLabel='正在說話';a.intentUntil=Date.now()+a.chatTimer*1000;\n    addLog('💬 '+agentLabel(a)+'：'+text);",
    )

    # Do not treat an empty 'chat' movement as real AI dialogue.
    html = html.replace(
        "const allowed=['coffee','files','desk','plant','waterPlant','lookSea','stretch','radio','chat','checkCoworker','fishing','wander'];",
        "const allowed=['coffee','files','desk','plant','waterPlant','lookSea','stretch','radio','checkCoworker','fishing','wander'];",
    )

    # Manual testing should reveal the actual validated command list. This makes
    # it obvious whether DeepSeek merely wrote prose or actually controlled the world.
    marker = "  async function testDeepSeek(){"
    if "function directorActionLabel(action)" not in html and marker in html:
        helper = r'''  function directorActionLabel(action){
    if(!action||typeof action!=='object')return '無效指令';const type=String(action.type||'');
    if(type==='agent_action')return `${action.agent||'?'} → ${action.action||'?'}`;
    if(type==='agent_chat')return `${action.from||'?'} ↔ ${action.to||'?'} 對話 ${Array.isArray(action.turns)?action.turns.length:0} 句`;
    if(type==='agent_say')return `${action.agent||'?'} 說話`;
    if(type==='agent_outfit')return `${action.agent||'?'} 換衣服`;
    if(type==='agent_evolve')return `${action.agent||'?'} ${action.trait||'?'} ${Number(action.delta||0)>=0?'+':''}${action.delta||0}`;
    if(type==='plant_spawn')return '增加植物';if(type==='dog_visit')return '狗來訪';if(type==='layout_shuffle')return '重新布置辦公室';
    if(type==='furniture_add')return `新增家具 ${action.furniture||''}`;if(type==='furniture_move')return `移動家具 ${action.id||''}`;if(type==='furniture_remove')return `移除家具 ${action.id||''}`;
    if(type==='object_add')return `創造物件 ${action.label||''}`;return type||'未知指令';
  }
'''
        html = html.replace(marker, helper + marker, 1)

    html = html.replace(
        "applyAiTownActions(data?.actions||[]);\n       await pullTownWorld();\n       ui.status.textContent='AI 已完成一次決策';\n       addLog('AI：'+String(reply).slice(0,140));",
        "const actions=Array.isArray(data?.actions)?data.actions:[];\n"
        "      if(actions.length){addLog('AI 真正下令：'+actions.map(directorActionLabel).join('；'));applyAiTownActions(actions);ui.status.textContent='AI 指令已送入世界';if(reply)addLog('AI 理由：'+String(reply).slice(0,180));}\n"
        "      else{ui.status.textContent='AI 沒有下可執行指令';addLog('AI 只有想法，沒有任何通過驗證的指令；本輪畫面不應該有變化');}",
    )
    html = html.replace(
        "applyAiTownActions(data?.actions||[]);\n      await pullTownWorld();\n      ui.status.textContent='AI 已完成一次決策';\n      addLog('AI：'+String(reply).slice(0,140));",
        "const actions=Array.isArray(data?.actions)?data.actions:[];\n"
        "      if(actions.length){addLog('AI 真正下令：'+actions.map(directorActionLabel).join('；'));applyAiTownActions(actions);ui.status.textContent='AI 指令已送入世界';if(reply)addLog('AI 理由：'+String(reply).slice(0,180));}\n"
        "      else{ui.status.textContent='AI 沒有下可執行指令';addLog('AI 只有想法，沒有任何通過驗證的指令；本輪畫面不應該有變化');}",
    )
    return html
