"""Unslop mobile transaction-table visual regression guardrails.

User screenshots showed customer names clipped under history/reservations. Only
CSS layout is changed: business records, the original table, clickable customer
names, sortable headings and server API remain untouched.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def src():
    return (ROOT / "scanner.html").read_text(encoding="utf-8")


def test_mobile_history_and_reservation_customer_not_truncated():
    html=src()
    css=html.split("</style>",1)[0]
    assert "@media(max-width:700px)" in css
    assert '#fullResult:is([data-full-tab="history"],[data-full-tab="reservar"]) .full-table .full-customer,' in css
    assert "max-width:none;" in css
    assert "white-space:normal;" in css
    assert "text-overflow:clip;" in css
    assert "overflow-wrap:anywhere;" in css
    assert "grid-column:1 / -1;" in css
    assert "#fullResult[data-full-tab=\"history\"] .full-table tbody td:nth-child(4)" in css
    assert "#fullResult[data-full-tab=\"reservar\"] .full-table tbody td:nth-child(2)" in css


def test_sort_controls_and_extra_fields_remain_visible():
    html=src()
    assert "th.tabIndex=0;th.setAttribute('role','button')" in html
    assert "th.onclick=sort;th.onkeydown=e=>" in html
    assert "b.textContent=value;b.title=value;b.onclick=()=>b.classList.toggle('expanded')" in html
    assert "fullTab==='history'&&data.price_allowed?[...fullFields.history" in html
    assert 'data-fulltab="history"' in html and 'data-fulltab="reservar"' in html
    assert 'tbody tr:has(> td.full-empty)' in html
    assert 'max-height:none;' in html
    assert 'overflow-x:auto;' in html


def test_scanner_save_and_cart_handlers_still_present():
    html=src()
    assert "await reader.start({facingMode:'environment'},{fps:10,qrbox:{width:220,height:220}},onScan,()=>{});" in html
    assert "post('/scanner/api/save'" in html
    assert "function fullTable(rows,columns){" in html
    assert "$('fullTabs').addEventListener('click',e=>" in html
    assert "function fullRenderProduct(data){" in html
    ids=re.findall(r'\bid="([^"]+)"', html)
    assert len(ids)==len(set(ids))
