'use strict';
// Cart controller for the existing /scanner page. Guest can access cart endpoints
// only; staff-only DOM is also removed from the guest presentation.
let cartRole='none', cartData=null, cartSearch=null, cartGuestCode='',cartBusy=false;
let cartAll=false,cartRecent=[],cartLookupPending=false;
let cartView='pick',cartSkuSearch='';
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
 const n=$('cartMessage');n.textContent=text==='✓ SAVED'?'':text||'';n.className=bad?'error':'';
 if(bad)msg(text,'error');
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
 cartText('cartShortCode',cartSearch?.product_code||'#'+cartData.short_code.split('-').slice(-1)[0]);
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
 cartText('cartCustomerLabel',cartData.customer_name||'客户 / Cliente');
 cartText('cartTotal',String(cartSum()));
 cartText('cartSkuCount',cartEffectiveItems().length+' SKU');
 cartText('cartDockSkuCount',cartEffectiveItems().length+' SKU');
 cartText('cartGuestCode',cartGuestCode||'········');
 $('cartGuestCode').classList.toggle('cart-code-empty',!cartGuestCode);
 $('cartShareRow').classList.toggle('hidden',cartRole!=='staff');
 $('cartEditName').classList.toggle('hidden',cartRole!=='staff');
 $('cartBack').classList.toggle('hidden',cartRole!=='staff');
 $('cartStateButton').textContent=cartData.state==='ready'&&cartData.confirmed_version>0&&!cartPending.size&&!cartSending.size?'↻ 继续':'✓ 确认';
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
 const stock=document.createElement('small');
 const n=stockValue==null||String(stockValue).trim()===''?null:Number(stockValue);
 const available=n!=null&&Number.isFinite(n)?Math.max(0,Math.floor(n)):null;
 stock.textContent=fromSearch?((available===null?'—':fmt(available))+' 匹 · Stock') : '';
 if(fromSearch&&available===0)stock.classList.add('cart-out');
 left.append(name,stock);row.append(left);
 const controls=document.createElement('div');controls.className='cart-qty-controls';
 const dec=document.createElement('button');dec.type='button';dec.className='secondary';dec.textContent='−';dec.setAttribute('aria-label',sku+' minus');
 const value=document.createElement('input');value.type='number';value.inputMode='numeric';
 value.min='0';value.max=String(available===null?9999:Math.min(9999,available));value.step='1';
 value.className='cart-qty';value.value=String(qty);value.setAttribute('aria-label',sku+' ROLL');value.title='點一下輸入匹數';
 const inc=document.createElement('button');inc.type='button';inc.className='secondary';inc.textContent='+';inc.setAttribute('aria-label',sku+' plus');
 dec.disabled=cartBusy||qty===0;
 inc.disabled=cartBusy||(fromSearch?available===null||qty>=available:qty>=9999);
 const update=n=>{
  if(n>9999||n<0||!Number.isInteger(n)||fromSearch&&(available===null||n>available)){
   cartNotice('數量必須為有效匹數，不得超過庫存參考值','error');
   value.value=String(cartItemQty(sku));return;
  }
  if(n!==cartItemQty(sku))cartChange(sku,n);
 };
 value.onfocus=()=>value.select();
 value.onchange=()=>{
  const raw=value.value.trim(),n=Number(raw);
  if(raw===''||!/^\d+$/.test(raw)){value.value=String(cartItemQty(sku));return}
  update(n);
 };
 value.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();value.blur()}};
 dec.onclick=()=>update(Math.max(0,cartItemQty(sku)-1));
 inc.onclick=()=>update(cartItemQty(sku)+1);
 controls.append(dec,value,inc);row.append(controls);
 return row;
}
function cartRender(){
 const isGuest=cartRole==='guest',hasCart=Boolean(cartData),picking=cartView==='pick';
 $('cartStart').classList.toggle('hidden',isGuest||hasCart);
 if(mode==='cart'){
  const park=hasCart&&!picking&&running;
  $('scanPanel').classList.toggle('hidden',!hasCart||(!picking&&!running));
  $('scanPanel').classList.toggle('cart-scanner-parked',park);
 }
 $('cartActive').classList.toggle('hidden',!hasCart);
 $('cartStaffList').classList.toggle('hidden',isGuest);
 $('cartWorkspace').classList.toggle('cart-has-active',hasCart);
 $('cartWorkspace').dataset.cartRole=cartRole;
 if(!hasCart)return;
 cartUpdateHeader();
 $('cartPickView').classList.toggle('hidden',!picking);
 $('cartItemView').classList.toggle('hidden',picking);
 $('cartSwitchView').textContent=picking?'购物车 · '+cartEffectiveItems().length:'扫码';
 $('cartStateButton').classList.remove('hidden');
 const host=$('cartItems');
 if(!picking){
  host.replaceChildren();
  const rows=cartEffectiveItems();
  if(!rows.length){
   const empty=document.createElement('p');empty.className='muted';empty.textContent='尚未选择商品，点扫码开始选货';host.append(empty);
  }
  for(const item of rows)host.append(cartRow(item.sku,item.qty,null,false));
 }
 $('cartPickEmpty').classList.toggle('hidden',Boolean(cartSearch));
 const products=$('cartProducts');
 if(!picking)return;
 products.replaceChildren();
 if(cartSearch){
  const header=document.createElement('div');header.className='cart-products-head';
  const title=document.createElement('strong');title.textContent=cartSearch.product_code;
  const time=document.createElement('small');time.textContent='STOCK '+cartLocalTime(cartSearch.as_of);
  header.append(title,time);products.append(header);
  const all=Array.isArray(cartSearch.variants)?[...cartSearch.variants].sort((a,b)=>compareSkus(a.code,b.code)):[];
  const selectedSkus=all.filter(v=>cartItemQty(v.code)>0);
  const bar=document.createElement('div');bar.className='cart-filter';
  for(const [key,label,count] of [[false,'全部 · Todos',all.length],[true,'已选 · Elegidos',selectedSkus.length]]){
   const button=document.createElement('button');button.type='button';
   button.className=cartAll===key?'active':'';
   const countEl=document.createElement('strong');countEl.textContent=String(count);
   const labelEl=document.createElement('span');labelEl.textContent=label;
   button.append(countEl,labelEl);
   button.onclick=()=>{cartAll=key;cartRender()};bar.append(button);
  }
  products.append(bar);
  const selected=(cartAll?selectedSkus:all).filter(v=>v.code.toLowerCase().includes(cartSkuSearch.toLowerCase()));
  $('cartProductToolbar').classList.remove('hidden');
  if(!selected.length){
   const empty=document.createElement('p');empty.className='muted';empty.textContent='沒有符合的 SKU';products.append(empty);
  }
  for(const v of selected)products.append(cartRow(v.code,cartItemQty(v.code),v.stock_rolls,true));
  $('cartStockNote').classList.remove('hidden');
  $('cartStockNote').textContent='库存仅供参考 / Stock de referencia · 未扣 RESERVAR';
 }else{
  $('cartProductToolbar').classList.add('hidden');
  $('cartStockNote').classList.add('hidden');
 }
}
function cartApplyRole(){
 const guest=cartRole==='guest';
 $('cartNav').classList.toggle('hidden',guest||cartRole!=='staff');
 $('cartEditName').classList.toggle('hidden',guest);
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
 if(changed){cartClearTimer();cartPending.clear();cartSending.clear();cartSaveError=false;cartData=null;cartSearch=null;cartGuestCode='';cartRecent=[];lastQrCode='';cartView='pick';cartSkuSearch='';}
 cartApplyRole();
 if(role==='guest'){
  // Drop staff-only query results when a company phone becomes a guest device.
  current=null;fullData=null;
  $('rows').replaceChildren();$('fullDetails').replaceChildren();$('totals').replaceChildren();
  setMode('cart'); 
  try{
   const d=await post('/scanner/api/cart/open',{cart_id:guestId});
   cartView=d.cart.items?.length?'cart':'pick';cartSetData(d.cart);cartNotice('');
  }catch(e){cartNotice(e.message,true)}
 }else if(role==='staff'){
  const link=new URLSearchParams(location.search).get('cart');
  if(link&&/^[a-f0-9]{32}$/.test(link)&&(!cartData||cartData.id!==link)){
   setMode('cart');await cartOpen(link);
  }else if(mode==='cart'){
   if(cartData)cartRender();else await cartLoadList();
  }
 }else if(role==='none'){
  cartData=null;cartSearch=null;cartGuestCode='';cartRender();
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
  cartRender();
 }catch(e){cartNotice(e.message,true)}
}
function cartRenderList(){
 const host=$('cartRecent');host.replaceChildren();
 const filter=$('cartFilter').value.trim().toLowerCase();
 const carts=cartRecent.filter(c=>c.short_code.toLowerCase().includes(filter)||(c.customer_name||'').toLowerCase().includes(filter));
 if(!carts.length){const p=document.createElement('p');p.className='muted';p.textContent='No carts';host.append(p)}
 for(const item of carts){
  const btn=document.createElement('button');btn.className='cart-history-row secondary';btn.type='button';
  const left=document.createElement('span');left.className='cart-history-left';
  const id=document.createElement('strong');id.textContent=item.short_code;
  const desc=document.createElement('small');desc.textContent=(item.customer_name||'客户 / Cliente')+' · '+(item.confirmed_version?'V'+item.confirmed_version+' · ':'')+cartLocalTime(item.confirmed_at||item.guest_opened_at||item.updated_at);
  const state=document.createElement('small');state.textContent=item.state==='ready'?'就绪':'草稿';
  left.append(id,desc,state);
  const right=document.createElement('span');right.textContent=item.qty_total+' ROLL';
  btn.append(left,right);btn.onclick=()=>cartOpen(item.id);
  host.append(btn);
 }
}
async function cartOpen(id){
 if(cartBusy)return;
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 cartBusy=true;lastQrCode='';
 $('cartConfirmedBox').classList.add('hidden');$('cartConfirmedBox').replaceChildren();
 try{const d=await post('/scanner/api/cart/open',{cart_id:id});
  cartView=d.cart.items?.length?'cart':'pick';cartSkuSearch='';$('cartSkuFilter').value='';
  cartGuestCode='';cartSearch=null;cartSetData(d.cart);cartMsgClean();
  if(cartRole==='staff')history.replaceState(null,'',location.pathname+'?cart='+id);}
 catch(e){cartNotice(e.message,true)}
 finally{cartBusy=false;cartRender()}
}
async function cartCreate(){
 if(cartBusy)return;
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 cartBusy=true;lastQrCode='';$('cartCreateBtn').disabled=true;
 $('cartConfirmedBox').classList.add('hidden');$('cartConfirmedBox').replaceChildren();
 try{
  const d=await post('/scanner/api/cart/create',{name:$('cartNewName').value.trim()});
  cartGuestCode=d.guest_code;cartView='pick';cartSkuSearch='';$('cartSkuFilter').value='';cartSearch=null;cartSetData(d.cart);
  $('cartNewName').value='';cartMsgClean();
  history.replaceState(null,'',location.pathname+'?cart='+d.cart.id);
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
  cartSetData(d.cart);cartNotice('✓ RELOADED');
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
    cartNotice(e.status===409?'資料已變更或庫存不足，請檢查數量；可重新載入。':e.message,true);
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
   cartSetData(d.cart);cartNotice('DRAFT · previous confirmation retained');
  }else{
   const d=await post('/scanner/api/cart/confirm',{
    cart_id:cartData.id,revision:cartData.revision
   });
   cartSetData(d.cart);
   cartNotice('✓ CONFIRMED V'+d.cart.confirmed_version+' · NOT RESERVAR');
   if(cartRole==='staff')void cartLoadList();
  }
 }catch(e){
  cartNotice(e.message,true);
  if(e.status===409)cartNotice('Cart changed. Please reload and check before confirming.',true);
 }finally{cartBusy=false;cartRender()}
}

async function cartShare(){
 if(cartRole!=='staff'||!cartData||cartBusy)return;
 if(cartPending.size&&!(await cartFlush()))return;
 cartBusy=true;
 try{
  const d=await post('/scanner/api/cart/share',{cart_id:cartData.id});
  cartGuestCode=d.guest_code;cartSetData(d.cart);
  cartNotice('已產生 8 小時臨時碼。舊臨時碼立即失效。');
 }catch(e){cartNotice(e.message,true)}finally{cartBusy=false;cartRender()}
}
async function cartGuestHandoff(){
 if(!cartData||cartRole!=='staff')return;
 if(cartPending.size&&!(await cartFlush()))return;
 if(!cartGuestCode)await cartShare();
 if(!cartGuestCode)return;
 if(!(await xwConfirm('将退出员工账号，访客只能操作当前购物车。返回员工功能需要重新登录。 / Se cerrará la sesión del personal.','访客模式 / Modo visita')))return;
 try{
  await stopCamera();
  await post('/scanner/api/cart/guest-login',{code:cartGuestCode});
  cartGuestCode='';cartRole='none';
  await session();
 }catch(e){cartNotice(e.message,true)}
}
async function cartLookup(input){
 if(mode!=='cart'||!cartData||cartLookupPending)return;
 const code=normalizeProductCode(input);
 if(!valid(code)){cartNotice('Invalid QR / SKU',true);return}
 cartLookupPending=true;busy=true;$('queryBtn').disabled=true;
 $('code').value=code;syncSearchClear();
 try{
  const d=await post('/scanner/api/cart/lookup',{cart_id:cartData.id,code});
  cartView='pick';cartSearch=d;cartAll=false;cartSkuSearch='';$('cartSkuFilter').value='';
  cartRender();cartMsgClean();
  if($('cameraToggle').getAttribute('aria-pressed')!=='true'){
   $('cartProducts').scrollIntoView({behavior:'smooth',block:'nearest'});
  }
 }catch(e){cartNotice(e.message,true)}
 finally{cartLookupPending=false;busy=false;$('queryBtn').disabled=false}
}
window.cartLookup=cartLookup;
window.cartIsReviewing=()=>cartView==='cart';
window.cartBootstrap=cartBootstrap;
window.cartApplyRole=cartApplyRole;
window.cartLoadList=cartLoadList;
$('cartNav').onclick=async()=>{
 if(cartRole!=='staff')return;
 if(mode==='cart'&&(cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 setMode(mode==='cart'?'sample':'cart');
 if(mode==='cart'){if(cartData)cartRender();else void cartLoadList()}
};
$('cartCreateBtn').onclick=cartCreate;
$('cartFilter').oninput=cartRenderList;
$('cartSkuFilter').oninput=()=>{cartSkuSearch=$('cartSkuFilter').value.trim();cartRender()};
$('cartShortCode').onclick=async()=>{
 if(!cartData)return;
 try{await navigator.clipboard.writeText(cartData.short_code);cartNotice('✓ CART ID COPIED')}
 catch(_){void xwCopyFallback('复制购物车编号 / Copiar ID',cartData.short_code)}
};
$('cartDetailsBtn').onclick=()=>{
 const meta=$('cartMeta'),hidden=meta.classList.toggle('hidden');
 $('cartDetailsBtn').setAttribute('aria-expanded',String(!hidden));
};
async function cartScanNow(){
 if(!cartData)return;
 cartView='pick';
 cartRender();
 if(!running){
  await startCamera();
 }
 const target=running?$('reader'):$('scanPanel');
 target.scrollIntoView({behavior:'smooth',block:'center'});
}
$('cartScanNow').onclick=cartScanNow;
$('cartSwitchView').onclick=async()=>{
 if(!cartData)return;
 if(cartView==='cart')await cartScanNow();
 else{cartView='cart';cartRender();$('cartWorkspace').scrollIntoView({behavior:'smooth',block:'start'})}
};
$('cartBack').onclick=async()=>{
 if((cartPending.size||cartSaveJob)&&!(await cartFlush()))return;
 cartClearTimer();cartPending.clear();cartData=null;cartSearch=null;cartGuestCode='';lastQrCode='';cartView='pick';cartSkuSearch='';
 history.replaceState(null,'',location.pathname);cartRender();void cartLoadList()
};
$('cartShareBtn').onclick=cartShare;
$('cartGuestCode').title='Tap to copy the temporary code';
$('cartGuestCode').onclick=async()=>{
 if(!cartGuestCode)return;
 try{await navigator.clipboard.writeText(cartGuestCode);cartNotice('✓ COPIED')}
 catch(_){void xwCopyFallback('访客码 / Código visita',cartGuestCode)}
};
$('cartGuestHandoff').onclick=cartGuestHandoff;
$('cartStateButton').onclick=cartSetState;
$('cartReload').onclick=cartRefresh;
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
$('cartEditName').onclick=async()=>{
 if(!cartData||cartRole!=='staff'||cartBusy)return;
 if(cartPending.size&&!(await cartFlush()))return;
 const name=await xwPrompt('客户 / Cliente',cartData.customer_name||'');
 if(name===null)return;
 cartBusy=true;
 try{
  const d=await post('/scanner/api/cart/name',{cart_id:cartData.id,revision:cartData.revision,name:name.trim()});
  cartSetData(d.cart);cartNotice('✓ SAVED');
 }catch(e){cartNotice(e.message,true);if(e.status===409)await cartRefresh()}finally{cartBusy=false}
};
$('cartCopy').onclick=async()=>{
 if(!cartData)return;
 if(cartPending.size&&!(await cartFlush()))return;
 const text=[cartData.short_code,cartData.customer_name,
  ...cartEffectiveItems().map(i=>i.sku+'\t'+i.qty)].filter(Boolean).join('\n');
 try{await navigator.clipboard.writeText(text);cartNotice('✓ COPIED')}
 catch(_){void xwCopyFallback('复制清单 / Copiar lista',text)}
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
