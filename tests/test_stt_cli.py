"""Mode selection contracts for the shared STT command."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from stt_client import STTProviderError  # noqa: E402


SPEC = importlib.util.spec_from_file_location("jarvis_stt_cli", ROOT / "bin" / "stt.py")
assert SPEC and SPEC.loader
stt_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stt_cli)


def _configure(monkeypatch, values):
    monkeypatch.setattr(stt_cli, "load_config", lambda mode: {"mode": mode})
    monkeypatch.setattr(
        stt_cli, "get_config_value", lambda key, default=None: values.get(key, default)
    )


def test_local_mode_keeps_faster_whisper_default(tmp_path, monkeypatch, capsys):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    _configure(monkeypatch, {})
    calls = []
    monkeypatch.setattr(
        stt_cli,
        "_transcribe_provider",
        lambda provider, path, model: calls.append((provider, path, model)) or "hello",
    )

    assert stt_cli.main([str(audio), "--mode", "local"]) == 0
    assert calls == [("faster-whisper", str(audio), "small.en")]
    assert capsys.readouterr().out == "hello\n"


def test_cloud_mode_can_opt_into_compatible_endpoint(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    _configure(
        monkeypatch,
        {"STT_PROVIDER": "openai-compatible", "STT_MODEL": "parakeet-en"},
    )
    calls = []
    monkeypatch.setattr(
        stt_cli,
        "_transcribe_provider",
        lambda provider, path, model: calls.append((provider, model)) or "hello",
    )

    assert stt_cli.main([str(audio), "--mode", "cloud"]) == 0
    assert calls == [("openai-compatible", "parakeet-en")]


def test_cli_uses_explicit_fallback_model_for_transient_failure(
    tmp_path, monkeypatch
):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    _configure(
        monkeypatch,
        {
            "STT_PROVIDER": "openai-compatible",
            "STT_MODEL": "parakeet-en",
            "STT_FALLBACK_PROVIDER": "faster-whisper",
            "STT_FALLBACK_MODEL": "tiny.en",
        },
    )
    calls = []

    def transcribe(provider, _path, model):
        calls.append((provider, model))
        if provider == "openai-compatible":
            raise STTProviderError("offline", retryable=True)
        return "fallback text"

    monkeypatch.setattr(stt_cli, "_transcribe_provider", transcribe)
    assert stt_cli.main([str(audio), "--mode", "local"]) == 0
    assert calls == [
        ("openai-compatible", "parakeet-en"),
        ("faster-whisper", "tiny.en"),
    ]


def test_explicit_provider_disables_configured_fallback(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"audio")
    _configure(
        monkeypatch,
        {
            "STT_PROVIDER": "openai-compatible",
            "STT_FALLBACK_PROVIDER": "faster-whisper",
        },
    )
    calls = []

    def transcribe(provider, _path, _model):
        calls.append(provider)
        raise STTProviderError("offline", retryable=True)

    monkeypatch.setattr(stt_cli, "_transcribe_provider", transcribe)
    try:
        stt_cli.main(
            [str(audio), "--mode", "local", "--provider", "openai-compatible"]
        )
    except STTProviderError:
        pass
    else:
        raise AssertionError("retryable primary failure should propagate")
    assert calls == ["openai-compatible"]
