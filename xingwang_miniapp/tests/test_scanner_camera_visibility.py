"""The dark QR preview appears only after an explicit camera start."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_empty_scanner_preview_hidden_until_camera_started():
    ui = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert '<div id="reader"></div>' in ui
    assert "#scanPanel #reader:not(.camera-active)" in ui
    assert "display:none!important;height:0!important;min-height:0!important" in ui
    assert "#scanPanel #reader:not(.camera-active):before" in ui
    assert "content:none!important;display:none!important" in ui


def test_camera_start_stop_and_failure_toggle_visibility():
    ui = (ROOT / "scanner.html").read_text(encoding="utf-8")
    start = ui.split("async function startCamera(){")[1].split("async function stopCamera(){")[0]
    stop = ui.split("async function stopCamera(){")[1].split("function syncCameraButton(){")[0]
    assert "$('reader').classList.add('camera-active');" in start
    assert start.index("classList.add('camera-active')") < start.index("reader.start(")
    assert "await reader.start({facingMode:'environment'}" in start
    assert "$('reader').classList.remove('camera-active');" in start  # startup failure
    assert "$('reader').classList.remove('camera-active');" in stop  # camera off
    assert "$('cameraToggle').onclick=async()=>{if(running)await stopCamera();else await startCamera()};" in ui


def test_sample_scanning_stays_on_same_page():
    ui = (ROOT / "scanner.html").read_text(encoding="utf-8")
    assert "body.cc-sample-detail #scanPanel #reader:not(.camera-active)" in ui
    assert "function showResult(d){" in ui
    assert "void lookup(code);" in ui
    assert "stopCamera(" not in ui.split("function onScan(raw){")[1].split("async function startCamera(){")[0]
    assert "post('/scanner/api/save'" in ui  # SAVE still explicit
