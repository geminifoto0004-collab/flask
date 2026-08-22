"""Small post-patch for shared chat history and compact language controls.

Keeps the known-good game/dialogue renderer intact. New local dialogue is shown
immediately, then persisted asynchronously. Other viewers poll the shared TiDB
history on a short interval, so the current speaker bubble never waits on DB I/O.
"""


def patch_render_shared_dialogue(html: str) -> str:
    css = r'''
<style id="town-shared-dialogue-style">
#town-side-panel>.panel-title,#town-side-panel>.panel-sub{display:none!important}
#town-side-panel{padding-top:10px!important}
#town-side-panel>#town-dialogue-list{flex:1 1 auto!important;min-height:0!important}
#town-inline-language-row{display:flex!important;align-items:center!important;gap:8px!important;margin:0!important;padding:0!important;border:0!important;flex:0 0 auto!important}
#town-inline-language-row label{display:flex!important;flex-direction:row!important;align-items:center!important;gap:5px!important;font-size:12px!important;color:inherit!important}
#town-inline-language-row select{min-height:44px!important;padding:7px 9px!important;background:light-dark(#f4efe3,#202936)!important;color:inherit!important;border:2px solid light-dark(#655d50,#3c4657)!important;font:inherit!important;font-weight:700!important}
@media(max-width:700px){#town-inline-language-row{width:100%;flex-wrap:wrap}}
</style>
'''
    js = r'''
<script id="town-shared-dialogue-runtime">
(()=>{
  const app=document.getElementById('customs-sim');
  if(!app)return;

  function moveLanguageControls(){
    const panel=document.getElementById('town-side-panel');
    const controls=app.querySelector('.controls');
    if(!panel||!controls)return;
    panel.querySelectorAll('.panel-title,.panel-sub').forEach(el=>el.remove());
    let row=panel.querySelector('.panel-row');
    if(!row)return;
    row.id='town-inline-language-row';
    const auto=app.querySelector('#aiAutoBtn');
    if(auto&&auto.parentNode===controls)auto.insertAdjacentElement('afterend',row);
    else controls.appendChild(row);
  }

  let backing=Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[];
  let proxy=null;
  const alreadyPosted=new Set();
  const pendingById=new Map();

  function dialogueId(chat){
    if(chat&&chat.id)return String(chat.id);
    const members=Array.isArray(chat&&chat.members)?chat.members.join('-'):'chat';
    return members+'@'+String(chat&&chat.at||'');
  }

  function renderNow(){
    if(typeof renderDialogueSidebar==='function'){
      try{renderDialogueSidebar();}catch(_e){}
    }
  }

  function postDialogue(chat){
    if(!chat||!Array.isArray(chat.turns)||!chat.turns.length)return;
    const id=dialogueId(chat);
    if(alreadyPosted.has(id))return;
    alreadyPosted.add(id);
    const payload={
      ...chat,
      id,
      source:'browser',
      turns:chat.turns.map(turn=>({
        speaker:String(turn&&turn.speaker||''),
        text:String(turn&&turn.text||''),
        text_zh:String(turn&&turn.text_zh||turn&&turn.textZh||'')
      }))
    };
    pendingById.set(id,payload);
    fetch('/api/town/dialogues',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({dialogue:payload})})
      .then(r=>r.ok?r.json():Promise.reject(new Error('dialogue save failed')))
      .then(()=>{pendingById.delete(id);setTimeout(refreshSharedHistory,80);})
      .catch(()=>{alreadyPosted.delete(id);});
  }

  function wrapArray(value){
    const arr=Array.isArray(value)?value:[];
    return new Proxy(arr,{
      get(target,prop,receiver){
        if(prop==='push')return (...items)=>{
          const result=Array.prototype.push.apply(target,items);
          // Current viewer sees the dialogue immediately. TiDB persistence happens
          // in parallel and must never gate the visible chat panel.
          requestAnimationFrame(renderNow);
          items.forEach(postDialogue);
          return result;
        };
        return Reflect.get(target,prop,receiver);
      }
    });
  }

  try{
    proxy=wrapArray(backing);
    Object.defineProperty(window,'__townDialogueHistory',{
      configurable:true,
      enumerable:true,
      get(){return proxy;},
      set(value){
        if(value===proxy)return;
        backing=Array.isArray(value)?value:[];
        proxy=wrapArray(backing);
        requestAnimationFrame(renderNow);
      }
    });
  }catch(_e){ }

  let refreshing=false;
  function refreshSharedHistory(){
    if(refreshing)return;
    refreshing=true;
    fetch('/api/town/dialogues?limit=12',{headers:{'Accept':'application/json'}})
      .then(r=>r.ok?r.json():null)
      .then(data=>{
        if(!data||!Array.isArray(data.dialogues))return;
        const shared=data.dialogues.map(chat=>({
          id:chat.id,
          at:chat.at,
          members:Array.isArray(chat.members)?chat.members:[],
          turns:Array.isArray(chat.turns)?chat.turns.map(turn=>({speaker:turn.speaker,text:turn.text,text_zh:turn.text_zh,textZh:turn.text_zh})):[],
          text:chat.text||''
        }));
        const ids=new Set(shared.map(dialogueId));
        // Never erase a just-spoken local conversation while its POST is still
        // travelling to TiDB. Merge it until the shared copy becomes visible.
        pendingById.forEach((chat,id)=>{if(!ids.has(id))shared.push(chat);});
        shared.sort((a,b)=>Number(a.at||0)-Number(b.at||0));
        window.__townDialogueHistory=shared.slice(-12);
        renderNow();
      })
      .catch(()=>{})
      .finally(()=>{refreshing=false;});
  }

  moveLanguageControls();
  refreshSharedHistory();
  // Other viewers receive shared dialogue within about 3 seconds. The speaker's
  // own browser still updates instantly and does not wait for this timer.
  setInterval(refreshSharedHistory,3000);
  setTimeout(moveLanguageControls,150);
})();
</script>
'''
    if 'town-shared-dialogue-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-shared-dialogue-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
