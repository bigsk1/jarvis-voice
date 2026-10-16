"""Regression coverage for Canvas video model metadata and badges."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from flask import Flask
from server_package_utils import load_canvas_server_package

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
VIDEO_JS = (
    CANVAS_ROOT / "client" / "static" / "js" / "video-gallery.js"
).read_text()
VIDEO_CSS = (
    CANVAS_ROOT / "client" / "static" / "css" / "video-gallery.css"
).read_text()


def _load_video_gallery():
    alias = "canvas_video_model_badge_test_server"
    load_canvas_server_package(alias)
    return importlib.import_module(f"{alias}.routes.video_gallery")


def test_video_gallery_api_forwards_catalog_model(tmp_path, monkeypatch):
    video_gallery = _load_video_gallery()
    video_file = tmp_path / "video_example.mp4"
    video_file.write_bytes(b"fake-video")
    monkeypatch.setattr(video_gallery, "GENERATED_VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(video_gallery, "get_video_duration", lambda _path: None)
    monkeypatch.setattr(
        video_gallery,
        "sync_video_catalog",
        lambda: {
            video_file.name: {
                "provider": "Gemini",
                "model": "veo-3.1-generate-preview",
            }
        },
    )

    app = Flask(__name__)
    app.register_blueprint(video_gallery.video_gallery_bp)
    response = app.test_client().get("/api/gallery/videos")

    assert response.status_code == 200
    listed = response.get_json()["videos"][0]
    assert listed["provider"] == "Gemini"
    assert listed["model"] == "veo-3.1-generate-preview"


def test_video_gallery_renders_model_badges_only_for_cataloged_models():
    assert "const model = String(vid.model || '').trim();" in VIDEO_JS
    assert 'class="video-badges"' in VIDEO_JS
    assert 'class="video-model"' in VIDEO_JS
    assert "${model ?" in VIDEO_JS
    assert ".video-model" in VIDEO_CSS
    model_rule = re.search(r"\.video-model\s*\{([^}]+)\}", VIDEO_CSS)
    assert model_rule
    assert "pointer-events: none" not in model_rule.group(1)
    assert "top: 38px" not in model_rule.group(1)
    assert ".video-badges" in VIDEO_CSS


def test_video_gallery_does_not_guess_provider_from_generic_video_filename():
    assert "lower.startsWith('video_')" not in VIDEO_JS
