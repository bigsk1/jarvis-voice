"""Canvas generated-audio action proxy regression coverage."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
CANVAS_ROOT = ROOT / "jarvis-canvas"
for path in (CANVAS_ROOT, ROOT / "lib"):
    sys.path.insert(0, str(path))

from server.routes import audio_actions as routes  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(routes.audio_actions_bp)
    return app.test_client()


def test_delete_proxy_uses_internal_fastapi_auth(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_internal_api_base_url",
        lambda: "http://jarvis-api:8880",
    )
    monkeypatch.setattr(
        routes,
        "get_internal_api_headers",
        lambda: {"Authorization": "Bearer internal-key"},
    )
    api_response = Mock(status_code=200)
    api_response.json.return_value = {
        "ok": True,
        "deleted": "music result.mp3",
    }

    with patch.object(routes.requests, "request", return_value=api_response) as request:
        response = _client().delete(
            "/api/audio-actions/delete",
            json={"filename": "music result.mp3"},
        )

    assert response.status_code == 200
    request.assert_called_once_with(
        "DELETE",
        "http://jarvis-api:8880/api/generated-music/music%20result.mp3",
        headers={"Authorization": "Bearer internal-key"},
        timeout=120,
        params={"revoke_public_shares": False},
    )


def test_publish_proxy_uses_internal_fastapi_auth(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_internal_api_base_url",
        lambda: "http://jarvis-api:8880",
    )
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
            "public_url": "https://files-cdn.x.ai/public/audio.mp4",
        },
    }

    with patch.object(routes.requests, "request", return_value=api_response) as request:
        response = _client().post(
            "/api/xai-audio-shares/publish",
            json={
                "filename": "music result.mp3",
                "ttl_days": 7,
                "expected_audio_sha256": "c" * 64,
                "confirmed": True,
            },
        )

    assert response.status_code == 201
    request.assert_called_once_with(
        "POST",
        "http://jarvis-api:8880/api/generated-music/xai-shares/publish",
        headers={"Authorization": "Bearer internal-key"},
        timeout=1200,
        json={
            "filename": "music result.mp3",
            "ttl_days": 7,
            "expected_audio_sha256": "c" * 64,
            "confirmed": True,
        },
    )


def test_delete_proxy_rejects_unsafe_filename():
    response = _client().delete(
        "/api/audio-actions/delete",
        json={"filename": "../music.mp3"},
    )

    assert response.status_code == 400


def test_delete_proxy_preserves_active_share_conflict(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_internal_api_base_url",
        lambda: "http://jarvis-api:8880",
    )
    monkeypatch.setattr(routes, "get_internal_api_headers", lambda: {})
    api_response = Mock(status_code=409)
    api_response.json.return_value = {
        "detail": {
            "code": "active_public_audio_shares",
            "message": "This audio still has active public copies.",
            "active_shares": [{"share_id": "a" * 32}],
        }
    }

    with patch.object(routes.requests, "request", return_value=api_response):
        response = _client().delete(
            "/api/audio-actions/delete",
            json={"filename": "music.mp3"},
        )

    assert response.status_code == 409
    assert response.get_json()["code"] == "active_public_audio_shares"
    assert len(response.get_json()["active_shares"]) == 1


def test_audio_delete_mutation_is_protected():
    app_source = (CANVAS_ROOT / "server" / "app.py").read_text(encoding="utf-8")
    public_prefix_line = next(
        line
        for line in app_source.splitlines()
        if line.strip().startswith("PUBLIC_API_PREFIXES =")
    )
    audio_routes = (
        CANVAS_ROOT / "server" / "routes" / "audio_gallery.py"
    ).read_text(encoding="utf-8")

    assert "/api/audio-actions" not in public_prefix_line
    assert "/api/xai-audio-shares" not in public_prefix_line
    assert 'methods=["DELETE"]' not in audio_routes
