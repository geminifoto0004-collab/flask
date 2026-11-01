"""Regressions: sample stocktaking must NEVER navigate away from a live QR camera."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_scanning_does_not_hide_camera_when_sample_result_arrives():
    ui=(ROOT/"scanner.html").read_text(encoding="utf-8")
    assert "body.cc-sample-detail #scanPanel,body.cc-stock-detail #scanPanel{display:block!important}" in ui
    assert "body.cc-sample-detail header,body.cc-stock-detail header{display:flex!important}" in ui
    assert "if(busy||mode==='admin')return;" in ui
    assert "ccResultView&&mode!=='cart'" not in ui
    assert "reader.start({facingMode:'environment'}" in ui
    assert "function showResult(d){" in ui
    assert "function renderRows(){" in ui
    # Only explicit camera controls and logout may stop the actual stream.
    camera_region=ui.split("function showResult(d){")[1].split("async function lookup(input){")[0]
    assert "stopCamera(" not in camera_region
    scan_region=ui.split("function onScan(raw){")[1].split("async function startCamera(){")[0]
    assert "stopCamera(" not in scan_region
    assert "void lookup(code);" in scan_region


def test_scan_does_not_discard_unsaved_sample_choices():
    ui=(ROOT/"scanner.html").read_text(encoding="utf-8")
    scan=ui.split("function onScan(raw){")[1].split("async function startCamera(){")[0]
    assert "sampleDirty&&!saved" in scan
    assert "請先按保存。相機仍然保持開啟。" in scan
    assert "return;" in scan
    assert "lastQrCode=code;" in scan
    assert "scanBlockedAt" in scan
    assert "saved=true;sampleDirty=false;scanBlockedCode='';lastQrCode='';" in ui
    # A QR scan must NEVER write a stocktaking record until SAVE is tapped.
    assert "$('saveBtn').onclick=async()=>{" in ui
    assert "post('/scanner/api/save'" in ui


def test_inventory_lookup_remains_in_same_dom():
    ui=(ROOT/"scanner.html").read_text(encoding="utf-8")
    assert 'id="scanPanel"' in ui
    assert 'id="reader"' in ui
    assert 'id="result"' in ui
    assert 'id="rows"' in ui
    assert 'id="saveBtn"' in ui
    assert 'id="fullResult"' in ui
