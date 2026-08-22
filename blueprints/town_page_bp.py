"""Standalone browser page for CUSTOMS AGENT TOWN."""

from flask import Blueprint, render_template


town_page_bp = Blueprint("town_page", __name__)


@town_page_bp.route("/customs-town", methods=["GET"])
def customs_town_page():
    return render_template("customs_agent_town.html")
