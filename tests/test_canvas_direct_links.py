#!/usr/bin/env python3
"""Regression tests for browser-facing Canvas page links."""

from pathlib import Path
import sys

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
sys.path.insert(0, str(CANVAS_ROOT))

from server.routes.views import views_bp  # noqa: E402


def test_direct_canvas_page_link_serves_canvas_ui():
    app = Flask(
        __name__,
        template_folder=str(CANVAS_ROOT / "client" / "templates"),
        static_folder=str(CANVAS_ROOT / "client" / "static"),
    )
    app.register_blueprint(views_bp)

    response = app.test_client().get("/page_20260331_121401")

    assert response.status_code == 200
    assert b"Jarvis Canvas" in response.data
