/* PDF groups extend the existing order view. No original PDF requests. */
(() => {
'use strict';
function init(root) {
 if(root.dataset.pdfBound)return; root.dataset.pdfBound='1';
 let rows; try{rows=JSON.parse(root.dataset.pdfJson||'[]').filter(x=>x.media_type==='pdf_page')}catch(_){return}
 const groups=new Map(); rows.forEach(r=>{const id=r.document_id||r.pdf_document_id||r.name.replace(/ · .*/, ''); if(!groups.has(id))groups.set(id,[]);groups.get(id).push(r)});
 let metadata=[];try{metadata=JSON.parse(root.dataset.pdfMetadata||'[]')}catch(_){}
 metadata.forEach(d=>{if(!groups.has(d.id))groups.set(d.id,[])});
 const list=root.querySelector('[data-pdf-list]'), stage=root.querySelector('[data-pdf-stage]');
 let active=[], index=0, opener=null, viewer=null;
 const text=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n};
 function label(r){return `${r.document_name||r.original_filename||r.name} · Página ${r.pdf_page_number} de ${r.pdf_page_count}`}
 function image(url,alt,lazy=false){const img=new Image();img.alt=alt;img.loading=lazy?'lazy':'eager';img.decoding='async';img.src=url;return img}
 function show(){const r=active[index]; if(!r)return;stage.replaceChildren();
  const title=text('div',label(r));title.className='pdf-page-label';stage.append(title);
  const button=document.createElement('button');button.type='button';button.className='pdf-open-page';button.setAttribute('aria-label',label(r));button.append(image(r.preview_url||r.url,label(r)));button.onclick=()=>open(button);stage.append(button);
  const nav=document.createElement('div');nav.className='pdf-page-nav';
  [-1,1].forEach(delta=>{const b=text('button',delta<0?'‹ Anterior':'Siguiente ›');b.type='button';b.disabled=index+delta<0||index+delta>=active.length;b.onclick=()=>{index+=delta;show()};nav.append(b)});stage.append(nav);
 }
 function paintViewer(){const r=active[index];viewer.querySelector('[data-pdf-title]').textContent=label(r);
  const area=viewer.querySelector('[data-pdf-view-image]');area.replaceChildren();const img=image(r.url,label(r));area.append(img);
  img.onerror=()=>{const retry=text('button','Reintentar');retry.type='button';retry.onclick=()=>{img.src=r.url;retry.remove()};area.append(retry)};
  viewer.querySelector('[data-pdf-prev]').disabled=index===0;viewer.querySelector('[data-pdf-next]').disabled=index===active.length-1;
 }
 function close(){if(!viewer)return;viewer.remove();viewer=null;document.removeEventListener('keydown',keys,true);opener?.focus();}
 function move(delta){if(index+delta<0||index+delta>=active.length)return;index+=delta;paintViewer();show()}
 function keys(e){if(['Escape','ArrowLeft','ArrowRight'].includes(e.key)){e.stopImmediatePropagation();e.preventDefault()}if(e.key==='Escape')close();else if(e.key==='ArrowLeft')move(-1);else if(e.key==='ArrowRight')move(1)}
 function open(button){opener=button;viewer=document.createElement('div');viewer.className='pdf-full-view';viewer.setAttribute('role','dialog');viewer.setAttribute('aria-modal','true');viewer.setAttribute('aria-label','Documento PDF');
  viewer.innerHTML='<div class="pdf-view-head"><span data-pdf-title></span><button type="button" data-pdf-close aria-label="Cerrar">✕</button></div><div class="pdf-view-image" data-pdf-view-image></div><div class="pdf-page-nav"><button type="button" data-pdf-prev>‹ Anterior</button><button type="button" data-pdf-next>Siguiente ›</button></div>';
  document.body.append(viewer);viewer.querySelector('[data-pdf-close]').onclick=close;viewer.querySelector('[data-pdf-prev]').onclick=()=>move(-1);viewer.querySelector('[data-pdf-next]').onclick=()=>move(1);
  let touch=null, multi=false;const area=viewer.querySelector('[data-pdf-view-image]');
  area.addEventListener('touchstart',e=>{multi=e.touches.length!==1;touch=!multi?{x:e.touches[0].clientX,y:e.touches[0].clientY}:null},{passive:true});
  area.addEventListener('touchmove',e=>{if(e.touches.length>1)multi=true},{passive:true});
  area.addEventListener('touchend',e=>{if(!touch||multi||(window.visualViewport?.scale||1)>1.02)return;const t=e.changedTouches[0],dx=t.clientX-touch.x,dy=t.clientY-touch.y;touch=null;if(Math.abs(dx)>70&&Math.abs(dx)>Math.abs(dy)*1.8)move(dx<0?1:-1)},{passive:true});
  document.addEventListener('keydown',keys,true);paintViewer();viewer.querySelector('[data-pdf-close]').focus();
 }
 groups.forEach((pages,id)=>{pages.sort((a,b)=>a.pdf_page_number-b.pdf_page_number);const doc=metadata.find(d=>d.id===id)||{}, first=pages[0]||{document_name:doc.filename,name:doc.filename,uploaded_at:doc.uploaded_at,pdf_page_count:doc.page_count};
  const button=document.createElement('button');button.type='button';button.className='pdf-document-row';
  if(first.preview_url||first.url){const cover=image(first.preview_url||first.url,first.document_name||first.name,true);cover.loading='lazy';button.append(cover)}
  const copy=document.createElement('span');copy.append(text('strong',first.document_name||first.name));copy.append(text('small',`${first.document_date?'Fecha del doc.: '+first.document_date:'Subido: '+(first.uploaded_at||'—').slice(0,10)} · ${first.pdf_page_count} páginas`));button.append(copy);
  if(!pages.length){button.disabled=true;copy.append(text('small',doc.status==='failed'||doc.status==='missing'?'Vista previa no disponible; pendiente de revisión':'Preparando vista previa…'))}else if(pages.length<first.pdf_page_count){copy.append(text('small','Sincronizando páginas…'))}
  button.onclick=()=>{active=pages;index=0;list.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));show()};button.setAttribute('aria-pressed','false');list.append(button);
 });
 if(!groups.size)root.hidden=true;
}
function scan(){document.querySelectorAll('[data-pdf-documents]').forEach(init)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scan);else scan();
new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});
})();
