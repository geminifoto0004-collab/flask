"""Standalone browser page for CUSTOMS AGENT TOWN."""

import os

from flask import Blueprint, Response, current_app, jsonify


town_page_bp = Blueprint("town_page", __name__)


def _town_page_path():
    return os.path.join(current_app.root_path, "templates", "customs_agent_town.html")


def _patched_town_html():
    """Serve the current standalone town with the latest AI-control and layout fixes."""
    page_path = _town_page_path()
    with open(page_path, "r", encoding="utf-8") as fh:
        html = fh.read()

    # AI decisions must drive the real character target instead of being overwritten
    # by the next random idle decision.
    html = html.replace(
        "a.idle=action.action;a.timer=0;a.decisionTimer=rand(1.5,4.5);\n          chooseIdleTarget(a);",
        "a.path=[];a.pathTarget='';a.timer=0;a.decisionTimer=rand(4.5,8.5);\n          chooseIdleTarget(a,action.action);",
    )
    html = html.replace(
        "function chooseIdleTarget(a){",
        "function chooseIdleTarget(a,forcedMode=''){",
    )
    html = html.replace(
        "const mode=randIdle(a);",
        "const mode=forcedMode||randIdle(a);",
    )
    html = html.replace(
        "coffee:[{x:120,y:180},{x:262,y:180}],",
        "coffee:[{x:500,y:130},{x:486,y:146}],",
    )
    html = html.replace(
        "files:[{x:a.homeX-54,y:146},{x:a.homeX+48,y:146}],",
        "files:[{x:112,y:126},{x:120,y:146}],",
    )
    html = html.replace(
        "lookSea:[{x:438,y:258},{x:410,y:258}],",
        "lookSea:[{x:300,y:246},{x:340,y:246}],",
    )

    # Desktop Render page should open at a comfortable overview size instead of
    # stretching the 640x400 pixel world across the full browser width.
    html = html.replace(
        "  padding:18px;\n  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
        "  padding:10px;\n  max-width:1180px;\n  margin:0 auto;\n  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
    )
    html = html.replace(
        "#customs-sim .game-wrap{background:#090d13;padding:8px;border:3px solid #080a0d;box-shadow:0 0 0 3px light-dark(#696153,#344052);overflow:hidden}",
        "#customs-sim .game-wrap{background:#090d13;padding:6px;border:3px solid #080a0d;box-shadow:0 0 0 3px light-dark(#696153,#344052);overflow:hidden;display:flex;justify-content:center}",
    )
    html = html.replace(
        "#customs-sim canvas{display:block;width:100%;height:auto;aspect-ratio:8/5;image-rendering:pixelated;image-rendering:crisp-edges;background:#173344}",
        "#customs-sim canvas{display:block;width:min(100%,960px);height:auto;aspect-ratio:8/5;image-rendering:pixelated;image-rendering:crisp-edges;background:#173344}",
    )
    html = html.replace(
        "@media(max-width:600px){#customs-sim.app-root{padding:10px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
        "@media(max-width:600px){#customs-sim.app-root{padding:8px}#customs-sim .controls>*{flex:1 1 100%}#customs-sim .hud{align-items:flex-start}}",
    )
    return html


@town_page_bp.route("/customs-town", methods=["GET"])
@town_page_bp.route("/customs-town/", methods=["GET"])
def customs_town_page():
    return Response(_patched_town_html(), mimetype="text/html")


@town_page_bp.route("/api/town/page-health", methods=["GET"])
def customs_town_page_health():
    page_path = _town_page_path()
    return jsonify({
        "ok": True,
        "page": "customs-town",
        "file_exists": os.path.isfile(page_path),
        "file_size": os.path.getsize(page_path) if os.path.isfile(page_path) else 0,
        "ai_action_patch": True,
        "compact_layout": True,
    })
