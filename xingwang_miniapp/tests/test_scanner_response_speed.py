"""Scan responsiveness regression checks; preserve one-page SAMPLE workflow."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
def ui(): return (ROOT/"scanner.html").read_text("utf-8")

def test_pre_cc_video_uses_native_geometry_after_sample_lookup():
    s=ui()
    css=s[s.index("/* CC-pre-redesign camera restoration"):s.index("</style>",s.index("/* CC-pre-redesign camera restoration"))]
    assert "height:auto!important;min-height:0!important;max-height:none!important;" in css
    assert "body.cc-sample-detail #scanPanel #reader.camera-active" in css
    assert "body.cc-stock-detail #scanPanel #reader.camera-active" in css
    assert "max-width:460px!important" in css
    assert "object-fit:initial!important" in css
    assert "#scanPanel #reader:not(.camera-active)" in css
    assert "display:none!important" in css

def test_exact_pre_cc_working_scanner_decoding_parameters():
    s=ui()
    start=s[s.index("async function startCamera(){"):s.index("async function stopCamera(){")]
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in start
    assert "fps:12" not in start
    assert "qrbox:(width,height)" not in start
    assert "classList.add('camera-active')" in start

def test_no_busy_qr_drop_and_keep_unsaved_sample():
    s=ui()
    scanner=s[s.index("function onScan(raw){"):s.index("async function startCamera(){")]
    lookup=s[s.index("async function lookup(input){"):s.index("function syncSearchClear(){")]
    assert "scanQueuedCode=code;scanQueuedAt=Date.now();" in scanner
    assert "sampleDirty&&!saved" in scanner
    assert "queueMicrotask(()=>{if(running&&!busy)onScan(queued)})" in lookup
    assert "freshnessCheckedAt<20000" in lookup
    assert "post('/scanner/api/save'" in s
    assert "stopCamera(" not in scanner
