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
    assert not (uploads / (payload['filename'] + '.source.png')).exists()
    assert payload['source_width'] == 1600 and payload['source_preserved'] is False


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


def test_image_upload_retains_full_resolution_and_transparency_for_craft(tmp_path, monkeypatch):
    client, generated, uploads = _client(tmp_path, monkeypatch)
    source=Image.new('RGBA',(1600,800),(20,40,60,80))
    source.save(generated/'transparent.png')
    response=client.post('/api/media-handoff/import',json={'media_type':'image','filename':'transparent.png','preserve_source':True})
    assert response.status_code==200
    data=response.get_json()
    with Image.open(uploads/(data['filename']+'.source.png')) as original:
        assert original.size==(1600,800) and original.mode=='RGBA'
        assert original.getpixel((100,100))==(20,40,60,80)
    assert (data['width'],data['height'])==(1024,512)


def test_large_phone_photo_keeps_preview_upload_and_bounds_only_explicit_full_source(tmp_path, monkeypatch):
    client,generated,uploads=_client(tmp_path,monkeypatch)
    image=Image.new('RGB',(8000,6000),'navy')
    image.save(generated/'phone.jpg',quality=80)
    image.close()
    preview=client.post('/api/media-handoff/import',json={'media_type':'image','filename':'phone.jpg'})
    assert preview.status_code==200
    payload=preview.get_json()
    assert (payload['width'],payload['height'])==(1024,768)
    assert payload['source_width']==8000 and payload['source_height']==6000
    assert not list(uploads.glob('*.source.png'))
    full=client.post('/api/media-handoff/import',json={'media_type':'image','filename':'phone.jpg','preserve_source':True})
    assert full.status_code==400 and 'Full-size Craft/Stash' in full.get_json()['error']
