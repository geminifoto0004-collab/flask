/* Source dates are from local SQLite. Never use B2 created_at/updated_at. */
(() => {
'use strict';
const WEEK=7*24*60*60*1000;
function epoch(raw){if(!raw)return 0;const n=Number(raw);if(Number.isFinite(n)&&n>0)return n*1000;return 0}
function refresh(){const now=Date.now();document.querySelectorAll('[data-media-uploaded-at]').forEach(node=>{
 const at=epoch(node.dataset.mediaUploadedAt);const fresh=at>0&&now>=at&&now-at<WEEK;
 node.classList.toggle('media-new-active',fresh);node.hidden=!fresh;
})}
window.orderMediaIsNew=(at,now=Date.now())=>{const value=epoch(at);return value>0&&now>=value&&now-value<WEEK};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh);else refresh();
new MutationObserver(refresh).observe(document.documentElement,{childList:true,subtree:true});
setInterval(refresh,60000);
})();
