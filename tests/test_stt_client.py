"""Focused provider and fallback contracts for speech-to-text."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import stt_client  # noqa: E402
from stt_client import (  # noqa: E402
    STTProviderError,
    normalize_stt_provider,
    resolve_transcriptions_url,
    run_with_stt_fallback,
    transcribe_openai_compatible,
)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("http://127.0.0.1:5092", "http://127.0.0.1:5092/v1/audio/transcriptions"),
        ("http://127.0.0.1:5092/v1", "http://127.0.0.1:5092/v1/audio/transcriptions"),
        (
            "http://127.0.0.1:5092/v1/audio/transcriptions",
            "http://127.0.0.1:5092/v1/audio/transcriptions",
        ),
    ],
)
def test_resolve_transcriptions_url_accepts_supported_forms(configured, expected):
    assert resolve_transcriptions_url(configured) == expected


def test_provider_names_are_explicit_not_openai_catch_all():
    assert normalize_stt_provider("OpenAI-Compatible") == "openai-compatible"
    with pytest.raises(ValueError, match="Unsupported STT_PROVIDER"):
        normalize_stt_provider("parakeet")


def test_compatible_request_uses_dedicated_key_model_and_audio_type(tmp_path, monkeypatch):
    audio = tmp_path / "dictation.webm"
    audio.write_bytes(b"audio")
    observed = {}

    def fake_post(url, **kwargs):
        observed.update(url=url, **kwargs)
        return SimpleNamespace(status_code=200, text='{"text":"hello"}', json=lambda: {"text": " hello "})

    monkeypatch.setattr(stt_client.requests, "post", fake_post)

    result = transcribe_openai_compatible(
        str(audio),
        base_url="http://127.0.0.1:5092/v1",
        api_key="private-gateway-key",
        model="parakeet-en",
        timeout=7,
    )

    assert result == "hello"
    assert observed["url"] == "http://127.0.0.1:5092/v1/audio/transcriptions"
    assert observed["headers"] == {"Authorization": "Bearer private-gateway-key"}
    assert observed["data"] == {"model": "parakeet-en", "response_format": "json"}
    assert observed["files"]["file"][2] == "audio/webm"
    assert observed["timeout"] == 7


def test_blank_compatible_key_omits_authorization(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    observed = {}

    def fake_post(_url, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"text": ""})

    monkeypatch.setattr(stt_client.requests, "post", fake_post)
    assert transcribe_openai_compatible(
        str(audio), base_url="http://localhost:5092", api_key="", model="model"
    ) == ""
    assert observed["headers"] == {}


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
def test_transient_http_failures_are_retryable(tmp_path, monkeypatch, status):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        stt_client.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=status, text="temporarily unavailable"
        ),
    )

    with pytest.raises(STTProviderError) as exc:
        transcribe_openai_compatible(
            str(audio), base_url="http://localhost:5092", api_key="key", model="model"
        )
    assert exc.value.retryable is True


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_auth_model_and_endpoint_failures_do_not_retry(tmp_path, monkeypatch, status):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        stt_client.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=status, text="rejected"),
    )

    with pytest.raises(STTProviderError) as exc:
        transcribe_openai_compatible(
            str(audio), base_url="http://localhost:5092", api_key="key", model="model"
        )
    assert exc.value.retryable is False


def test_disconnect_is_retryable(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")

    def disconnect(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(stt_client.requests, "post", disconnect)
    with pytest.raises(STTProviderError) as exc:
        transcribe_openai_compatible(
            str(audio), base_url="http://localhost:5092", api_key="key", model="model"
        )
    assert exc.value.retryable is True


def test_invalid_success_payload_does_not_trigger_fallback(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        stt_client.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text="not-json", json=lambda: (_ for _ in ()).throw(ValueError())
        ),
    )

    with pytest.raises(STTProviderError) as exc:
        transcribe_openai_compatible(
            str(audio), base_url="http://localhost:5092", api_key="key", model="model"
        )
    assert exc.value.retryable is False


def test_fallback_runs_only_for_retryable_failure():
    calls = []

    def transcribe(provider):
        calls.append(provider)
        if provider == "openai-compatible":
            raise STTProviderError("offline", retryable=True)
        return "local transcript"

    result = run_with_stt_fallback(
        "openai-compatible", "faster-whisper", transcribe
    )
    assert result == "local transcript"
    assert calls == ["openai-compatible", "faster-whisper"]


def test_no_fallback_for_nonretryable_failure():
    calls = []

    def transcribe(provider):
        calls.append(provider)
        raise STTProviderError("unauthorized", retryable=False)

    with pytest.raises(STTProviderError):
        run_with_stt_fallback("openai-compatible", "faster-whisper", transcribe)
    assert calls == ["openai-compatible"]


def test_empty_transcript_is_not_a_fallback_condition():
    calls = []

    def transcribe(provider):
        calls.append(provider)
        return ""

    assert run_with_stt_fallback(
        "openai-compatible", "faster-whisper", transcribe
    ) == ""
    assert calls == ["openai-compatible"]
