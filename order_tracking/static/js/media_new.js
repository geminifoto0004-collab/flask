/* Source dates are from local SQLite. Never use B2 created_at/updated_at. */
(() => {
'use strict';
const WEEK=7*24*60*60*1000;
function epoch(raw){if(!raw)return 0;const n=Number(raw);if(Number.isFinite(n)&&n>0)return n*1000;return 0}
function refresh(){const now=Date.now();
 const zh=(typeof window.getTrackingLanguage==='function'?window.getTrackingLanguage():localStorage.getItem('tracking_ui_language'))==='zh_cn';
 const label=zh?'新图':'NUEVO',hint=zh?'最近7天新增的图片':'Imágenes nuevas de los últimos 7 días';
 document.querySelectorAll('[data-guest-new-filter]').forEach(button=>{const text=button.querySelector('span');if(text&&text.textContent!==label)text.textContent=label;button.title=hint;button.setAttribute('aria-label',label+': '+hint)});
document.querySelectorAll('[data-media-uploaded-at]').forEach(node=>{
 const at=epoch(node.dataset.mediaUploadedAt);const fresh=at>0&&now>=at&&now-at<WEEK;
 if(node.textContent!==label)node.textContent=label;
 node.title=hint;
 node.classList.toggle('media-new-active',fresh);node.hidden=!fresh;
})}
window.orderMediaIsNew=(at,now=Date.now())=>{const value=epoch(at);return value>0&&now>=value&&now-value<WEEK};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh);else refresh();
new MutationObserver(refresh).observe(document.documentElement,{childList:true,subtree:true});
document.addEventListener('tracking:languagechange',refresh);
setInterval(refresh,60000);
})();
