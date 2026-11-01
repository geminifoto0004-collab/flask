"""Fast sample checkboxes: checked=present, unchecked=missing; visible-only bulk/save."""
from pathlib import Path
UI=(Path(__file__).resolve().parents[1]/'scanner.html').read_text(encoding='utf-8')
def test_controls_and_no_dropdown():
 for id in ('sampleSelectAll','sampleSelectNone','samplePositiveBtn','sampleAllBtn',
            'codeClearBtn','cameraToggle'):
  assert 'id="'+id+'"' in UI
 assert "cb.type='checkbox'" in UI
 assert "cb.checked=sampleStates.get(row.code)===true" in UI
 assert "<select class=\"sample-choice" not in UI
 assert "['','未檢查']" not in UI
def test_only_filtered_rows_saved():
 assert "const visible=visibleSampleRows();" in UI
 assert "const present=visible.filter(row=>sampleStates.get(row.code)===true)" in UI
 assert "const missing=visible.filter(row=>sampleStates.get(row.code)!==true)" in UI
 assert "post('/scanner/api/save',{scan_id:current.scan_id,present,missing})" in UI
 assert "for(const row of visible)" in UI
 assert "samplePositiveOnly?current.variants.filter" in UI or "samplePositiveOnly" in UI
def test_bulk_and_clear():
 assert "setSampleVisibleState(true)" in UI
 assert "setSampleVisibleState(false)" in UI
 assert "$('codeClearBtn').onclick=" in UI
 assert "syncSearchClear();" in UI
