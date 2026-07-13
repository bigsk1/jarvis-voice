"""Regression coverage for private Canvas-to-Web image handoffs."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from flask import Flask
from PIL import Image

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_media_handoff_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_media_handoff_test.routes import api  # noqa: E402


def _client(tmp_path, monkeypatch):
    generated_images = tmp_path / "generated_images"
    uploads = tmp_path / "uploads"
    generated_images.mkdir()
    monkeypatch.setattr(api, "GENERATED_IMAGES_PATH", generated_images)
    monkeypatch.setattr(api, "UPLOADS_PATH", uploads)

    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client(), generated_images, uploads


def test_image_handoff_imports_through_normal_web_upload_pipeline(tmp_path, monkeypatch):
    client, generated_images, uploads = _client(tmp_path, monkeypatch)
    source = generated_images / "generated_example.png"
    buffer = io.BytesIO()
    Image.new("RGB", (1600, 800), "navy").save(buffer, "PNG")
    source.write_bytes(buffer.getvalue())
    original = source.read_bytes()

    response = client.post(
        "/api/media-handoff/import",
        json={"media_type": "image", "filename": source.name},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["media_type"] == "image"
    assert payload["url"].startswith("/api/uploads/upload_")
    assert payload["url"].endswith(".jpg")
    assert (payload["width"], payload["height"]) == (1024, 512)
    assert "base64" not in payload
    assert (uploads / payload["filename"]).is_file()
    assert source.read_bytes() == original


def test_media_handoff_rejects_path_traversal(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media-handoff/import",
        json={"media_type": "image", "filename": "../private.png"},
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_media_handoff_is_typed_and_rejects_video_until_supported(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media-handoff/import",
        json={"media_type": "video", "filename": "generated_example.mp4"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Unsupported media type" in payload["error"]
