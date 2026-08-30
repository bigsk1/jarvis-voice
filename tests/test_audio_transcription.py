"""Long-file transcription policy and first-class tool contracts."""

from __future__ import annotations

import importlib.util
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import audio_transcription  # noqa: E402
from audio_transcription import (  # noqa: E402
    AudioInfo,
    AudioTranscriptionResult,
    AudioTranscriptionSettings,
    PartialAudioTranscriptionError,
    load_audio_transcription_settings,
    transcribe_audio_file,
)
from stash_helper import get_retention_policy  # noqa: E402
from stt_client import STTProviderError  # noqa: E402

TOOL_SPEC = importlib.util.spec_from_file_location(
    "jarvis_transcribe_audio_tool", ROOT / "skills" / "transcribe_audio.py"
)
assert TOOL_SPEC and TOOL_SPEC.loader
transcribe_tool = importlib.util.module_from_spec(TOOL_SPEC)
TOOL_SPEC.loader.exec_module(transcribe_tool)


def _settings(**overrides) -> AudioTranscriptionSettings:
    values = {
        "provider": "openai-compatible",
        "model": "parakeet-en",
        "fallback_provider": "",
        "fallback_model": "",
        "max_file_bytes": 250 * 1024 * 1024,
        "max_duration_seconds": 7200,
        "provider_max_bytes": 25 * 1024 * 1024,
        "chunk_seconds": 600,
        "timeout_seconds": 900,
        "request_timeout_seconds": 300.0,
        "compatible_base_url": "http://stt-host:5092/v1",
        "compatible_api_key": "gateway-key",
        "openai_api_key": "openai-key",
        "device": "cpu",
        "compute_type": "int8",
    }
    values.update(overrides)
    return AudioTranscriptionSettings(**values)


def _info(path: Path, *, size: int = 1024, duration: float = 60.0) -> AudioInfo:
    return AudioInfo(
        path=path,
        filename=path.name,
        size_bytes=size,
        duration_seconds=duration,
        format_name="wav",
    )


def test_batch_policy_inherits_primary_provider_and_model_but_not_stt_fallback(
    monkeypatch,
):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_MODEL": "parakeet-en",
        "STT_FALLBACK_PROVIDER": "openai",
    }
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    settings = load_audio_transcription_settings()

    assert settings.provider == "openai-compatible"
    assert settings.model == "parakeet-en"
    assert settings.fallback_provider == ""
    assert settings.chunk_seconds == 300


def test_explicit_batch_provider_without_model_uses_its_own_default(monkeypatch):
    values = {
        "AUDIO_TRANSCRIBE_PROVIDER": "openai",
        "STT_PROVIDER": "openai-compatible",
        "STT_MODEL": "parakeet-en",
    }
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    settings = load_audio_transcription_settings()

    assert settings.provider == "openai"
    assert settings.model == "whisper-1"


def test_pinned_matching_provider_still_inherits_stt_model(monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_MODEL": "custom-parakeet",
        "AUDIO_TRANSCRIBE_PROVIDER": "openai-compatible",
    }
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    settings = load_audio_transcription_settings()

    assert settings.model == "custom-parakeet"


def test_compatible_url_override_never_inherits_stt_api_key(monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_BASE_URL": "http://lan-stt:5092/v1",
        "STT_API_KEY": "lan-secret",
        "AUDIO_TRANSCRIBE_BASE_URL": "https://vendor.example/v1",
        "AUDIO_TRANSCRIBE_API_KEY": "   ",
    }
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    settings = load_audio_transcription_settings()

    assert settings.compatible_base_url == "https://vendor.example/v1"
    assert settings.compatible_api_key == ""


def test_compatible_blank_override_inherits_stt_endpoint_pair(monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_BASE_URL": "http://lan-stt:5092/v1",
        "STT_API_KEY": "lan-secret",
        "AUDIO_TRANSCRIBE_BASE_URL": "   ",
        "AUDIO_TRANSCRIBE_API_KEY": "   ",
        "AUDIO_TRANSCRIBE_DEVICE": "   ",
        "STT_DEVICE": "cuda",
        "AUDIO_TRANSCRIBE_COMPUTE_TYPE": "   ",
        "STT_COMPUTE_TYPE": "float16",
    }
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    settings = load_audio_transcription_settings()

    assert settings.compatible_base_url == "http://lan-stt:5092/v1"
    assert settings.compatible_api_key == "lan-secret"
    assert settings.device == "cuda"
    assert settings.compute_type == "float16"


def test_compatible_key_without_dedicated_url_fails_closed(monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "STT_BASE_URL": "http://lan-stt:5092/v1",
        "STT_API_KEY": "lan-secret",
        "AUDIO_TRANSCRIBE_API_KEY": "different-secret",
    }
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    with pytest.raises(ValueError, match="requires AUDIO_TRANSCRIBE_BASE_URL"):
        load_audio_transcription_settings()


def test_provider_credentials_are_snapshotted_and_never_crossed():
    settings = _settings(
        compatible_base_url="https://compatible.example/v1",
        compatible_api_key="compatible-key",
        openai_api_key="openai-key",
    )

    assert audio_transcription._remote_endpoint("openai-compatible", settings) == (
        "https://compatible.example/v1",
        "compatible-key",
    )
    assert audio_transcription._remote_endpoint("openai", settings) == (
        "https://api.openai.com/v1",
        "openai-key",
    )


def test_request_timeout_is_clamped_to_overall_deadline(monkeypatch):
    values = {
        "STT_PROVIDER": "openai-compatible",
        "AUDIO_TRANSCRIBE_TIMEOUT_SECONDS": "60",
        "AUDIO_TRANSCRIBE_REQUEST_TIMEOUT_SECONDS": "300",
    }
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda key, default=None: values.get(key, default),
    )

    assert load_audio_transcription_settings().request_timeout_seconds == 60.0


def test_local_mode_default_does_not_silently_select_openai(monkeypatch):
    monkeypatch.setattr(audio_transcription, "get_active_config_mode", lambda: "local")
    monkeypatch.setattr(
        audio_transcription,
        "get_config_value",
        lambda _key, default=None: default,
    )

    settings = load_audio_transcription_settings()

    assert settings.provider == "faster-whisper"
    assert settings.model == "small.en"


def test_small_remote_file_is_normalized_to_wav_before_multipart(tmp_path, monkeypatch):
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"audio")
    info = _info(source)
    observed = {}
    rendered = []
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)
    def fake_render(render_source, output, start, duration, **_kwargs):
        rendered.append((render_source, output, start, duration))
        output.write_bytes(b"normalized wav")

    def fake_transcribe(path, **kwargs):
        observed.update(path=path, **kwargs)
        return "hello from the recording"

    monkeypatch.setattr(audio_transcription, "_render_wav_chunk", fake_render)
    monkeypatch.setattr(audio_transcription, "transcribe_openai_compatible", fake_transcribe)

    result = transcribe_audio_file(source, settings=_settings())

    assert result.transcript == "hello from the recording"
    assert result.chunk_count == 1
    assert len(rendered) == 1
    render_source, rendered_path, start, duration = rendered[0]
    assert render_source == source
    assert rendered_path.name == "chunk_0001.wav"
    assert start == 0.0
    assert duration == info.duration_seconds
    assert observed.pop("path").endswith("/chunk_0001.wav")
    assert observed == {
        "base_url": "http://stt-host:5092/v1",
        "api_key": "gateway-key",
        "model": "parakeet-en",
        "timeout": 300.0,
    }


def test_long_remote_file_is_split_and_never_sends_oversized_original(
    tmp_path, monkeypatch
):
    source = tmp_path / "long.m4a"
    source.write_bytes(b"original")
    info = _info(source, size=36 * 1024 * 1024, duration=1250.0)
    sent_paths = []
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)
    monkeypatch.setattr(audio_transcription, "_silence_points", lambda *_a, **_k: [590.0, 1190.0])
    def render(_source, output, _start, _duration, **_kwargs):
        output.write_bytes(b"bounded wav")

    def transcribe(path, **_kwargs):
        sent_paths.append(Path(path))
        return f"chunk {len(sent_paths)}"

    monkeypatch.setattr(audio_transcription, "_render_wav_chunk", render)
    monkeypatch.setattr(audio_transcription, "transcribe_openai_compatible", transcribe)

    result = transcribe_audio_file(source, settings=_settings())

    assert result.transcript == "chunk 1\n\nchunk 2\n\nchunk 3"
    assert result.chunk_count == 3
    assert len(sent_paths) == 3
    assert all(path.name.startswith("chunk_") and path.suffix == ".wav" for path in sent_paths)
    assert source not in sent_paths


def test_remote_partial_failure_preserves_completed_chunk_text(tmp_path, monkeypatch):
    source = tmp_path / "partial.m4a"
    source.write_bytes(b"audio")
    info = _info(source, duration=1200.0)
    calls = 0
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)
    monkeypatch.setattr(audio_transcription, "_silence_points", lambda *_a, **_k: [])
    monkeypatch.setattr(
        audio_transcription,
        "_render_wav_chunk",
        lambda _source, output, *_a, **_k: output.write_bytes(b"wav"),
    )

    def transcribe(_path, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "completed first chunk"
        raise STTProviderError("provider stopped", retryable=True)

    monkeypatch.setattr(audio_transcription, "transcribe_openai_compatible", transcribe)

    with pytest.raises(PartialAudioTranscriptionError) as raised:
        transcribe_audio_file(source, settings=_settings())

    assert raised.value.partial_transcript == "completed first chunk"
    assert raised.value.completed_chunks == 1
    assert raised.value.total_chunks == 2
    assert raised.value.retryable is False


def test_remote_empty_chunk_is_marked_but_fully_silent_file_fails(tmp_path, monkeypatch):
    source = tmp_path / "silence.m4a"
    source.write_bytes(b"audio")
    info = _info(source, duration=1200.0)
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)
    monkeypatch.setattr(audio_transcription, "_silence_points", lambda *_a, **_k: [])
    monkeypatch.setattr(
        audio_transcription,
        "_render_wav_chunk",
        lambda _source, output, *_a, **_k: output.write_bytes(b"wav"),
    )
    responses = iter(["", "speech in second chunk"])
    monkeypatch.setattr(
        audio_transcription,
        "transcribe_openai_compatible",
        lambda *_a, **_k: next(responses),
    )

    result = transcribe_audio_file(source, settings=_settings())

    assert "No speech detected in audio chunk 1 of 2" in result.transcript
    assert result.transcript.endswith("speech in second chunk")

    monkeypatch.setattr(
        audio_transcription,
        "transcribe_openai_compatible",
        lambda *_a, **_k: "",
    )
    with pytest.raises(STTProviderError, match="No speech detected"):
        transcribe_audio_file(source, settings=_settings())


def test_nonretryable_provider_failure_never_uses_file_fallback(tmp_path, monkeypatch):
    source = tmp_path / "auth.m4a"
    source.write_bytes(b"audio")
    monkeypatch.setattr(
        audio_transcription,
        "inspect_audio_file",
        lambda *_a, **_k: _info(source),
    )
    monkeypatch.setattr(
        audio_transcription,
        "_transcribe_remote",
        lambda *_a, **_k: (_ for _ in ()).throw(
            STTProviderError("authentication failed", retryable=False)
        ),
    )

    class ForbiddenFallback:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("non-retryable failures must not fall back")

    monkeypatch.setattr(
        audio_transcription, "_FasterWhisperTranscriber", ForbiddenFallback
    )

    with pytest.raises(STTProviderError, match="authentication failed"):
        transcribe_audio_file(
            source,
            settings=_settings(
                fallback_provider="faster-whisper", fallback_model="tiny.en"
            ),
        )


def test_monotonic_deadline_applies_before_provider_work(tmp_path, monkeypatch):
    source = tmp_path / "deadline.m4a"
    source.write_bytes(b"audio")
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(audio_transcription.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(audio_transcription, "_deadline_alarm", lambda _d: nullcontext())
    monkeypatch.setattr(
        audio_transcription,
        "inspect_audio_file",
        lambda *_a, **_k: _info(source),
    )

    with pytest.raises(STTProviderError, match="overall deadline"):
        transcribe_audio_file(source, settings=_settings(timeout_seconds=1))


def test_local_model_is_loaded_once_and_receives_complete_file(tmp_path, monkeypatch):
    source = tmp_path / "long.wav"
    source.write_bytes(b"audio")
    info = _info(source, size=50 * 1024 * 1024, duration=3600.0)
    created = []
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)

    class FakeWhisper:
        def __init__(self, model, **kwargs):
            created.append(model)
            assert kwargs == {"device": "cpu", "compute_type": "int8"}

        def transcribe(self, path):
            assert path == source
            return "local transcript"

    monkeypatch.setattr(audio_transcription, "_FasterWhisperTranscriber", FakeWhisper)

    result = transcribe_audio_file(
        source,
        settings=_settings(provider="faster-whisper", model="medium.en"),
    )

    assert result.transcript == "local transcript"
    assert result.chunk_count == 1
    assert created == ["medium.en"]


def test_file_tool_fallback_is_explicit_and_reports_actual_provider(
    tmp_path, monkeypatch
):
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"audio")
    info = _info(source)
    monkeypatch.setattr(audio_transcription, "inspect_audio_file", lambda *_a, **_k: info)
    monkeypatch.setattr(
        audio_transcription,
        "_transcribe_remote",
        lambda *_a, **_k: (_ for _ in ()).throw(
            STTProviderError("compatible host offline", retryable=True)
        ),
    )

    class FakeWhisper:
        def __init__(self, model, **_kwargs):
            assert model == "tiny.en"

        def transcribe(self, _path):
            return "fallback transcript"

    monkeypatch.setattr(audio_transcription, "_FasterWhisperTranscriber", FakeWhisper)

    result = transcribe_audio_file(
        source,
        settings=_settings(
            fallback_provider="faster-whisper", fallback_model="tiny.en"
        ),
    )

    assert result.provider_requested == "openai-compatible"
    assert result.provider == "faster-whisper"
    assert result.fallback_used is True
    assert result.fallback_reason == "compatible host offline"


def test_size_limit_fails_before_ffprobe(tmp_path, monkeypatch):
    source = tmp_path / "huge.wav"
    source.write_bytes(b"12345")
    monkeypatch.setattr(
        audio_transcription.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("ffprobe must not run after size rejection"),
    )

    with pytest.raises(ValueError, match="exceeds"):
        audio_transcription.inspect_audio_file(
            source, max_file_bytes=4, max_duration_seconds=60
        )


def test_tool_bounds_inline_transcript_and_returns_full_stash_reference(
    tmp_path, monkeypatch
):
    source = tmp_path / "meeting.m4a"
    source.write_bytes(b"audio")
    long_transcript = "word " * 2000
    monkeypatch.setattr(
        transcribe_tool,
        "_resolve_source",
        lambda _source: (source, "stash://space_audio/f_source"),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: AudioTranscriptionResult(
            transcript=long_transcript,
            info=_info(source, duration=1200),
            provider_requested="openai-compatible",
            provider="openai-compatible",
            model="parakeet-en",
            fallback_used=False,
            fallback_reason=None,
            chunk_count=2,
        ),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "_save_transcript",
        lambda _plan, transcript: (
            "stash://space_transcript/f_text",
            "space_transcript",
        ) if transcript == long_transcript else pytest.fail("full transcript was not saved"),
    )

    result = transcribe_tool.execute({"source": "stash://space_audio/f_source"})

    assert result["ok"] is True
    data = result["data"]
    assert "transcript" not in data
    assert len(data["transcript_excerpt"]) == transcribe_tool.INLINE_TRANSCRIPT_CHARS
    assert data["transcript_truncated"] is True
    assert data["transcript_chars"] == len(long_transcript)
    assert data["transcript_stash_ref"] == "stash://space_transcript/f_text"


def test_tool_forces_stash_for_long_transcript_when_save_was_disabled(
    tmp_path, monkeypatch
):
    source = tmp_path / "long.m4a"
    source.write_bytes(b"audio")
    transcript = "x" * (transcribe_tool.INLINE_TRANSCRIPT_CHARS + 1)
    monkeypatch.setattr(
        transcribe_tool, "_resolve_source", lambda _source: (source, None)
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: AudioTranscriptionResult(
            transcript=transcript,
            info=_info(source),
            provider_requested="openai-compatible",
            provider="openai-compatible",
            model="parakeet-en",
            fallback_used=False,
            fallback_reason=None,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "_save_transcript",
        lambda _plan, text: ("stash://space/f_text", "space")
        if text == transcript
        else pytest.fail("wrong transcript"),
    )

    result = transcribe_tool.execute({"source": str(source), "save_to_stash": False})

    assert result["ok"] is True
    assert result["data"]["stash_forced"] is True
    assert result["data"]["transcript_stash_ref"] == "stash://space/f_text"
    assert "transcript" not in result["data"]


def test_tool_returns_complete_text_when_stash_save_fails(tmp_path, monkeypatch):
    source = tmp_path / "save-failure.m4a"
    source.write_bytes(b"audio")
    transcript = "z" * (transcribe_tool.INLINE_TRANSCRIPT_CHARS + 500)
    monkeypatch.setattr(
        transcribe_tool, "_resolve_source", lambda _source: (source, None)
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: AudioTranscriptionResult(
            transcript=transcript,
            info=_info(source),
            provider_requested="openai-compatible",
            provider="openai-compatible",
            model="parakeet-en",
            fallback_used=False,
            fallback_reason=None,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "_save_transcript",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    result = transcribe_tool.execute({"source": str(source)})

    assert result["ok"] is True
    assert result["data"]["transcript"] == transcript
    assert "transcript_excerpt" not in result["data"]
    assert result["data"]["transcript_save_error"]


def test_tool_short_result_emits_transcript_without_duplicate_excerpt(
    tmp_path, monkeypatch
):
    source = tmp_path / "short.m4a"
    source.write_bytes(b"audio")
    monkeypatch.setattr(
        transcribe_tool, "_resolve_source", lambda _source: (source, None)
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: AudioTranscriptionResult(
            transcript="short complete transcript",
            info=_info(source),
            provider_requested="openai-compatible",
            provider="openai-compatible",
            model="parakeet-en",
            fallback_used=False,
            fallback_reason=None,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "_save_transcript",
        lambda *_a, **_k: ("stash://space/f_text", "space"),
    )

    result = transcribe_tool.execute({"source": str(source)})

    assert result["data"]["transcript"] == "short complete transcript"
    assert "transcript_excerpt" not in result["data"]


def test_tool_saves_partial_transcript_from_late_chunk_failure(tmp_path, monkeypatch):
    source = tmp_path / "partial.m4a"
    source.write_bytes(b"audio")
    partial = "partial text " * 700
    monkeypatch.setattr(
        transcribe_tool, "_resolve_source", lambda _source: (source, None)
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: (_ for _ in ()).throw(
            PartialAudioTranscriptionError(
                "overall deadline reached",
                partial_transcript=partial,
                completed_chunks=3,
                total_chunks=5,
            )
        ),
    )
    monkeypatch.setattr(
        transcribe_tool,
        "_save_transcript",
        lambda _plan, text: ("stash://space/f_partial", "space")
        if text == partial
        else pytest.fail("wrong partial transcript"),
    )

    result = transcribe_tool.execute({"source": str(source)})

    assert result["ok"] is False
    assert result["data"]["partial"] is True
    assert result["data"]["completed_chunks"] == 3
    assert result["data"]["transcript_stash_ref"] == "stash://space/f_partial"
    assert "transcript" not in result["data"]
    assert result["data"]["transcript_excerpt"]


def test_tool_validates_output_policy_before_provider_work(tmp_path, monkeypatch):
    source = tmp_path / "invalid-policy.m4a"
    source.write_bytes(b"audio")
    monkeypatch.setattr(
        transcribe_tool, "_resolve_source", lambda _source: (source, None)
    )
    monkeypatch.setattr(
        transcribe_tool,
        "transcribe_audio_file",
        lambda _source: pytest.fail("provider work must not start"),
    )

    with pytest.raises(ValueError, match="save_to_stash must be true or false"):
        transcribe_tool.execute({"source": str(source), "save_to_stash": "false"})


def test_audio_transcript_retention_is_durable_source_artifact():
    policy, _ttl_days = get_retention_policy(
        ["audio_transcripts", "audio_transcript", "transcript"], "session"
    )

    assert policy == "source_artifact"


def test_wake_word_and_native_question_scripts_still_use_existing_stt_cli():
    cloud = (ROOT / "bin" / "question-orchestrator.sh").read_text(encoding="utf-8")
    local = (ROOT / "bin" / "question-orchestrator-local.sh").read_text(encoding="utf-8")
    wake_cloud = (ROOT / "bin" / "wake-jarvis.py").read_text(encoding="utf-8")
    wake_local = (ROOT / "bin" / "wake-jarvis-local.py").read_text(encoding="utf-8")

    assert 'bin/stt.py" --mode cloud' in cloud
    assert 'bin/stt.py' in local and '--mode local' in local
    assert "question-orchestrator.sh" in wake_cloud
    assert "question-orchestrator-local.sh" in wake_local
    for content in (cloud, local, wake_cloud, wake_local):
        assert "transcribe_audio" not in content
