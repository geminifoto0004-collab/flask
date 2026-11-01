"""Scanner two-tab layout, compact camera and safe sample selection."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_two_tabs_camera_and_sample_filters():
 s=(ROOT/'scanner.html').read_text('utf-8')
 for name in ('modeSample','modeFull','cameraToggle','samplePositiveBtn','sampleAllBtn','adminTab'):
  assert 'id="'+name+'"' in s
 for name in ('modeStock','cameraStart','cameraStop','stockResult'):
  assert 'id="'+name+'"' not in s
 assert "samplePositiveOnly?all.filter(r=>hasPositivePieces(r.stock_rolls)):all" in s
 assert "['','未檢查']" in s and "['present','有樣']" in s and "['missing','無樣']" in s
def test_sample_and_full_keep_separate_cached_results():
 s=(ROOT/'scanner.html').read_text('utf-8')
 assert "current.product_code===sharedProductCode" in s
 assert "fullCode===(fullKind==='nota'?notaInput:sharedProductCode)" in s
 assert "post('/scanner/api/sample',{code})" in s
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in s
 assert 'id="dbSetupBtn"' in s
