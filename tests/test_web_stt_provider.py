"""Web STT routing contracts for the compatible endpoint integration."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest
from flask import Flask

from server_package_utils import load_server_package


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "jarvis-web"))
load_server_package("jarvis_web_stt_test", ROOT / "jarvis-web" / "server")

from jarvis_web_stt_test import config as web_config  # noqa: E402
from jarvis_web_stt_test.routes import api  # noqa: E402
from stt_client import STTProviderError  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_empty_transcription_has_distinct_code_and_removes_upload(mode, monkeypatch):
    monkeypatch.setattr(web_config, 'load_jarvis_config', lambda _mode: None)
    monkeypatch.setattr(web_config, 'get_jarvis_setting', lambda _key, default=None: default)
    paths = []

    def transcribe(path, *_args):
        paths.append(path)
        return ''

    monkeypatch.setattr(api, '_transcribe_configured', transcribe)
    response = _client().post('/api/stt', data={
        'mode': mode, 'audio': (io.BytesIO(b'non-speech'), 'talk.wav', 'audio/wav'),
    }, content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json() == {'ok': False, 'error': 'No speech detected', 'code': 'no_speech'}
    assert len(paths) == 1
    assert not Path(paths[0]).exists()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_interruption_wav_upload_retains_format_and_is_removed(mode, monkeypatch):
    monkeypatch.setattr(web_config, "load_jarvis_config", lambda _mode: None)
    monkeypatch.setattr(web_config, "get_jarvis_setting", lambda _key, default=None: default)
    observed = []

    def transcribe(path, selected_mode, _provider, _model):
        assert selected_mode == mode
        assert Path(path).suffix == ".wav"
        assert Path(path).read_bytes() == b"RIFFtest-wave"
        observed.append(path)
        return "And tomorrow?"

    monkeypatch.setattr(api, "_transcribe_configured", transcribe)
    response = _client().post("/api/stt", data={
        "mode": mode, "audio": (io.BytesIO(b"RIFFtest-wave"), "talk.wav", "audio/wav"),
    }, content_type="multipart/form-data")
    assert response.get_json() == {"ok": True, "text": "And tomorrow?"}
    assert len(observed) == 1
    assert not Path(observed[0]).exists()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_speech_children_exclude_credentials_and_keep_selected_device(mode, tmp_path, monkeypatch):
    import config_loader
    source = tmp_path / "recording.webm"
    source.write_bytes(b"audio")
    monkeypatch.setenv("UNRELATED_SECRET", "canary-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "canary-key")
    monkeypatch.setenv("HF_TOKEN", "canary-token")
    monkeypatch.setenv("STT_DEVICE", "wrong-mode-device")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "model-cache"))
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda selected_mode: {
        "STT_DEVICE": "cpu", "STT_COMPUTE_TYPE": "int8",
        "HF_HOME": str(tmp_path / f"{selected_mode}-cache"),
    })
    environments = []

    def run(command, **kwargs):
        env = kwargs["env"]
        assert "canary-secret" not in env.values()
        assert "OPENAI_API_KEY" not in env and "HF_TOKEN" not in env
        assert env["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
        assert Path(env["HOME"]).is_dir()
        assert not list(Path(env["HOME"]).iterdir())
        environments.append(env)
        if command[0] == "ffmpeg":
            assert "STT_DEVICE" not in env
            Path(command[-1]).write_bytes(b"wav")
        else:
            assert env["JARVIS_MODE"] == mode
            assert env["STT_DEVICE"] == "cpu"
            assert env["HF_HOME"] == str(tmp_path / f"{mode}-cache")
        return subprocess.CompletedProcess(command, 0, stdout="And tomorrow?", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert api._transcribe_faster_whisper(str(source), mode, "small.en") == "And tomorrow?"
    assert len(environments) == 2
    assert all(not Path(env["HOME"]).exists() for env in environments)


def test_real_ffmpeg_speech_conversion_with_restricted_environment(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is not installed")
    from speech_child_environment import speech_child_environment

    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(bytes(3200))
    encoded = tmp_path / "source.ogg"
    with speech_child_environment(dict(os.environ)) as child_environment:
        subprocess.run(["ffmpeg", "-y", "-i", str(source), str(encoded)],
                       env=child_environment, check=True, capture_output=True, timeout=10)
    converted = api._convert_to_wav(str(encoded))
    assert converted != str(encoded)
    with wave.open(converted, "rb") as result:
        assert result.getframerate() == 16000
        assert result.getnchannels() == 1
        assert result.getnframes() > 0


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_restricted_stt_child_does_not_reload_mode_credentials(mode, tmp_path):
    from speech_child_environment import speech_child_environment

    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from config_loader import load_config, get_config_value; "
        "load_config(sys.argv[2]); "
        "assert get_config_value('STT_DEVICE') == 'cpu'; "
        "assert get_config_value('OPENAI_API_KEY') is None; "
        "assert get_config_value('STT_API_KEY') is None"
    )
    source = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
              "STT_DEVICE": "cpu", "OPENAI_API_KEY": "excluded-canary"}
    with speech_child_environment(source, transcription=True) as child_environment:
        assert child_environment["HF_HOME"] == str(tmp_path / ".cache" / "huggingface")
        subprocess.run([sys.executable, "-c", script, str(ROOT / "lib"), mode],
                       env=child_environment, check=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_web_route_accepts_compatible_provider_in_either_mode(mode, monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_MODEL": "parakeet-en",
    }
    monkeypatch.setattr(web_config, "load_jarvis_config", lambda _mode: None)
    monkeypatch.setattr(
        web_config,
        "get_jarvis_setting",
        lambda key, default=None: values.get(key, default),
    )
    observed = {}

    def fake_transcribe(path, selected_mode, provider, model):
        observed.update(
            path=path, mode=selected_mode, provider=provider, model=model
        )
        return "local parakeet text"

    monkeypatch.setattr(api, "_transcribe_configured", fake_transcribe)
    response = _client().post(
        "/api/stt",
        data={"mode": mode, "audio": (io.BytesIO(b"audio"), "clip.webm")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "text": "local parakeet text"}
    assert observed["mode"] == mode
    assert observed["provider"] == "openai-compatible"
    assert observed["model"] == "parakeet-en"


def test_web_compatible_dispatch_uses_explicit_faster_whisper_fallback(monkeypatch):
    values = {
        "STT_FALLBACK_PROVIDER": "faster-whisper",
        "STT_FALLBACK_MODEL": "small.en",
    }
    monkeypatch.setattr(
        web_config,
        "get_jarvis_setting",
        lambda key, default=None: values.get(key, default),
    )
    calls = []

    def compatible(_path, model):
        calls.append(("openai-compatible", model))
        raise STTProviderError("mini-ai disconnected", retryable=True)

    def faster(_path, mode, model):
        calls.append(("faster-whisper", mode, model))
        return "fallback text"

    monkeypatch.setattr(api, "_transcribe_compatible", compatible)
    monkeypatch.setattr(api, "_transcribe_faster_whisper", faster)

    result = api._transcribe_configured(
        "/tmp/clip.webm", "cloud", "openai-compatible", "parakeet-en"
    )

    assert result == "fallback text"
    assert calls == [
        ("openai-compatible", "parakeet-en"),
        ("faster-whisper", "cloud", "small.en"),
    ]


def test_web_unknown_provider_does_not_fall_through_to_openai(monkeypatch):
    values = {"STT_PROVIDER": "parakeet", "STT_MODEL": "parakeet-en"}
    monkeypatch.setattr(web_config, "load_jarvis_config", lambda _mode: None)
    monkeypatch.setattr(
        web_config,
        "get_jarvis_setting",
        lambda key, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        api,
        "_transcribe_configured",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("unknown provider must not dispatch")
        ),
    )

    response = _client().post(
        "/api/stt",
        data={"mode": "local", "audio": (io.BytesIO(b"audio"), "clip.webm")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert "Unsupported STT_PROVIDER" in response.get_json()["error"]


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_web_wav_conversion_removes_partial_output_on_failure(
    failure, tmp_path, monkeypatch
):
    source = tmp_path / "recording.webm"
    source.write_bytes(b"original recording")
    output = source.with_suffix(".wav")
    error = (
        subprocess.CalledProcessError(1, "ffmpeg", stderr=b"invalid audio")
        if failure == "error"
        else subprocess.TimeoutExpired("ffmpeg", timeout=30)
    )

    def fail_conversion(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial converted recording")
        raise error

    monkeypatch.setattr(subprocess, "run", fail_conversion)

    if failure == "error":
        assert api._convert_to_wav(str(source)) == str(source)
    else:
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            api._convert_to_wav(str(source))
        assert raised.value is error

    assert source.read_bytes() == b"original recording"
    assert not output.exists()


def test_web_wav_conversion_keeps_successful_output_for_transcription(
    tmp_path, monkeypatch
):
    source = tmp_path / "recording.webm"
    source.write_bytes(b"original recording")
    output = source.with_suffix(".wav")

    def convert(command, **_kwargs):
        Path(command[-1]).write_bytes(b"converted recording")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", convert)

    assert api._convert_to_wav(str(source)) == str(output)
    assert output.read_bytes() == b"converted recording"
    assert source.read_bytes() == b"original recording"


def test_web_wav_conversion_preserves_existing_wav(tmp_path, monkeypatch):
    source = tmp_path / "recording.WAV"
    source.write_bytes(b"original recording")

    def unexpected_conversion(*_args, **_kwargs):
        pytest.fail("WAV input must pass through without conversion")

    monkeypatch.setattr(subprocess, "run", unexpected_conversion)

    assert api._convert_to_wav(str(source)) == str(source)
    assert source.read_bytes() == b"original recording"


@pytest.mark.parametrize("outcome", ["success", "error", "timeout"])
def test_web_faster_whisper_removes_converted_wav_after_transcription(
    outcome, tmp_path, monkeypatch
):
    source = tmp_path / "recording.webm"
    source.write_bytes(b"original recording")
    output = source.with_suffix(".wav")
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"converted recording")
            return subprocess.CompletedProcess(command, 0)

        assert command[-1] == str(output)
        assert output.read_bytes() == b"converted recording"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, timeout=10)
        return subprocess.CompletedProcess(
            command,
            3 if outcome == "error" else 0,
            stdout="transcribed words\n",
            stderr="transcription failed" if outcome == "error" else "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(api, "_stt_timeout", lambda: 10)

    if outcome == "success":
        assert (
            api._transcribe_faster_whisper(str(source), "local", "small.en")
            == "transcribed words"
        )
    else:
        message = "timed out" if outcome == "timeout" else "process failed"
        with pytest.raises(STTProviderError, match=message):
            api._transcribe_faster_whisper(str(source), "local", "small.en")

    assert len(calls) == 2
    assert source.read_bytes() == b"original recording"
    assert not output.exists()
