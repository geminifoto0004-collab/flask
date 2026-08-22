"""Keep the town renderer alive even if one update subsystem throws.

The Render page could stay as a plain blue canvas because frame() called update()
before drawing anything. One runtime exception aborted the whole animation loop.
This patch makes update failures non-fatal and draws a first frame immediately.
"""


def patch_render_frame_safety(html: str) -> str:
    html = html.replace(
        "    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;update(dt);drawRoom();drawAtmosphere();",
        "    if(!running)return;let dt=Math.min(.05,(now-last)/1000)*speed;last=now;\n"
        "    try{update(dt);}catch(err){if(!window.__townFrameErrorShown){window.__townFrameErrorShown=true;addLog('動畫更新錯誤，畫面繼續運行：'+String(err&&err.message||err));}}\n"
        "    drawRoom();drawAtmosphere();",
        1,
    )

    html = html.replace(
        "    sync();\n    requestAnimationFrame(frame);",
        "    sync();\n"
        "    try{drawRoom();drawAtmosphere();}catch(err){addLog('第一幀繪製錯誤：'+String(err&&err.message||err));}\n"
        "    requestAnimationFrame(frame);",
        1,
    )
    return html
