"""Scan responsiveness regression checks; preserve one-page SAMPLE workflow."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
def ui(): return (ROOT/"scanner.html").read_text("utf-8")

def test_live_camera_same_height_after_sample_lookup():
    s=ui()
    css=s[s.index("/* LIVE QR camera:"):s.index("/* Preview comparison fixes:")]
    assert "height:320px!important;min-height:320px!important;max-height:320px!important" in css
    assert "body.cc-sample-detail #scanPanel #reader.camera-active" in css
    assert "body.cc-stock-detail #scanPanel #reader.camera-active" in css
    assert "object-fit:contain!important" in css
    assert "#scanPanel #reader:not(.camera-active)" in css
    assert "display:none!important" in css

def test_qrbox_fits_viewfinder_instead_of_220_fixed():
    s=ui()
    start=s[s.index("async function startCamera(){"):s.index("async function stopCamera(){")]
    assert "{fps:12,qrbox:(width,height)=>{" in start
    assert "Math.min(width,height)*0.78" in start
    assert "return {width:side,height:side}" in start
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
