"""Render-page patch for a clearer dialogue sidebar and UI language toggles."""


def patch_render_dialogue_panel(html: str) -> str:
    if "town-side-panel" not in html:
        html = html.replace(
            "</style>",
            """
  #town-side-panel{position:fixed;right:10px;top:72px;width:320px;max-width:min(42vw,320px);max-height:calc(100vh - 92px);display:flex;flex-direction:column;gap:8px;z-index:9998;background:rgba(16,24,33,.92);border:2px solid #506778;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.28);padding:10px;color:#eef4ff;font:12px/1.45 "Segoe UI",Arial,sans-serif;backdrop-filter:blur(5px)}
  #town-side-panel .panel-title{font-size:15px;font-weight:700;letter-spacing:.4px;color:#fff}
  #town-side-panel .panel-sub{font-size:11px;opacity:.75}
  #town-side-panel .panel-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  #town-side-panel label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#d6e4ff;flex:1 1 130px}
  #town-side-panel select{background:#243646;color:#fff;border:1px solid #4e6a84;border-radius:6px;padding:6px 8px;font-size:12px}
  #town-dialogue-list{overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:2px}
  .town-dialogue-card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:8px}
  .town-dialogue-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;font-size:11px;color:#b8cae6}
  .town-dialogue-members{font-weight:700;color:#fff;letter-spacing:.3px}
  .town-dialogue-line{font-size:13px;line-height:1.45;margin:4px 0;word-break:break-word}
  .town-dialogue-speaker{font-weight:700;color:#9dd1ff;margin-right:6px}
  @media (max-width: 920px){
    #town-side-panel{position:fixed;left:8px;right:8px;top:auto;bottom:8px;width:auto;max-width:none;max-height:40vh}
  }
</style>""",
            1,
        )

    marker = "  function applyAiTownActions(actions=[]){"
    if "function ensureTownSidePanel()" not in html and marker in html:
        helper = r'''  const TOWN_UI_PREF_KEY='town-ui-prefs-v2';
  function loadTownUiPrefs(){
    try{
      const raw=localStorage.getItem(TOWN_UI_PREF_KEY);
      const prefs=raw?JSON.parse(raw):{};
      return {
        dialogueLang:prefs&&prefs.dialogueLang==='zh'?'zh':'es',
        statusLang:prefs&&prefs.statusLang==='es'?'es':'zh'
      };
    }catch(_){return {dialogueLang:'es',statusLang:'zh'};}
  }
  function saveTownUiPrefs(){
    try{localStorage.setItem(TOWN_UI_PREF_KEY,JSON.stringify(window.__townUiPrefs||{dialogueLang:'es',statusLang:'zh'}));}catch(_){ }
  }
  window.__townUiPrefs=window.__townUiPrefs||loadTownUiPrefs();
  window.__townDialogueHistory=Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[];
  window.__townStatusHistory=Array.isArray(window.__townStatusHistory)?window.__townStatusHistory:[];
  function dialogueText(turn){
    if((window.__townUiPrefs||{}).dialogueLang==='zh'&&turn&&turn.text_zh)return String(turn.text_zh);
    return String((turn&&turn.text)||'');
  }
  function translateTownLog(message, lang){
    const raw=String(message==null?'':message);
    if(lang!=='es')return raw;
    let out=raw;
    const replacements=[
      ['AI 生活檔案：','Perfil AI: '],['AI 更新 ','AI actualizó '],[' 的生活檔案',' del perfil de vida'],
      ['AI 指派：','AI asignó: '],['AI 動作完成：','Acción AI completada: '],['AI 新增家具：','AI añadió mueble: '],
      ['AI 新增物件：','AI añadió objeto: '],['AI 本輪決定保持現狀','La AI decidió mantener el estado actual'],
      ['開始聊天','empezaron a conversar'],['聊完了','terminaron de conversar'],['開始 ','inició '],
      ['去沖咖啡','fue por café'],['去整理文件','fue a ordenar archivos'],['回工位工作','volvió a su puesto'],
      ['去看植物','fue a ver las plantas'],['去澆花','fue a regar una planta'],['去窗邊看海','fue a mirar el mar'],
      ['伸展一下','se estiró un poco'],['去用海事電台','fue a usar la radio marítima'],['去找同事','fue a buscar a una compañera'],
      ['去釣魚','fue a pescar'],['走一走','salió a caminar'],['重新布置辦公室','reorganizó la oficina'],
      ['一隻狗來到辦公室附近','llegó un perro cerca de la oficina'],['辦公室增加一盆植物','apareció una planta nueva en la oficina'],
      ['新增家具','añadió mueble'],['移動家具','movió mueble'],['移除家具','retiró mueble'],['新增物件','añadió objeto'],
      ['設定生活檔案','definió el perfil de vida'],['歲',' años'],['個小孩',' hijos'],['無小孩','sin hijos'],['喜歡 ','le gusta ']
    ];
    replacements.forEach(pair=>{out=out.split(pair[0]).join(pair[1]);});
    return out;
  }
  function ensureTownSidePanel(){
    let panel=document.getElementById('town-side-panel');
    if(panel)return panel;
    panel=document.createElement('div');
    panel.id='town-side-panel';
    panel.innerHTML=''
      +'<div class="panel-title">IQUIQUE · AI DIALOGUE</div>'
      +'<div class="panel-sub">對話可在右側清楚查看；下方狀態可切換中文 / Español。</div>'
      +'<div class="panel-row">'
      +'<label>對話 / Diálogo<select id="town-dialogue-lang"><option value="es">Español</option><option value="zh">中文</option></select></label>'
      +'<label>狀態 / Estado<select id="town-status-lang"><option value="zh">中文</option><option value="es">Español</option></select></label>'
      +'</div>'
      +'<div id="town-dialogue-list"></div>';
    document.body.appendChild(panel);
    const dialogueSel=panel.querySelector('#town-dialogue-lang');
    const statusSel=panel.querySelector('#town-status-lang');
    dialogueSel.value=(window.__townUiPrefs||{}).dialogueLang||'es';
    statusSel.value=(window.__townUiPrefs||{}).statusLang||'zh';
    dialogueSel.addEventListener('change',()=>{window.__townUiPrefs.dialogueLang=dialogueSel.value;saveTownUiPrefs();renderDialogueSidebar();});
    statusSel.addEventListener('change',()=>{window.__townUiPrefs.statusLang=statusSel.value;saveTownUiPrefs();if(typeof addLog==='function')addLog(statusSel.value==='es'?'Idioma del registro cambiado a Español':'狀態列語言已切換為中文');});
    return panel;
  }
  function renderDialogueSidebar(){
    const panel=ensureTownSidePanel();
    const box=panel.querySelector('#town-dialogue-list');
    const items=(Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[]).slice(-10).reverse();
    if(!items.length){box.innerHTML='<div class="town-dialogue-card"><div class="town-dialogue-line">尚無對話 / Aún no hay diálogo.</div></div>';return;}
    box.innerHTML=items.map(item=>{
      const members=(Array.isArray(item.members)?item.members:[]).join(' · ')||'MIA · ANA';
      const turns=(Array.isArray(item.turns)?item.turns:[]).map(turn=>'<div class="town-dialogue-line"><span class="town-dialogue-speaker">'+String(turn.speaker||'?')+':</span>'+dialogueText(turn).replace(/</g,'&lt;')+'</div>').join('');
      const stamp=item.at?new Date(item.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
      return '<div class="town-dialogue-card"><div class="town-dialogue-head"><span class="town-dialogue-members">'+members+'</span><span>'+stamp+'</span></div>'+(turns||'<div class="town-dialogue-line">'+String(item.text||'').replace(/</g,'&lt;')+'</div>')+'</div>';
    }).join('');
  }
  function installTownLanguageUi(){
    if(window.__townLangUiInstalled)return;
    window.__townLangUiInstalled=true;
    ensureTownSidePanel();
    if(typeof addLog==='function'&&!window.__townAddLogWrapped){
      window.__townRawAddLog=addLog;
      addLog=function(message){
        const item={at:Date.now(),zh:String(message==null?'':message),es:translateTownLog(message,'es')};
        window.__townStatusHistory=Array.isArray(window.__townStatusHistory)?window.__townStatusHistory:[];
        window.__townStatusHistory.push(item);
        window.__townStatusHistory=window.__townStatusHistory.slice(-120);
        return window.__townRawAddLog((window.__townUiPrefs||{}).statusLang==='es'?item.es:item.zh);
      };
      window.__townAddLogWrapped=true;
    }
    renderDialogueSidebar();
  }
  setTimeout(installTownLanguageUi,0);

'''
        html = html.replace(marker, helper + marker, 1)

    html = html.replace(
        "    if(!turns.length)return;\n    const midX=",
        "    if(!turns.length)return;\n"
        "    window.__townDialogueHistory=Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[];\n"
        "    const storedTurns=turns.map(turn=>({speaker:String(turn.speaker||''),text:String(turn.text||''),text_zh:String(turn.text_zh||'')}));\n"
        "    window.__townDialogueHistory.push({at:Date.now(),members:[from.name,to.name],turns:storedTurns,text:storedTurns.map(turn=>turn.speaker+': '+(turn.text||'')).join(' ').slice(0,520)});\n"
        "    window.__townDialogueHistory=window.__townDialogueHistory.slice(-10);\n"
        "    if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();\n"
        "    turns=turns.map(turn=>({...turn,text:dialogueText(turn)}));\n"
        "    const midX=",
        1,
    )

    html = html.replace(
        "  function applyServerWorld(world){",
        "  function applyServerWorld(world){\n"
        "    if(Array.isArray(world?.recentDialogue)){window.__townDialogueHistory=world.recentDialogue.map(item=>({at:item.at,members:Array.isArray(item.members)?item.members:[],turns:Array.isArray(item.turns)?item.turns:[],text:item.text||''})).slice(-10);setTimeout(()=>{if(typeof renderDialogueSidebar==='function')renderDialogueSidebar();},0);}",
        1,
    )

    return html
