"""Make forced on-duty officers visibly enter from outside instead of teleporting."""


def patch_render_shift_walk(html: str) -> str:
    html = html.replace(
        "function isAgentOnDuty(a){if(a?.manualOffDuty&&!a?.task)return false;return !isIquiqueNight()||a.index===nightShiftIndex()||!!a.task;}",
        "function isAgentOnDuty(a){if(a?.manualOffDuty&&!a?.task)return false;if(a?.manualOnDuty)return true;return !isIquiqueNight()||a.index===nightShiftIndex()||!!a.task;}",
        1,
    )
    html = html.replace(
        "careerState:a.careerState,manualOffDuty:!!a.manualOffDuty,generation:a.generation,state:a.state",
        "careerState:a.careerState,manualOffDuty:!!a.manualOffDuty,manualOnDuty:!!a.manualOnDuty,generation:a.generation,state:a.state",
        1,
    )
    html = html.replace(
        "        if(typeof saved.manualOffDuty==='boolean')a.manualOffDuty=saved.manualOffDuty;",
        "        if(typeof saved.manualOffDuty==='boolean')a.manualOffDuty=saved.manualOffDuty;\n        if(typeof saved.manualOnDuty==='boolean')a.manualOnDuty=saved.manualOnDuty;",
        1,
    )
    html = html.replace(
        "      a.manualOffDuty=true;a.state='offDuty';a.path=[];a.pathTarget='';a.chatText='';a.chatTimer=0;a.intentLabel='';a.intentUntil=0;",
        "      a.manualOnDuty=false;a.manualOffDuty=true;a.state='offDuty';a.path=[];a.pathTarget='';a.chatText='';a.chatTimer=0;a.intentLabel='';a.intentUntil=0;",
        1,
    )
    html = html.replace(
        "      a.manualOffDuty=false;a.state='idle';a.x=a.homeX;a.y=a.homeY;a.timer=.2;a.decisionTimer=.2;\n      addLog('AI 安排 '+agentLabel(a)+' 回來上班');saveWorld();",
        "      a.manualOffDuty=false;a.manualOnDuty=true;a.x=320;a.y=300;a.path=[];a.pathTarget='';a.state='idleWalk';a.idle='desk';a.idleAction='walk';a.targetX=a.homeX;a.targetY=a.homeY;a.timer=.2;a.decisionTimer=999;a.intentLabel='半夜被叫回來上班';a.intentUntil=Date.now()+45000;\n      addLog('AI 安排 '+agentLabel(a)+' 從外面走進辦公室上班');saveWorld();",
        1,
    )
    return html
