"""Regression coverage for Canvas CDN catalog HTML exports."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"


def _load_gallery_module():
    sys.path.insert(0, str(CANVAS_ROOT))
    module_path = CANVAS_ROOT / "server" / "routes" / "gallery.py"
    spec = importlib.util.spec_from_file_location("canvas_cdn_export_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _client(gallery):
    app = Flask(
        __name__,
        template_folder=str(CANVAS_ROOT / "client" / "templates"),
    )
    app.register_blueprint(gallery.gallery_bp)
    return app.test_client()


def test_cdn_catalog_export_is_standalone_dark_responsive_html(tmp_path, monkeypatch):
    gallery = _load_gallery_module()
    catalog_file = tmp_path / "cdn_catalog.json"
    catalog_file.write_text(json.dumps({
        "generated_night.png": {
            "url": "https://imagedelivery.net/account/night/public",
            "image_id": "night",
            "uploaded_at": "2026-07-13T22:15:00",
        },
        "generated_day.png": {
            "url": "https://imagedelivery.net/account/day/public",
            "image_id": "day",
            "uploaded_at": "2026-07-12T12:00:00",
        },
        "unsafe.png": {"url": "javascript:alert(1)"},
    }))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(gallery, "CDN_CATALOG_FILE", catalog_file)
    monkeypatch.setattr(gallery, "cloudflare_configured", lambda: True)

    response = _client(gallery).get("/api/gallery/cdn-catalog/export")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert response.headers["Content-Disposition"].startswith("inline;")
    html = response.get_data(as_text=True)
    assert "color-scheme: dark" in html
    assert '<link rel="icon" href="data:,">' in html
    assert "repeat(auto-fill, minmax(" in html
    assert "generated_night.png" in html
    assert "generated_day.png" in html
    assert html.index("generated_night.png") < html.index("generated_day.png")
    assert "Copy URL" in html
    assert "Delete from Cloudflare" in html
    assert "Permanently delete" in html
    assert "https://imagedelivery.net/account/night/public" in html
    assert "javascript:alert(1)" not in html
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    assert catalog_file.read_bytes() == before


def test_cdn_catalog_export_reflects_only_current_catalog_entries(tmp_path, monkeypatch):
    gallery = _load_gallery_module()
    catalog_file = tmp_path / "cdn_catalog.json"
    monkeypatch.setattr(gallery, "CDN_CATALOG_FILE", catalog_file)
    monkeypatch.setattr(gallery, "cloudflare_configured", lambda: True)
    client = _client(gallery)

    catalog_file.write_text(json.dumps({
        "keep.png": {"url": "https://cdn.example/keep", "uploaded_at": "2026-07-13"},
        "removed.png": {"url": "https://cdn.example/removed", "uploaded_at": "2026-07-12"},
    }))
    assert "removed.png" in client.get("/api/gallery/cdn-catalog/export").get_data(as_text=True)

    catalog_file.write_text(json.dumps({
        "keep.png": {"url": "https://cdn.example/keep", "uploaded_at": "2026-07-13"},
    }))
    html = client.get("/api/gallery/cdn-catalog/export").get_data(as_text=True)

    assert "keep.png" in html
    assert "removed.png" not in html


def test_cdn_catalog_export_explains_missing_cloudflare_configuration(tmp_path, monkeypatch):
    gallery = _load_gallery_module()
    monkeypatch.setattr(gallery, "CDN_CATALOG_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(gallery, "cloudflare_configured", lambda: False)

    html = _client(gallery).get("/api/gallery/cdn-catalog/export").get_data(as_text=True)

    assert "CLOUDFLARE_API_TOKEN" in html
    assert "CLOUDFLARE_ACCOUNT_ID" in html
    assert "No CDN images are currently cataloged" in html


def test_canvas_local_delete_preserves_cdn_catalog_entry(tmp_path, monkeypatch):
    gallery = _load_gallery_module()
    image = tmp_path / "generated_example.png"
    image.write_bytes(b"local-image")
    catalog_file = tmp_path / "cdn_catalog.json"
    catalog_file.write_text(json.dumps({
        image.name: {
            "url": "https://imagedelivery.net/account/example/public",
            "image_id": "example",
            "uploaded_at": "2026-07-13T20:00:00",
        }
    }))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(gallery, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(gallery, "CDN_CATALOG_FILE", catalog_file)
    monkeypatch.setattr(gallery, "IMAGE_CATALOG_FILE", tmp_path / "image_catalog.json")

    response = _client(gallery).delete(f"/api/gallery/images/{image.name}")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert not image.exists()
    assert catalog_file.read_bytes() == before


def test_canvas_cdn_delete_proxies_to_internal_fastapi(monkeypatch):
    gallery = _load_gallery_module()
    monkeypatch.setattr(gallery, "get_internal_api_base_url", lambda: "http://jarvis-api:8880")
    monkeypatch.setattr(
        gallery,
        "get_internal_api_headers",
        lambda: {"Authorization": "Bearer internal-key"},
    )
    api_response = Mock(status_code=200)
    api_response.json.return_value = {
        "ok": True,
        "name": "generated example.png",
        "image_id": "example",
        "deleted_from_cloudflare": True,
        "removed_from_catalog": True,
    }

    with patch("requests.delete", return_value=api_response) as delete:
        response = _client(gallery).delete(
            "/api/cdn-catalog/delete",
            json={"filename": "generated example.png"},
        )

    assert response.status_code == 200
    assert response.get_json()["removed_from_catalog"] is True
    delete.assert_called_once_with(
        "http://jarvis-api:8880/api/generated-images/cdn-catalog/generated%20example.png",
        headers={"Authorization": "Bearer internal-key"},
        timeout=40,
    )


def test_canvas_stale_catalog_removal_proxies_expected_image_id(monkeypatch):
    gallery = _load_gallery_module()
    monkeypatch.setattr(gallery, "get_internal_api_base_url", lambda: "http://jarvis-api:8880")
    monkeypatch.setattr(gallery, "get_internal_api_headers", lambda: {})
    api_response = Mock(status_code=200)
    api_response.json.return_value = {
        "ok": True,
        "name": "orphan.png",
        "image_id": "missing",
        "deleted_from_cloudflare": False,
        "removed_from_catalog": True,
    }

    with patch("requests.delete", return_value=api_response) as delete:
        response = _client(gallery).delete(
            "/api/cdn-catalog/remove-entry",
            json={"filename": "orphan.png", "image_id": "missing"},
        )

    assert response.status_code == 200
    assert response.get_json()["deleted_from_cloudflare"] is False
    delete.assert_called_once_with(
        "http://jarvis-api:8880/api/generated-images/cdn-catalog/orphan.png/entry",
        headers={},
        json={"expected_image_id": "missing"},
        timeout=15,
    )


def test_canvas_cdn_delete_route_is_outside_public_gallery_api_prefix():
    gallery_source = (CANVAS_ROOT / "server" / "routes" / "gallery.py").read_text()
    template = (CANVAS_ROOT / "client" / "templates" / "cdn-catalog-export.html").read_text()
    delete_path = "/api/cdn-catalog/delete"

    assert "@gallery_bp.route('/api/cdn-catalog/delete', methods=['DELETE'])" in gallery_source
    assert "fetch('/api/cdn-catalog/delete'" in template
    assert "body: JSON.stringify({ filename })" in template
    assert "fetch('/api/cdn-catalog/remove-entry'" in template
    assert "cloudflare_image_not_found" in template
    assert not delete_path.startswith(("/api/gallery", "/api/pages", "/api/stash", "/api/video-gallery"))
    assert not delete_path.endswith((".png", ".jpg", ".svg", ".js", ".css", ".mp4", ".webm"))


def test_gallery_has_mobile_friendly_cdn_html_export_button():
    gallery_html = (CANVAS_ROOT / "client" / "templates" / "gallery.html").read_text()
    gallery_css = (CANVAS_ROOT / "client" / "static" / "css" / "gallery.css").read_text()

    assert 'id="exportCdnCatalogBtn"' in gallery_html
    assert 'href="/api/gallery/cdn-catalog/export"' in gallery_html
    assert 'target="_blank"' in gallery_html
    assert "cdn-export-btn" in gallery_css
    assert "min-height: 44px" in gallery_css
