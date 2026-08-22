"""Make Render start the town animation before persistence/network loading.

The browser must never remain on the blank canvas just because IndexedDB or a
remote world request is slow.  This mirrors the v150 App Block startup order.
"""


def patch_render_boot_safety(html: str) -> str:
    start = html.find("  async function bootWorld(){")
    end = html.find("  window.addEventListener('pagehide',saveWorld);", start)
    if start < 0 or end < 0:
        return html

    boot = r'''  async function bootWorld(){
    // Start rendering first. Persistence/network work is allowed to finish later.
    if(!plantStates.length)seedPlants();
    applyOfficeLayoutToAgents();
    agents.forEach((a,i)=>{a.x=a.homeX+(i-1)*16;a.y=a.homeY-34-i*5;a.decisionTimer=rand(.5,2.0);chooseIdleTarget(a);a.walkPhase=i*1.7;});
    if(ui.aiTest)ui.aiTest.textContent=IS_RENDER_HOST?'🧠 AI 立即想一下':'🧪 導演函數測試';
    if(ui.aiAuto)ui.aiAuto.textContent=IS_RENDER_HOST?(aiAuto?'⚡ AI 自動：開':'⚡ AI 自動：關'):'⚡ AI 自動：之後再接';
    if(ui.logLimit)ui.logLimit.value=String(logLimit);
    addLog('CUSTOMS AGENT TOWN 已啟動');
    sync();
    requestAnimationFrame(frame);

    try{
      await Promise.race([
        loadWorld(),
        new Promise((_,reject)=>setTimeout(()=>reject(new Error('world load timeout')),1800))
      ]);
      aiFurniture=sanitizeAiFurniture(aiFurniture);
      applyOfficeLayoutToAgents();
      agents.forEach((a,i)=>{if(!a.task){a.x=a.homeX+(i-1)*16;a.y=a.homeY-34-i*5;a.decisionTimer=rand(.5,2.0);chooseIdleTarget(a);a.walkPhase=i*1.7;}});
      saveWorld();
      addLog('生活資料已延續');
    }catch(_err){
      addLog('生活資料讀取較慢，先使用目前小鎮狀態');
    }
    if(aiAuto)aiAutoTimer=rand(8,22);
    if(IS_RENDER_HOST)setTimeout(()=>{pushTownState();pullTownWorld();pullTownPlan();refreshTownContext();},900);
  }
'''
    return html[:start] + boot + html[end:]
