/* PDF groups extend the existing order view. No original PDF requests. */
(() => {
'use strict';
const paths={
 document:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h6',
 clock:'M12 8v4l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 warning:'M12 8v5 M12 17h.01 M10.3 3.9 1.8 18.5A1.7 1.7 0 0 0 3.3 21h17.4a1.7 1.7 0 0 0 1.5-2.5L13.7 3.9a2 2 0 0 0-3.4 0',
 prev:'m15 18-6-6 6-6',next:'m9 18 6-6-6-6',close:'m6 6 12 12 M18 6 6 18',retry:'M20 7v5h-5 M4 17v-5h5 M6.1 7a7 7 0 0 1 11.6-2L20 8 M4 16l2.3 3a7 7 0 0 0 11.6-2'
};
function svg(name){const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('viewBox','0 0 24 24');n.setAttribute('fill','none');n.setAttribute('stroke','currentColor');n.setAttribute('stroke-width','1.7');n.setAttribute('stroke-linecap','round');n.setAttribute('stroke-linejoin','round');n.setAttribute('aria-hidden','true');const p=document.createElementNS(n.namespaceURI,'path');p.setAttribute('d',paths[name]);n.append(p);return n}
function iconButton(name,label){const n=document.createElement('button');n.type='button';n.setAttribute('aria-label',label);n.title=label;n.append(svg(name));return n}
function init(root) {
 if(root.dataset.pdfBound)return; root.dataset.pdfBound='1';
 let rows; try{rows=JSON.parse(root.dataset.pdfJson||'[]').filter(x=>x.media_type==='pdf_page')}catch(_){return}
 const groups=new Map(); rows.forEach(r=>{const id=r.document_id||r.pdf_document_id||r.name.replace(/ · .*/, ''); if(!groups.has(id))groups.set(id,[]);groups.get(id).push(r)});
 let metadata=[];try{metadata=JSON.parse(root.dataset.pdfMetadata||'[]')}catch(_){}
 metadata.forEach(d=>{if(!groups.has(d.id))groups.set(d.id,[])});
 const list=root.querySelector('[data-pdf-list]'), stage=root.querySelector('[data-pdf-stage]');
 let active=[], index=0, opener=null, viewer=null;
 function badge(parent,row){const b=document.createElement('span');b.className='media-new';b.dataset.mediaUploadedAt=String(row.uploaded_at_epoch||0);b.textContent='NEW~';b.hidden=true;parent.append(b)}
 const text=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n};
 function label(r){return `${r.document_name||r.original_filename||r.name} · ${r.pdf_page_number} / ${r.pdf_page_count}`}
 function image(url,alt,lazy=false){const img=new Image();img.alt=alt;img.loading=lazy?'lazy':'eager';img.decoding='async';img.src=url;return img}
 function show(){const r=active[index]; if(!r)return;stage.hidden=false;stage.replaceChildren();
  const title=text('div',label(r));title.className='pdf-page-label';badge(title,r);stage.append(title);
  const button=document.createElement('button');button.type='button';button.className='pdf-open-page';button.setAttribute('aria-label',label(r));button.append(image(r.preview_url||r.url,label(r)));button.onclick=()=>open(button);stage.append(button);
  const nav=document.createElement('div');nav.className='pdf-page-nav';
  [-1,1].forEach(delta=>{const b=iconButton(delta<0?'prev':'next',delta<0?'Anterior':'Siguiente');b.disabled=index+delta<0||index+delta>=active.length;b.onclick=()=>{index+=delta;show()};nav.append(b)});stage.append(nav);
 }
 function paintViewer(){const r=active[index];viewer.querySelector('[data-pdf-title]').textContent=label(r);
  const area=viewer.querySelector('[data-pdf-view-image]');area.replaceChildren();const img=image(r.url,label(r));area.append(img);
  img.onerror=()=>{const retry=iconButton('retry','Reintentar');retry.onclick=()=>{img.src=r.url;retry.remove()};area.append(retry)};
  viewer.querySelector('[data-pdf-prev]').disabled=index===0;viewer.querySelector('[data-pdf-next]').disabled=index===active.length-1;
 }
 function close(){if(!viewer)return;viewer.remove();viewer=null;document.removeEventListener('keydown',keys,true);opener?.focus();}
 function move(delta){if(index+delta<0||index+delta>=active.length)return;index+=delta;paintViewer();show()}
 function keys(e){if(['Escape','ArrowLeft','ArrowRight'].includes(e.key)){e.stopImmediatePropagation();e.preventDefault()}if(e.key==='Escape')close();else if(e.key==='ArrowLeft')move(-1);else if(e.key==='ArrowRight')move(1)}
 function open(button){opener=button;viewer=document.createElement('div');viewer.className='pdf-full-view';viewer.setAttribute('role','dialog');viewer.setAttribute('aria-modal','true');viewer.setAttribute('aria-label','Documento PDF');
  viewer.innerHTML='<div class="pdf-view-head"><span data-pdf-title></span><button type="button" data-pdf-close aria-label="Cerrar"></button></div><div class="pdf-view-image" data-pdf-view-image></div><div class="pdf-page-nav"><button type="button" data-pdf-prev aria-label="Anterior"></button><button type="button" data-pdf-next aria-label="Siguiente"></button></div>';
  document.body.append(viewer);[['close','close'],['prev','prev'],['next','next']].forEach(([key,name])=>viewer.querySelector(`[data-pdf-${key}]`).append(svg(name)));viewer.querySelector('[data-pdf-close]').onclick=close;viewer.querySelector('[data-pdf-prev]').onclick=()=>move(-1);viewer.querySelector('[data-pdf-next]').onclick=()=>move(1);
  let touch=null, multi=false;const area=viewer.querySelector('[data-pdf-view-image]');
  area.addEventListener('touchstart',e=>{multi=e.touches.length!==1;touch=!multi?{x:e.touches[0].clientX,y:e.touches[0].clientY}:null},{passive:true});
  area.addEventListener('touchmove',e=>{if(e.touches.length>1)multi=true},{passive:true});
  area.addEventListener('touchend',e=>{if(!touch||multi||(window.visualViewport?.scale||1)>1.02)return;const t=e.changedTouches[0],dx=t.clientX-touch.x,dy=t.clientY-touch.y;touch=null;if(Math.abs(dx)>70&&Math.abs(dx)>Math.abs(dy)*1.8)move(dx<0?1:-1)},{passive:true});
  document.addEventListener('keydown',keys,true);paintViewer();viewer.querySelector('[data-pdf-close]').focus();
 }
 groups.forEach((pages,id)=>{pages.sort((a,b)=>a.pdf_page_number-b.pdf_page_number);const doc=metadata.find(d=>d.id===id)||{}, first=pages[0]||{document_name:doc.filename,name:doc.filename,uploaded_at:doc.uploaded_at,pdf_page_count:doc.page_count};
  const button=document.createElement('button');button.type='button';button.className='pdf-document-row';
  const icon=document.createElement('span');icon.className='pdf-file-icon';icon.append(svg('document'));button.append(icon);
  const copy=document.createElement('span');copy.className='pdf-file-copy';copy.append(text('strong',first.document_name||first.name));
  const date=(first.document_date||first.uploaded_at||'').slice(0,10),count=Number(first.pdf_page_count)||0;
  copy.append(text('small',[date,count?String(count):''].filter(Boolean).join(' · ')));button.append(copy);badge(button,first);
  const state=document.createElement('span');state.className='pdf-file-state';
  if(!pages.length){const failed=doc.status==='failed'||doc.status==='missing';button.disabled=true;state.append(svg(failed?'warning':'clock'));state.title=failed?'Vista previa no disponible':'Preparando vista previa';button.setAttribute('aria-label',`${first.document_name||first.name}: ${state.title}`)}
  else{state.append(svg('next'));button.setAttribute('aria-label',first.document_name||first.name)}
  button.append(state);
  button.onclick=()=>{active=pages;index=0;list.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));show()};button.setAttribute('aria-pressed','false');list.append(button);
 });
 if(!groups.size)root.hidden=true;
}
function scan(){document.querySelectorAll('[data-pdf-documents]').forEach(init)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scan);else scan();
new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});
})();
