"""Standalone browser page for CUSTOMS AGENT TOWN."""

import os

from flask import Blueprint, current_app, jsonify, send_from_directory


town_page_bp = Blueprint("town_page", __name__)


@town_page_bp.route("/customs-town", methods=["GET"])
@town_page_bp.route("/customs-town/", methods=["GET"])
def customs_town_page():
    templates_dir = os.path.join(current_app.root_path, "templates")
    return send_from_directory(templates_dir, "customs_agent_town.html", mimetype="text/html")


@town_page_bp.route("/api/town/page-health", methods=["GET"])
def customs_town_page_health():
    templates_dir = os.path.join(current_app.root_path, "templates")
    page_path = os.path.join(templates_dir, "customs_agent_town.html")
    return jsonify({
        "ok": True,
        "page": "customs-town",
        "file_exists": os.path.isfile(page_path),
        "file_size": os.path.getsize(page_path) if os.path.isfile(page_path) else 0,
    })
