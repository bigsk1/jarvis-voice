"""Tests for shared missing-media placeholder assets."""

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from flask import Flask

from media_placeholders import (
    IMAGE_UNAVAILABLE,
    VIDEO_UNAVAILABLE,
    send_placeholder,
)
from server.app import app
from server.routes import api


def test_placeholder_assets_exist():
    assert IMAGE_UNAVAILABLE.is_file()
    assert VIDEO_UNAVAILABLE.is_file()


def test_send_placeholder_returns_cached_jpeg():
    test_app = Flask(__name__)
    with test_app.test_request_context("/assets/image-unavailable.jpg"):
        response = send_placeholder("image")
        response.direct_passthrough = False
        assert response.status_code == 200
        assert response.mimetype == "image/jpeg"
        assert 'max-age=31536000' in (response.headers.get('Cache-Control') or '')
        assert response.get_data()


def test_missing_generated_image_returns_placeholder(tmp_path):
    with app.test_request_context("/api/images/missing.jpg"), patch.object(
        api, "IMAGES_PATH", tmp_path
    ):
        response = api.serve_image("missing.jpg")
        response.direct_passthrough = False

    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.get_data() == IMAGE_UNAVAILABLE.read_bytes()


def test_missing_upload_returns_placeholder_after_stash_lookup(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    conversations = tmp_path / "conversations"
    conversations.mkdir()
    monkeypatch.setenv("STASH_DIR", str(tmp_path / "stash"))

    with app.test_request_context("/api/uploads/missing.jpg"), patch.object(
        api, "UPLOADS_PATH", uploads
    ), patch.object(api, "JARVIS_ROOT", tmp_path):
        response = api.serve_upload("missing.jpg")
        response.direct_passthrough = False

    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.get_data() == IMAGE_UNAVAILABLE.read_bytes()


def test_missing_video_thumbnail_returns_video_placeholder(tmp_path):
    with app.test_request_context("/api/videos/missing.mp4/thumbnail"), patch.object(
        api, "VIDEOS_PATH", tmp_path
    ):
        response = api.serve_video_thumbnail("missing.mp4")
        response.direct_passthrough = False

    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.get_data() == VIDEO_UNAVAILABLE.read_bytes()
