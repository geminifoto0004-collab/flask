document.addEventListener("DOMContentLoaded",function(){
  const root=document.getElementById("manualControls");
  if(!root)return;
  const key=root.dataset.apiKey||"";
  const add=document.getElementById("manualAdd");
  const minus=document.getElementById("manualMinus");
  const reset=document.getElementById("manualReset");
  const note=document.getElementById("manualNote");
  const url="/api/monitor/report/manual?api_key="+encodeURIComponent(key);
  const resetUrl="/api/monitor/report/reset-notification?api_key="+encodeURIComponent(key);
  let removing=false;
  let manualRows=[];

  function setNote(text){ if(note) note.textContent=text||""; }

  function markManualGroup(){
    document.querySelectorAll(".v-card,.um-card").forEach(function(card){
      const name=card.querySelector(".v-name,.um-vessel-name");
      if(!name)return;
      if((name.textContent||"").replace("🛳️","").trim()==="人工補入"){
        card.classList.add("manual-group");
        const icon=card.querySelector(".v-icon");
        if(icon)icon.style.display="none";
        name.textContent="人工補入";
      }
    });
  }

  function removeDeleteButtons(){
    document.querySelectorAll(".manual-inline-delete").forEach(function(b){b.remove();});
  }

  function applyDeleteButtons(){
    removeDeleteButtons();
    markManualGroup();
    if(!removing)return;
    const codes=new Set(manualRows.map(function(r){return r.container_no;}));
    document.querySelectorAll(".t-container,.um-container").forEach(function(el){
      const text=(el.textContent||"").trim().toUpperCase();
      let code="";
      codes.forEach(function(c){if(!code&&text.indexOf(c)===0)code=c;});
      if(!code)return;
      const btn=document.createElement("button");
      btn.type="button";
      btn.className="manual-inline-delete";
      btn.textContent="−";
      btn.style.cssText="margin-left:6px;border:0;border-radius:7px;background:#fee2e2;color:#991b1b;padding:2px 7px;cursor:pointer";
      btn.addEventListener("click",function(){change("DELETE",code);});
      el.appendChild(btn);
    });
  }

  async function load(){
    try{
      const r=await fetch(url,{cache:"no-store"});
      const j=await r.json();
      if(j.success){
        manualRows=j.rows||[];
        applyDeleteButtons();
      }
    }catch(_){}
  }

  async function change(method,code){
    setNote(method==="POST"?"核對中…":"更新中…");
    try{
      const r=await fetch(url,{
        method:method,
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({container_no:code})
      });
      const j=await r.json();
      if(!r.ok||!j.success){setNote("");alert(j.error||"Error");return;}
      manualRows=j.rows||[];
      applyDeleteButtons();
      setNote(method==="POST"?"已補入，正在重新檢查 ITI／通知":"已刪除，正在更新");
      setTimeout(function(){location.reload();},12000);
    }catch(_){
      setNote("");
      alert("Error");
    }
  }

  add.addEventListener("click",function(){
    const raw=prompt("Número de contenedor");
    if(raw===null)return;
    const code=raw.toUpperCase().replace(/[\s._-]/g,"");
    if(!/^[A-Z]{4}[0-9]{7}$/.test(code)){alert("Número inválido");return;}
    change("POST",code);
  });

  minus.addEventListener("click",function(){
    removing=!removing;
    minus.classList.toggle("active",removing);
    setNote(removing?"點人工補入櫃旁的 − 刪除":"");
    applyDeleteButtons();
  });

  reset.addEventListener("click",async function(){
    if(!confirm("重置防噪紀錄？下一次監控檢查會重新發送通知。"))return;
    setNote("重置中…");
    try{
      const r=await fetch(resetUrl,{method:"POST"});
      const j=await r.json();
      if(!r.ok||!j.success){setNote("");alert(j.error||j.message||"Error");return;}
      setNote("已重置；下一次檢查會重新通知");
    }catch(_){setNote("");alert("Error");}
  });

  markManualGroup();
  load();
});