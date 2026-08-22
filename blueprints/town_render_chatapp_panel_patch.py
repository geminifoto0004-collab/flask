"""Extra patch to make the right dialogue area behave like a chat app.

This keeps the existing right-side panel, but turns it into:
- a compact conversation list on top
- one active conversation view below
instead of infinitely stacking many dialogue cards downward.
"""


def patch_render_chatapp_panel(html: str) -> str:
    # Extend the existing sidebar CSS.
    html = html.replace(
        '#town-dialogue-list{overflow:auto;display:flex;flex-direction:column;gap:10px;padding-right:2px;min-height:0;flex:1 1 auto}',
        '#town-dialogue-list{display:flex;flex-direction:column;gap:8px;min-height:0;flex:1 1 auto;overflow:hidden}'
        '#town-chat-tabs{display:flex;flex-direction:column;gap:6px;max-height:158px;overflow:auto;padding-right:2px}'
        '.town-chat-tab{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;background:#162636;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:8px 10px;cursor:pointer}'
        '.town-chat-tab.active{background:#274561;border-color:#76a7d4}'
        '.town-chat-tab-main{min-width:0;display:flex;flex-direction:column;gap:2px;flex:1 1 auto}'
        '.town-chat-tab-title{font-size:12px;font-weight:700;color:#fff}'
        '.town-chat-tab-preview{font-size:11px;color:#c9d7e7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
        '.town-chat-tab-time{font-size:10px;color:#a8bdd2;flex:0 0 auto}'
        '#town-chat-view{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;background:#0f1b28;border:1px solid rgba(255,255,255,.08);border-radius:10px;overflow:hidden}'
        '#town-chat-view-head{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.08);background:#142333}'
        '#town-chat-view-title{font-size:14px;font-weight:800;color:#fff}'
        '#town-chat-view-time{font-size:11px;color:#a9bfd5}'
        '#town-chat-messages{display:flex;flex-direction:column;gap:8px;flex:1 1 auto;overflow:auto;padding:12px;background:#102030}'
        '.town-dialogue-card{display:none}',
        1,
    )
    html = html.replace(
        '#town-side-panel{position:relative;display:flex;flex-direction:column;gap:10px;flex:0 0 360px;width:360px;max-width:360px;min-height:640px;z-index:20;background:#1c2733;border:2px solid #1a2028;border-left:0;border-radius:0 10px 10px 0;box-shadow:none;padding:12px;color:#eef4ff;font:12px/1.45 "Segoe UI",Arial,sans-serif}',
        '#town-side-panel{position:relative;display:flex;flex-direction:column;gap:10px;flex:0 0 360px;width:360px;max-width:360px;height:760px;z-index:20;background:#1c2733;border:2px solid #1a2028;border-left:0;border-radius:0 10px 10px 0;box-shadow:none;padding:12px;color:#eef4ff;font:12px/1.45 "Segoe UI",Arial,sans-serif;overflow:hidden}',
        1,
    )

    # Default dialogue language to Chinese on the existing panel.
    html = html.replace(
        "dialogueSel.value=(window.__townUiPrefs||{}).dialogueLang||'es';",
        "dialogueSel.value=(window.__townUiPrefs||{}).dialogueLang||'zh';",
        1,
    )
    html = html.replace(
        "window.__townUiPrefs=window.__townUiPrefs||loadTownUiPrefs();",
        "window.__townUiPrefs=window.__townUiPrefs||loadTownUiPrefs();\n  if(!window.__townUiPrefs.dialogueLang)window.__townUiPrefs.dialogueLang='zh';\n  window.__townSelectedChatKey=window.__townSelectedChatKey||'';",
        1,
    )

    # Replace panel structure with tabs + active conversation.
    old_panel = (
        "      +'<div id=\"town-dialogue-list\"></div>'"
    )
    new_panel = (
        "      +'<div id=\"town-dialogue-list\">'"
        "+'<div id=\"town-chat-tabs\"></div>'"
        "+'<div id=\"town-chat-view\'><div id=\"town-chat-view-head\'><div id=\"town-chat-view-title\">尚無對話</div><div id=\"town-chat-view-time\"></div></div><div id=\"town-chat-messages\"><div class=\"town-dialogue-empty\">尚無對話 / Aún no hay diálogo.</div></div></div>'"
        "+'</div>'"
    )
    html = html.replace(old_panel, new_panel, 1)

    # Replace renderDialogueSidebar with chat-list behavior.
    old_render = """  function renderDialogueSidebar(){
    const panel=ensureTownSidePanel();
    const box=panel.querySelector('#town-dialogue-list');
    const items=(Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[]).slice(-8);
    if(!items.length){box.innerHTML='<div class=\"town-dialogue-empty\">尚無對話 / Aún no hay diálogo.</div>';return;}
    box.innerHTML=items.map(item=>{
      const members=(Array.isArray(item.members)?item.members:[]).slice(0,2);
      const first=members[0]||'MIA';
      const turns=(Array.isArray(item.turns)?item.turns:[]).map(turn=>{
        const side=String(turn.speaker||'')===first?'left':'right';
        return '<div class=\"town-dialogue-bubble '+side+'\"><div class=\"town-dialogue-speaker-chip\">'+escapeHtml(turn.speaker||'?')+'</div><div class=\"town-dialogue-line\">'+escapeHtml(dialogueText(turn))+'</div></div>';
      }).join('');
      const stamp=item.at?new Date(item.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
      return '<div class=\"town-dialogue-card\"><div class=\"town-dialogue-head\"><span class=\"town-dialogue-members\">'+escapeHtml(members.join(' ↔ ')||'MIA ↔ ANA')+'</span><span>'+escapeHtml(stamp)+'</span></div><div class=\"town-dialogue-turns\">'+(turns||('<div class=\"town-dialogue-bubble left\"><div class=\"town-dialogue-line\">'+escapeHtml(item.text||'')+'</div></div>'))+'</div></div>';
    }).join('');
    box.scrollTop=box.scrollHeight;
  }
"""
    new_render = """  function renderDialogueSidebar(){
    const panel=ensureTownSidePanel();
    const tabs=panel.querySelector('#town-chat-tabs');
    const title=panel.querySelector('#town-chat-view-title');
    const time=panel.querySelector('#town-chat-view-time');
    const messages=panel.querySelector('#town-chat-messages');
    const items=(Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[]).slice(-12);
    if(!items.length){
      if(tabs)tabs.innerHTML='';
      if(title)title.textContent='尚無對話';
      if(time)time.textContent='';
      if(messages)messages.innerHTML='<div class=\"town-dialogue-empty\">尚無對話 / Aún no hay diálogo.</div>';
      return;
    }
    const entries=items.map(item=>({item,key:[...(item.members||[])].join('-')+'@'+String(item.at||'')}));
    if(!window.__townSelectedChatKey||!entries.some(entry=>entry.key===window.__townSelectedChatKey)){
      window.__townSelectedChatKey=entries[entries.length-1].key;
    }
    if(tabs){
      tabs.innerHTML=entries.slice().reverse().map(entry=>{
        const item=entry.item;
        const preview=(Array.isArray(item.turns)&&item.turns.length)?dialogueText(item.turns[item.turns.length-1]):String(item.text||'');
        const stamp=item.at?new Date(item.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
        const active=entry.key===window.__townSelectedChatKey?' active':'';
        return '<div class=\"town-chat-tab'+active+'\" data-chat-key=\"'+escapeHtml(entry.key)+'\"><div class=\"town-chat-tab-main\"><div class=\"town-chat-tab-title\">'+escapeHtml((item.members||[]).join(' ↔ ')||'MIA ↔ ANA')+'</div><div class=\"town-chat-tab-preview\">'+escapeHtml(preview)+'</div></div><div class=\"town-chat-tab-time\">'+escapeHtml(stamp)+'</div></div>';
      }).join('');
      tabs.querySelectorAll('.town-chat-tab').forEach(el=>el.addEventListener('click',()=>{window.__townSelectedChatKey=el.getAttribute('data-chat-key')||'';renderDialogueSidebar();}));
    }
    const selected=(entries.find(entry=>entry.key===window.__townSelectedChatKey)||entries[entries.length-1]).item;
    if(title)title.textContent=(selected.members||[]).join(' ↔ ')||'MIA ↔ ANA';
    if(time)time.textContent=selected.at?new Date(selected.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
    const members=(Array.isArray(selected.members)?selected.members:[]).slice(0,2);
    const first=members[0]||'MIA';
    const turns=Array.isArray(selected.turns)?selected.turns:[];
    if(messages){
      if(!turns.length){
        messages.innerHTML='<div class=\"town-dialogue-empty\">'+escapeHtml(selected.text||'尚無內容')+'</div>';
      }else{
        messages.innerHTML=turns.map(turn=>{
          const side=String(turn.speaker||'')===first?'left':'right';
          return '<div class=\"town-dialogue-bubble '+side+'\"><div class=\"town-dialogue-speaker-chip\">'+escapeHtml(turn.speaker||'?')+'</div><div class=\"town-dialogue-line\">'+escapeHtml(dialogueText(turn))+'</div></div>';
        }).join('');
        messages.scrollTop=messages.scrollHeight;
      }
    }
  }
"""
    html = html.replace(old_render, new_render, 1)

    # Auto-select newest conversation when a new dialogue arrives.
    html = html.replace(
        "    if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();\n    turns=turns.map(turn=>({...turn,text:dialogueText(turn)}));",
        "    const latestChat=window.__townDialogueHistory[window.__townDialogueHistory.length-1];\n    if(latestChat)window.__townSelectedChatKey=[...(latestChat.members||[])].join('-')+'@'+String(latestChat.at||'');\n    if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();\n    turns=turns.map(turn=>({...turn,text:dialogueText(turn)}));",
        1,
    )

    # Keep the selected conversation after loading server state.
    html = html.replace(
        "    if(Array.isArray(world?.recentDialogue)){window.__townDialogueHistory=world.recentDialogue.map(item=>({at:item.at,members:Array.isArray(item.members)?item.members:[],turns:Array.isArray(item.turns)?item.turns:[],text:item.text||''})).slice(-10);setTimeout(()=>{if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();},0);}",
        "    if(Array.isArray(world?.recentDialogue)){window.__townDialogueHistory=world.recentDialogue.map(item=>({at:item.at,members:Array.isArray(item.members)?item.members:[],turns:Array.isArray(item.turns)?item.turns:[],text:item.text||''})).slice(-12);const latest=window.__townDialogueHistory[window.__townDialogueHistory.length-1];if(latest)window.__townSelectedChatKey=[...(latest.members||[])].join('-')+'@'+String(latest.at||'');setTimeout(()=>{if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();},0);}",
        1,
    )

    return html
