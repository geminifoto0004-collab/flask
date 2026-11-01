"""Uppercase entry, natural and numeric table header sorting."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
def test_case_and_heading_sort():
 ui=(ROOT/'scanner.html').read_text(encoding='utf-8')
 for item in ('id="sampleSkuSort"','id="sampleRollsSort"','id="sampleMetersSort"',
              "new Intl.Collator('en',{numeric:true,sensitivity:'base})",
              "function setSampleSort(field)",
              "function normalizeCodeInput()",
              "$('code').addEventListener('input',normalizeCodeInput)",
              "const code=nota?String(input||'').trim():normalizeProductCode(input)"):
  assert item in ui,item
 for phrase in ('點相機圖示開啟／停止連續掃描；第一次請允許相機權限。','請掃描或輸入商品系列編號。'):
  assert phrase not in ui
def test_case_normalization_in_backend():
 api=(ROOT/'scanner_backend.py').read_text(encoding='utf-8')
 db=(ROOT/'scanner_tidb.py').read_text(encoding='utf-8')
 assert 'code = code.strip().upper()' in api
 assert db.count('code = code.strip().upper()') >= 2
 ast.parse(api);ast.parse(db)
