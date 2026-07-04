"""Web status TTS caching and final-audio priority regression coverage."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "jarvis-web/client/js/app.js").read_text()


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


def test_web_client_cancels_status_tts_before_final_audio():
    assert "this._cancelStatusTTS();" in APP_JS
    assert "this._completedResponseIds.has(data.message_id)" in APP_JS
    assert "purpose: kind" in APP_JS
    assert "controller = new AbortController();" in APP_JS
    assert "this.currentAudioKind === 'final'" in APP_JS
    assert "!this.currentAudio.ended" in APP_JS


def test_web_status_tts_reuses_persistent_audio_cache():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server.app import app
    from server.routes import api
    from server import config as server_config

    settings = {
        "TTS_PROVIDER": "openai",
        "STATUS_CACHE_ENABLED": "true",
        "VOICE": "onyx",
        "TTS_MODEL": "gpt-4o-mini-tts",
    }

    def get_setting(key, default=""):
        return settings.get(key, default)

    def generate(text, output_dir, timestamp):
        path = output_dir / f"tts_{timestamp}.mp3"
        path.write_bytes(b"cached-status-audio")
        return path

    with TemporaryDirectory() as tmp:
        with (
            patch.object(api.Path, "home", return_value=Path(tmp)),
            patch.object(api, "JARVIS_ROOT", Path(tmp)),
            patch.object(api, "_apply_tts_provider_override", return_value=None),
            patch.object(server_config, "load_jarvis_config"),
            patch.object(server_config, "get_jarvis_setting", side_effect=get_setting),
            patch.object(api, "_generate_openai_tts", side_effect=generate) as generate_tts,
            patch.object(api, "log_status_event") as log_status_event,
        ):
            with app.test_client() as client:
                first = client.post("/api/tts", json={
                    "text": "Still checking that now",
                    "mode": "cloud",
                    "purpose": "status",
                })
                second = client.post("/api/tts", json={
                    "text": "Still checking that now",
                    "mode": "cloud",
                    "purpose": "status",
                })
                final = client.post("/api/tts", json={
                    "text": "Still checking that now",
                    "mode": "cloud",
                    "purpose": "final",
                })

    assert first.status_code == 200
    assert first.headers["X-Jarvis-TTS-Cache"] == "miss"
    assert second.status_code == 200
    assert second.headers["X-Jarvis-TTS-Cache"] == "hit"
    assert final.headers["X-Jarvis-TTS-Cache"] == "disabled"
    assert first.data == second.data == b"cached-status-audio"
    assert generate_tts.call_count == 2
    events = [call.args[0] for call in log_status_event.call_args_list]
    assert events.count("tts_provider_started") == 1
    assert events.count("tts_provider_completed") == 1
    assert events.count("tts_cache_hit") == 1
