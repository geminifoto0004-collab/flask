/* Shared photo/PDF-page viewer. Uses only already-authorized share image URLs. */
(() => {
'use strict';
const NS='http://www.w3.org/2000/svg';
const paths={photo:'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1 M3 16l5-5 5 5 3-3 5 5 M9 7h.01',
 info:'M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 all:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 document:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h6',
 pages:'M8 3h12v15H8z M4 7v14h12',up:'M12 20V4 M7 9l5-5 5 5',
 eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
 eyeOff:'m3 3 18 18 M10.6 5.1C17 4 22 12 22 12s-1.5 2.6-4.2 4.6 M6.3 6.3C3.6 8.3 2 12 2 12s4 7 10 7c1.7 0 3.2-.5 4.5-1.2 M10 10a3 3 0 0 0 4 4',
 prev:'m15 18-6-6 6-6',next:'m9 18 6-6-6-6',close:'m6 6 12 12 M18 6 6 18',
 retry:'M20 7v5h-5 M4 17v-5h5 M6.1 7a7 7 0 0 1 11.6-2L20 8 M4 16l2.3 3a7 7 0 0 0 11.6-2',
 clock:'M12 8v4l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',warning:'M12 8v5 M12 17h.01 M12 2 1 21h22z'};
function el(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n}
function icon(name){const n=document.createElementNS(NS,'svg');for(const [k,v] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))n.setAttribute(k,v);const p=document.createElementNS(NS,'path');p.setAttribute('d',paths[name]);n.append(p);return n}
function button(name,label,cls,fn){const b=el('button',cls);b.type='button';b.title=label;b.setAttribute('aria-label',label);if(name)b.append(icon(name));b.onclick=fn;return b}
function parse(raw){try{const a=JSON.parse(raw||'[]');return Array.isArray(a)?a:[]}catch(_){return []}}
function dateText(raw){const m=String(raw||'').match(/^(\d{4})-(\d{2})-(\d{2})/);return m?`${m[3]}-${m[2]}-${m[1]}`:'—'}
function imageURL(row){const raw=String(row.url||row.preview_url||'');try{const url=new URL(raw,location.href);return ['https:','http:'].includes(url.protocol)?url.href:''}catch(_){return ''}}
function mount(root,options={}){
 if(root.__orderDetail)return root.__orderDetail;
 const rows=parse(root.dataset.mediaJson).filter(r=>imageURL(r));
 const photos=rows.filter(r=>r.media_type!=='pdf_page');
 const docs=new Map();
 parse(root.dataset.documentsJson).forEach(d=>docs.set(String(d.id||d.content_hash||d.filename),{...d,pages:[]}));
 rows.filter(r=>r.media_type==='pdf_page').forEach(r=>{const id=String(r.document_id||r.pdf_document_id||r.document_name||r.name);if(!docs.has(id))docs.set(id,{id,filename:r.document_name||r.name,uploaded_at:r.uploaded_at,pages:[]});docs.get(id).pages.push(r)});
 docs.forEach(d=>d.pages.sort((a,b)=>Number(a.pdf_page_number)-Number(b.pdf_page_number)));
 const groups=[...docs.values()].sort((a,b)=>String(b.uploaded_at||'').localeCompare(String(a.uploaded_at||'')));
 const all=[...photos,...groups.flatMap(d=>d.pages)];
 let source=photos.length?'photos':groups.find(d=>d.pages.length)||'all';
 let seed=options.initialImage||'';
 let index=Math.max(0,Math.min(photos.length-1,Number(options.initialIndex)||0)),names=false,full=null,destroyed=false;
 if(options.initialUrl){const selected=rows.find(r=>imageURL(r)===imageURL({url:options.initialUrl}));if(selected){source=selected.media_type==='pdf_page'?groups.find(d=>d.pages.includes(selected)):'photos';index=(source==='photos'?photos:source.pages).indexOf(selected);}}
 const seq=()=>source==='all'?all:source==='photos'?photos:source.pages;
 const current=()=>seq()[index];
 const isDesktop=()=>matchMedia('(min-width:1024px) and (hover:hover) and (pointer:fine)').matches;
 root.className='order-detail';root.dataset.detailVersion='147';
 const head=el('div','od-head');if(options.head)head.append(options.head);
 head.append(button('close','Cerrar','od-close',options.close||(()=>document.getElementById('guestBackToOrders')?.click())));
 const view=el('div','od-view'),area=el('div','od-image'),caption=el('div','od-caption'),dots=el('div','od-dots');
 const prev=button('prev','Anterior','od-arrow od-prev',()=>move(-1)),next=button('next','Siguiente','od-arrow od-next',()=>move(1));
 view.append(area,caption,dots,prev,next);
 const tabs=el('div','od-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Pedido');
 const mediaTab=button('photo','Archivos','',()=>tab(false)),infoTab=button('info','Información del pedido','',()=>tab(true));
 tabs.append(mediaTab,infoTab);
 const list=el('div','od-list'),information=el('div','od-information');
 (options.panels||[]).forEach(p=>information.append(p));
 const pane=el('div','od-pane');pane.append(list,information);root.replaceChildren(head,view,tabs,pane);
 function tab(info){information.hidden=!info;list.hidden=info;[mediaTab,infoTab].forEach((b,i)=>{b.setAttribute('role','tab');b.setAttribute('aria-selected',String(Boolean(i)===info));b.tabIndex=Boolean(i)===info?0:-1});}
 tabs.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const info=infoTab.getAttribute('aria-selected')!=='true';tab(info);(info?infoTab:mediaTab).focus()}});
 function badge(parent,epoch){const b=el('span','media-new','NEW~');b.dataset.mediaUploadedAt=String(epoch||0);b.hidden=true;parent.append(b)}
 function stamp(row){const d=groups.find(g=>g.pages.includes(row));const actual=row.document_date||d?.document_date;const s=el('span','od-date',dateText(actual||row.uploaded_at||d?.uploaded_at));if(!actual){s.prepend(icon('up'));s.title='Fecha del archivo en el sistema local'}return s}
 function description(row,fullscreen=false){const out=el('span','od-description');if(!row)return out;const pdf=row.media_type==='pdf_page';const n=pdf?Number(row.pdf_page_number)||1:photos.indexOf(row)+1,total=pdf?Number(row.pdf_page_count)||seq().length:photos.length;
  const page=el('span','od-page',pdf?`Página ${n} de ${total}`:`${n} / ${total}`);if(!pdf)page.prepend(icon('photo'));out.append(page,stamp(row));
  if(pdf&&(names||fullscreen))out.append(el('span','od-filename',row.document_name||row.name||'PDF'));return out;
 }
 function select(value){source=value;index=0;tab(false);paint();}
 const selections=[];
 function groupRow(value,name,count,date,epoch,disabled,state){const b=button(null,name,'od-row',()=>select(value));b.disabled=disabled;b.setAttribute('aria-pressed','false');
  const box=el('span','od-icon');box.append(icon(state||(value==='photos'?'photo':value==='all'?'all':'document')));
  const copy=el('span','od-copy'),primary=el('strong','',date||String(count));copy.append(primary);
  if(value!=='photos'&&value!=='all'){const small=el('small');small.append(icon('pages'),document.createTextNode(count?String(count):state==='warning'?'Vista previa no disponible':'Preparando vista previa'));copy.append(small)}
  b.append(box,copy);if(epoch)badge(b,epoch);selections.push({b,value,primary,date,name});return b;
 }
 const whole=el('div','od-group');whole.append(groupRow('all','Ver todo',all.length));list.append(whole);
 if(photos.length){const g=el('div','od-group');g.append(groupRow('photos','Fotos del pedido',photos.length));list.append(g)}
 const docHeading=el('div','od-doc-heading');docHeading.append(icon('document'),el('span','',String(groups.length)));
 const eye=button('eyeOff','Mostrar nombres de archivo','od-eye',()=>{names=!names;eye.replaceChildren(icon(names?'eye':'eyeOff'));eye.setAttribute('aria-pressed',String(names));eye.title=names?'Ocultar nombres de archivo':'Mostrar nombres de archivo';eye.setAttribute('aria-label',eye.title);updateSelections();caption.replaceChildren(description(current()));if(full)full.title.replaceChildren(description(current(),true))});
 eye.setAttribute('aria-pressed','false');docHeading.append(eye);
 if(groups.length){list.append(docHeading);const g=el('div','od-group');groups.forEach(d=>{const first=d.pages[0]||{},date=stamp({...first,uploaded_at:first.uploaded_at||d.uploaded_at,document_date:first.document_date||d.document_date}).textContent;
  const b=groupRow(d,d.filename||first.document_name||'PDF',Number(d.page_count)||Number(first.pdf_page_count)||d.pages.length,(d.document_date?'':'↑ ')+date,first.uploaded_at_epoch,!d.pages.length,!d.pages.length?(d.status==='failed'||d.status==='missing'?'warning':'clock'):null);g.append(b)});list.append(g)}
 if(!all.length)list.prepend(el('p','od-empty','Este pedido no tiene imágenes disponibles'));
 function updateSelections(){selections.forEach(({b,value,primary,date,name})=>{b.setAttribute('aria-pressed',String(value===source));b.classList.toggle('od-here',source==='all'&&value!=='all'&&(value==='photos'?photos.includes(current()):value.pages.includes(current())));if(date){primary.textContent=names?name:date;primary.title=name}})}
 function loadInto(target,row,zoom=false){target.replaceChildren();target.classList.remove('od-zoomed');if(!row){target.append(el('p','od-empty','Sin imágenes'));return}
  if(seed&&target===area){const base=new Image();base.src=seed;base.alt='';base.dataset.odPlaceholder='';base.setAttribute('aria-hidden','true');target.append(base);seed='';}
  const img=new Image();img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label',zoom?'Imagen ampliada':'Abrir imagen');img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();img.click()}};img.alt=row.document_name||row.name||'Imagen';img.decoding='async';const url=imageURL(row);img.onload=()=>{if(!destroyed&&target.contains(img)){img.classList.add('od-ready');target.querySelector('[data-od-placeholder]')?.remove()}};img.onerror=()=>{if(!target.contains(img))return;const retry=button('retry','Reintentar','od-retry',()=>{img.removeAttribute('src');img.src=url;retry.remove()});retry.append(document.createTextNode('Reintentar'));target.append(retry)};
  if(zoom)img.onclick=()=>{if(isDesktop())target.classList.toggle('od-zoomed')};else img.onclick=()=>openFull();target.append(img);img.src=url;
 }
 function paint(){updateSelections();caption.replaceChildren(description(current()));prev.disabled=index<=0;next.disabled=index>=seq().length-1;loadInto(area,current());
  dots.replaceChildren();const length=seq().length,start=Math.max(0,Math.min(index-20,length-41));for(let i=start;i<Math.min(length,start+41);i++){const b=button(null,`Página ${i+1}`,'od-dot',()=>{index=i;paint()});b.classList.toggle('active',i===index);if(i===index)b.setAttribute('aria-current','true');dots.append(b)}dots.hidden=length<2;
  if(full){full.title.replaceChildren(description(current(),true));loadInto(full.area,current(),true);full.prev.disabled=prev.disabled;full.next.disabled=next.disabled}
 }
 function move(delta){if(index+delta<0||index+delta>=seq().length)return;index+=delta;paint()}
 function swipe(node){let touch=null,multi=false,drag=null,suppress=0;
  node.addEventListener('touchstart',e=>{multi=e.touches.length!==1;touch=multi?null:{x:e.touches[0].clientX,y:e.touches[0].clientY}},{passive:true});
  node.addEventListener('touchmove',e=>{if(e.touches.length!==1)multi=true},{passive:true});
  node.addEventListener('touchend',e=>{if(!touch||multi||(window.visualViewport?.scale||1)>1.02)return;const t=e.changedTouches[0],dx=t.clientX-touch.x,dy=t.clientY-touch.y;touch=null;if(Math.abs(dx)>65&&Math.abs(dx)>Math.abs(dy)*1.8){suppress=Date.now()+500;move(dx<0?1:-1)}},{passive:true});
  node.addEventListener('touchcancel',()=>{touch=null;multi=true},{passive:true});
  node.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'&&e.button===0&&!node.classList.contains('od-zoomed'))drag={x:e.clientX,y:e.clientY}});
  node.addEventListener('pointerup',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag=null;if(Math.abs(dx)>55&&Math.abs(dx)>Math.abs(dy)*1.8){suppress=Date.now()+500;move(dx<0?1:-1)}});
  node.addEventListener('pointerleave',()=>{drag=null});node.addEventListener('dragstart',e=>e.preventDefault());
  node.addEventListener('click',e=>{if(Date.now()<suppress){e.preventDefault();e.stopImmediatePropagation()}},true);
 }
 function closeFull(){if(!full)return;full.root.remove();full=null;document.body.classList.remove('od-full-open');area.querySelector('img')?.focus();}
 function openFull(){if(full||!current())return;const overlay=el('div','od-full');overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','Imagen del pedido');
  const h=el('div','od-full-head'),title=el('div'),close=button('close','Cerrar','od-close',closeFull),a=el('div','od-full-image');h.append(title,close);
  const p=button('prev','Anterior','od-arrow od-prev',()=>move(-1)),n=button('next','Siguiente','od-arrow od-next',()=>move(1));overlay.append(h,a,p,n);document.body.append(overlay);document.body.classList.add('od-full-open');full={root:overlay,title,area:a,prev:p,next:n};swipe(a);
  title.append(description(current(),true));loadInto(a,current(),true);p.disabled=prev.disabled;n.disabled=next.disabled;close.focus();
 }
 function keys(e){if(!root.isConnected)return;if(e.key==='Tab'&&full){const nodes=[...full.root.querySelectorAll('button:not(:disabled)')],first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}return}if(e.target.closest('input,textarea,select'))return;
  if(e.key==='Escape'&&full){e.preventDefault();e.stopImmediatePropagation();closeFull()}else if((full||root.contains(document.activeElement)||root.closest('.guest-desktop-detail-overlay:not([hidden])'))&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();e.stopPropagation();move(e.key==='ArrowLeft'?-1:1)}
 }
 swipe(area);document.addEventListener('keydown',keys,true);tab(false);paint();
 const api={currentURL:()=>current()?imageURL(current()):'',destroy(){destroyed=true;closeFull();document.removeEventListener('keydown',keys,true);delete root.__orderDetail;root.replaceChildren()},root};root.__orderDetail=api;return api;
}
window.OrderGuestDetail={mount};
function init(){document.querySelectorAll('[data-order-media]').forEach(root=>{if(root.__orderDetail)return;let index=0,initialUrl='';try{index=Number(sessionStorage.getItem('guestDetailPhoto:'+location.href))||0;initialUrl=sessionStorage.getItem('guestDetailMediaURL:'+location.href)||''}catch(_){}mount(root,{head:document.querySelector('.guest-order-head'),panels:[...document.querySelectorAll('.guest-panel:not(.pdf-documents)')],initialIndex:index,initialUrl})})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
