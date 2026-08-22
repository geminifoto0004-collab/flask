"""Runtime HTML patch for the standalone CUSTOMS AGENT TOWN Render page.

This layer keeps the existing large template untouched while adding the newer
AI-director world model: persistent furniture, life events, former-colleague
visits, real Iquique time, and weather-driven atmosphere.
"""


def patch_town_world(html: str) -> str:
    # The Render page no longer needs a visible endpoint field once it lives on
    # the same Flask origin as the town APIs.
    html = html.replace(
        "@media(max-width:600px){#customs-sim.app-root{padding:8px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
        "#customs-sim #aiBaseInput,#customs-sim #aiSaveBtn{display:none!important}\n"
        "@media(max-width:600px){#customs-sim.app-root{padding:8px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
    )

    # Persistent world collections and Iquique environment cache.
    html = html.replace(
        "  let decorVariant=Math.floor(rand(0,4));\n  let serverStateTimer=12;",
        "  let decorVariant=Math.floor(rand(0,4));\n"
        "  let aiFurniture=[];\n"
        "  let formerAgents=[];\n"
        "  let humanVisitors=[];\n"
        "  let townWeather={description:'',temperature:null,wind:null,code:null,updatedAt:0};\n"
        "  let townWeatherTimer=2;\n"
        "  let serverStateTimer=12;",
    )

    # Keep stable slot IDs (MIA/ANA/LIA) for work routing, while displayName and
    # life state may evolve or be replaced by the AI director.
    html = html.replace(
        "    return {name,index,persona:p.type,homeX:x,homeY:y,x,y,state:'idle'",
        "    return {name,displayName:name,index,persona:p.type,relationship:'single',partnerName:'',careerState:'active',generation:1,homeX:x,homeY:y,x,y,state:'idle'",
    )

    html = html.replace(
        "        savedAt:Date.now(),\n        decorVariant,\n        plants:plantStates,\n        agents:agents.map(a=>({name:a.name,workBias:a.workBias,energy:a.energy,mood:a.mood,curiosity:a.curiosity,social:a.social,focus:a.focus,restlessness:a.restlessness,coffeeLove:a.coffeeLove,flowerLove:a.flowerLove,fishLove:a.fishLove,fishCaught:a.fishCaught,persona:a.persona}))",
        "        savedAt:Date.now(),\n"
        "        decorVariant,\n"
        "        aiFurniture,\n"
        "        formerAgents,\n"
        "        plants:plantStates,\n"
        "        agents:agents.map(a=>({name:a.name,displayName:a.displayName,relationship:a.relationship,partnerName:a.partnerName,careerState:a.careerState,generation:a.generation,workBias:a.workBias,energy:a.energy,mood:a.mood,curiosity:a.curiosity,social:a.social,focus:a.focus,restlessness:a.restlessness,coffeeLove:a.coffeeLove,flowerLove:a.flowerLove,fishLove:a.fishLove,fishCaught:a.fishCaught,persona:a.persona,hairColor:a.hairColor,skinColor:a.skinColor,accentColor:a.accentColor}))",
    )
    html = html.replace(
        "      if(Number.isFinite(state.decorVariant))decorVariant=((state.decorVariant%4)+4)%4;\n      if(Array.isArray(state.plants)&&state.plants.length){",
        "      if(Number.isFinite(state.decorVariant))decorVariant=((state.decorVariant%4)+4)%4;\n"
        "      if(Array.isArray(state.aiFurniture))aiFurniture=state.aiFurniture.slice(0,24).filter(f=>f&&typeof f==='object');\n"
        "      if(Array.isArray(state.formerAgents))formerAgents=state.formerAgents.slice(-24).filter(f=>f&&typeof f==='object');\n"
        "      if(Array.isArray(state.plants)&&state.plants.length){",
    )
    html = html.replace(
        "          ['workBias','energy','mood','curiosity','social','focus','restlessness','coffeeLove','flowerLove','fishLove','fishCaught'].forEach(k=>{if(Number.isFinite(saved[k]))a[k]=saved[k];});",
        "          ['workBias','energy','mood','curiosity','social','focus','restlessness','coffeeLove','flowerLove','fishLove','fishCaught'].forEach(k=>{if(Number.isFinite(saved[k]))a[k]=saved[k];});\n"
        "          ['displayName','relationship','partnerName','careerState','persona','hairColor','skinColor','accentColor'].forEach(k=>{if(typeof saved[k]==='string'&&saved[k])a[k]=saved[k];});\n"
        "          if(Number.isFinite(saved.generation))a.generation=saved.generation;",
    )

    # The local micro-sim may fluctuate energy and mood, but only AI is allowed to
    # reshape long-term personality/work bias.
    html = html.replace(
        "        a.energy=Math.max(.12,Math.min(1,a.energy+rand(-.16,.14)));\n        a.mood=Math.max(.08,Math.min(1,a.mood+rand(-.18,.18)));\n        a.workBias=Math.max(.18,Math.min(.94,a.workBias+rand(-.12,.12)));",
        "        a.energy=Math.max(.12,Math.min(1,a.energy+rand(-.08,.08)));\n        a.mood=Math.max(.08,Math.min(1,a.mood+rand(-.08,.08)));",
    )

    # Real Chile clock helpers and richer world snapshot for DeepSeek.
    html = html.replace(
        "  function compactTownSnapshot(){",
        "  function chileNowParts(){\n"
        "    try{\n"
        "      const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Santiago',hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).formatToParts(new Date());\n"
        "      const out={};parts.forEach(p=>{if(p.type!=='literal')out[p.type]=p.value;});\n"
        "      return {year:+out.year,month:+out.month,day:+out.day,hour:(+out.hour)%24,minute:+out.minute,second:+out.second};\n"
        "    }catch(_e){const d=new Date();return {year:d.getFullYear(),month:d.getMonth()+1,day:d.getDate(),hour:d.getHours(),minute:d.getMinutes(),second:d.getSeconds()};}\n"
        "  }\n"
        "  function chileIsoLike(){const c=chileNowParts();return `${c.year}-${String(c.month).padStart(2,'0')}-${String(c.day).padStart(2,'0')} ${String(c.hour).padStart(2,'0')}:${String(c.minute).padStart(2,'0')}:${String(c.second).padStart(2,'0')}`;}\n"
        "  function agentLabel(a){return String(a?.displayName||a?.name||'').slice(0,18);}\n"
        "  function compactTownSnapshot(){",
    )
    html = html.replace(
        "      now:new Date().toISOString(),\n      stats:{total,done,waiting:queue.length,retry:retryQueue.length,held:vessels.filter(v=>v.state==='hold').length},\n      agents:agents.map(a=>({name:a.name,persona:a.persona,state:a.state,idle:a.idleAction,energy:+a.energy.toFixed(2),mood:+a.mood.toFixed(2),workBias:+a.workBias.toFixed(2),coffeeLove:+a.coffeeLove.toFixed(2),flowerLove:+a.flowerLove.toFixed(2),fishLove:+a.fishLove.toFixed(2),fishCaught:a.fishCaught})),",
        "      now:new Date().toISOString(),\n"
        "      iquiqueTime:chileIsoLike(),\n"
        "      weather:townWeather,\n"
        "      decorVariant,\n"
        "      stats:{total,done,waiting:queue.length,retry:retryQueue.length,held:vessels.filter(v=>v.state==='hold').length},\n"
        "      agents:agents.map(a=>({name:a.name,displayName:agentLabel(a),persona:a.persona,relationship:a.relationship,partnerName:a.partnerName,careerState:a.careerState,generation:a.generation,state:a.state,idle:a.idleAction,energy:+a.energy.toFixed(2),mood:+a.mood.toFixed(2),workBias:+a.workBias.toFixed(2),coffeeLove:+a.coffeeLove.toFixed(2),flowerLove:+a.flowerLove.toFixed(2),fishLove:+a.fishLove.toFixed(2),fishCaught:a.fishCaught})),\n"
        "      formerAgents:formerAgents.slice(-12).map(f=>({id:f.id,displayName:f.displayName,reason:f.reason||'',leftAt:f.leftAt||0})),",
    )
    html = html.replace(
        "      dogPoops:dogPoops.length\n    };",
        "      dogPoops:dogPoops.length,\n"
        "      furniture:aiFurniture.map(f=>({id:f.id,type:f.type,x:f.x,y:f.y,w:f.w,h:f.h,label:f.label||''}))\n"
        "    };",
    )

    # Insert generic AI-created furniture and life-event helpers before action handling.
    marker = "  function applyAiTownActions(actions=[]){"
    helpers = r'''  const AI_FURNITURE_TYPES=['file_box','chair','plant_shelf','dog_bowl','side_table','wall_frame','floor_lamp','small_cabinet','rug','notice_board'];
  function furnitureBounds(f){const w=Math.max(8,Math.min(72,Number(f.w)||24)),h=Math.max(8,Math.min(60,Number(f.h)||18));return {x1:f.x-w/2,y1:f.y-h/2,x2:f.x+w/2,y2:f.y+h/2,w,h};}
  function furniturePlacementValid(candidate,ignoreId=''){
    if(!candidate||!AI_FURNITURE_TYPES.includes(candidate.type))return false;const b=furnitureBounds(candidate);
    if(candidate.type==='wall_frame'||candidate.type==='notice_board'){if(b.x1<130||b.x2>510||b.y1<34||b.y2>92)return false;}
    else{if(b.x1<46||b.x2>586||b.y1<92||b.y2>250)return false;const door={x1:246,y1:236,x2:394,y2:282};if(!(b.x2<door.x1||b.x1>door.x2||b.y2<door.y1||b.y1>door.y2))return false;if(deskBlocks.some(d=>!(b.x2<d.x1-14||b.x1>d.x2+14||b.y2<d.y1-14||b.y1>d.y2+14)))return false;}
    return !aiFurniture.some(f=>{if(f.id===ignoreId)return false;const o=furnitureBounds(f);return !(b.x2<o.x1-6||b.x1>o.x2+6||b.y2<o.y1-6||b.y1>o.y2+6);});
  }
  function safeFurnitureFromAi(action){
    const type=String(action.furniture||action.typeName||'');if(!AI_FURNITURE_TYPES.includes(type))return null;const requestedId=String(action.id||'').slice(0,80);if(requestedId&&aiFurniture.some(f=>f.id===requestedId))return null;
    const defaults={file_box:[118,230,26,18],chair:[520,230,22,22],plant_shelf:[548,126,34,28],dog_bowl:[560,286,18,10],side_table:[500,214,28,22],wall_frame:[448,50,36,22],floor_lamp:[488,226,14,34],small_cabinet:[548,192,34,34],rug:[500,232,54,26],notice_board:[330,52,56,24]};const d=defaults[type];
    const f={id:requestedId||('ai-furn-'+Date.now()+'-'+Math.floor(Math.random()*9999)),type,x:Number(action.x)||d[0],y:Number(action.y)||d[1],w:Number(action.w)||d[2],h:Number(action.h)||d[3],label:String(action.label||'').slice(0,24)};
    if(furniturePlacementValid(f))return f;for(let i=0;i<20;i++){f.x=type==='wall_frame'||type==='notice_board'?rand(160,500):rand(70,570);f.y=type==='wall_frame'||type==='notice_board'?rand(42,78):rand(108,242);if(furniturePlacementValid(f))return f;}return null;
  }
  function drawAiFurniture(f){
    if(!f)return;const x=Math.round(f.x),y=Math.round(f.y),b=furnitureBounds(f),w=b.w,h=b.h;
    if(f.type==='file_box'){rect(x-w/2,y-h/2,w,h,'#8b6748');px(x-w/2+3,y-h/2+3,w-6,4,'#b59268');px(x-6,y-2,12,4,'#e0d0ae');}
    else if(f.type==='chair'){rect(x-w/2,y-h/2,w,h*.45,'#70565d');rect(x-w*.38,y-h*.05,w*.76,h*.38,'#5a454c');px(x-w*.32,y+h*.28,4,8,'#40343a');px(x+w*.2,y+h*.28,4,8,'#40343a');}
    else if(f.type==='plant_shelf'){rect(x-w/2,y-h/2,w,h,'#6e4c32');for(let r=0;r<2;r++)px(x-w/2+3,y-h/2+5+r*12,w-6,3,'#a9784d');drawPlant(x-10,y-7);drawPlant(x+8,y+4);}
    else if(f.type==='dog_bowl'){px(x-w/2,y-h/2+3,w,h-3,'#6f8a91');px(x-w/2+3,y-h/2+5,w-6,3,'#a9c3c7');}
    else if(f.type==='side_table'){px(x-w/2,y-h/2,w,6,'#9a714d');px(x-w*.34,y-h/2+6,4,h-6,'#5d422f');px(x+w*.2,y-h/2+6,4,h-6,'#5d422f');}
    else if(f.type==='wall_frame'){rect(x-w/2,y-h/2,w,h,'#674d38');rect(x-w/2+4,y-h/2+4,w-8,h-8,'#d9c9aa');px(x-w/2+8,y-h/2+8,w-16,h-16,'#789596');}
    else if(f.type==='floor_lamp'){px(x-2,y-h/2+8,4,h-12,'#66503b');px(x-10,y-h/2,20,10,'#d9b665');px(x-8,y+h/2-4,16,4,'#4e3c2f');}
    else if(f.type==='small_cabinet'){rect(x-w/2,y-h/2,w,h,'#705039');rect(x-w/2+4,y-h/2+4,w-8,h-8,'#94704f');px(x-3,y,6,2,'#d8c6a2');}
    else if(f.type==='rug'){rect(x-w/2,y-h/2,w,h,'#7d665f');rect(x-w/2+4,y-h/2+4,w-8,h-8,'#9a7e73');}
    else if(f.type==='notice_board'){rect(x-w/2,y-h/2,w,h,'#6f543d');rect(x-w/2+4,y-h/2+4,w-8,h-8,'#b98d62');px(x-w/2+8,y-h/2+7,14,8,'#e6ddc4');px(x+3,y-h/2+7,16,7,'#d9c98d');}
  }
  function replacementPalette(seed=''){let h=0;for(const ch of seed)h=(h*31+ch.charCodeAt(0))>>>0;const skins=['#d9a27b','#c98f6e','#b98262','#e0ad86','#9f6e55'],hairs=['#30251f','#5a3b2d','#24282d','#744b38','#3b2e42'],accents=['#c18a52','#7b75a7','#4f8a77','#a66767','#637ea3'];return {skin:skins[h%skins.length],hair:hairs[(h>>3)%hairs.length],accent:accents[(h>>6)%accents.length]};}
  function replaceAgentLife(target,action){
    if(!target||target.task)return;const old={id:'former-'+Date.now()+'-'+target.name,slot:target.name,displayName:agentLabel(target),persona:target.persona,reason:String(action.reason||'離開海關辦公室').slice(0,50),leftAt:Date.now(),hairColor:target.hairColor,skinColor:target.skinColor,accentColor:target.accentColor};formerAgents.push(old);formerAgents=formerAgents.slice(-24);
    const newName=String(action.newName||action.new_name||'新同事').trim().slice(0,18)||'新同事',palette=replacementPalette(newName);target.displayName=newName;target.relationship='single';target.partnerName='';target.careerState='active';target.generation=(target.generation||1)+1;target.persona=['lazy','busybody','restless'].includes(action.persona)?action.persona:'busybody';target.hairColor=palette.hair;target.skinColor=palette.skin;target.accentColor=palette.accent;
    const traits=action.traits&&typeof action.traits==='object'?action.traits:{};['workBias','energy','mood','curiosity','social','focus','restlessness','coffeeLove','flowerLove','fishLove'].forEach(k=>{if(Number.isFinite(Number(traits[k])))target[k]=Math.max(.05,Math.min(1,Number(traits[k])));});target.state='idle';target.task=null;target.path=[];target.pathTarget='';chooseIdleTarget(target,'desk');addLog(old.displayName+' '+old.reason+'；新同事 '+newName+' 來到 IQUIQUE 辦公室');saveWorld();
  }
  function spawnFormerVisitor(action){if(humanVisitors.length>=3||!formerAgents.length)return;const wanted=String(action.formerId||action.id||action.name||''),former=formerAgents.find(f=>f.id===wanted||f.displayName===wanted)||formerAgents[formerAgents.length-1];if(!former)return;humanVisitors.push({id:'visitor-'+Date.now(),name:former.displayName,x:320,y:296,targetX:500,targetY:232,state:'enter',timer:25,path:[],pathTarget:'',hairColor:former.hairColor||'#4a352b',skinColor:former.skinColor||'#c99472',accentColor:former.accentColor||'#8670a0'});addLog('以前的同事 '+former.displayName+' 回來探望大家');}
  function updateHumanVisitors(dt){humanVisitors.forEach(v=>{if(v.state==='enter'){if(moveToward(v,v.targetX,v.targetY,38*dt)){v.state='visit';v.timer=18+Math.random()*18;}}else if(v.state==='visit'){v.timer-=dt;if(v.timer<=0){v.state='leave';v.path=[];v.pathTarget='';}}else if(v.state==='leave'){if(moveToward(v,320,296,42*dt))v.done=true;}});humanVisitors=humanVisitors.filter(v=>!v.done);}
  function drawHumanVisitor(v){const x=Math.round(v.x),y=Math.round(v.y),skin=v.skinColor||'#c99472',hair=v.hairColor||'#4a352b';px(x-6,y+12,14,3,'rgba(0,0,0,.2)');px(x-6,y+5,5,9,'#3f5260');px(x+2,y+5,5,9,'#3f5260');px(x-9,y-8,18,14,'#b7a58e');px(x-7,y-6,14,10,'#d1c1aa');px(x-6,y-20,14,14,skin);px(x-8,y-22,18,5,hair);px(x-3,y-13,2,2,'#1b2228');px(x+3,y-13,2,2,'#1b2228');px(x-8,y-26,16,3,v.accentColor||'#8670a0');}
  function handleExtendedAiAction(action){
    if(action.type==='agent_life'){const target=agents.find(x=>x.name===action.agent);if(target){if(action.event==='marry'){target.relationship='married';target.partnerName=String(action.partnerName||'').slice(0,18);addLog(agentLabel(target)+' 結婚了'+(target.partnerName?'，伴侶是 '+target.partnerName:''));saveWorld();}else if(action.event==='divorce'){target.relationship='single';target.partnerName='';addLog(agentLabel(target)+' 的人生進入新階段');saveWorld();}}return true;}
    if(action.type==='replace_agent'){replaceAgentLife(agents.find(x=>x.name===action.agent),action);return true;}
    if(action.type==='former_visit'){spawnFormerVisitor(action);return true;}
    if(action.type==='furniture_add'){if(aiFurniture.length<24){const f=safeFurnitureFromAi(action);if(f){aiFurniture.push(f);addLog('AI 新增家具：'+f.type+(f.label?' · '+f.label:''));saveWorld();}}return true;}
    if(action.type==='furniture_move'){const f=aiFurniture.find(x=>x.id===action.id);if(f){const moved={...f,x:Number(action.x)||f.x,y:Number(action.y)||f.y};if(furniturePlacementValid(moved,f.id)){Object.assign(f,moved);addLog('AI 搬動了 '+f.type);saveWorld();}}return true;}
    if(action.type==='furniture_remove'){const idx=aiFurniture.findIndex(x=>x.id===action.id);if(idx>=0){const f=aiFurniture[idx];aiFurniture.splice(idx,1);addLog('AI 移除了 '+f.type);saveWorld();}return true;}
    return false;
  }
'''
    html = html.replace(marker, helpers + marker)
    html = html.replace(
        "    actions.slice(0,5).forEach(action=>{\n      if(!action||typeof action!=='object')return;",
        "    actions.slice(0,7).forEach(action=>{\n      if(!action||typeof action!=='object')return;\n      if(handleExtendedAiAction(action))return;",
    )
    html = html.replace("addLog('AI 決定：'+a.name+' → '+action.action);", "addLog('AI 決定：'+agentLabel(a)+' → '+action.action);")
    html = html.replace("addLog('AI 讓 '+target.name+' 的 '+trait+' 永久變成 '+target[trait].toFixed(2));", "addLog('AI 讓 '+agentLabel(target)+' 的 '+trait+' 永久變成 '+target[trait].toFixed(2));")

    # Consume every missed cron plan instead of only the newest one, and refresh
    # Iquique weather from Flask without exposing any API key.
    old_sync = """  async function pushTownState(){
    if(!TOWN_AI_BASE)return;
    try{await fetch(TOWN_AI_BASE+'/api/town/state',{method:'POST',headers:{'Accept':'application/json'},body:JSON.stringify({world:compactTownSnapshot()})});}catch(_e){}
  }
  async function pullTownPlan(){
    if(!TOWN_AI_BASE||aiBusy)return;
    try{
      const r=await fetch(TOWN_AI_BASE+'/api/town/plan',{headers:{'Accept':'application/json'}});
      if(!r.ok)return;
      const data=await r.json();
      const version=Number(data?.version||0);
      if(version<=lastServerPlanVersion)return;
      lastServerPlanVersion=version;
      localStorage.setItem('customs-town-plan-version',String(version));
      applyAiTownActions(data?.actions||[]);
      if(data?.thought)addLog('遠端 AI 演化：'+String(data.thought).slice(0,120));
    }catch(_e){}
  }
"""
    new_sync = """  async function pushTownState(){
    if(!TOWN_AI_BASE)return;
    try{await fetch(TOWN_AI_BASE+'/api/town/state',{method:'POST',headers:{'Accept':'application/json'},body:JSON.stringify({world:compactTownSnapshot()})});}catch(_e){}
  }
  async function refreshTownContext(){
    if(!TOWN_AI_BASE)return;
    try{const r=await fetch(TOWN_AI_BASE+'/api/town/context',{headers:{'Accept':'application/json'}});if(!r.ok)return;const data=await r.json();if(data?.weather)townWeather={...townWeather,...data.weather,updatedAt:Date.now()};}catch(_e){}
  }
  async function pullTownPlan(){
    if(!TOWN_AI_BASE||aiBusy)return;
    try{
      const r=await fetch(TOWN_AI_BASE+'/api/town/plan',{headers:{'Accept':'application/json'}});if(!r.ok)return;const data=await r.json();const plans=Array.isArray(data?.plans)?data.plans:[data];
      const pending=plans.filter(p=>Number(p?.version||0)>lastServerPlanVersion).sort((a,b)=>Number(a.version||0)-Number(b.version||0));
      pending.forEach(plan=>{applyAiTownActions(plan?.actions||[]);const version=Number(plan?.version||0);if(version>lastServerPlanVersion)lastServerPlanVersion=version;if(plan?.thought)addLog('遠端 AI 演化：'+String(plan.thought).slice(0,120));});
      if(pending.length)localStorage.setItem('customs-town-plan-version',String(lastServerPlanVersion));
    }catch(_e){}
  }
"""
    html = html.replace(old_sync, new_sync)
    html = html.replace(
        "    updateDogs(dt);\n    serverStateTimer-=dt;serverPlanTimer-=dt;",
        "    updateDogs(dt);\n    updateHumanVisitors(dt);\n    townWeatherTimer-=dt;if(townWeatherTimer<=0){townWeatherTimer=900;refreshTownContext();}\n    serverStateTimer-=dt;serverPlanTimer-=dt;",
    )

    # AI furniture becomes real collision geometry and is drawn into the room.
    html = html.replace(
        "    if(deskBlocks.some(b=>x>b.x1-pad&&x<b.x2+pad&&y>b.y1-pad&&y<b.y2+pad))return true;",
        "    if(deskBlocks.some(b=>x>b.x1-pad&&x<b.x2+pad&&y>b.y1-pad&&y<b.y2+pad))return true;\n"
        "    if(aiFurniture.some(f=>{if(['wall_frame','notice_board','rug','dog_bowl'].includes(f.type))return false;const b=furnitureBounds(f);return x>b.x1-6&&x<b.x2+6&&y>b.y1-6&&y<b.y2+6;}))return true;",
    )
    html = html.replace(
        "    drawBreakTable(decorVariant%2===0?520:500,216);",
        "    drawBreakTable(decorVariant%2===0?520:500,216);\n"
        "    aiFurniture.filter(f=>f.type==='wall_frame'||f.type==='notice_board').forEach(drawAiFurniture);\n"
        "    aiFurniture.filter(f=>f.type!=='wall_frame'&&f.type!=='notice_board').forEach(drawAiFurniture);",
    )

    # Make IQUIQUE explicit, make the wall clock truly follow Chile time, and tint
    # the whole town according to local day/night plus actual weather.
    html = html.replace(
        "    // 上牆改成一個完整的公共視覺中心：公告板、時鐘、掛畫與壁燈。\n    drawNoticeBoard(214,43);",
        "    // IQUIQUE 海關辦公室公共視覺中心。\n    txt('ADUANA · IQUIQUE',320,41,'#efe5c7',7,'center');\n    drawNoticeBoard(214,43);",
    )
    html = html.replace(
        "  function drawWallClock(x,y){\n    px(x-9,y-9,18,18,'#5b4636');px(x-6,y-6,12,12,'#ece4cf');px(x-1,y-5,2,6,'#3d4650');px(x-1,y-1,5,2,'#3d4650');\n  }",
        "  function drawWallClock(x,y){\n"
        "    const c=chileNowParts(),minute=c.minute+c.second/60,hour=(c.hour%12)+minute/60;\n"
        "    px(x-9,y-9,18,18,'#5b4636');px(x-6,y-6,12,12,'#ece4cf');px(x-1,y-1,2,2,'#3d4650');\n"
        "    const hand=(angle,len,color)=>{const ex=x+Math.sin(angle)*len,ey=y-Math.cos(angle)*len,steps=Math.max(1,Math.ceil(len));for(let i=1;i<=steps;i++){const q=i/steps;px(x+(ex-x)*q-1,y+(ey-y)*q-1,2,2,color);}};\n"
        "    hand(minute/60*Math.PI*2,5,'#3d4650');hand(hour/12*Math.PI*2,4,'#6a4338');\n"
        "  }\n"
        "  function drawAtmosphere(){\n"
        "    const c=chileNowParts(),h=c.hour+c.minute/60;let alpha=0;if(h>=20||h<6)alpha=.34;else if(h>=18)alpha=.12+(h-18)*.11;else if(h<8)alpha=.22-(h-6)*.11;\n"
        "    if(alpha>0){ctx.save();ctx.globalAlpha=alpha;rect(0,0,W,H,'#0b1b38');ctx.restore();}\n"
        "    const code=Number(townWeather.code),rainy=[51,53,55,56,57,61,63,65,66,67,80,81,82].includes(code),cloudy=[2,3,45,48].includes(code);\n"
        "    if(cloudy){ctx.save();ctx.globalAlpha=.08;rect(0,0,W,H,'#566477');ctx.restore();}\n"
        "    if(rainy){ctx.save();ctx.globalAlpha=.42;for(let i=0;i<38;i++){const rx=(i*47+Math.floor(t*55))%W,ry=(i*83+Math.floor(t*90))%H;px(rx,ry,2,8,'#a7d0df');}ctx.restore();}\n"
        "    txt('IQUIQUE '+String(c.hour).padStart(2,'0')+':'+String(c.minute).padStart(2,'0'),74,390,'#d5e6e8',6,'left');\n"
        "    if(Number.isFinite(Number(townWeather.temperature)))txt(Math.round(Number(townWeather.temperature))+'°C',156,390,'#d5e6e8',6,'left');\n"
        "  }",
    )
    html = html.replace(
        "  function frame(now){\n    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;update(dt);drawRoom();agents.slice().sort((a,b)=>a.y-b.y).forEach(drawAgent);requestAnimationFrame(frame);\n  }",
        "  function frame(now){\n    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;update(dt);drawRoom();agents.slice().sort((a,b)=>a.y-b.y).forEach(drawAgent);humanVisitors.slice().sort((a,b)=>a.y-b.y).forEach(drawHumanVisitor);drawAtmosphere();requestAnimationFrame(frame);\n  }",
    )
    html = html.replace(
        "    setTimeout(()=>{pushTownState();pullTownPlan();},900);",
        "    setTimeout(()=>{pushTownState();pullTownPlan();refreshTownContext();},900);",
    )

    return html
