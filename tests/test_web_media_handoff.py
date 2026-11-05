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


def test_gif_handoff_keeps_all_frames_and_returns_source_frame_metadata(tmp_path, monkeypatch):
    client, generated_images, uploads = _client(tmp_path, monkeypatch)
    frames = [Image.new('RGB', (32, 24), color) for color in ('red', 'blue')]
    buffer = io.BytesIO()
    frames[0].save(
        buffer, 'GIF', save_all=True, append_images=frames[1:], duration=[80, 120], loop=0,
    )
    original = buffer.getvalue()
    (generated_images / 'animation.gif').write_bytes(original)

    response = client.post('/api/media-handoff/import', json={
        'media_type': 'image', 'filename': 'animation.gif',
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['mime_type'] == 'image/gif'
    assert payload['filename'].endswith('.gif')
    assert payload['animated'] is True
    assert payload['source_frame_count'] == 2
    assert payload['duration_ms'] == 200
    assert (uploads / payload['filename']).read_bytes() == original
    assert (generated_images / 'animation.gif').read_bytes() == original
    assert not list(uploads.glob('*.jpg'))
    served = client.get(payload['url'])
    assert served.status_code == 200
    assert served.mimetype == 'image/gif'
    assert served.data == original
    served.close()


def test_gif_upload_keeps_animation_and_base64_bytes(tmp_path, monkeypatch):
    import base64

    client, _, uploads = _client(tmp_path, monkeypatch)
    frames = [Image.new('RGB', (16, 16), color) for color in ('green', 'purple')]
    buffer = io.BytesIO()
    frames[0].save(buffer, 'GIF', save_all=True, append_images=frames[1:], duration=100, loop=0)
    original = buffer.getvalue()
    response = client.post('/api/upload-image', data={
        'image': (io.BytesIO(original), 'animation.gif', ''), 'mode': 'cloud',
    }, content_type='multipart/form-data')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['source_frame_count'] == 2
    assert base64.b64decode(payload['base64']) == original
    assert (uploads / payload['filename']).read_bytes() == original


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


def test_blank_mime_upload_still_validates_actual_gif_bytes(tmp_path, monkeypatch):
    client, _, uploads = _client(tmp_path, monkeypatch)
    response = client.post('/api/upload-images', data={
        'images': (io.BytesIO(b'not an image'), 'fake.gif', ''),
    }, content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json()['ok'] is False
    assert not uploads.exists() or not list(uploads.iterdir())


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
