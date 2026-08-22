"""Standalone browser page for CUSTOMS AGENT TOWN."""

import os

from flask import Blueprint, Response, current_app, jsonify


town_page_bp = Blueprint("town_page", __name__)


def _town_page_path():
    return os.path.join(current_app.root_path, "templates", "customs_agent_town.html")


def _patched_town_html():
    """Serve the current standalone town with the latest AI-control fixes.

    Keeping these tiny replacements here lets the Render test page track the
    App Block behavior without duplicating/re-uploading the large HTML file.
    """
    page_path = _town_page_path()
    with open(page_path, "r", encoding="utf-8") as fh:
        html = fh.read()

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
    })
