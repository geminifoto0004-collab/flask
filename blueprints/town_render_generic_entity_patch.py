"""Safe browser overlay for the generic entity/action engine.

This patch does not replace the known-good game loop. It renders AI-created
visitors/actors on a transparent canvas and animates validated shared scripts
from /api/town/world.
"""


def patch_render_generic_entities(html: str) -> str:
    css = r'''
<style id="town-generic-entity-style">
#town-generic-entity-overlay{position:absolute;inset:6px;width:calc(100% - 12px);height:calc(100% - 12px);pointer-events:none;image-rendering:pixelated;image-rendering:crisp-edges;z-index:12;background:transparent!important}
</style>
'''
    js = r'''
<script id="town-generic-entity-runtime">
(()=>{
  const app=document.getElementById('customs-sim');
  const wrap=app&&app.querySelector('.game-wrap');
  const base=app&&app.querySelector('.game-wrap canvas');
  if(!app||!wrap||!base)return;

  let overlay=document.getElementById('town-generic-entity-overlay');
  if(!overlay){
    overlay=document.createElement('canvas');overlay.id='town-generic-entity-overlay';
    overlay.width=640;overlay.height=400;wrap.appendChild(overlay);
  }
  const c=overlay.getContext('2d');if(!c)return;c.imageSmoothingEnabled=false;
  const entities=new Map(), hidden=new Set(), officerPos=new Map();
  const officerFallback={MIA:{x:320,y:236},ANA:{x:500,y:236},LIA:{x:145,y:236}};
  let last=performance.now(),refreshing=false;

  function eventLog(text){
    const box=app.querySelector('#eventLog');if(!box)return;
    const d=document.createElement('div');d.textContent='> '+text;box.appendChild(d);box.scrollTop=box.scrollHeight;
  }
  function px(x,y,w,h,color){c.fillStyle=color;c.fillRect(Math.round(x/2)*2,Math.round(y/2)*2,Math.max(2,Math.round(w/2)*2),Math.max(2,Math.round(h/2)*2));}
  function targetPos(id){
    const key=String(id||'');
    if(entities.has(key)){const e=entities.get(key);return {x:e.x,y:e.y};}
    const upper=key.toUpperCase();return officerPos.get(upper)||officerFallback[upper]||null;
  }
  function zonePos(zone){
    if(zone==='office')return {x:320,y:238};
    if(zone==='office_door')return {x:320,y:278};
    if(zone==='harbor_walkway')return {x:320,y:292};
    if(zone==='pier')return {x:320,y:306};
    if(zone==='sea')return {x:520,y:350};
    return null;
  }
  function routeFor(e,tx,ty){
    const route=[];const insideNow=e.y<274,insideTarget=ty<274;
    if(insideNow!==insideTarget){
      if(insideNow){route.push({x:320,y:265},{x:320,y:282});}
      else{route.push({x:320,y:286},{x:320,y:266});}
    }
    route.push({x:tx,y:ty});return route;
  }
  function moveToward(e,p,speed,dt){
    const dx=p.x-e.x,dy=p.y-e.y,d=Math.hypot(dx,dy);if(d<2){e.x=p.x;e.y=p.y;return true;}
    const step=Math.min(d,Math.max(10,speed)*dt);e.x+=dx/d*step;e.y+=dy/d*step;return false;
  }
  function stepId(step){return String(step&&step.stepId||step&&step.id||'');}
  function startStep(e,step){
    e.current={...step,elapsed:0};const kind=String(step.type||'');
    if(kind==='move_entity'){
      const t=targetPos(step.target);const z=zonePos(step.zone);
      const tx=t?t.x:(Number.isFinite(Number(step.x))?Number(step.x):(z?z.x:e.x));
      const ty=t?t.y:(Number.isFinite(Number(step.y))?Number(step.y):(z?z.y:e.y));
      e.current.route=routeFor(e,tx,ty);e.current.speed=Number(step.speed)||38;
    }else if(kind==='say'){
      const zh=document.getElementById('dialogueLangSelect')?.value!=='es';
      e.speech=String(zh&&(step.text_zh||step.textZh)?(step.text_zh||step.textZh):(step.text||''));
      e.current.duration=Math.max(4,Math.min(12,2.8+e.speech.length*.08));
      if(e.speech)eventLog('💬 '+e.name+'：'+e.speech);
    }else if(kind==='wait')e.current.duration=Math.max(.5,Math.min(120,Number(step.seconds)||1));
    else if(kind==='give')e.current.duration=.9;
    else if(kind==='leave'){
      const outside=e.y>=274;
      e.current.route=outside?[{x:620,y:292}]:[{x:320,y:265},{x:320,y:286},{x:620,y:292}];e.current.speed=44;
    }
  }
  function finishStep(e){
    const step=e.current;if(!step)return;const id=stepId(step);if(id)e.done.add(id);
    if(step.type==='say')e.speech='';
    if(step.type==='give'){
      const item=String(step.item||'物品');e.carrying=e.carrying.filter(v=>v!==item);
      eventLog(e.name+' 把 '+item+' 交給 '+String(step.target||'對方'));
    }
    if(step.type==='leave'){hidden.add(e.id);eventLog(e.name+' 離開了');}
    e.current=null;
  }
  function tick(e,dt){
    if(hidden.has(e.id))return;
    if(!e.current&&e.queue.length)startStep(e,e.queue.shift());
    const s=e.current;if(!s)return;s.elapsed+=dt;
    if(s.type==='move_entity'||s.type==='leave'){
      if(!Array.isArray(s.route)||!s.route.length){finishStep(e);return;}
      const p=s.route[0];if(moveToward(e,p,s.speed||38,dt))s.route.shift();
      if(!s.route.length)finishStep(e);
    }else if(s.type==='say'||s.type==='wait'||s.type==='give'){
      if(s.elapsed>=Number(s.duration||1))finishStep(e);
    }else finishStep(e);
  }
  function label(text,x,y){
    const t=String(text||'').toUpperCase();if(!t)return;c.font='bold 7px monospace';const w=Math.max(30,Math.ceil(c.measureText(t).width)+8);px(x-w/2,y-35,w,10,'rgba(22,31,40,.88)');c.fillStyle='#fff';c.textAlign='center';c.fillText(t,Math.round(x),Math.round(y-27));
  }
  function bubble(e){
    if(!e.speech)return;c.font='8px sans-serif';const text=e.speech.slice(0,42),w=Math.min(210,Math.max(62,c.measureText(text).width+18));let x=Math.max(6,Math.min(640-w-6,e.x-w/2)),y=Math.max(6,e.y-70);px(x,y,w,23,'rgba(250,252,255,.96)');px(e.x-2,y+23,6,5,'rgba(250,252,255,.96)');c.fillStyle='#1d2730';c.textAlign='left';c.fillText(text,x+8,y+15);
  }
  function drawHuman(e){
    const x=e.x,y=e.y,body=e.bodyColor||'#62788a',accent=e.accentColor||'#d9a441';
    px(x-7,y+12,16,3,'rgba(0,0,0,.20)');px(x-7,y+4,6,10,'#334454');px(x+2,y+4,6,10,'#334454');
    px(x-10,y-10,20,15,body);px(x-8,y-8,16,3,accent);px(x-7,y-23,14,14,'#c99570');px(x-9,y-25,18,5,'#4a352b');
    px(x-4,y-16,2,2,'#172126');px(x+3,y-16,2,2,'#172126');px(x-2,y-11,5,2,'#9a5d52');
    px(x-13,y-7,4,12,body);px(x+10,y-7,4,12,body);
    if(e.carrying.length){px(x+13,y-1,9,11,'#b47b43');px(x+15,y-4,5,4,'#e4c48e');}
    label(e.name,x,y);bubble(e);
  }
  function drawVehicle(e){
    const x=e.x,y=e.y,body=e.bodyColor||'#b74747';px(x-20,y-8,40,13,body);px(x-11,y-14,23,7,'#d5e7ed');px(x-16,y-5,6,5,'#f1d45b');px(x-15,y+4,8,6,'#20282e');px(x+8,y+4,8,6,'#20282e');label(e.name,x,y);
  }
  function drawAnimal(e){const x=e.x,y=e.y,body=e.bodyColor||'#788890';px(x-11,y-5,22,10,body);px(x+7,y-10,9,9,body);px(x+12,y-7,2,2,'#182126');px(x-13,y-2,5,4,e.accentColor||'#58666d');label(e.name,x,y);}
  function drawItem(e){const x=e.x,y=e.y;px(x-8,y-8,16,16,e.bodyColor||'#c99548');px(x-5,y-5,10,10,e.accentColor||'#efd17a');label(e.name,x,y);}
  function draw(e){if(hidden.has(e.id))return;if(e.entityType==='vehicle')drawVehicle(e);else if(e.entityType==='animal')drawAnimal(e);else if(e.entityType==='item'||e.entityType==='decoration')drawItem(e);else drawHuman(e);}

  function mergeWorld(world){
    const agents=Array.isArray(world&&world.agents)?world.agents:[];
    agents.forEach(a=>{const name=String(a&&a.name||a&&a.slot||'').toUpperCase();if(!name)return;const fb=officerFallback[name];officerPos.set(name,{x:Number(a&&a.x)||(fb&&fb.x)||320,y:Number(a&&a.y)||(fb&&fb.y)||236});});
    const incoming=Array.isArray(world&&world.genericEntities)?world.genericEntities:[];
    incoming.forEach(raw=>{
      const id=String(raw&&raw.id||'');if(!id||hidden.has(id))return;
      let e=entities.get(id);
      if(!e){e={id,name:String(raw.name||id),entityType:String(raw.entityType||'human'),zone:String(raw.zone||''),x:Number(raw.x)||320,y:Number(raw.y)||292,bodyColor:raw.bodyColor,accentColor:raw.accentColor,carrying:Array.isArray(raw.carrying)?raw.carrying.slice():[],queue:[],current:null,done:new Set(),speech:''};entities.set(id,e);}
      e.name=String(raw.name||e.name);e.entityType=String(raw.entityType||e.entityType);e.bodyColor=raw.bodyColor||e.bodyColor;e.accentColor=raw.accentColor||e.accentColor;
      if(!e.current&&!e.queue.length&&Number.isFinite(Number(raw.x))&&Number.isFinite(Number(raw.y))){e.x=Number(raw.x);e.y=Number(raw.y);}
      const queued=new Set(e.queue.map(stepId));if(e.current)queued.add(stepId(e.current));
      (Array.isArray(raw.script)?raw.script:[]).forEach(step=>{const sid=stepId(step);if(sid&&!e.done.has(sid)&&!queued.has(sid)){e.queue.push({...step});queued.add(sid);}});
    });
    const ids=new Set(incoming.map(v=>String(v&&v.id||'')));
    [...entities.keys()].forEach(id=>{if(!ids.has(id)&&!entities.get(id)?.current)entities.delete(id);});
  }
  async function refresh(){
    if(refreshing)return;refreshing=true;
    try{const r=await fetch('/api/town/world',{headers:{Accept:'application/json'}});if(!r.ok)return;const data=await r.json();mergeWorld(data&&data.world||{});}catch(_e){}finally{refreshing=false;}
  }
  function frame(now){const dt=Math.min(.05,(now-last)/1000);last=now;c.clearRect(0,0,640,400);entities.forEach(e=>{tick(e,dt);draw(e);});requestAnimationFrame(frame);}
  refresh();setInterval(refresh,900);requestAnimationFrame(frame);
})();
</script>
'''
    if 'town-generic-entity-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-generic-entity-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
