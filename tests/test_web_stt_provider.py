"""Web STT routing contracts for the compatible endpoint integration."""

from __future__ import annotations

import io
import subprocess
import sys
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
