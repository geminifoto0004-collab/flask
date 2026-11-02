'use strict';
// Run: node xingwang_miniapp/tests/test_scanner_legacy_qr.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(base, 'scanner.html'), 'utf8');
const cart = fs.readFileSync(path.join(base, 'scanner_cart.js'), 'utf8');

// Exercise the real page parser, not a test-only copy.
const from = html.indexOf('const valid=s=>');
const to = html.indexOf('const skuCollator', from);
assert(from >= 0 && to > from, 'shared QR parser not found');
const parse = new Function(html.slice(from, to) + '\nreturn parseScannerQR;')();

const accepts = new Map([
  ['125G', '125G'],
  ['12-225D', '12-225D'],
  ['http://11.11.11.11:5000/scan/12-225D', '12-225D'],
  ['https://192.168.1.50/scan/125g', '125G'],
  ['HTTP://10.0.0.2:8080/SCAN/KC26001', 'KC26001'],
  ['http://127.0.0.1:5000/scan/12%2D225D', '12-225D'],
  ['http://11.11.11.11:5000/scan/125G/?ticket=ok#frag', '125G'],
  ['http://11.11.11.11:5000/scan/125G#top', '125G']
]);
const ignores = [
  'https://google.com/scan/125G',
  'https://11.11.11.11:5000/share/125G',
  'http://999.11.11.11:5000/scan/125G',
  'http://11.11.11.11:99999/scan/125G',
  'http://11.11.11.11:0/scan/125G',
  'http://11.11.11.11:5000/scan/125G/other',
  'http://11.11.11.11:5000/scan/12%2F225D',
  'http://11.11.11.11:5000/scan/%ZZ',
  'WIFI:T:WPA;S:Office;P:abc;;',
  'http://11.11.11.11:5000/login',
  'https://example.com/125G',
  '', '12 225', 'ftp://11.11.11.11/scan/125G'
];
for (const [raw, sku] of accepts) assert.equal(parse(raw), sku, raw);
for (const raw of ignores) assert.equal(parse(raw), null, raw);

const scan = html.split('function onScan(raw){')[1]?.split('async function startCamera(){')[0];
assert(scan, 'camera callback missing');
assert(scan.includes('const code=parseScannerQR(raw);'));
assert(scan.includes('if(!code)return;'));
assert(!scan.includes('QR 不是商品編號'));
assert(!scan.includes('stopCamera('));
assert(html.includes("await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});"));
assert(html.includes("$('saveBtn').onclick=async()=>{"));
assert(cart.includes('const code=parseScannerQR(input);'));
assert(cart.includes("const code=parseScannerQR(input||$('cartPublicCode').value);"));
assert(cart.includes('const code=parseScannerQR(decoded);'));

// Parse all real inline scripts and the cart controller for syntax regressions.
for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)) {
  if (match[1].trim()) new Function(match[1]);
}
new Function(cart);
console.log('Legacy QR parser and scanner entry points: 22 cases OK');
