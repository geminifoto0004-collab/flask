"""Header checkbox applies to visible sample rows without changing filtered SKUs."""
from pathlib import Path
UI=(Path(__file__).resolve().parents[1]/'scanner.html').read_text(encoding='utf-8')
def test_header_checkbox_and_clear():
 for id in ('sampleHeaderCheck','samplePositiveBtn','sampleAllBtn','codeClearBtn','cameraToggle'):
  assert 'id="'+id+'"' in UI
 for id in ('sampleSelectAll','sampleSelectNone'):
  assert 'id="'+id+'"' not in UI
 assert "cb.type='checkbox'" in UI
 assert "cb.checked=sampleStates.get(row.code)===true" in UI
 assert "('sampleHeaderCheck').onchange=" in UI
def test_only_visible_rows_saved():
 assert "const visible=visibleSampleRows();" in UI
 assert "const present=visible.filter(row=>sampleStates.get(row.code)===true)" in UI
 assert "const missing=visible.filter(row=>sampleStates.get(row.code)!==true)" in UI
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing,allow_stale:staleAccepted()})" in UI
def test_clear():
 assert "$('codeClearBtn').onclick=" in UI
 assert "syncSearchClear();" in UI
