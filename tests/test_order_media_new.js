const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const runtime={window:{},document:{readyState:'complete',querySelectorAll:()=>[],documentElement:{}},MutationObserver:class{observe(){}},setInterval(){},Date,Number};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../order_tracking/static/js/media_new.js'),'utf8'),runtime);
const isNew=runtime.window.orderMediaIsNew,now=1700000000000,WEEK=7*86400;
assert(isNew(now/1000-1,now));assert(isNew(now/1000-WEEK+1,now));assert(!isNew(now/1000-WEEK,now));
assert(!isNew(now/1000-WEEK-1,now));assert(!isNew(now/1000+1,now));assert(!isNew(0,now));
console.log('NEW source-clock boundaries passed');
