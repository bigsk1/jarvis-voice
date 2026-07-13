"""Web status TTS caching and final-audio priority regression coverage."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "jarvis-web/client/js/app.js").read_text()
NATIVE_STATUS_SCRIPT = (ROOT / "bin/say-status.sh").read_text()
DOCKER_COMPOSE = (ROOT / "docker-compose.yml").read_text()


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


def test_web_status_tts_cache_supports_docker_persistent_root():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server.routes import api

    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "status-tts-web"

        def get_setting(key, default=""):
            if key == "WEB_STATUS_TTS_CACHE_DIR":
                return str(root)
            return default

        audio_path, mime_path = api._status_tts_cache_paths(
            "cloud", "openai", "Still checking", get_setting
        )

        assert audio_path.parent == root / "cloud"
        assert mime_path.parent == root / "cloud"
        assert audio_path.suffix == ".audio"
        assert mime_path.suffix == ".mime"
        assert audio_path.parent.is_dir()

    assert (
        "JARVIS_OVERRIDE_WEB_STATUS_TTS_CACHE_DIR: "
        "/app/data/cache/status-tts-web"
    ) in DOCKER_COMPOSE


def test_elevenlabs_status_uses_flash_without_changing_final_model_or_voice():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server.app import app
    from server.routes import api
    from server import config as server_config

    settings = {
        "TTS_PROVIDER": "elevenlabs",
        "STATUS_CACHE_ENABLED": "true",
        "ELEVENLABS_TTS_MODEL": "eleven_v3",
        "ELEVENLABS_STATUS_TTS_MODEL": "eleven_flash_v2_5",
        "ELEVENLABS_TTS_VOICE": "custom-voice-id",
    }
    selected_models = []

    def get_setting(key, default=""):
        return settings.get(key, default)

    def generate(text, output_dir, timestamp, model_override=None):
        selected_models.append(model_override)
        path = output_dir / f"tts_{timestamp}_{len(selected_models)}.mp3"
        path.write_bytes(b"elevenlabs-audio")
        return path

    with TemporaryDirectory() as tmp:
        with (
            patch.object(api.Path, "home", return_value=Path(tmp)),
            patch.object(api, "JARVIS_ROOT", Path(tmp)),
            patch.object(api, "_apply_tts_provider_override", return_value=None),
            patch.object(server_config, "load_jarvis_config"),
            patch.object(server_config, "get_jarvis_setting", side_effect=get_setting),
            patch.object(api, "_generate_elevenlabs_tts", side_effect=generate),
            patch.object(api, "log_status_event") as log_status_event,
        ):
            with app.test_client() as client:
                status = client.post("/api/tts", json={
                    "text": "Still checking",
                    "mode": "cloud",
                    "purpose": "status",
                })
                final = client.post("/api/tts", json={
                    "text": "Here is the final answer",
                    "mode": "cloud",
                    "purpose": "final",
                })

    assert status.status_code == final.status_code == 200
    assert selected_models == ["eleven_flash_v2_5", "eleven_v3"]
    started = next(
        call.kwargs
        for call in log_status_event.call_args_list
        if call.args[0] == "tts_provider_started"
    )
    assert started["model"] == "eleven_flash_v2_5"
    cache_settings = api._status_tts_cache_settings("elevenlabs", get_setting)
    assert cache_settings["voice"] == "custom-voice-id"
    assert cache_settings["model"] == "eleven_flash_v2_5"


def test_native_status_script_uses_status_only_elevenlabs_model():
    assert "ELEVENLABS_STATUS_TTS_MODEL" in NATIVE_STATUS_SCRIPT
    assert 'ELEVENLABS_TTS_MODEL="${STATUS_ELEVENLABS_TTS_MODEL:-eleven_multilingual_v2}"' in NATIVE_STATUS_SCRIPT


def test_native_openai_status_cache_includes_tts_instructions():
    openai_cache_line = next(
        line for line in NATIVE_STATUS_SCRIPT.splitlines()
        if '${text}|openai|' in line
    )

    assert "TTS_INSTRUCTIONS" in openai_cache_line


def test_elevenlabs_cache_hashes_only_effective_model_settings():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server.routes import api

    base = {
        "ELEVENLABS_TTS_VOICE": "custom-voice",
        "ELEVENLABS_TTS_MODEL": "eleven_v3",
        "ELEVENLABS_STATUS_TTS_MODEL": "eleven_flash_v2_5",
        "ELEVENLABS_TTS_STABILITY": "0.5",
        "ELEVENLABS_TTS_SIMILARITY_BOOST": "0.75",
        "ELEVENLABS_TTS_STYLE": "0.2",
        "ELEVENLABS_TTS_USE_SPEAKER_BOOST": "true",
    }

    def settings(values):
        return api._status_tts_cache_settings(
            "elevenlabs",
            lambda key, default="": values.get(key, default),
        )

    flash = settings(base)
    changed_style = settings({**base, "ELEVENLABS_TTS_STYLE": "0.8"})
    changed_final_model = settings({**base, "ELEVENLABS_TTS_MODEL": "eleven_multilingual_v2"})
    assert flash != changed_style
    assert flash == changed_final_model

    v3 = {**base, "ELEVENLABS_STATUS_TTS_MODEL": "eleven_v3"}
    assert "style" not in settings(v3)
    assert "use_speaker_boost" not in settings(v3)
    assert settings(v3) == settings({
        **v3,
        "ELEVENLABS_TTS_STYLE": "0.9",
        "ELEVENLABS_TTS_USE_SPEAKER_BOOST": "false",
    })
    assert api._effective_elevenlabs_models(
        lambda key, default="": {
            "ELEVENLABS_TTS_MODEL": "eleven_v3",
            "ELEVENLABS_STATUS_TTS_MODEL": "",
        }.get(key, default)
    ) == ("eleven_v3", "eleven_v3")


def test_elevenlabs_flash_request_preserves_custom_voice_id():
    _purge_server_modules()
    sys.path.insert(0, str(ROOT / "jarvis-web"))
    from server.routes import api
    from server import config as server_config

    settings = {
        "ELEVENLABS_API_KEY": "test-key",
        "ELEVENLABS_TTS_VOICE": "my-custom-cloned-voice",
        "ELEVENLABS_TTS_STABILITY": "0.5",
        "ELEVENLABS_TTS_SIMILARITY_BOOST": "0.75",
        "ELEVENLABS_TTS_STYLE": "0.0",
        "ELEVENLABS_TTS_USE_SPEAKER_BOOST": "true",
    }
    response = type("Response", (), {
        "status_code": 200,
        "content": b"flash-audio",
        "text": "",
    })()

    with TemporaryDirectory() as tmp:
        with (
            patch.object(
                server_config,
                "get_jarvis_setting",
                side_effect=lambda key, default="": settings.get(key, default),
            ),
            patch("requests.post", return_value=response) as post,
        ):
            output = api._generate_elevenlabs_tts(
                "Quick status",
                Path(tmp),
                "test",
                model_override="eleven_flash_v2_5",
            )
            assert output.read_bytes() == b"flash-audio"

    assert post.call_args.args[0].endswith("/my-custom-cloned-voice")
    assert post.call_args.kwargs["json"]["model_id"] == "eleven_flash_v2_5"
