"""Qwen3-TTS wake-up is scoped, non-blocking, and best effort."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def _purge_server_modules():
    for key in list(sys.modules):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]
    flask_module = sys.modules.get("flask")
    if flask_module is not None and not hasattr(flask_module, "Flask"):
        del sys.modules["flask"]
    socketio_module = sys.modules.get("flask_socketio")
    if socketio_module is not None and not hasattr(socketio_module, "SocketIO"):
        del sys.modules["flask_socketio"]


def _load_web_server():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server import config as server_config
    from server.app import app
    from server.routes import api

    return app, api, server_config


def test_qwen3_tts_reload_url_is_derived_from_trusted_speech_url():
    _, api, _ = _load_web_server()

    assert api._qwen3_tts_reload_url(
        "http://tts.internal:8881/v1/audio/speech"
    ) == "http://tts.internal:8881/admin/reload"
    assert api._qwen3_tts_reload_url(
        "https://proxy.example/qwen/v1/audio/speech?token=private"
    ) == "https://proxy.example/qwen/admin/reload"
    assert api._qwen3_tts_reload_url("http://tts.internal:8881/health") is None
    assert api._qwen3_tts_reload_url("file:///v1/audio/speech") is None


def test_qwen3_tts_warmup_route_starts_background_reload_without_exposing_url():
    app, api, server_config = _load_web_server()
    settings = {
        "TTS_PROVIDER": "qwen3-tts",
        "QWEN3_TTS_URL": "http://tts.internal:8881/v1/audio/speech",
    }

    with (
        patch.object(api, "_apply_tts_provider_override", return_value=None),
        patch.object(server_config, "load_jarvis_config"),
        patch.object(
            server_config,
            "get_jarvis_setting",
            side_effect=lambda key, default="": settings.get(key, default),
        ),
        patch.object(api, "_start_qwen3_tts_warmup", return_value=True) as start,
        patch("server.app.is_auth_enabled", return_value=False),
    ):
        with app.test_client() as client:
            response = client.post("/api/tts/warmup", json={"mode": "local"})

    assert response.status_code == 202
    assert response.get_json() == {
        "ok": True,
        "provider": "qwen3-tts",
        "status": "warming",
    }
    start.assert_called_once_with("http://tts.internal:8881/admin/reload", "local")
    assert "tts.internal" not in response.get_data(as_text=True)


def test_qwen3_tts_warmup_route_skips_other_providers():
    app, api, server_config = _load_web_server()

    with (
        patch.object(api, "_apply_tts_provider_override", return_value=None),
        patch.object(server_config, "load_jarvis_config"),
        patch.object(
            server_config,
            "get_jarvis_setting",
            side_effect=lambda key, default="": (
                "elevenlabs" if key == "TTS_PROVIDER" else default
            ),
        ),
        patch.object(api, "_start_qwen3_tts_warmup") as start,
        patch("server.app.is_auth_enabled", return_value=False),
    ):
        with app.test_client() as client:
            response = client.post("/api/tts/warmup", json={"mode": "cloud"})

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "provider": "elevenlabs",
        "status": "skipped",
    }
    start.assert_not_called()


def test_qwen3_tts_warmup_worker_accepts_loaded_status_and_releases_dedupe():
    _, api, _ = _load_web_server()
    reload_url = "http://tts.internal:8881/admin/reload"
    response = Mock()
    response.json.return_value = {"status": "already_loaded"}
    api._qwen3_tts_warmups.add(reload_url)

    with patch("requests.post", return_value=response) as post:
        api._run_qwen3_tts_warmup(reload_url, "local")

    post.assert_called_once_with(reload_url, timeout=(3.05, 90))
    response.raise_for_status.assert_called_once_with()
    assert reload_url not in api._qwen3_tts_warmups


def test_qwen3_tts_warmup_coalesces_overlapping_requests():
    _, api, _ = _load_web_server()
    reload_url = "http://tts.internal:8881/admin/reload"
    api._qwen3_tts_warmups.clear()
    worker = Mock()

    with patch.object(api.threading, "Thread", return_value=worker) as thread:
        assert api._start_qwen3_tts_warmup(reload_url, "local") is True
        assert api._start_qwen3_tts_warmup(reload_url, "local") is False

    thread.assert_called_once()
    worker.start.assert_called_once_with()
    api._qwen3_tts_warmups.clear()
