'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

class FakeNode {
  constructor(tag, value, klass) {
    this.tag = tag;
    this.textContent = value === undefined ? '' : String(value);
    this.className = klass || '';
    this.children = [];
    this.isConnected = true;
    this.zoomed = false;
    this.classList = {toggle: () => { this.zoomed = !this.zoomed; }};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this.textContent = ''; }
}
function allNodes(root, tag) {
  return [root, ...root.children.flatMap(child => allNodes(child, tag))]
    .filter(node => node.tag === tag);
}
function textOf(root) {
  return [root.textContent, ...root.children.map(textOf)].join(' ');
}
function gallery(fetchMock) {
  const first = html.indexOf('function zoomableNotaImage(');
  const last = html.indexOf('async function loadNotaMedia(', first);
  assert(first >= 0 && last > first, 'Cloud gallery code must remain in its owning module');
  const code = html.slice(first, last);
  const sandbox = {
    fetch: fetchMock,
    node: (tag, value, klass) => new FakeNode(tag, value, klass),
  };
  vm.runInNewContext(code + '\nthis.appendNotaCloudPhotos = appendNotaCloudPhotos;', sandbox);
  return sandbox.appendNotaCloudPhotos;
}

test('the full browser script remains valid JavaScript', () => {
  const opening = html.indexOf('<script>', html.indexOf('</style>'));
  const ending = html.lastIndexOf('</script>');
  assert(opening>=0&&ending>opening);
  const script=html.slice(opening+'<script>'.length,ending);
  assert.doesNotThrow(()=>new vm.Script(script, {filename:'index-inline.js'}));
});

test('existing local preview and read-only media contract are preserved', () => {
  assert(html.includes("action:'nota_media'"));
  assert(html.includes('data:image/jpeg;base64,'));
  assert(html.includes("classList.toggle('zoomed')"));
  assert(html.includes('init_data:tg.initData'));
  assert(html.includes('mediaCache'));
});

test('cloud photos appear inline, never as an external link, and zoom inside Mini App', async () => {
  const photos = ['/public/nota-images/44833/11','/public/nota-images/44833/12'];
  const append = gallery(async () => ({ok:true,json:async()=>({
    nota:'44833', found:true,image_count:2,truncated:false,images:photos,
    view_url:'/public/nota-images/44833'
  })}));
  const host = new FakeNode('div');
  await append(host, '44833');
  const imgs = allNodes(host, 'img');
  assert.equal(imgs.length, 2, 'Each confirmed image needs an inline thumbnail');
  assert.equal(allNodes(host,'a').length, 0, 'No external gallery links');
  assert.equal(imgs[0].src, 'https://xingwang-nota.onrender.com'+photos[0]);
  const frames = allNodes(host, 'div').filter(n=>n.className==='nota-media-imagebox');
  assert.equal(frames.length, 2);
  assert.equal(typeof imgs[0].onclick,'function');
  imgs[0].onclick();
  assert.equal(frames[0].zoomed, true);
});

test('no NOTA photos and cloud failures never break the surrounding card', async () => {
  const empty = gallery(async()=>({ok:true,json:async()=>({
    nota:'44833',found:false,image_count:0,images:[],view_url:null
  })}));
  const host = new FakeNode('div');
  await empty(host,'44833');
  assert.equal(allNodes(host,'img').length,0);
  assert.match(textOf(host),/暂[无时].*照片/);
  const offline = gallery(async()=>{throw Error('network unreachable');});
  const fallback = new FakeNode('div');
  await offline(fallback,'44833');
  assert.equal(allNodes(fallback,'img').length,0);
  assert.match(textOf(fallback),/暂时无法查询/);
});

test('cloud photo failure does not hide local media content', async () => {
  const append=gallery(async()=>{throw Error('cloud is offline');});
  const host=new FakeNode('div');
  const local=new FakeNode('div', '已找到本机重量 20 KG');
  host.append(local);
  await append(host,'44833');
  assert.equal(allNodes(host,'img').length,0);
  assert.match(textOf(host),/本机重量 20 KG/);
  assert.match(textOf(host),/暂时无法查询/);
});

test('unsafe image paths cannot be used as remote image sources', async () => {
  const append = gallery(async()=>({ok:true,json:async()=>({
    nota:'44833',found:true,image_count:1,
    images:['https://attacker.invalid/photo'],view_url:'/public/nota-images/44833'
  })}));
  const host = new FakeNode('div');
  await append(host,'44833');
  assert.equal(allNodes(host,'img').length,0);
});

test('visible NOTA cards load automatically, without another button click', () => {
  assert(html.includes('new IntersectionObserver('));
  assert(html.includes('loadNotaMedia(doc,host)'));
  assert(!html.includes('button.onclick=()=>loadNotaMedia(doc,button,host)'));
  assert(!html.includes("link.target='_blank'"));
});
