"""Safe Render patch for town admin controls, shared duty state and sea life."""


def patch_render_admin_world(html: str) -> str:
    # Teach the known-good browser runtime one additional persistent capability
    # without replacing its animation loop.
    html = html.replace(
        "  function isAgentOnDuty(a){return !isIquiqueNight()||a.index===nightShiftIndex()||!!a.task;}",
        "  function isAgentOnDuty(a){if(a?.manualOffDuty&&!a?.task)return false;return !isIquiqueNight()||a.index===nightShiftIndex()||!!a.task;}",
        1,
    )
    html = html.replace(
        "careerState:a.careerState,generation:a.generation,state:a.state",
        "careerState:a.careerState,manualOffDuty:!!a.manualOffDuty,generation:a.generation,state:a.state",
        1,
    )
    html = html.replace(
        "        if(Number.isFinite(Number(saved.generation)))a.generation=Number(saved.generation);",
        "        if(Number.isFinite(Number(saved.generation)))a.generation=Number(saved.generation);\n        if(typeof saved.manualOffDuty==='boolean')a.manualOffDuty=saved.manualOffDuty;",
        1,
    )
    shift_marker = "  registerDirectorTool('agent_action',action=>{"
    if "registerDirectorTool('agent_shift'" not in html and shift_marker in html:
        shift_runtime = r'''  registerDirectorTool('agent_shift',action=>{
    const a=agents.find(x=>x.name===String(action.agent||'').toUpperCase());
    if(!a){addLog('AI 班次指令未執行：找不到 '+String(action.agent||'')+' 這個角色');return;}
    const mode=String(action.mode||action.shift||'').toLowerCase();
    if(mode==='off'){
      if(a.task){addLog('AI 班次指令未執行：'+agentLabel(a)+' 正在處理船務');return;}
      a.manualOffDuty=true;a.state='offDuty';a.path=[];a.pathTarget='';a.chatText='';a.chatTimer=0;a.intentLabel='';a.intentUntil=0;
      addLog('AI 安排 '+agentLabel(a)+' 下班離開辦公室');saveWorld();return;
    }
    if(mode==='on'){
      a.manualOffDuty=false;a.state='idle';a.x=a.homeX;a.y=a.homeY;a.timer=.2;a.decisionTimer=.2;
      addLog('AI 安排 '+agentLabel(a)+' 回來上班');saveWorld();
    }
  });
'''
        html = html.replace(shift_marker, shift_runtime + shift_marker, 1)

    css = r'''
<style id="town-admin-world-style">
#customs-sim .town-admin-created{display:none!important}
#customs-sim.town-admin-mode .town-admin-created{display:inline-flex!important}
#customs-sim:not(.town-admin-mode) #startBtn,
#customs-sim:not(.town-admin-mode) #addBtn,
#customs-sim:not(.town-admin-mode) #finishBtn,
#customs-sim:not(.town-admin-mode) #aiTestBtn,
#customs-sim:not(.town-admin-mode) #aiAutoBtn,
#customs-sim:not(.town-admin-mode) #resetBtn{display:none!important}
#customs-sim #town-admin-btn{order:-20}
#customs-sim #town-world-prompt{display:none;align-items:center;gap:6px;flex:1 1 360px;min-width:280px}
#customs-sim.town-admin-mode #town-world-prompt{display:flex!important}
#customs-sim #town-world-prompt-input{min-height:44px;flex:1 1 auto;min-width:220px;border:2px solid light-dark(#655d50,#3c4657);background:light-dark(#fffaf0,#202936);color:inherit;padding:8px 10px;font:inherit;box-sizing:border-box}
#customs-sim #town-world-prompt-run{min-height:44px}
#customs-sim .game-wrap{position:relative}
#town-sea-overlay{position:absolute;inset:6px;width:calc(100% - 12px);height:calc(100% - 12px);pointer-events:none;image-rendering:pixelated;image-rendering:crisp-edges;z-index:8;background:transparent!important}
</style>
'''
    js = r'''
<script id="town-admin-world-runtime">
(()=>{
  const app=document.getElementById('customs-sim');
  if(!app)return;
  const controls=app.querySelector('.controls');
  const gameWrap=app.querySelector('.game-wrap');
  const game=app.querySelector('canvas');
  if(!controls)return;

  function log(msg){
    const box=app.querySelector('#eventLog');
    if(!box)return;
    const d=document.createElement('div');d.textContent='> '+msg;box.appendChild(d);box.scrollTop=box.scrollHeight;
  }
  function setAdmin(enabled){
    app.classList.toggle('town-admin-mode',!!enabled);
    const btn=document.getElementById('town-admin-btn');
    if(btn)btn.textContent=enabled?'🔓 管理員已登入':'🔒 管理員';
  }

  let adminBtn=document.getElementById('town-admin-btn');
  if(!adminBtn){
    adminBtn=document.createElement('button');
    adminBtn.id='town-admin-btn';adminBtn.type='button';adminBtn.textContent='🔒 管理員';
    controls.insertBefore(adminBtn,controls.firstChild);
  }
  let promptWrap=document.getElementById('town-world-prompt');
  if(!promptWrap){
    promptWrap=document.createElement('label');promptWrap.id='town-world-prompt';promptWrap.className='town-admin-created';
    promptWrap.innerHTML='<span>AI 指令</span><input id="town-world-prompt-input" type="text" maxlength="180" placeholder="例如：在海上生成一隻海豹、讓 MIA 下班"><button id="town-world-prompt-run" type="button">✨ 執行</button>';
    const aiBtn=app.querySelector('#aiTestBtn');
    if(aiBtn&&aiBtn.parentNode===controls)aiBtn.insertAdjacentElement('afterend',promptWrap);else controls.appendChild(promptWrap);
  }

  async function adminStatus(){
    try{
      const r=await fetch('/api/town/admin/status',{credentials:'include',headers:{Accept:'application/json'}});
      const data=await r.json();setAdmin(!!data.admin);
    }catch(_){setAdmin(false);}
  }
  adminBtn.addEventListener('click',async()=>{
    if(app.classList.contains('town-admin-mode')){
      try{await fetch('/api/town/admin/logout',{method:'POST',credentials:'include'});}catch(_){}
      setAdmin(false);log('已離開管理員模式');return;
    }
    const password=window.prompt('請輸入 AI 小鎮管理員密碼');
    if(password==null||!String(password).trim())return;
    try{
      const r=await fetch('/api/town/admin/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({password:String(password)})});
      const data=await r.json().catch(()=>({}));
      if(!r.ok||!data.ok)throw new Error(data.error||'密碼錯誤');
      setAdmin(true);log('管理員模式已開啟');
    }catch(err){setAdmin(false);log('管理員登入失敗：'+String(err&&err.message||err));}
  });

  async function runWorldPrompt(){
    if(!app.classList.contains('town-admin-mode'))return;
    const input=document.getElementById('town-world-prompt-input');
    const btn=document.getElementById('town-world-prompt-run');
    const prompt=String(input&&input.value||'').trim();if(!prompt)return;
    if(btn)btn.disabled=true;
    try{
      const worldResp=await fetch('/api/town/world',{headers:{Accept:'application/json'}}).then(r=>r.ok?r.json():({})).catch(()=>({}));
      const r=await fetch('/api/town/admin/command',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({prompt,world:worldResp.world||{}})});
      const data=await r.json().catch(()=>({}));
      if(!r.ok||!data.ok)throw new Error(data.error||('HTTP '+r.status));
      if(input)input.value='';log('AI 指令已送入共同世界：'+prompt);
      setTimeout(refreshWorld,300);
    }catch(err){log('AI 指令失敗：'+String(err&&err.message||err));}
    finally{if(btn)btn.disabled=false;}
  }
  const runBtn=document.getElementById('town-world-prompt-run');
  const promptInput=document.getElementById('town-world-prompt-input');
  if(runBtn)runBtn.addEventListener('click',runWorldPrompt);
  if(promptInput)promptInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();runWorldPrompt();}});

  let seaCreatures=[];
  let overlay=null,oc=null;
  if(gameWrap&&game){
    overlay=document.createElement('canvas');overlay.id='town-sea-overlay';overlay.width=640;overlay.height=400;gameWrap.appendChild(overlay);oc=overlay.getContext('2d');oc.imageSmoothingEnabled=false;
  }
  function px(x,y,w,h,color){if(!oc)return;oc.fillStyle=color;oc.fillRect(Math.round(x/2)*2,Math.round(y/2)*2,Math.max(2,Math.round(w/2)*2),Math.max(2,Math.round(h/2)*2));}
  function drawSeal(c,now){
    const phase=(now/1000)*1.4+((Number(c.createdAt)||0)%997)/100;
    const dir=Number(c.direction)<0?-1:1;
    const x=Math.max(70,Math.min(570,Number(c.x)||320));
    const y=Math.max(326,Math.min(374,Number(c.y)||350))+Math.sin(phase)*2;
    const hx=x+dir*11;
    px(x-12,y-3,24,8,'#738488');
    px(x-9,y-6,18,4,'#819196');
    px(hx-(dir<0?8:0),y-7,8,8,'#89999d');
    px(hx+dir*5-(dir<0?3:0),y-4,5,4,'#a5b2b4');
    px(hx+dir*3-(dir<0?2:0),y-6,2,2,'#172126');
    px(hx+dir*8-(dir<0?2:0),y-3,2,2,'#263237');
    px(x-dir*13-(dir<0?7:0),y-1,7,4,'#5d6c70');
    px(x-7,y+4,7,4,'#627276');px(x+2,y+4,7,4,'#627276');
    if(oc){oc.strokeStyle='rgba(230,245,246,.72)';oc.lineWidth=1;for(let i=-1;i<=1;i++){oc.beginPath();oc.moveTo(hx+dir*7,y-1+i*2);oc.lineTo(hx+dir*13,y-3+i*3);oc.stroke();}}
    px(x-16,y+8,32,2,'rgba(220,245,250,.6)');
  }
  function seaFrame(now){
    if(oc){oc.clearRect(0,0,640,400);seaCreatures.forEach(c=>drawSeal(c,now));}
    requestAnimationFrame(seaFrame);
  }
  requestAnimationFrame(seaFrame);

  async function refreshWorld(){
    try{
      const r=await fetch('/api/town/world',{headers:{Accept:'application/json'}});if(!r.ok)return;
      const data=await r.json();
      seaCreatures=Array.isArray(data&&data.world&&data.world.seaCreatures)?data.world.seaCreatures.filter(c=>String(c&&c.kind||'').toLowerCase()==='seal').slice(-12):[];
    }catch(_){}
  }
  adminStatus();refreshWorld();setInterval(refreshWorld,3000);
})();
</script>
'''
    if 'town-admin-world-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-admin-world-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
