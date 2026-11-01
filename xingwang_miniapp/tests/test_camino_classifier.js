'use strict';
/* Run: node xingwang_miniapp/tests/test_camino_classifier.js */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.resolve(__dirname,'../scanner_cart.js'),'utf8');
const start=src.indexOf('/* Camino order classification');
assert.ok(start>=0,'Classifier marker missing');
const context={window:{}};vm.createContext(context);vm.runInContext(src.slice(start),context);
const classify=context.window.XWCaminoOrder.classify;
function expect(description,kind,order='',customer=''){
 const out=classify({Descripcion:description});
 assert.equal(out.kind,kind,description);
 assert.equal(out.order_number,order,description);
 assert.equal(out.customer_name,customer,description);
 assert.equal(out.description,description,'raw description must survive');
}
expect('定单号：1008149 WALTER HERRERA 660克/米 公司封条 冷柜装柜量：3.2万米','customer','1008149','WALTER HERRERA');
expect('訂單號：KC26001 MARIA PEREZ 300cm 染色','customer','KC26001','MARIA PEREZ');
expect('订单号 G26001 MODA SUR 660克/米','customer','G26001','MODA SUR');
expect('PEDIDO 1008000 TEXTILES LIMA 400克/米','customer','1008000','TEXTILES LIMA');
expect('公司備貨 660克/米','company');
expect('補貨 300cm 12箱','company');
expect('STOCK PROPIO 45CAJAS','company');
expect('660克/米 公司封条 冷柜装柜量：3.2万米','unknown');
expect('没有订单号的描述 660克/米','unknown');
expect('订单号 1008000 660克/米','unknown','1008000','');
expect('订单号 1008000 MARIA 公司備貨','unknown','1008000','MARIA');
const missing=classify({code:'12-225D-1',caja:14});
assert.equal(missing.kind,'unknown');
assert.equal(missing.reason,'上游未提供 Descripcion');
const alias=classify({description:'定单号: G26001 MODA SUR 660克/米'});
assert.equal(alias.kind,'customer');
console.log('CAMINO CLASSIFIER 14 CASES PASS');
