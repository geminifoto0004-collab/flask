/* XINGWANG Browser-only Excel parser. Excel file is NEVER uploaded. */
(function(){
"use strict";
const $=id=>document.getElementById(id);
const state={records:[],file:null,scanned:0,excluded:0,skipped:0,page:1,busy:false};
const PAGE=45;
function say(msg){const e=$("toast");e.textContent=msg;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),5500)}
function nowChile(){const v=Object.fromEntries(new Intl.DateTimeFormat("en-US",{timeZone:"America/Santiago",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date()).map(x=>[x.type,x.value]));return v.year+"-"+v.month+"-"+v.day}
function shiftMonths(s,n){let [y,m,d]=s.split("-").map(Number);m+=n;while(m<=0){m+=12;y--}while(m>12){m-=12;y++}const last=new Date(Date.UTC(y,m,0)).getUTCDate();return y+"-"+pad(m)+"-"+pad(Math.min(d,last))}
function pad(n){return String(n).padStart(2,"0")}
function recent(){const d=nowChile();$("toDate").value=d;$("fromDate").value=shiftMonths(d,-3)}
recent();
function norm(s){return String(s??"").normalize("NFKC").replace(/\u00a0/g," ").trim()}
function isoYMD(y,m,d){y=Number(y);m=Number(m);d=Number(d);if(y<100)y+=y>=80?1900:2000;if(y<2000||y>2099||m<1||m>12||d<1||d>31)return null;const z=new Date(Date.UTC(y,m-1,d));return z.getUTCFullYear()===y&&z.getUTCMonth()===m-1&&z.getUTCDate()===d?y+"-"+pad(m)+"-"+pad(d):null}
function parseDate(v){
 if(v instanceof Date && !Number.isNaN(v.getTime()))return isoYMD(v.getFullYear(),v.getMonth()+1,v.getDate());
 const s=norm(v);if(!s)return null;
 let m=s.match(/(?:^|[^0-9])((?:20)?[0-9]{2})\s*年\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日?/);
 if(!m)m=s.match(/(?:^|[^0-9])((?:20)?[0-9]{2})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})(?![0-9])/);
 return m?isoYMD(m[1],m[2],m[3]):null;
}
function normCode(s){return norm(s).toUpperCase().replace(/[\s._·-]+/g,"")}
function validCode(s){return /^[A-Z]{4}[0-9]{7}$/.test(s)}
function daysVal(s){const x=norm(s);if(!/^\d{1,3}(?:\.0+)?$/.test(x))return null;const n=Number(x);return Number.isInteger(n)&&n>=1&&n<=120?n:null}
function headerRow(rows){for(let i=0;i<Math.min(35,rows.length);i++){const a=norm(rows[i]?.[0]).replace(/\s/g,""),c=norm(rows[i]?.[2]).replace(/\s/g,""),h=norm(rows[i]?.[7]).replace(/\s/g,"");if(/装[柜櫃]时间|裝[柜櫃]時間|装[柜櫃]日期|裝[柜櫃]日期/.test(a)&&/箱[号號]|[柜櫃][号號]/.test(c)&&/免用|免箱|FREE/i.test(h))return i}return -1}
function inRange(s){return !!s&&s>=$("fromDate").value&&s<=$("toDate").value}
function flags(){
 const codes=new Map();
 for(const r of state.records){r.issues=[];if(!r.date)r.issues.push("缺少日期");else if(!inRange(r.date))r.issues.push("日期超出範圍");if(!validCode(r.container))r.issues.push("貨櫃號碼錯誤");if(r.days===null)r.issues.push("未提供免箱天數");r.invalid=r.issues.length>0;r.duplicate=false;r.conflict=false;
 if(validCode(r.container)){if(!codes.has(r.container))codes.set(r.container,[]);codes.get(r.container).push(r)}}
 for(const arr of codes.values())if(arr.length>1){
 const diffs=new Set(arr.map(r=>[r.date,r.loadingText,r.days,norm(r.remark)].join("|")));
 arr.forEach(r=>r[diffs.size===1?"duplicate":"conflict"]=true);}
 const seen=new Set();
 for(const r of state.records.slice().reverse()){if(r.invalid)r.selected=false;if(r.selected){if(seen.has(r.container))r.selected=false;else seen.add(r.container)}}
}
function safeSelect(){state.records.forEach(r=>r.selected=false);flags();const seen=new Set();for(const r of state.records.slice().reverse()){if(!r.invalid&&!r.conflict&&!seen.has(r.container)){r.selected=true;seen.add(r.container)}}flags();render()}
function make(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function matching(){const q=norm($("search").value).toUpperCase(),filter=$("filter").value;return state.records.filter(r=>(!q||[r.container,r.remark,r.loadingText,r.sheet,r.date].join(" ").toUpperCase().includes(q))&&
(filter==="all"||(filter==="selected"&&r.selected)||(filter==="problems"&&(r.invalid||r.conflict))||(filter==="duplicate"&&r.duplicate)))}
function cellInput(r,key,type){const e=make("input");e.type=type;e.value=r[key]??"";if(key==="days"){e.min=1;e.max=120;e.step=1}e.setAttribute("aria-label",r.sheet+" 第"+r.row+"列 "+key);
e.addEventListener("change",()=>{const old=r.container;
 if(key==="date")r.date=e.value;
 else if(key==="container")r.container=normCode(e.value);
 else if(key==="days")r.days=daysVal(e.value);
 else r.remark=norm(e.value);
 if(key==="container"&&r.container!==old)r.selected=false;
 flags();render()});return e}
function render(){
 flags();const all=state.records,selected=all.filter(r=>r.selected&&!r.invalid).length;
 $("sheets").textContent=state.file?state.scanned:"—";$("found").textContent=state.file?all.length:"—";
 $("selected").textContent=state.file?selected:"—";$("dup").textContent=state.file?all.filter(r=>r.duplicate&&!r.selected).length:"—";
 $("problems").textContent=state.file?all.filter(r=>r.invalid||r.conflict).length:"—";
 $("commit").disabled=$("csv").disabled=$("json").disabled=selected===0||state.busy;
 $("selectionInfo").textContent=state.file?"已選 "+selected+" 筆。只會送出裝櫃日期、A欄原文、箱號、備註及天數，不會上傳 Excel。":"請先選擇 Excel";
 const warning=[];if(state.skipped)warning.push(state.skipped+" 張工作表未找到 A/C/H 標題，已跳過");
 if(state.excluded)warning.push(state.excluded+" 筆日期超出範圍，已略過");
 const invalid=all.filter(r=>r.invalid||r.conflict).length;if(invalid)warning.push(invalid+" 筆衝突或天數不完整，請檢查紅色／黃色紀錄");
 $("issues").classList.toggle("show",warning.length>0);$("issues").textContent=warning.join("；");
 const list=matching(),pages=Math.max(1,Math.ceil(list.length/PAGE));state.page=Math.min(state.page,pages);
 const start=(state.page-1)*PAGE;$("tbody").replaceChildren();
 if(!list.length){const tr=make("tr"),td=make("td","",state.file?"目前篩選沒有紀錄":"請先選 Excel");td.colSpan=9;td.style.padding="40px";td.style.textAlign="center";tr.append(td);$("tbody").append(tr)}
 for(const r of list.slice(start,start+PAGE)){
 const tr=make("tr",r.invalid?"invalid":r.conflict?"conflict":r.duplicate&&!r.selected?"duplicate":r.selected?"selected":"");
 const checktd=make("td"),ck=make("input");ck.type="checkbox";ck.checked=r.selected;ck.disabled=r.invalid;
 ck.addEventListener("change",()=>{r.selected=ck.checked;if(r.selected)all.forEach(other=>{if(other!==r&&other.container===r.container)other.selected=false});render()});
 checktd.append(ck);tr.append(checktd);
 for(const [field,type] of [["date","date"]]){const td=make("td");td.append(cellInput(r,field,type));tr.append(td)}
 const original=make("td","original");original.append(make("div","",r.loadingText||"—"));if(r.inherited)original.append(make("small","","↳ 沿用上方完整原文"));tr.append(original);
 for(const [field,type] of [["container","text"],["remark","text"],["days","number"]]){const td=make("td");td.append(cellInput(r,field,type));tr.append(td)}
 const status=make("td","status "+(r.invalid?"bad":r.conflict?"warn":"good"),r.invalid?r.issues.join("／"):r.conflict?"衝突 · 請選一筆":r.duplicate?"重複 · 保留一筆":"正常");tr.append(status);
 const sheet=make("td","",r.sheet);sheet.title=r.sheet;tr.append(sheet,make("td","",String(r.row)));$("tbody").append(tr)
 }
 $("pageInfo").textContent="顯示 "+(list.length?start+1:0)+"～"+Math.min(list.length,start+PAGE)+" / "+list.length+" · 第 "+state.page+"/"+pages+" 頁";
 $("prev").disabled=state.page<=1;$("next").disabled=state.page>=pages;
}
async function readFile(file){
 if(!file||state.busy)return;
 if(!/\.(xls|xlsx|xlsm)$/i.test(file.name)){say("請選擇 Excel .xls/.xlsx/.xlsm");return}
 if(!window.XLSX){say("Excel 解析器未載入");return}
 if(!$("fromDate").value||!$("toDate").value||$("fromDate").value>$("toDate").value){say("日期範圍不正確");return}
 state.busy=true;state.records=[];state.scanned=0;state.skipped=0;state.excluded=0;state.page=1;state.file=null;$("progress").textContent="讀取檔案中…";render();
 try{
 const wb=XLSX.read(await file.arrayBuffer(),{type:"array",cellDates:true,cellFormula:false});
 for(let si=0;si<wb.SheetNames.length;si++){
 const sheetName=wb.SheetNames[si],sheet=wb.Sheets[sheetName];state.scanned++;
 if(!sheet||!sheet["!ref"]){state.skipped++;continue}
 const range=XLSX.utils.decode_range(sheet["!ref"]);
 const rows=XLSX.utils.sheet_to_json(sheet,{header:1,raw:false,defval:"",blankrows:true});
 const hi=headerRow(rows);if(hi<0){state.skipped++;continue}
 let dateText=null,loadingText="";
 for(let i=hi+1;i<rows.length;i++){
 const row=rows[i]||[],rawA=String(row[0]??""),a=norm(rawA),code=normCode(row[2]),remark=norm(row[5]),h=norm(row[7]);
 if(a){dateText=parseDate(a);loadingText=rawA}
 if(!code&&!h)continue;
 if(dateText&&!inRange(dateText)){state.excluded++;continue}
 if(!dateText&&!code)continue;
 state.records.push({id:state.records.length+1,sheet:sheetName,row:range.s.r+i+1,order:si,date:dateText||"",loadingText,container:code,remark,days:daysVal(h),inherited:!a,selected:false});
 }
 if(si%15===0){$("progress").textContent="掃描 "+(si+1)+" / "+wb.SheetNames.length+" 張工作表";await new Promise(resolve=>setTimeout(resolve,0))}
 }
 state.file=file;state.records.sort((a,b)=>b.date.localeCompare(a.date)||b.order-a.order||b.row-a.row);safeSelect();
 $("fileStatus").textContent=file.name+" · "+(file.size/1024).toFixed(1)+" KB · "+state.scanned+" 張工作表";
 $("progress").textContent="掃描完成："+state.records.length+" 筆";
 say("已找到 "+state.records.length+" 筆貨櫃");
 }catch(err){console.error(err);state.records=[];state.file=null;$("progress").textContent="讀取失敗";say("Excel 讀取失敗："+err.message)}
 finally{state.busy=false;render()}
}
function payload(){const records=state.records.filter(r=>r.selected&&!r.invalid).map(r=>({loading_date:r.date,loading_text:r.loadingText,container_no:r.container,remark:r.remark,free_days:r.days}));return {format:"xingwang-container-import-v1",date_from:$("fromDate").value,date_to:$("toDate").value,records,count:records.length}}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=make("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$("json").addEventListener("click",()=>download("XINGWANG_ACFH.json",JSON.stringify(payload(),null,2),"application/json"));
$("csv").addEventListener("click",()=>{const q=s=>'"'+String(s??"").replace(/"/g,'""')+'"';const data=payload().records;const rows=[["裝櫃日期","A欄原文","箱號","備註","免箱天數"],...data.map(r=>[r.loading_date,r.loading_text,r.container_no,r.remark,r.free_days])];download("XINGWANG_ACFH.csv","\uFEFF"+rows.map(x=>x.map(q).join(",")).join("\r\n"),"text/csv;charset=utf-8")});
$("commit").addEventListener("click",async()=>{
 const body=payload();if(!body.count)return;
 if(!window.confirm("確認將 "+body.count+" 筆選中的貨櫃資料寫入 TiDB？不會上傳原始 Excel。"))return;
 state.busy=true;render();$("commit").textContent="寫入中…";
 try{
 const response=await fetch("/api/admin/container-excel/commit",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json","X-Requested-With":"XMLHttpRequest"},body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok&&response.status!==207||!result.success)throw new Error(result.error||"TiDB 寫入失敗");
 const info=Object.entries(result.totals||{}).map(([k,v])=>k+":"+v+"筆").join(" / ");
 say("已寫入 "+result.count+" 筆："+info+(result.warning?"；"+result.warning:""));
 $("progress").textContent="TiDB 已保存 "+result.count+" 筆；"+(result.warning||"兩端成功");
 refreshDb();
 }catch(e){say(e.message||"寫入失敗")}finally{state.busy=false;$("commit").textContent="確認寫入 TiDB";render()}
});
async function refreshDb(){try{const r=await fetch("/api/admin/container-excel/status",{credentials:"same-origin",cache:"no-store"});const d=await r.json();if(!d.success)throw Error("無法讀取");$("dbState").textContent=Object.entries(d.databases).map(([k,v])=>k+": "+(v.ready?v.rows+"筆":"尚未建表／離線")).join(" · ")}catch(e){$("dbState").textContent="TiDB 狀態無法讀取"}}
$("drop").addEventListener("click",e=>{if(e.target.id!=="browse")$("file").click()});
$("browse").addEventListener("click",e=>{e.stopPropagation();$("file").click()});
$("drop").addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();$("file").click()}});
$("file").addEventListener("change",e=>{if(e.target.files?.[0])readFile(e.target.files[0]);e.target.value=""});
for(const event of ["dragenter","dragover"]){$("drop").addEventListener(event,e=>{e.preventDefault();$("drop").classList.add("drag")})}
for(const event of ["dragleave","drop"]){$("drop").addEventListener(event,e=>{e.preventDefault();$("drop").classList.remove("drag")})}
$("drop").addEventListener("drop",e=>{if(e.dataTransfer?.files?.[0])readFile(e.dataTransfer.files[0])});
$("search").addEventListener("input",()=>{state.page=1;render()});$("filter").addEventListener("change",()=>{state.page=1;render()});
$("prev").addEventListener("click",()=>{state.page--;render()});$("next").addEventListener("click",()=>{state.page++;render()});
$("safe").addEventListener("click",()=>{safeSelect();say("已重選有效且無衝突的貨櫃")});
$("clear").addEventListener("click",()=>{state.records.forEach(r=>r.selected=false);render()});
async function rescan(){if(state.file)await readFile(state.file)}
$("recent").addEventListener("click",()=>{recent();rescan()});$("fromDate").addEventListener("change",rescan);$("toDate").addEventListener("change",rescan);
render();refreshDb();
})();
