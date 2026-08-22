"""Render-page patch for persistent AI character profiles and topic memory."""


def patch_render_profiles(html: str) -> str:
    marker = "  function applyAiTownActions(actions=[]){"
    if "function ensureAgentProfile(a)" not in html and marker in html:
        helper = r'''  function ensureAgentProfile(a){
    if(!a)return {};
    if(!a.profile||typeof a.profile!=='object')a.profile={};
    if(!Array.isArray(a.profile.likes))a.profile.likes=[];
    if(!Array.isArray(a.profile.dislikes))a.profile.dislikes=[];
    if(!Array.isArray(a.profile.interests))a.profile.interests=[];
    return a.profile;
  }
  registerDirectorTool('agent_profile',action=>{
    const a=agents.find(x=>x.name===String(action.agent||'').toUpperCase());
    if(!a)return;
    const p=ensureAgentProfile(a);
    if(Number.isFinite(Number(action.age)))p.age=Math.max(18,Math.min(75,Math.round(Number(action.age))));
    if(action.gender!=null)p.gender=String(action.gender).slice(0,18);
    if(action.zodiac!=null)p.zodiac=String(action.zodiac).slice(0,18);
    if(action.maritalStatus!=null)p.maritalStatus=String(action.maritalStatus).slice(0,24);
    if(action.hasChildren!=null)p.hasChildren=!!action.hasChildren;
    if(Number.isFinite(Number(action.childrenCount)))p.childrenCount=Math.max(0,Math.min(8,Math.round(Number(action.childrenCount))));
    if(Array.isArray(action.likes))p.likes=action.likes.map(v=>String(v).trim()).filter(Boolean).slice(0,10);
    if(Array.isArray(action.dislikes))p.dislikes=action.dislikes.map(v=>String(v).trim()).filter(Boolean).slice(0,10);
    if(Array.isArray(action.interests))p.interests=action.interests.map(v=>String(v).trim()).filter(Boolean).slice(0,10);
    addLog('AI 更新 '+agentLabel(a)+' 的生活檔案');saveWorld();
  });

'''
        html = html.replace(marker, helper + marker, 1)

    # Actually execute the new validated tool in the browser.
    html = html.replace(
        "      }else if(action.type==='plant_spawn'){",
        "      }else if(action.type==='agent_profile'){\n        DIRECTOR_TOOLS.agent_profile?.(action);\n      }else if(action.type==='plant_spawn'){",
    )

    # Send persistent life context and recent conversation memory back to the
    # director so it can choose topics instead of recycling the latest headline.
    html = html.replace(
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12)\n    };",
        "      recentDirectorActions:(Array.isArray(window.__townDirectorHistory)?window.__townDirectorHistory:[]).slice(-12),\n"
        "      characterProfiles:agents.map(a=>({name:a.name,profile:ensureAgentProfile(a)})),\n"
        "      recentDialogue:(Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[]).slice(-8),\n"
        "      profileGuidance:'If a profile is empty, AI may create it with agent_profile. Use age, gender, zodiac, marital status, children, likes, dislikes and interests as persistent context together with mood, relationships and recent events. Do not stereotype and do not force profile facts into every conversation. Avoid recently discussed topics; news is optional, not the default.'\n"
        "    };",
    )

    # Record what the AI actually made the characters say. This memory is sent
    # on the next director call and deliberately kept short.
    html = html.replace(
        "    if(!turns.length)return;\n    const midX=",
        "    if(!turns.length)return;\n"
        "    window.__townDialogueHistory=Array.isArray(window.__townDialogueHistory)?window.__townDialogueHistory:[];\n"
        "    window.__townDialogueHistory.push({at:Date.now(),members:[from.name,to.name],text:turns.map(turn=>turn.speaker+': '+turn.text).join(' ').slice(0,520)});\n"
        "    window.__townDialogueHistory=window.__townDialogueHistory.slice(-8);\n"
        "    const midX=",
        1,
    )

    # Make the manual-test log show profile creation as a real function call.
    html = html.replace(
        "    if(type==='agent_evolve')return `${action.agent||'?'} ${action.trait||'?'} ${Number(action.delta||0)>=0?'+':''}${action.delta||0}`;",
        "    if(type==='agent_evolve')return `${action.agent||'?'} ${action.trait||'?'} ${Number(action.delta||0)>=0?'+':''}${action.delta||0}`;\n"
        "    if(type==='agent_profile')return `${action.agent||'?'} 設定生活檔案`;",
    )

    # On reload, restore server-persisted profiles before the rest of the world
    # snapshot is applied to the local agent objects.
    html = html.replace(
        "  function applyServerWorld(world){",
        "  function applyServerWorld(world){\n"
        "    if(Array.isArray(world?.characterProfiles)){world.characterProfiles.forEach(item=>{const a=agents.find(x=>x.name===String(item?.name||'').toUpperCase());if(a&&item?.profile&&typeof item.profile==='object')a.profile={...ensureAgentProfile(a),...item.profile};});}",
        1,
    )
    return html
