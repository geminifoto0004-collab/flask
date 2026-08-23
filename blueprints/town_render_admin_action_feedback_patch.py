"""Make admin story commands visibly execute transient actions on Render."""


def patch_render_admin_action_feedback(html: str) -> str:
    html = html.replace(
        "promptWrap.innerHTML='<span>AI 指令</span><input id=\"town-world-prompt-input\" type=\"text\" maxlength=\"180\" placeholder=\"例如：道路來一台車、Oscar 帶晚餐來探 MIA\"><button id=\"town-world-prompt-run\" type=\"button\">✨ 執行</button>';",
        "promptWrap.innerHTML='<span>AI 劇情</span><input id=\"town-world-prompt-input\" type=\"text\" maxlength=\"300\" placeholder=\"告訴 AI 核心劇情；沒指定的細節讓它自己導演\"><button id=\"town-world-prompt-run\" type=\"button\">✨ 執行</button>';",
        1,
    )
    html = html.replace(
        "log('AI 已收到指令：'+prompt+'（已送出，不必重按）');",
        "log('AI 已收到劇情種子：'+prompt+'（明確指定的核心會保留，其餘由 AI 導演）');",
        1,
    )
    old = """      if(actions.length)log('AI 真正下令：'+actions.map(a=>String(a.type||'動作')+(a.name?' '+a.name:'')+(a.target?' → '+a.target:'')).join('；'));
      if(data.duplicate)log('這個 command_id 已執行過，本次沒有重複建立物件');"""
    new = """      if(data.thought)log('AI 導演改編：'+String(data.thought).slice(0,300));
      if(actions.length){
        log('AI 真正執行：'+actions.map(a=>String(a.type||'動作')+(a.agent?' '+a.agent:'')+(a.name?' '+a.name:'')+(a.action?' · '+a.action:'')+(a.target?' → '+a.target:'')+(a.group?' · '+a.group:'')).join('；'));
        try{if(typeof applyAiTownActions==='function')applyAiTownActions(actions);}catch(err){log('AI 即時動作顯示失敗：'+String(err&&err.message||err));}
      }
      if(data.director_note)log('AI 優化：'+String(data.director_note).slice(0,180));
      if(data.duplicate)log('這個 command_id 已執行過，本次沒有重複建立物件');"""
    html = html.replace(old, new, 1)
    return html
