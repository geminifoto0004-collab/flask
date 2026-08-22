"""Small post-patch for shared chat history and compact language controls.

Keeps the known-good game/dialogue renderer intact. It only moves the existing
language selects into the bottom control row and observes accepted browser chat
history so executed conversations are persisted through /api/town/dialogues.
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
  let posting=false;
  const alreadyPosted=new Set();

  function dialogueId(chat){
    if(chat&&chat.id)return String(chat.id);
    const members=Array.isArray(chat&&chat.members)?chat.members.join('-'):'chat';
    return members+'@'+String(chat&&chat.at||'');
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
    posting=true;
    fetch('/api/town/dialogues',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({dialogue:payload})})
      .catch(()=>{})
      .finally(()=>{posting=false;});
  }

  function wrapArray(value){
    const arr=Array.isArray(value)?value:[];
    return new Proxy(arr,{
      get(target,prop,receiver){
        if(prop==='push')return (...items)=>{
          const result=Array.prototype.push.apply(target,items);
          if(!posting)items.forEach(postDialogue);
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
      }
    });
  }catch(_e){ }

  function refreshSharedHistory(){
    fetch('/api/town/dialogues?limit=12',{headers:{'Accept':'application/json'}})
      .then(r=>r.ok?r.json():null)
      .then(data=>{
        if(!data||!Array.isArray(data.dialogues))return;
        window.__townDialogueHistory=data.dialogues.map(chat=>({
          id:chat.id,
          at:chat.at,
          members:Array.isArray(chat.members)?chat.members:[],
          turns:Array.isArray(chat.turns)?chat.turns.map(turn=>({speaker:turn.speaker,text:turn.text,text_zh:turn.text_zh,textZh:turn.text_zh})):[],
          text:chat.text||''
        }));
        if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();
      })
      .catch(()=>{});
  }

  moveLanguageControls();
  refreshSharedHistory();
  setInterval(refreshSharedHistory,15000);
  setTimeout(moveLanguageControls,150);
})();
</script>
'''
    if 'town-shared-dialogue-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-shared-dialogue-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
