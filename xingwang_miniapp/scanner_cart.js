'use strict';
// Cart controller for the existing /scanner page. Guest can access cart endpoints
// only; staff-only DOM is also removed from the guest presentation.
let cartRole='none', cartData=null, cartSearch=null,cartBusy=false;
let cartFilterMode='all',cartRecent=[],cartLookupPending=false;
let cartView='pick',cartSkuSearch='',cartCameraOpen=false,cartSummaryOpen=false;
let cartToastTimer=null;
const CART_SAVE_DELAY=1200;
let cartPending=new Map(),cartSending=new Map(),cartSaveTimer=null,cartSaveJob=null,cartSaveError=false;
function cartClearTimer(){if(cartSaveTimer){clearTimeout(cartSaveTimer);cartSaveTimer=null;}}
function cartEffectiveItems(){
 const items=new Map((cartData?.items||[]).map(i=>[i.sku,i.qty]));
 for(const [sku,qty] of cartSending){if(qty>0)items.set(sku,qty);else items.delete(sku);}
 for(const [sku,qty] of cartPending){if(qty>0)items.set(sku,qty);else items.delete(sku);}
 return Array.from(items,([sku,qty])=>({sku,qty})).sort((a,b)=>compareSkus(a.sku,b.sku));
}
const cartText=(id,text)=>{const el=document.getElementById(id);if(el)el.textContent=text};
function cartNotice(text,bad=false){
 const el=$('cartMessage');
 clearTimeout(cartToastTimer);cartToastTimer=null;
 if(!text||text==='✓ SAVED'){el.textContent='';el.className='';return}
 el.textContent=String(text);
 el.className='show'+(bad?' error':'');
 cartToastTimer=setTimeout(()=>{el.className='';el.textContent='';},bad?6000:2500);
}
function cartLocalTime(value){
 if(!value)return '—';
 const d=new Date(value);return Number.isFinite(d.valueOf())?d.toLocaleString('es-CL',{timeZone:'America/Santiago',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';
}
function cartMsgClean(){
 cartNotice('');msg('');
}
function cartItemQty(sku){
 if(cartPending.has(sku))return cartPending.get(sku);
 if(cartSending.has(sku))return cartSending.get(sku);
 return Number(cartData?.items?.find(i=>i.sku===sku)?.qty||0);
}
function cartSum(){return cartEffectiveItems().reduce((n,i)=>n+i.qty,0)}
function cartUpdateHeader(){
 $('cartNavCount').textContent=String(cartSum());
 if(!cartData)return;
 cartText('cartShortCode',(cartData.customer_name||'').trim()||'#'+cartData.short_code.split('-').slice(-1)[0]);
 $('cartShortCode').title=cartData.short_code+' · tap to copy';
 const ready=!(cartPending.size||cartSending.size)&&cartData.state==='ready';
 cartText('cartStateLabel',ready?'就绪':'草稿');
 $('cartStateLabel').dataset.state=ready?'ready':'draft';
 cartText('cartOpenedAt',cartLocalTime(cartData.guest_opened_at));
 cartText('cartConfirmedAt',cartLocalTime(cartData.confirmed_at));
 cartText('cartVersionLabel',cartData.confirmed_version?'V'+cartData.confirmed_version:'—');
 $('cartVersionBtn').classList.toggle('hidden',cartRole!=='staff'||!cartData.confirmed_version);
 $('cartVersionBtn').textContent='V'+(cartData.confirmed_version||'—');
 cartText('cartSavedAt',cartSaveError?'! 未保存':cartSaveJob?'… 保存中':cartPending.size?'● 待保存':'✓ 已保存');
 $('cartSavedAt').dataset.error=cartSaveError?'true':'false';
 cartText('cartCustomerLabel','#'+cartData.short_code.split('-').slice(-1)[0]+(cartSearch?.product_code?' · '+cartSearch.product_code:''));
 cartText('cartTotal',String(cartSum()));
 $('cartCopy').title='复制 '+cartEffectiveItems().length+' SKU × 2 列 / Excel';
 cartText('cartSkuCount',cartEffectiveItems().length+' SKU');
 cartText('cartDockSkuCount',cartEffectiveItems().length+' SKU');
 $('cartCopy').disabled=cartRole!=='staff'&&cartRole!=='guest';
 $('cartBack').classList.toggle('hidden',cartRole!=='staff');
 const reopening=cartData.state==='ready'&&cartData.confirmed_version>0&&!cartPending.size&&!cartSending.size;
 $('cartStateButton').innerHTML=reopening
  ?'<svg viewBox="0 0 24 24" width="29" height="29" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 12a9 9 0 1 0 3-7M3 3v6h6"/></svg>'
  :'<svg viewBox="0 0 24 24" width="29" height="29" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="m5 12 4.5 4.5L19 7"/></svg>';
 $('cartStateButton').setAttribute('aria-label',reopening?'继续编辑 / Seguir editando':'确认选货 / Confirmar selección');
 $('cartStateButton').title=cartData.state==='ready'&&cartData.confirmed_version>0&&!cartPending.size&&!cartSending.size?'繼續選貨':'確認本次選貨，保留不可覆蓋的版本';
 $('cartStateButton').disabled=cartBusy||Boolean(cartSaveJob);
}
function cartSetData(data){
 cartData=data;
 if(data)cartRender();
}
function cartRow(sku,qty,stockValue,fromSearch){
 const row=document.createElement('div');row.className='cart-line'+(qty>0?' selected':'');
 const left=document.createElement('div');left.className='cart-line-title';
 const name=document.createElement('strong');name.textContent=sku;
 const stock=document.createElement('small');stock.className='cc-stock-line';
 const box='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m3 8 9-5 9 5v8l-9 5-9-5V8ZM3 8l9 5 9-5M12 13v8"/></svg>';
 const warn='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m12 3 9 17H3L12 3zM12 9v5M12 17v.5"/></svg>';
 const n=stockValue==null||String(stockValue).trim()===''?null:Number(stockValue);
 const available=n!=null&&Number.isFinite(n)?Math.max(0,Math.floor(n)):null;
 if(fromSearch){
  stock.innerHTML=(available!==null&&available<=2?warn:box);
  const count=document.createElement('span');count.textContent=available===null?'—':fmt(available);
  stock.append(count);
 }
 if(fromSearch&&available!==null&&available<=2)stock.classList.add('cart-out');
 left.append(name,stock);row.append(left);
 const controls=document.createElement('div');controls.className='cart-qty-controls';
 const minus='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M5 12h14"/></svg>';
 const plus='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';
 const dec=document.createElement('button');dec.type='button';dec.className='secondary';dec.innerHTML=minus;dec.setAttribute('aria-label',sku+' 减 / Menos');
 const value=document.createElement('input');value.type='text';value.inputMode='numeric';
 value.className='cart-qty';value.value=String(qty);value.setAttribute('aria-label',sku+' 匹 / Rollos');value.title='点击输入匹数';
 const inc=document.createElement('button');inc.type='button';inc.className='secondary';inc.innerHTML=plus;inc.setAttribute('aria-label',sku+' 加 / Más');
 dec.disabled=cartBusy||qty===0;
 inc.disabled=cartBusy||(fromSearch?available===null||qty>=available:qty>=9999);
 const update=number=>{
  if(!Number.isInteger(number)||number>9999||number<0||(fromSearch&&(available===null||number>available))){
   cartNotice('数量不可超过参考库存 / Cantidad inválida',true);
   value.value=String(cartItemQty(sku));return;
  }
  if(number!==cartItemQty(sku))cartChange(sku,number);
 };
 value.onfocus=()=>value.select();
 value.onchange=()=>{
  const raw=value.value.trim();
  if(!/^\d+$/.test(raw)){value.value=String(cartItemQty(sku));return}
  update(Number(raw));
 };
 value.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();value.blur()}};
 dec.onclick=()=>update(Math.max(0,cartItemQty(sku)-1));
 inc.onclick=()=>update(cartItemQty(sku)+1);
 controls.append(dec,value,inc);row.append(controls);
 return row;
}
let cartNoteCartId=null,cartNoteOriginal='',cartNoteSaveJob=null;
function cartNoteDirty(){
 return cartRole==='staff'&&cartData&&cartNoteCartId===cartData.id&&
        $('cartNoteText').value.trim()!==cartNoteOriginal;
}
async function cartLoadNote(id){
 const input=$('cartNoteText'),save=$('cartNoteSave'),status=$('cartNoteStatus');
 cartNoteCartId=id;cartNoteOriginal='';input.value='';
 input.disabled=true;save.disabled=true;status.textContent='…';
 if(cartRole!=='staff')return;
 try{
  const d=await post('/scanner/api/cart/note/get',{cart_id:id});
  if(cartData?.id!==id||cartNoteCartId!==id)return;
  cartNoteOriginal=d.note||'';
  input.value=cartNoteOriginal;
  input.disabled=false;save.disabled=true;status.textContent='';
 }catch(e){
  if(cartData?.id!==id)return;
  status.textContent='读取失败 / Error';cartNotice(e.message,true);
 }
}
async function cartSaveNote(){
 if(cartNoteSaveJob)return cartNoteSaveJob;
 if(!cartNoteDirty())return true;
 if(!cartData||cartRole!=='staff')return false;
 const id=cartData.id,content=$('cartNoteText').value.trim();
 const save=$('cartNoteSave'),status=$('cartNoteStatus');
 const job=(async()=>{
  try{
   if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return false;
   if(!cartData||cartData.id!==id)return false;
   save.disabled=true;status.textContent='保存中 / Guardando…';
   const d=await post('/scanner/api/cart/note/save',{cart_id:id,revision:cartData.revision,note:content});
   if(!cartData||cartData.id!==id)return false;
   cartData.revision=d.revision;cartNoteOriginal=d.note;
   status.textContent='✓ 已保存';return true;
  }catch(e){
   status.textContent=e.status===409?'资料已变动 / Conflicto':'保存失败 / Error';
   cartNotice(e.message,true);
   return false;
  }finally{
   if(cartData?.id===id)save.disabled=!cartNoteDirty();
  }
 })();
 cartNoteSaveJob=job;
 try{return await job}finally{cartNoteSaveJob=null}
}
$('cartNoteText').addEventListener('input',()=>{
 $('cartNoteStatus').textContent=cartNoteDirty()?'● 待保存 / Sin guardar':'';
 $('cartNoteSave').disabled=!cartNoteDirty();
});
$('cartNoteSave').onclick=()=>void cartSaveNote();
function cartRender(){
 const isGuest=cartRole==='guest',hasCart=Boolean(cartData);
 $('cartStart').classList.toggle('hidden',isGuest||hasCart);
 $('cartActive').classList.toggle('hidden',!hasCart);
 $('cartStaffList').classList.toggle('hidden',isGuest);
 $('cartWorkspace').classList.toggle('cart-has-active',hasCart);
 $('cartWorkspace').dataset.cartRole=cartRole;
 $('cartNoteSection').classList.toggle('hidden',isGuest||!hasCart);
 if(mode==='cart'){
  $('scanPanel').classList.toggle('hidden',!hasCart||!cartCameraOpen);
  $('scanPanel').classList.toggle('cc-cart-camera-active',hasCart&&cartCameraOpen);
  $('scanPanel').classList.remove('cart-scanner-parked');
 }
 if(!hasCart)return;
 cartUpdateHeader();
 $('cartPickView').classList.remove('hidden');
 $('cartItemView').classList.toggle('hidden',!cartSummaryOpen);
 $('cartStateButton').classList.remove('hidden');
 $('cartPickEmpty').classList.toggle('hidden',Boolean(cartSearch)||(cartEffectiveItems().length>0));
 const host=$('cartItems');host.replaceChildren();
 const items=cartEffectiveItems();
 // Stock is returned with the saved cart from the TiDB snapshot.
 // Don't require the customer to scan the series again after re-opening.
 const knownStock=new Map((cartData.items||[]).map(i=>[i.sku,i.stock_rolls]));
 if(!items.length){
  const p=document.createElement('p');p.className='muted';
  p.textContent='尚未选择商品 / Sin productos';host.append(p);
 }
 for(const item of items)host.append(cartRow(item.sku,item.qty,knownStock.get(item.sku)??null,true));
 const products=$('cartProducts');products.replaceChildren();
 let rows=[],selected=[],inStock=[],all=[];
 if(cartSearch){
  all=Array.isArray(cartSearch.variants)?[...cartSearch.variants].sort((a,b)=>compareSkus(a.code,b.code)):[];
  selected=all.filter(v=>cartItemQty(v.code)>0);
  inStock=all.filter(v=>Number(v.stock_rolls)>0);
 }else{
  all=items.map(i=>({code:i.sku,stock_rolls:knownStock.get(i.sku)??null}));
  selected=all;
  inStock=all.filter(v=>v.stock_rolls!=null&&Number(v.stock_rolls)>0);
 }
 $('cartProductToolbar').classList.toggle('hidden',!hasCart);
 const bar=document.createElement('div');bar.className='cart-filter cc-three-filters';
 const choices=[
  {key:'all',items:all,label:'全部',es:'Todos',icon:'<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>'},
  {key:'stock',items:inStock,label:'有库存',es:'Con stock',icon:'<path d="m3 7 9-4 9 4v10l-9 4-9-4V7Z"/><path d="m3 7 9 4 9-4M12 11v10"/>'},
  {key:'selected',items:selected,label:'已选',es:'Elegidos',icon:'<path d="m5 12.5 4.5 4.5L19 7"/>'}
 ];
 for(const choice of choices){
  const button=document.createElement('button');button.type='button';
  button.className=cartFilterMode===choice.key?'active':'';
  button.setAttribute('aria-pressed',String(cartFilterMode===choice.key));
  button.setAttribute('aria-label',choice.label+' / '+choice.es+' '+choice.items.length);
  const icon=document.createElement('span');icon.className='cc-filter-icon';
  icon.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">'+choice.icon+'</svg>';
  const label=document.createElement('span');label.className='cc-filter-name';
  label.textContent=choice.label;
  const countEl=document.createElement('strong');countEl.textContent=String(choice.items.length);
  button.append(icon,label,countEl);
  button.onclick=()=>{cartFilterMode=choice.key;cartRender()};
  bar.append(button);
 }
 if(all.length)products.append(bar);
 const pools={all,inStock,selected};
 const filterRows=cartFilterMode==='stock'?pools.inStock:cartFilterMode==='selected'?pools.selected:pools.all;
 rows=filterRows.filter(v=>v.code.toLowerCase().includes(cartSkuSearch.toLowerCase()));
 if(!rows.length&&all.length){
  const p=document.createElement('p');p.className='muted cc-empty-filter';
  p.textContent='本组没有符合的编号，可按查询查找其他系列 / Buscar otra serie';products.append(p);
 }
 for(const item of rows)products.append(cartRow(item.code,cartItemQty(item.code),item.stock_rolls,true));
 $('cartStockNote').classList.toggle('hidden',!all.length);
 $('cartStockNote').textContent='库存为参考值，正式订货前须核对 RESERVAR';
}
function cartApplyRole(){
 const guest=cartRole==='guest';
 $('cartNav').classList.toggle('hidden',guest||cartRole!=='staff');
 $('workModes').classList.toggle('hidden',guest||mode==='cart');
 if(guest){
  $('adminLink').classList.add('hidden');
  $('fullKindControls').classList.add('hidden');
  $('fullResult').classList.add('hidden');
  $('result').classList.add('hidden');
  $('adminTab').classList.add('hidden');
  $('cartBack').classList.add('hidden');
  $('app').classList.remove('hidden');
 }
}
async function cartBootstrap(role,guestId){
 const changed=role!==cartRole;
 cartRole=role;
 if(changed){cartClearTimer();cartPending.clear();cartSending.clear();cartSaveError=false;cartData=null;cartSearch=null;cartRecent=[];lastQrCode='';cartView='pick';cartSkuSearch='';cartCameraOpen=false;cartSummaryOpen=false;}
 cartApplyRole();
 if(role==='guest'){
  // Drop staff-only query results when a company phone becomes a guest device.
  current=null;fullData=null;
  $('rows').replaceChildren();$('fullDetails').replaceChildren();$('totals').replaceChildren();
  setMode('cart'); 
  try{
   const d=await post('/scanner/api/cart/open',{cart_id:guestId});
   cartView='pick';cartSetData(d.cart);cartNotice('');
  }catch(e){cartNotice(e.message,true)}
 }else if(role==='staff'){
  // Staff enter on the cart list, not on an automatically selected item.
  if(new URLSearchParams(location.search).has('cart'))
   history.replaceState(null,'',location.pathname);
  if(mode==='cart'){
   if(cartData&&!changed)cartRender();else await cartLoadList();
  }
 }else if(role==='none'){
  cartData=null;cartSearch=null;cartRender();
 }
}
async function cartLoadList(){
 if(cartRole!=='staff')return;
 try{
  const res=await fetch('/scanner/api/cart/list',{credentials:'same-origin',cache:'no-store'});
  const data=await res.json();
  if(!res.ok)throw Error(data.detail||'Unable to load carts');
  cartRecent=data.carts||[];
  cartRenderList();
  // Both desktop and mobile stay on the list until a cart is selected.
  cartRender();
 }catch(e){cartNotice(e.message,true)}
}
let cartEditingId=null,cartUndoEntry=null,cartUndoTimer=null;
const CART_TRASH_ICON='<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>';
const CART_PENCIL_ICON='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 5 5 5M4 20l4.5-1 11-11a2 2 0 0 0-4-4l-11 11L4 20Z"/></svg>';
const CART_CHECK_ICON='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m5 12 4 4 10-10"/></svg>';
function cartClearUndo(){
 if(cartUndoTimer){clearTimeout(cartUndoTimer);cartUndoTimer=null}
 cartUndoEntry=null;
 $('cartUndoBar').classList.add('hidden');
}
function cartShowUndo(item,response){
 cartClearUndo();
 cartUndoEntry={id:item.id,revision:response.revision,until:Date.parse(response.undo_until)};
 $('cartUndoText').textContent='已删除 '+item.short_code.split('-').pop()+' · 8 秒可恢复';
 $('cartUndoBar').classList.remove('hidden');
 const ms=Math.min(8000,Math.max(0,cartUndoEntry.until-Date.now()));
 cartUndoTimer=setTimeout(cartClearUndo,ms);
}
async function cartUndoDelete(){
 const entry=cartUndoEntry;
 if(!entry||cartBusy||Date.now()>entry.until){cartClearUndo();return}
 cartBusy=true;
 try{
  await post('/scanner/api/cart/undo-delete',{cart_id:entry.id,revision:entry.revision});
  cartClearUndo();cartNotice('已恢复 / Restaurado');
  
 }catch(e){
  cartClearUndo();cartNotice('无法恢复 / No se pudo restaurar: '+e.message,true);
 }finally{cartBusy=false;void cartLoadList()}
}
async function cartDeleteItem(item){
 if(cartBusy||cartRole!=='staff')return;
 if(cartData?.id===item.id&&(cartPending.size||cartSaveJob)){
  if(!(await cartFlush()))return;
 }
 if(cartData?.id===item.id&&!(await cartSaveNote()))return;
 const revision=cartData?.id===item.id?cartData.revision:item.revision;
 cartBusy=true;
 try{
  const result=await post('/scanner/api/cart/delete',{cart_id:item.id,revision});
  cartRecent=cartRecent.filter(c=>c.id!==item.id);
  if(cartData?.id===item.id){
   cartData=null;cartSearch=null;cartCameraOpen=false;cartSummaryOpen=false;
   
   history.replaceState(null,'',location.pathname);
  }
  if(cartEditingId===item.id)cartEditingId=null;
  cartRender();cartRenderList();
  cartShowUndo(item,result);
 }catch(e){
  cartNotice(e.status===409?'购物车已更新，请重试 / Carrito modificado':e.message,true);
 }finally{
  cartBusy=false;
  if(mode==='cart')void cartLoadList();
 }
}
async function cartSaveListName(item,field){
 if(cartBusy||cartRole!=='staff')return;
 const name=field.value.trim();
 if(name===(item.customer_name||'')){cartEditingId=null;cartRenderList();return}
 if(cartData?.id===item.id&&(cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 cartBusy=true;
 try{
  const revision=cartData?.id===item.id?cartData.revision:item.revision;
  const d=await post('/scanner/api/cart/name',{cart_id:item.id,revision,name});
  if(cartData?.id===item.id)cartSetData(d.cart);
  cartEditingId=null;
  cartNotice('客户已保存 / Nombre guardado');
  await cartLoadList();
 }catch(e){
  cartNotice(e.status===409?'资料已变动，请重新编辑 / Datos modificados':e.message,true);
  await cartLoadList();
 }finally{cartBusy=false}
}
function cartRenderList(){
 const host=$('cartRecent');host.replaceChildren();
 const filter=$('cartFilter').value.trim().toLowerCase();
 const carts=cartRecent.filter(c=>c.short_code.toLowerCase().includes(filter)||(c.customer_name||'').toLowerCase().includes(filter));
 if(!carts.length){
  const p=document.createElement('p');p.className='muted';p.textContent='暂无购物车 / Sin carritos';host.append(p);
 }
 for(const item of carts){
  const wrapper=document.createElement('div');wrapper.className='cart-history-entry';
  const main=document.createElement('div');main.className='cart-history-main';
  const btn=document.createElement('button');btn.type='button';btn.className='cart-history-row';
  const title=document.createElement('strong');title.className='cart-history-name';
  title.textContent=(item.customer_name||'').trim()||item.short_code.replace(/^C-[0-9]{6}-/,'');
  title.title=(item.customer_name||'').trim()||item.short_code;
  const code=document.createElement('span');code.className='cart-history-code';
  code.textContent=(item.customer_name?'#':'')+item.short_code.replace(/^C-[0-9]{6}-/,'')+
      (item.confirmed_version?' · V'+item.confirmed_version:'');
  const date=document.createElement('small');date.className='cart-history-date';
  date.textContent=cartLocalTime(item.confirmed_at||item.guest_opened_at||item.updated_at);
  btn.append(title,code,date);
  btn.onclick=()=>{
   if(wrapper.classList.contains('swiped')){wrapper.classList.remove('swiped');return}
   void cartOpen(item.id);
  };
  if(cartData?.id===item.id){wrapper.classList.add('current');btn.setAttribute('aria-current','true')}
  const foot=document.createElement('div');foot.className='cart-history-footer';
  const count=document.createElement('span');count.className='cart-history-count';
  const n=document.createElement('strong');n.textContent=String(item.qty_total);
  count.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><path d="M5 6c0 1.7 3.1 3 7 3s7-1.3 7-3-3.1-3-7-3-7 1.3-7 3zM5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/></svg>';
  count.append(n);
  const status=document.createElement('span');status.className='cart-history-status '+(item.state==='ready'?'ready':'draft');
  status.textContent=item.state==='ready'?'已确认':'草稿';
  const edit=document.createElement('button');edit.type='button';edit.className='cart-history-edit';
  edit.innerHTML=CART_PENCIL_ICON;edit.title='编辑客户 / Editar cliente';
  edit.setAttribute('aria-label','编辑客户名称 / Editar cliente');
  edit.onclick=()=>{
   cartEditingId=cartEditingId===item.id?null:item.id;
   cartRenderList();
   if(cartEditingId){const input=host.querySelector('.cart-history-entry.editing input');if(input){input.focus();input.select()}}
  };
  foot.append(count,status,edit);
  main.append(btn,foot);
  if(cartEditingId===item.id){
   wrapper.classList.add('editing');
   const editor=document.createElement('div');editor.className='cart-history-editor';
   const field=document.createElement('input');field.type='text';field.maxLength=80;
   field.placeholder='客户名称 / Nombre';field.value=item.customer_name||'';
   field.setAttribute('aria-label','客户名称 / Nombre cliente');
   const save=document.createElement('button');save.type='button';save.innerHTML=CART_CHECK_ICON;
   save.setAttribute('aria-label','保存客户名称 / Guardar nombre');
   save.onclick=()=>void cartSaveListName(item,field);
   field.onkeydown=e=>{
    if(e.key==='Enter'){e.preventDefault();save.click()}
    if(e.key==='Escape'){cartEditingId=null;cartRenderList()}
   };
   editor.append(field,save);main.append(editor);
  }
  const del=document.createElement('button');del.type='button';del.className='cart-history-delete';
  del.innerHTML=CART_TRASH_ICON;del.setAttribute('aria-label','删除购物车 / Eliminar carrito');
  del.title='删除 / Eliminar';del.onclick=()=>void cartDeleteItem(item);
  wrapper.append(del,main);
  let startX=0,startY=0;
  wrapper.addEventListener('click',event=>{
   if(Date.now()<Number(wrapper.dataset.swipeClickUntil||0)&&event.target!==del&&!del.contains(event.target)){
    event.preventDefault();event.stopPropagation();
   }
  },true);
  wrapper.addEventListener('touchstart',e=>{
   if(!window.matchMedia('(max-width:949px)').matches||!e.touches.length)return;
   startX=e.touches[0].clientX;startY=e.touches[0].clientY;
  },{passive:true});
  wrapper.addEventListener('touchend',e=>{
   if(!window.matchMedia('(max-width:949px)').matches||!e.changedTouches.length)return;
   const dx=e.changedTouches[0].clientX-startX,dy=e.changedTouches[0].clientY-startY;
   if(Math.abs(dx)>48&&Math.abs(dx)>Math.abs(dy)*1.25){
    for(const open of host.querySelectorAll('.cart-history-entry.swiped'))if(open!==wrapper)open.classList.remove('swiped');
    wrapper.classList.toggle('swiped',dx>0);
    wrapper.dataset.swipeClickUntil=String(Date.now()+450);
   }
  },{passive:true});
  host.append(wrapper);
 }
}
async function cartOpen(id){
 if(cartBusy)return;
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 if(!(await cartSaveNote()))return;
 cartBusy=true;lastQrCode='';
 $('cartConfirmedBox').classList.add('hidden');$('cartConfirmedBox').replaceChildren();
 try{const d=await post('/scanner/api/cart/open',{cart_id:id});
  cartView='pick';cartCameraOpen=false;cartSummaryOpen=false;cartSkuSearch='';$('cartSkuFilter').value='';
  cartSearch=null;cartSetData(d.cart);cartRenderList();cartMsgClean();
  void cartLoadNote(d.cart.id);
  if(cartRole==='staff')history.replaceState(null,'',location.pathname);}
 catch(e){cartNotice(e.message,true)}
 finally{cartBusy=false;cartRender()}
}
async function cartCreate(){
 if(cartBusy)return;
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 if(!(await cartSaveNote()))return;
 cartBusy=true;lastQrCode='';$('cartCreateBtn').disabled=true;
 $('cartConfirmedBox').classList.add('hidden');$('cartConfirmedBox').replaceChildren();
 try{
  const d=await post('/scanner/api/cart/create',{name:$('cartNewName').value.trim()});
  cartView='pick';cartCameraOpen=false;cartSummaryOpen=false;cartSkuSearch='';$('cartSkuFilter').value='';cartSearch=null;cartSetData(d.cart);
  void cartLoadNote(d.cart.id);
  $('cartNewName').value='';cartMsgClean();
  history.replaceState(null,'',location.pathname);
  void cartLoadList();
 }catch(e){cartNotice(e.message,true)}
 finally{cartBusy=false;$('cartCreateBtn').disabled=false;cartRender()}
}
async function cartRefresh(discardPending=false){
 if(!cartData)return;
 if((cartPending.size||cartSending.size)&&!discardPending&&!(await xwConfirm('有未保存的修改，是否放弃并重新载入？ / Descartar cambios sin guardar')))return;
 if(cartSaveJob)await cartSaveJob;
 if(discardPending||cartPending.size){cartPending.clear();cartSending.clear();cartClearTimer();cartSaveError=false;}
 try{
  const d=await post('/scanner/api/cart/open',{cart_id:cartData.id});
  cartSetData(d.cart);void cartLoadNote(d.cart.id);cartNotice('已刷新 / Actualizado');
 }catch(e){cartNotice(e.message,true)}
}
async function cartPostBatch(items,revision){
 const response=await fetch('/scanner/api/cart/batch',{
  method:'POST',credentials:'same-origin',cache:'no-store',keepalive:true,
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({cart_id:cartData.id,revision,items})
 });
 let data={};try{data=await response.json()}catch(_){}
 if(!response.ok)throw Object.assign(new Error(data.detail||data.error||'SAVE FAILED'),{status:response.status});
 return data;
}
async function cartFlush(){
 cartClearTimer();
 if(cartSaveJob){
  const ok=await cartSaveJob;
  return ok&&cartPending.size?cartFlush():ok;
 }
 if(!cartPending.size)return true;
 if(!cartData)return false;
 const submission=new Map(cartPending);
 cartPending.clear();
 cartSending=new Map(submission);
 const cartId=cartData.id;
 const revision=cartData.revision;
 const task=(async()=>{
  try{
   const data=await cartPostBatch(Array.from(submission,([sku,qty])=>({sku,qty})),revision);
   if(cartData?.id===cartId){
    cartData=data.cart;
    cartSaveError=false;
    cartNotice('✓ SAVED');
   }
   return true;
  }catch(e){
   if(cartData?.id===cartId){
    for(const [sku,qty] of submission)if(!cartPending.has(sku))cartPending.set(sku,qty);
    cartSaveError=true;
    cartNotice(e.status===409?'数据已变动或库存不足 / Datos cambiados o stock insuficiente':e.message,true);
   }
   return false;
  }finally{
   cartSending.clear();cartSaveJob=null;cartRender();
  }
 })();
 cartSaveJob=task;
 cartRender();
 const ok=await task;
 if(ok&&cartPending.size)return cartFlush();
 return ok;
}
function cartPlanSave(){
 cartSaveError=false;
 cartClearTimer();
 cartSaveTimer=setTimeout(()=>{void cartFlush()},CART_SAVE_DELAY);
}
function cartChange(sku,qty){
 if(!cartData||cartBusy||!Number.isInteger(qty)||qty<0||qty>9999)return;
 const existing=cartSending.has(sku)?cartSending.get(sku):
  Number(cartData.items.find(i=>i.sku===sku)?.qty||0);
 if(qty===existing)cartPending.delete(sku);
 else cartPending.set(sku,qty);
 cartPlanSave();
 cartRender();
}

async function cartSetState(){
 if(!cartData||cartBusy)return;
 cartBusy=true;
 try{
  if(cartPending.size||cartSaveJob){
   if(!(await cartFlush()))return;
  }
  if(cartData.state==='ready'&&cartData.confirmed_version>0){
   const d=await post('/scanner/api/cart/state',{
    cart_id:cartData.id,revision:cartData.revision,state:'open'
   });
   cartSetData(d.cart);cartNotice('草稿 · 保留上次确认 / Borrador · se mantiene la confirmación');
  }else{
   const d=await post('/scanner/api/cart/confirm',{
    cart_id:cartData.id,revision:cartData.revision
   });
   cartSetData(d.cart);
   cartNotice('已确认 V'+d.cart.confirmed_version+' · 未预留 / Confirmado V'+d.cart.confirmed_version+' · sin reservar');
   if(cartRole==='staff')void cartLoadList();
  }
 }catch(e){
  cartNotice(e.message,true);
  if(e.status===409)cartNotice('购物车已变动，请刷新 / Carrito modificado, actualiza',true);
 }finally{cartBusy=false;cartRender()}
}

async function cartLookup(input){
 if(mode!=='cart'||!cartData||cartLookupPending)return;
 const code=normalizeProductCode(input);
 if(!valid(code)){cartNotice('无效二维码或编号 / Código QR o SKU no válido',true);return}
 cartLookupPending=true;busy=true;$('queryBtn').disabled=true;
 $('code').value=code;syncSearchClear();
 try{
  const d=await post('/scanner/api/cart/lookup',{cart_id:cartData.id,code});
  if(cartCameraOpen&&running)await stopCamera();
  cartCameraOpen=false;cartView='pick';cartSearch=d;cartFilterMode='all';cartSkuSearch='';$('cartSkuFilter').value='';
  cartRender();cartMsgClean();
  $('cartWorkspace').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){cartNotice(e.message,true)}
 finally{cartLookupPending=false;busy=false;$('queryBtn').disabled=false}
}
window.cartLookup=cartLookup;
window.cartIsReviewing=()=>!cartCameraOpen;
window.cartBootstrap=cartBootstrap;
window.cartApplyRole=cartApplyRole;
window.cartLoadList=cartLoadList;
$('cartNav').onclick=async()=>{
 if(cartRole!=='staff')return;
 if(mode==='cart'&&(cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 if(mode==='cart'&&!(await cartSaveNote()))return;
 setMode(mode==='cart'?'sample':'cart');
 if(mode==='cart'){
  cartData=null;cartSearch=null;cartCameraOpen=false;cartSummaryOpen=false;
  history.replaceState(null,'',location.pathname);
  cartRender();void cartLoadList();
 }
};
$('cartCreateBtn').onclick=cartCreate;
$('cartSidebarCreateBtn').onclick=async()=>{
 if(cartRole!=='staff'||cartBusy)return;
 $('cartNewName').value='';
 await cartCreate();
};
$('cartFilter').oninput=cartRenderList;
$('cartSkuFilter').oninput=()=>{cartSkuSearch=$('cartSkuFilter').value.trim();cartRender()};
// Keep the QR workflow unchanged; manual entry shares the existing safe stock lookup.
$('cartSeriesLookup').onclick=()=>{
 const typed=$('cartSkuFilter').value.trim();
 if(!typed){$('cartSkuFilter').focus();return}
 void cartLookup(typed);
};
$('cartSkuFilter').addEventListener('keydown',event=>{
 if(event.key==='Enter'){
  event.preventDefault();
  $('cartSkuFilter').blur();
  $('cartSeriesLookup').click();
 }
});
$('cartShortCode').onclick=async()=>{
 if(!cartData)return;
 try{await navigator.clipboard.writeText(cartData.short_code);cartNotice('已复制编号 / ID copiado')}
 catch(_){void xwCopyFallback('复制购物车编号 / Copiar ID',cartData.short_code)}
};
$('cartDetailsBtn').onclick=()=>{
 const meta=$('cartMeta'),hidden=meta.classList.toggle('hidden');
 $('cartDetailsBtn').setAttribute('aria-expanded',String(!hidden));
};
async function cartScanNow(){
 if(!cartData)return;
 cartCameraOpen=true;cartSummaryOpen=false;cartView='pick';
 cartRender();
 if(!running)await startCamera();
 if(!running){cartCameraOpen=false;cartRender();return}
 $('ccCartCameraClose').focus();
}
async function cartCloseCamera(){
 cartCameraOpen=false;
 if(running)await stopCamera();
 cartRender();
}
window.cartCloseCamera=cartCloseCamera;
$('cartScanNow').onclick=cartScanNow;
$('cartSwitchView').onclick=()=>{cartSummaryOpen=true;cartRender()};
$('ccCartTotalInfo').onclick=()=>{cartSummaryOpen=true;cartRender()};
$('ccSummaryShade').onclick=()=>{cartSummaryOpen=false;cartRender()};
$('ccSummaryClose').onclick=()=>{cartSummaryOpen=false;cartRender()};

$('cartBack').onclick=async()=>{
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 if(!(await cartSaveNote()))return;
 cartClearTimer();cartPending.clear();cartData=null;cartSearch=null;lastQrCode='';cartView='pick';cartSkuSearch='';cartCameraOpen=false;cartSummaryOpen=false;
 
 history.replaceState(null,'',location.pathname);cartRender();void cartLoadList()
};
$('cartStateButton').onclick=cartSetState;
$('cartUndoButton').onclick=()=>void cartUndoDelete();
$('cartVersionBtn').onclick=async()=>{
 if(cartRole!=='staff'||!cartData?.confirmed_version)return;
 const host=$('cartConfirmedBox');
 if(!host.classList.contains('hidden')){host.classList.add('hidden');return}
 try{
  const d=await post('/scanner/api/cart/confirmed',{cart_id:cartData.id});
  host.replaceChildren();
  const title=document.createElement('strong');
  title.textContent='V'+d.confirmed.version+' · '+cartLocalTime(d.confirmed.confirmed_at)+' · '+d.confirmed.qty_total+' ROLL';
  host.append(title);
  for(const item of d.confirmed.items){
   const row=document.createElement('div');row.className='cart-spread';
   const sku=document.createElement('span');sku.textContent=item.sku;
   const qty=document.createElement('strong');qty.textContent=item.qty+' ROLL';
   row.append(sku,qty);host.append(row);
  }
  host.classList.remove('hidden');
 }catch(e){cartNotice(e.message,true)}
};
$('cartCopy').onclick=async()=>{
 if(!cartData)return;
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 const items=cartEffectiveItems().filter(i=>i.qty>0);
 if(!items.length){cartNotice('没有已选商品 / Sin productos seleccionados',true);return}
 // TSV: two columns only, safe to paste directly into Excel.
 const text=items.map(i=>i.sku+'\t'+i.qty).join('\n');
 try{await navigator.clipboard.writeText(text);cartNotice('已复制 '+items.length+' 个编号 / '+items.length+' SKU copiados')}
 catch(_){void xwCopyFallback('商品编号 + 匹数 / SKU + rollos',text)}
};
$('guestLoginBtn').onclick=async()=>{
 const code=$('guestCode').value.trim(),button=$('guestLoginBtn');button.disabled=true;
 try{
  await post('/scanner/api/cart/guest-login',{code});
  $('guestCode').value='';await session();
 }catch(e){$('loginMessage').textContent=e.message}finally{button.disabled=false}
};
$('guestCode').addEventListener('keydown',e=>{if(e.key==='Enter')$('guestLoginBtn').click()});

document.addEventListener('visibilitychange',()=>{if(document.hidden&&cartPending.size)void cartFlush()});
window.addEventListener('pagehide',()=>{if(cartPending.size&&!cartSaveJob)void cartFlush()});
window.cartEnsureSaved=cartFlush;
