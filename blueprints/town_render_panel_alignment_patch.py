"""Keep the Render dialogue panel aligned with the black game frame.

The older dialogue patch wrapped the whole app, so the right panel started beside
HUD/results instead of beside the game canvas. This post-patch safely moves only
the panel next to .game-wrap and pins its height to that frame. It does not touch
the animation loop or game logic.
"""


def patch_render_panel_alignment(html: str) -> str:
    css = r'''
<style id="town-panel-alignment-style">
#town-game-chat-row{display:flex;align-items:flex-start;justify-content:center;gap:0;width:100%;min-width:0}
#town-game-chat-row>.game-wrap{flex:1 1 auto;min-width:0}
#town-game-chat-row>#town-side-panel{flex:0 0 360px;width:360px;max-width:360px;min-height:0;margin:0!important;align-self:flex-start;box-sizing:border-box}
#town-side-panel #town-dialogue-list{min-height:0;overflow-y:auto!important;overflow-x:hidden!important;scrollbar-gutter:stable;overscroll-behavior:contain}
@media(max-width:1180px){
  #town-game-chat-row{display:block}
  #town-game-chat-row>#town-side-panel{width:100%;max-width:none;height:320px!important;border-left:2px solid #1a2028;border-top:0}
}
</style>
'''
    js = r'''
<script id="town-panel-alignment-runtime">
(()=>{
  function alignTownDialoguePanel(){
    const app=document.getElementById('customs-sim');
    const game=app&&app.querySelector('.game-wrap');
    const panel=document.getElementById('town-side-panel');
    if(!app||!game||!panel)return;

    const oldDock=document.getElementById('town-dock-layout');
    if(oldDock&&oldDock.contains(app)){
      const parent=oldDock.parentNode;
      if(parent){parent.insertBefore(app,oldDock);oldDock.remove();}
    }

    let row=document.getElementById('town-game-chat-row');
    if(!row){
      row=document.createElement('div');
      row.id='town-game-chat-row';
      game.parentNode.insertBefore(row,game);
      row.appendChild(game);
    }
    if(panel.parentNode!==row)row.appendChild(panel);

    const sync=()=>{
      if(window.matchMedia('(max-width:1180px)').matches){panel.style.height='320px';return;}
      const h=Math.round(game.getBoundingClientRect().height);
      if(h>0)panel.style.height=h+'px';
      const list=panel.querySelector('#town-dialogue-list');
      if(list)requestAnimationFrame(()=>{list.scrollTop=list.scrollHeight;});
    };
    sync();
    requestAnimationFrame(sync);
    setTimeout(sync,80);
    setTimeout(sync,350);
    if('ResizeObserver' in window&&!panel.__townAligned){
      panel.__townAligned=true;
      new ResizeObserver(sync).observe(game);
      window.addEventListener('resize',sync);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(alignTownDialoguePanel,0),{once:true});
  else setTimeout(alignTownDialoguePanel,0);
})();
</script>
'''
    if 'town-panel-alignment-style' not in html:
        html = html.replace('</head>', css + '</head>', 1) if '</head>' in html else css + html
    if 'town-panel-alignment-runtime' not in html:
        html = html.replace('</body>', js + '</body>', 1) if '</body>' in html else html + js
    return html
