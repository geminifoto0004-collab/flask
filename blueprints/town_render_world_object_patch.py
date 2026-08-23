"""Safe post-patch for generic AI pixel objects, visitors and presence hints.

This stays outside the known-good game animation loop. Shared world objects and
temporary visitors are drawn on one transparent overlay, while the original
game canvas remains untouched.
"""


def patch_render_world_objects(html: str) -> str:
    html = html.replace(
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12),",
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12),\n"
        "      onDutyAgents:agents.filter(a=>isAgentOnDuty(a)).map(a=>a.name),\n"
        "      nightShiftAgent:isIquiqueNight()?(agents[nightShiftIndex()]?.name||''):'',",
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
    overlay=document.createElement('canvas');overlay.id='town-generic-object-overlay';overlay.width=640;overlay.height=400;wrap.appendChild(overlay);
  }
  const oc=overlay.getContext('2d');if(!oc)return;oc.imageSmoothingEnabled=false;

  let objects=[],visitors=[];
  let last=performance.now();
  function px(x,y,w,h,color){oc.fillStyle=color;oc.fillRect(Math.round(x/2)*2,Math.round(y/2)*2,Math.max(2,Math.round(w/2)*2),Math.max(2,Math.round(h/2)*2));}
  function txt(text,x,y,color='#fff',size=6){oc.fillStyle=color;oc.font=size+'px monospace';oc.textAlign='center';oc.fillText(String(text||''),Math.round(x),Math.round(y));}
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
    const behavior=String(o.behavior||'static'),b=bounds(String(o.zone||''));
    let speed=0;
    if(behavior==='swim_left')speed=-10;else if(behavior==='swim_right')speed=10;else if(behavior==='drive_left')speed=-28;else if(behavior==='drive_right')speed=28;else if(behavior==='drift')speed=(Number(o.direction)<0?-1:1)*6;
    if(speed){o.x=Number(o.x||0)+speed*dt;if(o.x<b.l)o.x=b.r;if(o.x>b.r)o.x=b.l;}
  }
  function visitorTarget(name){return ({MIA:132,ANA:272,LIA:412})[String(name||'').toUpperCase()]||320;}
  function visitorPosition(v,now){
    const created=Number(v.createdAt)||now,age=Math.max(0,(now-created)/1000),stay=Math.max(8,Math.min(45,Number(v.staySeconds)||18));
    const sx=320,sy=300,tx=visitorTarget(v.target)+24,ty=234,enter=3.5,leave=3.5;
    if(age<enter){const q=age/enter;return {x:sx+(tx-sx)*q,y:sy+(ty-sy)*q};}
    if(age<enter+stay)return {x:tx,y:ty};
    const q=Math.min(1,(age-enter-stay)/leave);return {x:tx+(sx-tx)*q,y:ty+(sy-ty)*q};
  }
  function drawVisitor(v,now){
    const p=visitorPosition(v,now),x=p.x,y=p.y;
    px(x-6,y+12,14,3,'rgba(0,0,0,.22)');px(x-6,y+5,5,9,'#3f5260');px(x+2,y+5,5,9,'#3f5260');
    px(x-9,y-8,18,14,'#b9a58c');px(x-7,y-6,14,10,'#d1c1aa');px(x-6,y-20,14,14,'#c99370');px(x-8,y-22,18,5,'#4b352b');
    px(x-3,y-13,2,2,'#1b2228');px(x+3,y-13,2,2,'#1b2228');px(x-8,y-26,16,3,'#806b9b');
    const label=String(v.name||'VISITOR').slice(0,8).toUpperCase();px(x-16,y-38,32,y?10:10,'rgba(23,32,42,.88)');txt(label,x,y-30,'#fff',6);
    if(v.gift){px(x+8,y-3,10,9,'#b9854f');px(x+10,y-6,6,4,'#d4b37a');txt(String(v.gift).slice(0,4),x+13,y+14,'#fff',5);}
  }
  function frame(nowPerf){
    const dt=Math.min(.05,(nowPerf-last)/1000);last=nowPerf;oc.clearRect(0,0,640,400);
    objects.forEach(o=>{stepObject(o,dt);drawObject(o);});
    const now=Date.now();visitors.forEach(v=>drawVisitor(v,now));
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  let refreshing=false;
  async function refresh(){
    if(refreshing)return;refreshing=true;
    try{
      const r=await fetch('/api/town/world',{headers:{Accept:'application/json'}});if(!r.ok)return;
      const data=await r.json(),world=data&&data.world||{};
      const incoming=Array.isArray(world.worldObjects)?world.worldObjects:[];
      const oldById=new Map(objects.map(o=>[String(o.id||''),o]));
      objects=incoming.slice(-40).map(raw=>{const old=oldById.get(String(raw&&raw.id||''));return {...raw,x:Number(raw&&raw.x||0),y:Number(raw&&raw.y||0),phase:old?Number(old.phase||0):Math.random()*6.28};});
      visitors=Array.isArray(world.visitors)?world.visitors.slice(-8).map(v=>({...v})):[];
    }catch(_e){}finally{refreshing=false;}
  }
  refresh();setInterval(refresh,900);
})();
</script>
'''
    if 'town-generic-world-object-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-generic-world-object-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
