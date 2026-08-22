"""Depth-sort movable town actors and AI furniture on the Render page."""


def patch_render_depth(html: str) -> str:
    # Wall-mounted items stay in the background. Floor furniture is drawn later
    # together with characters according to Y, so walking in front/behind an
    # object looks natural instead of every AI object covering every person.
    html = html.replace(
        "    aiFurniture.filter(f=>f.type==='wall_frame'||f.type==='notice_board').forEach(drawAiFurniture);\n"
        "    aiFurniture.filter(f=>f.type!=='wall_frame'&&f.type!=='notice_board'&&f.type!=='custom_object').forEach(drawAiFurniture);\n"
        "    aiFurniture.filter(f=>f.type==='custom_object').forEach(drawAiCustomObject);\n\n"
        "    plantStates.forEach(drawLifePlant);",
        "    aiFurniture.filter(f=>f.type==='wall_frame'||f.type==='notice_board').forEach(drawAiFurniture);\n\n"
        "    plantStates.forEach(drawLifePlant);",
    )

    old_frame = (
        "    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;update(dt);drawRoom();drawAtmosphere();"
        "agents.filter(a=>isAgentOnDuty(a)||a.task).slice().sort((a,b)=>a.y-b.y).forEach(drawAgent);"
        "agents.filter(a=>(isAgentOnDuty(a)||a.task)&&a.chatTimer>0&&a.chatText).forEach(a=>bubble(a,a.chatText));"
        "humanVisitors.slice().sort((a,b)=>a.y-b.y).forEach(drawHumanVisitor);"
        "aiFurniture.filter(f=>f.type==='wall_frame'||f.type==='notice_board').forEach(drawAiFurniture);"
        "aiFurniture.filter(f=>f.type!=='wall_frame'&&f.type!=='notice_board'&&f.type!=='custom_object').forEach(drawAiFurniture);"
        "aiFurniture.filter(f=>f.type==='custom_object').forEach(drawAiCustomObject);requestAnimationFrame(frame);"
    )
    new_frame = (
        "    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;update(dt);drawRoom();drawAtmosphere();\n"
        "    const depthItems=[];\n"
        "    agents.filter(a=>isAgentOnDuty(a)||a.task).forEach(a=>depthItems.push({y:a.y,draw:()=>drawAgent(a)}));\n"
        "    humanVisitors.forEach(v=>depthItems.push({y:v.y,draw:()=>drawHumanVisitor(v)}));\n"
        "    aiFurniture.filter(f=>f.type!=='wall_frame'&&f.type!=='notice_board').forEach(f=>depthItems.push({y:Number(f.y)||0,draw:()=>f.type==='custom_object'?drawAiCustomObject(f):drawAiFurniture(f)}));\n"
        "    depthItems.sort((a,b)=>a.y-b.y).forEach(item=>item.draw());\n"
        "    agents.filter(a=>(isAgentOnDuty(a)||a.task)&&a.chatTimer>0&&a.chatText).forEach(a=>bubble(a,a.chatText));requestAnimationFrame(frame);"
    )
    html = html.replace(old_frame, new_frame)
    return html
