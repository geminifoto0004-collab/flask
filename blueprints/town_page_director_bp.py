"""Render the CUSTOMS AGENT TOWN page with the AI director runtime enabled."""

from flask import Blueprint, Response, jsonify

from .town_page_bp import _patched_town_html
from .town_world_runtime_patch import patch_town_world


town_page_director_bp = Blueprint("town_page_director", __name__)


def _director_html():
    html = patch_town_world(_patched_town_html())

    # During validation we drive the town only with the manual "AI think now" button.
    html = html.replace(
        "let aiAuto=localStorage.getItem('customs-town-ai-auto')!=='0';",
        "let aiAuto=false;",
    )

    # IQUIQUE is the only large wall label. Time stays on the real wall clock and
    # occasionally on workstation monitors, never as text floating over the sea.
    html = html.replace(
        "txt('ADUANA · IQUIQUE',320,41,'#efe5c7',7,'center');",
        "txt('IQUIQUE',320,44,'#efe5c7',12,'center');",
    )
    html = html.replace(
        "txt('IQUIQUE '+String(c.hour).padStart(2,'0')+':'+String(c.minute).padStart(2,'0'),74,390,'#d5e6e8',6,'left');\n    if(Number.isFinite(Number(townWeather.temperature)))txt(Math.round(Number(townWeather.temperature))+'°C',156,390,'#d5e6e8',6,'left');",
        "",
    )
    html = html.replace(
        "px(x-16,163,5,9,'#82b3bf');px(x-9,166,5,6,'#6b98a4');px(x-2,161,5,11,'#91aa71');px(x+5,164,5,8,'#d0a65c');px(x+12,168,4,4,'#b66f62');",
        "const cc=chileNowParts();px(x-16,163,30,11,'#2f5f70');txt(String(cc.hour).padStart(2,'0')+':'+String(cc.minute).padStart(2,'0'),x,173,'#dff3f5',7,'center');",
    )
    return html


@town_page_director_bp.route('/customs-town', methods=['GET'])
@town_page_director_bp.route('/customs-town/', methods=['GET'])
def customs_town_director_page():
    return Response(_director_html(), mimetype='text/html')


@town_page_director_bp.route('/api/town/director-page-health', methods=['GET'])
def director_page_health():
    return jsonify({
        'ok': True,
        'director_runtime': True,
        'manual_ai_test_mode': True,
        'tidb_required': False,
    })
