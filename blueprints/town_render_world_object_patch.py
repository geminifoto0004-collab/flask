"""Safe post-patch for generic AI pixel objects and presence hints.

This stays outside the known-good game animation loop. It adds a transparent
world-object overlay, gives the backend authoritative on-duty hints, and makes
admin command submission visibly react on the first click.
"""


def patch_render_world_objects(html: str) -> str:
    # Presence hints let DeepSeek know who is actually in the office. In
    # particular, the visual runtime has exactly one night-shift officer.
    html = html.replace(
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12),",
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12),\n"
        "      onDutyAgents:agents.filter(a=>isAgentOnDuty(a)).map(a=>a.name),\n"
        "      nightShiftAgent:isIquiqueNight()?(agents[nightShiftIndex()]?.name||''):'',",
        1,
    )

    # One click must feel like one submission even though DeepSeek can take a
    # few seconds. Show feedback immediately instead of encouraging repeat clicks.
    html = html.replace(
        "    if(btn)btn.disabled=true;\n    try{",
        "    const oldBtnText=btn?btn.textContent:'';\n"
        "    if(btn){btn.disabled=true;btn.textContent='⏳ 執行中…';}\n"
        "    log('AI 已收到指令，正在轉成世界動作：'+prompt);\n"
        "    try{",
        1,
    )
    html = html.replace(
        "    finally{if(btn)btn.disabled=false;}",
        "    finally{if(btn){btn.disabled=false;btn.textContent=oldBtnText||'✨ 執行';}}",
        1,
    )

    css = r'''
<style id="town-generic-world-object-style">
#town-generic-object-overlay{position:absolute;inset:6px;width:calc(100% - 12px);height:calc(100% - 12px);pointer-events:none;image-rendering:pixelated;image-rendering:crisp-edges;z-index:9;background:transparent!important}
</style>
'''
    js = r'''
<script id="town-generic-world-object-runtime">
(()=>{
  const app=document.getElementById('customs-sim');
  const wrap=app&&app.querySelector('.game-wrap');
  const game=app&&app.querySelector('canvas');
  if(!app||!wrap||!game)return;

  let overlay=document.getElementById('town-generic-object-overlay');
  if(!overlay){
    overlay=document.createElement('canvas');
    overlay.id='town-generic-object-overlay';
    overlay.width=640;overlay.height=400;
    wrap.appendChild(overlay);
  }
  const oc=overlay.getContext('2d');
  if(!oc)return;
  oc.imageSmoothingEnabled=false;

  let objects=[];
  let last=performance.now();
  function px(x,y,w,h,color){
    oc.fillStyle=color;
    oc.fillRect(Math.round(x/2)*2,Math.round(y/2)*2,Math.max(2,Math.round(w/2)*2),Math.max(2,Math.round(h/2)*2));
  }
  function drawObject(o){
    if(!o||!Array.isArray(o.parts))return;
    const behavior=String(o.behavior||'static');
    const bob=(behavior==='bob'||behavior==='float')?Math.sin(Number(o.phase)||0)*2:0;
    o.parts.slice(0,24).forEach(p=>{
      if(!p||String(p.shape||'rect')!=='rect')return;
      const color=/^#[0-9a-f]{6}$/i.test(String(p.color||''))?String(p.color):'#7b8790';
      px(Number(o.x||0)+Number(p.x||0),Number(o.y||0)+Number(p.y||0)+bob,Number(p.w||2),Number(p.h||2),color);
    });
  }
  function bounds(zone){
    if(zone==='office')return {l:54,r:586,t:76,b:250};
    if(zone==='harbor_walkway')return {l:50,r:590,t:282,b:298};
    if(zone==='pier')return {l:288,r:352,t:304,b:314};
    if(zone==='sea')return {l:24,r:616,t:322,b:378};
    return {l:20,r:620,t:70,b:380};
  }
  function stepObject(o,dt){
    o.phase=(Number(o.phase)||0)+dt*1.7;
    const behavior=String(o.behavior||'static');
    const b=bounds(String(o.zone||''));
    let speed=0;
    if(behavior==='swim_left')speed=-10;
    else if(behavior==='swim_right')speed=10;
    else if(behavior==='drive_left')speed=-28;
    else if(behavior==='drive_right')speed=28;
    else if(behavior==='drift')speed=(Number(o.direction)<0?-1:1)*6;
    if(speed){o.x=Number(o.x||0)+speed*dt;if(o.x<b.l)o.x=b.r;if(o.x>b.r)o.x=b.l;}
  }
  function frame(now){
    const dt=Math.min(.05,(now-last)/1000);last=now;
    oc.clearRect(0,0,640,400);
    objects.forEach(o=>{stepObject(o,dt);drawObject(o);});
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  let refreshing=false;
  async function refresh(){
    if(refreshing)return;refreshing=true;
    try{
      const r=await fetch('/api/town/world',{headers:{Accept:'application/json'}});if(!r.ok)return;
      const data=await r.json();
      const incoming=Array.isArray(data&&data.world&&data.world.worldObjects)?data.world.worldObjects:[];
      const oldById=new Map(objects.map(o=>[String(o.id||''),o]));
      objects=incoming.slice(-40).map(raw=>{
        const old=oldById.get(String(raw&&raw.id||''));
        return {...raw,x:Number(raw&&raw.x||0),y:Number(raw&&raw.y||0),phase:old?Number(old.phase||0):Math.random()*6.28};
      });
    }catch(_e){}
    finally{refreshing=false;}
  }
  refresh();
  setInterval(refresh,1200);
})();
</script>
'''
    if 'town-generic-world-object-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-generic-world-object-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
