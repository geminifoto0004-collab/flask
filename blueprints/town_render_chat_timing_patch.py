"""Make Render chat start promptly and keep the event log chronological."""


def patch_render_chat_timing(html: str) -> str:
    # Oldest event stays at the top; newest event appears at the bottom and the
    # log follows it automatically. This makes the AI execution timeline read in
    # the same order that events actually happened.
    html = html.replace(
        "const d=document.createElement('div'); d.textContent='> '+msg; ui.log.prepend(d);\n    while(ui.log.children.length>logLimit) ui.log.removeChild(ui.log.lastChild);",
        "const d=document.createElement('div'); d.textContent='> '+msg; ui.log.appendChild(d);\n    while(ui.log.children.length>logLimit) ui.log.removeChild(ui.log.firstChild);\n    ui.log.scrollTop=ui.log.scrollHeight;",
    )
    html = html.replace(
        "while(ui.log.children.length>logLimit)ui.log.removeChild(ui.log.lastChild);",
        "while(ui.log.children.length>logLimit)ui.log.removeChild(ui.log.firstChild);ui.log.scrollTop=ui.log.scrollHeight;",
    )

    # Once DeepSeek has already supplied real dialogue turns, do not make the
    # user wait up to eight seconds before hearing the first line. Characters
    # still attempt to walk together naturally, but after 2.2s the existing
    # fallback meeting position is used and the first line begins immediately.
    html = html.replace("timer:.4,started:false,done:false,waited:0", "timer:.12,started:false,done:false,waited:0")
    html = html.replace("chat.waited<8", "chat.waited<2.2")
    html = html.replace("chat.started=true;chat.timer=.5", "chat.started=true;chat.timer=.12")
    return html
