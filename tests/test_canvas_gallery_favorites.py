"""Regression coverage for Canvas image gallery favorites."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
GALLERY_JS = (CANVAS_ROOT / "client" / "static" / "js" / "gallery.js").read_text()
GALLERY_HTML = (CANVAS_ROOT / "client" / "templates" / "gallery.html").read_text()


def _load_gallery_module():
    sys.path.insert(0, str(CANVAS_ROOT))
    module_path = CANVAS_ROOT / "server" / "routes" / "gallery.py"
    spec = importlib.util.spec_from_file_location("canvas_gallery_favorites_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_gallery_favorite_endpoint_updates_catalog_and_list_response(tmp_path, monkeypatch):
    gallery = _load_gallery_module()
    monkeypatch.setattr(gallery, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(gallery, "IMAGE_CATALOG_FILE", tmp_path / "image_catalog.json")
    monkeypatch.setattr(gallery, "CDN_CATALOG_FILE", tmp_path / "cdn_catalog.json")

    image = tmp_path / "generated_example_20260711_120000.png"
    image.write_bytes(b"fake-png")
    (tmp_path / "cdn_catalog.json").write_text(
        json.dumps({image.name: {"url": "https://cdn.example/image"}})
    )

    app = Flask(__name__)
    app.register_blueprint(gallery.gallery_bp)
    client = app.test_client()

    favorite_response = client.patch(
        f"/api/gallery/images/{image.name}/favorite",
        json={"favorite": True},
    )
    list_response = client.get("/api/gallery/images")

    assert favorite_response.status_code == 200
    assert favorite_response.get_json()["favorite"] is True
    catalog = json.loads((tmp_path / "image_catalog.json").read_text())
    assert catalog[image.name]["favorite"] is True
    assert catalog[image.name]["favorited_at"]
    assert list_response.status_code == 200
    listed = list_response.get_json()["images"][0]
    assert listed["name"] == image.name
    assert listed["favorite"] is True
    assert listed["cdn_cached"] is True
    assert listed["favorited_at"] == catalog[image.name]["favorited_at"]

    clear_response = client.patch(
        f"/api/gallery/images/{image.name}/favorite",
        json={"favorite": False},
    )

    assert clear_response.status_code == 200
    assert clear_response.get_json()["favorite"] is False
    catalog = json.loads((tmp_path / "image_catalog.json").read_text())
    assert catalog[image.name]["favorite"] is False
    assert catalog[image.name]["favorited_at"] is None


def test_gallery_confirms_uncached_cdn_uploads_before_get_url():
    assert "function confirmCdnUploadIfNeeded" in GALLERY_JS
    assert "if (img && img.cdn_cached) return true;" in GALLERY_JS
    assert "Create a public Cloudflare CDN URL for this image?" in GALLERY_JS
    assert "Cloudflare CDN is not configured for this Jarvis mode/env" in GALLERY_JS


def test_gallery_can_sort_by_cached_cdn_status():
    assert 'value="cdn-desc"' in GALLERY_HTML
    assert 'value="cdn-asc"' in GALLERY_HTML
    assert "case 'cdn-desc':" in GALLERY_JS
    assert "case 'cdn-asc':" in GALLERY_JS
    assert "Copy cached CDN URL" in GALLERY_JS
