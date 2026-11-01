"""Scanner sample flow avoids nonessential copy/next buttons."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_only_one_sample_save_action():
 ui=(ROOT/"scanner.html").read_text(encoding="utf-8")
 assert 'id="saveBtn"' in ui
 for elem in ('id="copyBtn"','id="nextBtn"',"'copyBtn').onclick","'nextBtn').onclick"):
  assert elem not in ui
 assert 'id="copyScannerBtn"' in ui
 assert 'id="fullNext"' in ui
def test_continuous_scanning_after_saving():
 ui=(ROOT/"scanner.html").read_text(encoding="utf-8")
 assert 'let mode=' in ui and 'lastQrCode' in ui
 assert 'if(busy||mode===\'admin\')return;' in ui
 assert "code===lastQrCode" in ui
 assert "code===current?.product_code" in ui
 assert "lastQrCode=code;" in ui
 assert "void lookup(code);" in ui
 assert "if(mode==='sample'&&current&&current.product_code!==code&&sampleDirty&&!saved&&!confirm(" in ui
 assert '完成一張後按下一張' not in ui
