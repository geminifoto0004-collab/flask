"""Product SKU input case and natural ordering in scanner UI."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
def test_ui_sku_uppercase_and_natural_sort():
 ui=(ROOT/'scanner.html').read_text('utf-8')
 for chunk in ('id="sampleSkuSort"',
              "new Intl.Collator('en',{numeric:true,sensitivity:'base})",
              "compareSkus(a.code,b.code)*(sampleDescending?-1:1)",
              "sortTitle.setAttribute('aria-sort'",
              "$('sampleSkuSort').onclick=toggleSampleSort",
              "$('sampleSkuSort').onkeydown=",
              "$('code').addEventListener('input',normalizeCodeInput)",
              "const code=nota?String(input||'').trim():normalizeProductCode(input)",
              "fullSort=fullKind==='product'?'code':''"):
  assert chunk in ui,chunk
 for chunk in ('點相機圖示開啟／停止連續掃描；第一次請允許相機權限。','請掃描或輸入商品系列編號。'):
  assert chunk not in ui
def test_api_case_normalized():
 api=(ROOT/'scanner_backend.py').read_text('utf-8')
 db=(ROOT/'scanner_tidb.py').read_text('utf-8')
 assert 'code = code.strip().upper()' in api
 assert db.count('code = code.strip().upper()') >= 2
 ast.parse(api);ast.parse(db)
