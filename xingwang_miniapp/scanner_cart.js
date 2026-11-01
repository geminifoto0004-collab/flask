'use strict';
// Cart controller for the existing /scanner page. Guest can access cart endpoints
// only; staff-only DOM is also removed from the guest presentation.
let cartRole='none', cartData=null, cartSearch=null, cartGuestCode='',cartBusy=false;
let cartAll=false,cartRecent=[],cartLookupPending=false;
const cartText=(id,text)=>{const el=document.getElementById(id);if(el)el.textContent=text};
function cartNotice(text,bad=false){
 const n=$('cartMessage');n.textContent=text||'';n.className=bad?'error':'';
 if(bad)msg(text,'error');
}
function cartLocalTime(value){
 if(!value)return '—';
 const d=new Date(value);return Number.isFinite(d.valueOf())?d.toLocaleString('es-CL',{timeZone:'America/Santiago',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';
}
function cartMsgClean(){
 cartNotice('');msg('');
}
function cartItemQty(sku){return Number(cartData?.items?.find(i=>i.sku===sku)?.qty||0)}
function cartSum(){return (cartData?.items||[]).reduce((n,i)=>n+i.qty,0)}
function cartUpdateHeader(){
 $('cartNavCount').textContent=String(cartSum());
 if(!cartData)return;
 cartText('cartShortCode',cartData.short_code);
 cartText('cartStateLabel',cartData.state==='ready'?'READY':'OPEN');
 cartText('cartCustomerLabel',cartData.customer_name||'CUSTOMER');
 cartText('cartTotal',String(cartSum()));
 cartText('cartSavedAt',cartLocalTime(cartData.updated_at));
 cartText('cartGuestCode',cartGuestCode||'········');
 $('cartGuestCode').classList.toggle('cart-code-empty',!cartGuestCode);
 $('cartShareRow').classList.toggle('hidden',cartRole!=='staff');
 $('cartEditName').classList.toggle('hidden',cartRole!=='staff');
 $('cartBack').classList.toggle('hidden',cartRole!=='staff');
 $('cartStateButton').textContent=cartData.state==='ready'?'REOPEN':'✓ READY';
 $('cartStateButton').title=cartData.state==='ready'?'繼續選貨':'完成選貨（不等於正式預定）';
}
function cartSetData(data){
 cartData=data;
 if(data)cartRender();
}
function cartRow(sku,qty,stockValue,fromSearch){
 const row=document.createElement('div');row.className='cart-line';
 const left=document.createElement('div');left.className='cart-line-title';
 const name=document.createElement('strong');name.textContent=sku;
 const stock=document.createElement('small');
 const n=stockValue==null||String(stockValue).trim()===''?null:Number(stockValue);
 const available=n!=null&&Number.isFinite(n)?Math.max(0,Math.floor(n)):null;
 stock.textContent=fromSearch?('STOCK '+(available===null?'—':fmt(available))+' ROLL'):''; 
 if(fromSearch&&available===0)stock.classList.add('cart-out');
 left.append(name,stock);row.append(left);
 const controls=document.createElement('div');controls.className='cart-qty-controls';
 const dec=document.createElement('button');dec.className='secondary';dec.textContent='−';dec.type='button';dec.setAttribute('aria-label',sku+' minus');
 const value=document.createElement('strong');value.textContent=String(qty);value.className='cart-qty';
 const inc=document.createElement('button');inc.className='secondary';inc.textContent='+';inc.type='button';inc.setAttribute('aria-label',sku+' plus');
 dec.disabled=cartBusy||qty===0;
 inc.disabled=cartBusy|| (fromSearch?available===null||qty>=available:qty>=9999);
 dec.onclick=()=>cartChange(sku,Math.max(0,cartItemQty(sku)-1));
 inc.onclick=()=>cartChange(sku,cartItemQty(sku)+1);
 controls.append(dec,value,inc);row.append(controls);
 return row;
}
function cartRender(){
 const isGuest=cartRole==='guest',hasCart=Boolean(cartData);
 $('cartStart').classList.toggle('hidden',isGuest||hasCart);
 if(mode==='cart')$('scanPanel').classList.toggle('hidden',!hasCart);
 $('cartActive').classList.toggle('hidden',!hasCart);
 $('cartStaffList').classList.toggle('hidden',isGuest||hasCart);
 if(!hasCart)return;
 cartUpdateHeader();
 const host=$('cartItems');host.replaceChildren();
 const rows=cartData.items||[];
 if(!rows.length){
  const empty=document.createElement('p');empty.className='muted';empty.textContent='0 ROLL · Scan QR';host.append(empty);
 }
 for(const item of rows)host.append(cartRow(item.sku,item.qty,null,false));
 const products=$('cartProducts');products.replaceChildren();
 if(cartSearch){
  const header=document.createElement('div');header.className='cart-products-head';
  const title=document.createElement('strong');title.textContent=cartSearch.product_code;
  const time=document.createElement('small');time.textContent='STOCK '+cartLocalTime(cartSearch.as_of);
  header.append(title,time);products.append(header);
  const all=Array.isArray(cartSearch.variants)?cartSearch.variants:[];
  const positive=all.filter(v=>Number(v.stock_rolls)>0);
  const bar=document.createElement('div');bar.className='cart-filter';
  for(const [key,label,count] of [[false,'>0',positive.length],[true,'ALL',all.length]]){
   const button=document.createElement('button');button.type='button';button.textContent=count+' '+label;
   button.className=cartAll===key?'active':'';
   button.onclick=()=>{cartAll=key;cartRender()};bar.append(button);
  }
  products.append(bar);
  const selected=cartAll?all:positive;
  if(!selected.length){
   const empty=document.createElement('p');empty.className='muted';empty.textContent='0 STOCK · ALL';products.append(empty);
  }
  for(const v of selected)products.append(cartRow(v.code,cartItemQty(v.code),v.stock_rolls,true));
  $('cartStockNote').classList.remove('hidden');
  $('cartStockNote').textContent='STOCK = Access/TiDB 快照參考，RESERVAR 尚未獨立核算。正式開單前須再次確認。';
 }else{
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
 if(changed){cartData=null;cartSearch=null;cartGuestCode='';cartRecent=[];}
 cartApplyRole();
 if(role==='guest'){
  // Drop staff-only query results when a company phone becomes a guest device.
  current=null;fullData=null;
  $('rows').replaceChildren();$('fullDetails').replaceChildren();$('totals').replaceChildren();
  setMode('cart'); 
  try{
   const d=await post('/scanner/api/cart/open',{cart_id:guestId});
   cartSetData(d.cart);cartNotice('');
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
  const desc=document.createElement('small');desc.textContent=(item.customer_name||'CUSTOMER')+' · '+cartLocalTime(item.updated_at);
  left.append(id,desc);
  const right=document.createElement('span');right.textContent=item.qty_total+' ROLL';
  btn.append(left,right);btn.onclick=()=>cartOpen(item.id);
  host.append(btn);
 }
}
async function cartOpen(id){
 if(cartBusy)return;cartBusy=true;
 try{const d=await post('/scanner/api/cart/open',{cart_id:id});cartGuestCode='';cartSearch=null;cartSetData(d.cart);cartMsgClean();
  if(cartRole==='staff')history.replaceState(null,'',location.pathname+'?cart='+id);}
 catch(e){cartNotice(e.message,true)}
 finally{cartBusy=false;cartRender()}
}
async function cartCreate(){
 if(cartBusy)return;cartBusy=true;$('cartCreateBtn').disabled=true;
 try{
  const d=await post('/scanner/api/cart/create',{name:$('cartNewName').value.trim()});
  cartGuestCode=d.guest_code;cartSearch=null;cartSetData(d.cart);
  $('cartNewName').value='';cartMsgClean();
  history.replaceState(null,'',location.pathname+'?cart='+d.cart.id);
 }catch(e){cartNotice(e.message,true)}
 finally{cartBusy=false;$('cartCreateBtn').disabled=false;cartRender()}
}
async function cartRefresh(){
 if(!cartData)return;
 try{const d=await post('/scanner/api/cart/open',{cart_id:cartData.id});cartSetData(d.cart)}
 catch(e){cartNotice(e.message,true)}
}
async function cartChange(sku,qty){
 if(!cartData||cartBusy||!Number.isInteger(qty))return;
 cartBusy=true;
 try{
  const d=await post('/scanner/api/cart/item',{cart_id:cartData.id,revision:cartData.revision,sku,qty});
  cartSetData(d.cart);cartNotice('✓ SAVED','');
 }catch(e){
  cartNotice(e.message,true);
  if(e.status===409)await cartRefresh();
 }finally{cartBusy=false;cartRender()}
}
async function cartSetState(){
 if(!cartData||cartBusy)return;
 cartBusy=true;
 try{
  const state=cartData.state==='ready'?'open':'ready';
  const d=await post('/scanner/api/cart/state',{cart_id:cartData.id,revision:cartData.revision,state});
  cartSetData(d.cart);
  cartNotice(state==='ready'?'✓ READY · 非正式 RESERVAR':'✓ OPEN');
 }catch(e){cartNotice(e.message,true);if(e.status===409)await cartRefresh()}
 finally{cartBusy=false}
}
async function cartShare(){
 if(cartRole!=='staff'||!cartData||cartBusy)return;
 cartBusy=true;
 try{
  const d=await post('/scanner/api/cart/share',{cart_id:cartData.id});
  cartGuestCode=d.guest_code;cartSetData(d.cart);
  cartNotice('已產生 8 小時臨時碼。舊臨時碼立即失效。');
 }catch(e){cartNotice(e.message,true)}finally{cartBusy=false;cartRender()}
}
async function cartGuestHandoff(){
 if(!cartData||cartRole!=='staff')return;
 if(!cartGuestCode)await cartShare();
 if(!cartGuestCode)return;
 if(!confirm('交給客人後會登出公司員工帳號，返回員工功能需要重新登入。確定？'))return;
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
  cartSearch=d;cartAll=false;cartRender();
  cartMsgClean();
 }catch(e){cartNotice(e.message,true)}
 finally{cartLookupPending=false;busy=false;$('queryBtn').disabled=false}
}
window.cartLookup=cartLookup;
window.cartBootstrap=cartBootstrap;
window.cartApplyRole=cartApplyRole;
window.cartLoadList=cartLoadList;
$('cartNav').onclick=()=>{
 if(cartRole==='staff'){
  setMode(mode==='cart'?'sample':'cart');
  if(mode==='cart'){if(cartData)cartRender();else void cartLoadList()}
 }
};
$('cartCreateBtn').onclick=cartCreate;
$('cartFilter').oninput=cartRenderList;
$('cartBack').onclick=()=>{cartData=null;cartSearch=null;cartGuestCode='';history.replaceState(null,'',location.pathname);cartRender();void cartLoadList()};
$('cartShareBtn').onclick=cartShare;
$('cartGuestCode').title='Tap to copy the temporary code';
$('cartGuestCode').onclick=async()=>{
 if(!cartGuestCode)return;
 try{await navigator.clipboard.writeText(cartGuestCode);cartNotice('✓ COPIED')}
 catch(_){window.prompt('Temporary code',cartGuestCode)}
};
$('cartGuestHandoff').onclick=cartGuestHandoff;
$('cartStateButton').onclick=cartSetState;
$('cartReload').onclick=cartRefresh;
$('cartEditName').onclick=async()=>{
 if(!cartData||cartRole!=='staff'||cartBusy)return;
 const name=prompt('Customer / Cliente',cartData.customer_name||'');
 if(name===null)return;
 cartBusy=true;
 try{
  const d=await post('/scanner/api/cart/name',{cart_id:cartData.id,revision:cartData.revision,name:name.trim()});
  cartSetData(d.cart);cartNotice('✓ SAVED');
 }catch(e){cartNotice(e.message,true);if(e.status===409)await cartRefresh()}finally{cartBusy=false}
};
$('cartCopy').onclick=async()=>{
 if(!cartData)return;
 const text=[cartData.short_code,cartData.customer_name,
  ...(cartData.items||[]).map(i=>i.sku+'\t'+i.qty)].filter(Boolean).join('\n');
 try{await navigator.clipboard.writeText(text);cartNotice('✓ COPIED')}
 catch(_){window.prompt('Copy cart',text)}
};
$('guestLoginBtn').onclick=async()=>{
 const code=$('guestCode').value.trim(),button=$('guestLoginBtn');button.disabled=true;
 try{
  await post('/scanner/api/cart/guest-login',{code});
  $('guestCode').value='';await session();
 }catch(e){$('loginMessage').textContent=e.message}finally{button.disabled=false}
};
$('guestCode').addEventListener('keydown',e=>{if(e.key==='Enter')$('guestLoginBtn').click()});
