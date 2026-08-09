"""Canvas proxy and Video Gallery public-share regression coverage."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
CANVAS_ROOT = ROOT / "jarvis-canvas"
for path in (CANVAS_ROOT, ROOT / "lib"):
    sys.path.insert(0, str(path))

from server.routes import video_shares as routes  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(routes.video_shares_bp)
    return app.test_client()


def test_publish_proxy_uses_internal_fastapi_auth(monkeypatch):
    monkeypatch.setattr(routes, "get_internal_api_base_url", lambda: "http://jarvis-api:8880")
    monkeypatch.setattr(
        routes,
        "get_internal_api_headers",
        lambda: {"Authorization": "Bearer internal-key"},
    )
    api_response = Mock(status_code=201)
    api_response.json.return_value = {
        "ok": True,
        "share": {
            "share_id": "a" * 32,
            "public_url": "https://files-cdn.x.ai/public/test.mp4",
        },
    }

    with patch.object(routes.requests, "request", return_value=api_response) as request:
        response = _client().post(
            "/api/xai-video-shares/publish",
            json={
                "filename": "gemini result.mp4",
                "ttl_days": 7,
                "expected_video_sha256": "c" * 64,
                "confirmed": True,
            },
        )

    assert response.status_code == 201
    request.assert_called_once_with(
        "POST",
        "http://jarvis-api:8880/api/generated-videos/xai-shares/publish",
        headers={"Authorization": "Bearer internal-key"},
        timeout=240,
        json={
            "filename": "gemini result.mp4",
            "ttl_days": 7,
            "expected_video_sha256": "c" * 64,
            "confirmed": True,
        },
    )


def test_delete_proxy_can_revoke_public_copies(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "get_internal_api_base_url", lambda: "http://jarvis-api:8880")
    monkeypatch.setattr(routes, "get_internal_api_headers", lambda: {})
    monkeypatch.setattr(routes, "GENERATED_VIDEOS_DIR", tmp_path)
    thumbnail = tmp_path / ".thumbnails" / "example.jpg"
    thumbnail.parent.mkdir()
    thumbnail.write_bytes(b"thumb")
    api_response = Mock(status_code=200)
    api_response.json.return_value = {"ok": True, "deleted": "example.mp4"}

    with patch.object(routes.requests, "request", return_value=api_response) as request:
        response = _client().delete(
            "/api/video-actions/delete",
            json={"filename": "example.mp4", "revoke_public_shares": True},
        )

    assert response.status_code == 200
    assert not thumbnail.exists()
    request.assert_called_once_with(
        "DELETE",
        "http://jarvis-api:8880/api/generated-videos/example.mp4",
        headers={},
        timeout=120,
        params={"revoke_public_shares": True},
    )


def test_video_share_mutations_are_protected_and_ui_is_guarded():
    app_source = (CANVAS_ROOT / "server" / "app.py").read_text(encoding="utf-8")
    public_prefix_line = next(
        line for line in app_source.splitlines() if line.strip().startswith("PUBLIC_API_PREFIXES =")
    )
    template = (CANVAS_ROOT / "client" / "templates" / "video-gallery.html").read_text()
    script = (CANVAS_ROOT / "client" / "static" / "js" / "video-gallery.js").read_text()

    assert "/api/xai-video-shares" not in public_prefix_line
    assert "/api/video-actions" not in public_prefix_line
    assert "Anyone with the URL can play or download this video" in template
    assert "xaiVideoShareStatus.available" in script
    assert "expected_video_sha256" in script
    assert "revoke_public_shares" in script
    assert "fetch('/api/video-actions/delete'" in script
    assert "fetch(`/api/gallery/videos/${encodeURIComponent(filename)}`" not in script
    assert "window.isSecureContext" in script
    assert "document.execCommand('copy')" in script
    assert "Automatic copy was blocked" in script
    assert "window.prompt('Copy public URL:'" not in script
