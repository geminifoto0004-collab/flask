"""Two work tabs, continuous camera and table-header bulk control."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_two_tabs_and_camera():
 s=(ROOT/'scanner.html').read_text(encoding='utf-8')
 for id in ('modeSample','modeFull','cameraToggle','samplePositiveBtn','sampleAllBtn','adminTab','sampleHeaderCheck'):
  assert 'id="'+id+'"' in s
 for id in ('modeStock','cameraStart','cameraStop','stockResult'):
  assert 'id="'+id+'"' not in s
 assert "cb.type='checkbox'" in s
 assert "samplePositiveOnly" in s
def test_cache_and_save():
 s=(ROOT/'scanner.html').read_text(encoding='utf-8')
 assert "current.product_code===sharedProductCode" in s
 assert "fullCode===(fullKind==='nota'?notaInput:sharedProductCode)" in s
 assert "post('/scanner/api/sample',{code})" in s
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in s
 assert 'id="dbSetupBtn"' in s

def test_filter_counts_and_scope_badge():
 s=(ROOT/'scanner.html').read_text(encoding='utf-8')
 for id in ('samplePositiveCount','sampleAllCount','fullPositiveCount','fullAllCount','saveScopeCount'):
  assert 'id="'+id+'"' in s
 assert "function updateVisibilityCounts(" in s
 assert "stock.filter(row=>hasPositivePieces(row.pieces)).length" in s
 assert "all.filter(row=>hasPositivePieces(row.stock_rolls)).length" in s
 assert "badge.textContent='● '+age" in s
 assert "tip.textContent='上次：'" not in s
 assert "'7−'" in s and "'180+'" in s
