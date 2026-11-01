"""Scanner two-tab layout, compact camera, checkboxes and safe stock filters."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_two_tabs_camera_and_checkbox():
 s=(ROOT/'scanner.html').read_text('utf-8')
 for name in ('modeSample','modeFull','cameraToggle','samplePositiveBtn','sampleAllBtn','adminTab','sampleSelectAll','sampleSelectNone'):
  assert 'id="'+name+'"' in s
 for name in ('modeStock','cameraStart','cameraStop','stockResult'):
  assert 'id="'+name+'"' not in s
 assert "cb.type='checkbox'" in s
 assert "samplePositiveOnly" in s
def test_cache_and_save():
 s=(ROOT/'scanner.html').read_text('utf-8')
 assert "current.product_code===sharedProductCode" in s
 assert "fullCode===(fullKind==='nota'?notaInput:sharedProductCode)" in s
 assert "post('/scanner/api/sample',{code})" in s
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in s
 assert 'id="dbSetupBtn"' in s
