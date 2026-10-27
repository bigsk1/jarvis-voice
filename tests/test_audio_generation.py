"""Deterministic request and outcome contracts for spoken-audio artifacts."""

import io
import json
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import audio_generation as audio
import pytest
import requests
from remote_completion import RemoteCompletionError


@pytest.fixture
def config(monkeypatch):
    values = {
        "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "test-eleven-key",
        "ELEVENLABS_TTS_VOICE": "testvoice123", "OPENAI_API_KEY": "test-openai-key",
        "XAI_API_KEY": "test-xai-key", "QWEN3_TTS_URL": "http://127.0.0.1:8881/v1/audio/speech",
        "KOKORO_TTS_URL": "http://kokoro.internal:8880/v1/audio/speech",
    }
    monkeypatch.setattr(audio, "get_config_value", lambda key, default="": values.get(key, default))
    return values


def wav_bytes(seconds=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * (8000 * seconds))
    return buffer.getvalue()


@pytest.fixture
def transport(monkeypatch):
    response = Mock(status_code=200, headers={})
    response.iter_content.return_value = [wav_bytes()]
    session = Mock()
    session.post.return_value = response
    factory = Mock(return_value=session)
    monkeypatch.setattr(audio, "get_session", factory)
    return factory, session, response


@pytest.mark.parametrize("provider,expected_model,expected_voice,expected_url", [
    ("openai", "gpt-4o-mini-tts", "onyx", "https://api.openai.com/v1/audio/speech"),
    ("elevenlabs", "eleven_multilingual_v2", "testvoice123", "https://api.elevenlabs.io/v1/text-to-speech/testvoice123"),
    ("xai", "grok-tts", "eve", "https://api.x.ai/v1/tts"),
    ("qwen3-tts", "tts-1", "Jarvis", "http://127.0.0.1:8881/v1/audio/speech"),
    ("kokoro", "kokoro", "af_nicole", "http://kokoro.internal:8880/v1/audio/speech"),
])
def test_each_provider_preserves_script_and_makes_one_post(config, transport, provider, expected_model, expected_voice, expected_url):
    script = "  Hello!\n[Chapter 1] Exact words, please.  "
    settings = audio.resolve_audio_settings({"text": script, "provider": provider})
    assert settings["model"] == expected_model
    assert settings["voice"] == expected_voice
    assert set(settings) == {"text", "provider", "model", "voice", "title"}
    result = audio.synthesize_audio(settings)
    factory, session, response = transport
    factory.assert_called_once_with(use_proxy=False, retries=0)
    assert session.trust_env is False
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == (expected_url,)
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    payload = kwargs["json"]
    assert payload.get("input", payload.get("text")) == script
    if provider == "xai":
        assert payload == {"text": script, "voice_id": "eve", "language": "en",
                           "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000}}
    elif provider == "elevenlabs":
        assert payload["model_id"] == expected_model
        assert payload["voice_settings"] == {"stability": 0.5, "similarity_boost": 0.75,
                                             "style": 0.5, "use_speaker_boost": True}
    else:
        assert payload["model"] == expected_model
        assert payload["voice"] == expected_voice
        assert payload["response_format"] == "mp3"
    assert result["duration_seconds"] == 1
    assert result["audio_bytes"] == wav_bytes()
    response.close.assert_called_once()
    session.close.assert_called_once()


def test_tool_overrides_do_not_cross_provider_boundaries(config):
    config.update(AUDIO_TOOL_VOICE="privateelevenvoice", AUDIO_TOOL_MODEL="eleven_v3",
                  VOICE="coral", TTS_MODEL="tts-1-hd")
    assert audio.resolve_audio_settings({"text": "Hi"})["voice"] == "privateelevenvoice"
    openai = audio.resolve_audio_settings({"text": "Hi", "provider": "openai"})
    assert (openai["model"], openai["voice"]) == ("tts-1-hd", "coral")
    explicit = audio.resolve_audio_settings({"text": "Hi", "voice": "providedid", "model": "eleven_flash_v2_5"})
    assert (explicit["model"], explicit["voice"]) == ("eleven_flash_v2_5", "providedid")


def test_requires_opt_in_even_with_explicit_provider(config):
    config.pop("AUDIO_TOOL_PROVIDER")
    with pytest.raises(ValueError, match="AUDIO_TOOL_PROVIDER"):
        audio.resolve_audio_settings({"text": "Hello", "provider": "openai"})


@pytest.mark.parametrize("arguments,match", [
    ({"text": " "}, "nonempty"), ({"text": "Hi", "duration": 30}, "Unsupported"),
    ({"text": "Hi", "voice": "../bad"}, "voice ID"),
    ({"text": "Hi", "provider": "openai", "voice": "elevenvoice123"}, "built-in"),
    ({"text": "Hi", "provider": "xai", "model": "eleven_v3"}, "no selectable model"),
    ({"text": "Hi", "provider": "kokoro", "model": "tts-1"}, "configured service model"),
    ({"text": "Hi", "provider": "qwen3-tts", "model": "other-model"}, "configured service model"),
    ({"text": "Hi", "title": "A" * 201}, "title"),
])
def test_rejects_invalid_arguments_before_http(config, transport, arguments, match):
    with pytest.raises(ValueError, match=match):
        audio.resolve_audio_settings(arguments)
    transport[0].assert_not_called()


@pytest.mark.parametrize("provider,model,limit", [
    ("openai", "tts-1", 4096), ("elevenlabs", "eleven_v3", 5000),
    ("elevenlabs", "eleven_flash_v2_5", 40000), ("elevenlabs", "eleven_flash_v2", 30000),
    ("elevenlabs", "eleven_multilingual_v2", 10000), ("xai", "grok-tts", 15000),
    ("qwen3-tts", "tts-1", 4096), ("kokoro", "kokoro", 40000),
])
def test_limits_reject_whole_script_without_splitting_or_truncation(config, transport, provider, model, limit):
    args = {"provider": provider, "model": model, "text": "A" * limit}
    assert audio.resolve_audio_settings(args)["text"] == args["text"]
    args["text"] += "Z"
    with pytest.raises(ValueError, match="not sent or truncated"):
        audio.resolve_audio_settings(args)
    transport[0].assert_not_called()


def test_more_than_thirty_seconds_is_allowed(config, transport):
    transport[2].iter_content.return_value = [wav_bytes(45)]
    assert audio.synthesize_audio(audio.resolve_audio_settings({"text": "A longer speech."}))["duration_seconds"] == 45


@pytest.mark.parametrize("status,completion", [(400, "rejected"), (401, "rejected"), (429, "rejected"), (500, "unknown"), (302, "unknown")])
def test_http_error_never_replays_or_leaks_body(config, transport, status, completion):
    factory, session, response = transport
    response.status_code = status
    response.text = "secret-and-signed-provider-url"
    with pytest.raises(RuntimeError) as error:
        audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert getattr(error.value, "completion", "unknown") == completion
    assert str(error.value) == f"Audio provider returned HTTP {status}"
    assert "secret" not in str(error.value)
    session.post.assert_called_once()
    response.close.assert_called_once()
    session.close.assert_called_once()


def test_transport_error_is_unknown_and_closes_session(config, transport):
    transport[1].post.side_effect = requests.Timeout("secret URL")
    with pytest.raises(RuntimeError, match="outcome is unknown") as error:
        audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert not isinstance(error.value, RemoteCompletionError)
    assert "secret" not in str(error.value)
    transport[1].post.assert_called_once()
    transport[1].close.assert_called_once()


@pytest.mark.parametrize("length_header", [False, True])
def test_download_limit_bounds_declared_and_streamed_bodies(config, transport, monkeypatch, length_header):
    monkeypatch.setattr(audio, "MAX_AUDIO_BYTES", 5)
    transport[2].headers = {"Content-Length": "6"} if length_header else {}
    transport[2].iter_content.return_value = [b"aaa", b"bbb"]
    with pytest.raises(RemoteCompletionError) as error:
        audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert error.value.completion == "completed"
    transport[2].close.assert_called_once()
    transport[1].close.assert_called_once()


def test_missing_duration_probe_preserves_paid_audio(config, transport, monkeypatch):
    transport[2].iter_content.return_value = [b"ID3-example"]
    monkeypatch.setattr(audio.subprocess, "run", Mock(side_effect=FileNotFoundError))
    result = audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert result["audio_bytes"] == b"ID3-example"
    assert result["duration_seconds"] is None
    assert "preserved" in result["duration_warning"]


def test_probe_measures_compressed_audio(config, transport, monkeypatch):
    transport[2].iter_content.return_value = [b"ID3-example"]
    probe = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
        "format": {"duration": "42.25"}, "streams": [{"codec_type": "audio"}]}).encode()))
    monkeypatch.setattr(audio.subprocess, "run", probe)
    result = audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert result["duration_seconds"] == 42.25
    assert probe.call_args.kwargs["timeout"] == 15
    assert set(probe.call_args.kwargs["env"]) <= {"PATH", "LANG", "LC_ALL"}


@pytest.mark.parametrize("timeout", ["0", "901", "nan", "five"])
def test_timeout_validation(config, transport, timeout):
    config["AUDIO_TOOL_TIMEOUT_SECONDS"] = timeout
    with pytest.raises(ValueError, match="AUDIO_TOOL_TIMEOUT_SECONDS"):
        audio.resolve_audio_settings({"text": "Hi"})
    transport[0].assert_not_called()


def test_elevenlabs_v3_preserves_tags_and_snaps_stability(config, transport):
    config.update(ELEVENLABS_TTS_MODEL="eleven_v3", ELEVENLABS_TTS_STABILITY="0.4")
    text = "[whispering] Keep this. [laughs]"
    audio.synthesize_audio(audio.resolve_audio_settings({"text": text}))
    payload = transport[1].post.call_args.kwargs["json"]
    assert payload == {"text": text, "model_id": "eleven_v3",
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}


def test_configured_raw_xai_codec_rejected_before_billing(config, transport):
    config["XAI_TTS_CODEC"] = "pcm"
    with pytest.raises(ValueError, match="mp3 or wav"):
        audio.resolve_audio_settings({"text": "Hi", "provider": "xai"})
    transport[0].assert_not_called()


def test_no_retry_adapters_preserve_http_rejection_responses(config, transport):
    audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    mounts = transport[1].mount.call_args_list
    assert [call.args[0] for call in mounts] == ["http://", "https://"]
    for call in mounts:
        retry = call.args[1].max_retries
        assert retry.total == 0
        assert not retry.is_retry("POST", 429)
        assert not retry.is_retry("POST", 503)


def test_non_audio_response_is_completed_failure(config, transport):
    transport[2].headers["Content-Type"] = "application/json; charset=utf-8"
    with pytest.raises(RemoteCompletionError, match="non-audio") as error:
        audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert error.value.completion == "completed"
    transport[2].iter_content.assert_not_called()
    transport[2].close.assert_called_once()
    transport[1].close.assert_called_once()


def test_html_without_content_type_is_not_saved_as_audio(config, transport):
    transport[2].iter_content.return_value = [b"<html>Bad proxy response</html>"]
    with pytest.raises(RemoteCompletionError, match="unrecognized audio") as error:
        audio.synthesize_audio(audio.resolve_audio_settings({"text": "Hi"}))
    assert error.value.completion == "completed"


def test_qwen_unsupported_format_rejected_before_request(config, transport):
    config["QWEN3_TTS_FORMAT"] = "flac"
    with pytest.raises(ValueError, match="mp3 or wav"):
        audio.resolve_audio_settings({"text": "Hi", "provider": "qwen3-tts"})
    transport[0].assert_not_called()


@pytest.mark.parametrize("model", ["gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"])
def test_openai_delivery_instructions_are_separate_and_exact(config, transport, model):
    script = "  Here are the exact words.\nPlease keep them.  "
    instructions = "  Read warmly, at a measured pace.  "
    settings = audio.resolve_audio_settings({
        "provider": "openai", "model": model, "text": script, "instructions": instructions,
    })
    assert settings["text"] == script
    assert settings["instructions"] == instructions
    audio.synthesize_audio(settings)
    payload = transport[1].post.call_args.kwargs["json"]
    assert payload["input"] == script
    assert payload["instructions"] == instructions
    assert "instruct" not in payload


def test_qwen_does_not_claim_instruction_support_from_its_compatibility_schema(config, transport):
    capabilities = audio.get_audio_delivery_capabilities("qwen3-tts", "tts-1")
    assert capabilities["instructions_supported"] is False
    assert "instructions_field" not in capabilities
    assert "No verified" in capabilities["note"]
    with pytest.raises(ValueError, match="does not support separate instructions"):
        audio.resolve_audio_settings({
            "provider": "qwen3-tts", "text": "Exact narration.", "instructions": "Speak calmly.",
        })
    transport[0].assert_not_called()


@pytest.mark.parametrize(("provider", "model"), [
    ("openai", "tts-1"), ("openai", "tts-1-hd"),
    ("elevenlabs", "eleven_v3"), ("elevenlabs", "eleven_v4"),
    ("xai", "grok-tts"), ("kokoro", "kokoro"), ("qwen3-tts", "tts-1"),
])
def test_separate_instructions_unsupported_models_fail_before_network(config, transport, provider, model):
    with pytest.raises(ValueError, match="does not support separate instructions"):
        audio.resolve_audio_settings({
            "provider": provider, "model": model, "text": "Exact words.",
            "instructions": "Speak cheerfully.",
        })
    transport[0].assert_not_called()


@pytest.mark.parametrize("instructions", [None, [], {}, 123, True, "", "   ", "x" * 4097])
def test_invalid_instructions_rejected_before_provider_construction(config, transport, instructions):
    with pytest.raises(ValueError, match="instructions"):
        audio.resolve_audio_settings({
            "provider": "openai", "text": "Words.", "instructions": instructions,
        })
    transport[0].assert_not_called()


@pytest.mark.parametrize("model", ["eleven_v3", "eleven_v4", "eleven_v4_turbo"])
def test_eleven_native_inline_tags_do_not_depend_on_runtime_reply_toggles(config, transport, model):
    config.update(TTS_PROVIDER="kokoro", ELEVENLABS_TTS_STYLE_TAGS_ENABLED="false")
    text = "[whispering] A secret. [laughs] [curious] What happened?"
    audio.synthesize_audio(audio.resolve_audio_settings({"text": text, "model": model}))
    payload = transport[1].post.call_args.kwargs["json"]
    assert payload["text"] == text
    assert "instructions" not in payload


def test_xai_native_inline_and_wrapping_cues_are_preserved_without_runtime_toggle(config, transport):
    config["XAI_TTS_STYLE_TAGS_ENABLED"] = "false"
    text = "<whisper>Keep this secret.</whisper> [pause] [laugh] <slow>Goodbye.</slow>"
    audio.synthesize_audio(audio.resolve_audio_settings({"provider": "xai", "text": text}))
    assert transport[1].post.call_args.kwargs["json"]["text"] == text


@pytest.mark.parametrize(("provider", "model", "text"), [
    ("elevenlabs", "eleven_multilingual_v2", "[whispering] Hello."),
    ("elevenlabs", "eleven_flash_v2_5", "[laughs] Hello."),
    ("elevenlabs", "eleven_v4", "<whisper>Hello.</whisper>"),
    ("elevenlabs", "eleven_v3", '<break time="1s"/> Hello.'),
    ("openai", "gpt-4o-mini-tts", "[excited] Hello."),
    ("qwen3-tts", "tts-1", "[whispering] Hello."),
    ("kokoro", "kokoro", "<soft>Hello.</soft>"),
    ("xai", "grok-tts", "[whispering] Hello."),
])
def test_incompatible_known_markup_is_rejected_instead_of_spoken_literally(config, transport, provider, model, text):
    with pytest.raises(ValueError, match="does not support"):
        audio.resolve_audio_settings({"provider": provider, "model": model, "text": text})
    transport[0].assert_not_called()


def test_direct_synthesis_cannot_bypass_instructions_validation(config, transport):
    settings = audio.resolve_audio_settings({"text": "Hello."})
    settings["instructions"] = "Unsupported separate direction."
    with pytest.raises(ValueError, match="does not support"):
        audio.synthesize_audio(settings)
    transport[0].assert_not_called()


def test_public_delivery_capabilities_are_model_specific_and_independent(config):
    config.update(TTS_PROVIDER="elevenlabs", ELEVENLABS_TTS_STYLE_TAGS_ENABLED="false")
    eleven = audio.get_audio_delivery_capabilities("elevenlabs", "eleven_v4")
    assert eleven["inline_tags_supported"] is True
    assert eleven["instructions_supported"] is False
    assert "[whispering]" in eleven["inline_tag_examples"]
    assert audio.get_audio_delivery_capabilities("elevenlabs", "eleven_multilingual_v2")["inline_tags_supported"] is False
    assert audio.get_audio_delivery_capabilities("openai", "gpt-4o-mini-tts")["instructions_field"] == "instructions"
    assert audio.get_audio_delivery_capabilities("openai", "tts-1")["instructions_supported"] is False
    assert audio.get_audio_delivery_capabilities("qwen3-tts", "tts-1")["instructions_supported"] is False
    xai = audio.get_audio_delivery_capabilities("xai", "grok-tts")
    assert xai["wrapping_tags_supported"] is True
    assert "<whisper>text</whisper>" in xai["wrapping_tag_examples"]
    assert "key" not in json.dumps(eleven)


@pytest.mark.parametrize("model", ["tts-1", "tts-1-hd"])
@pytest.mark.parametrize("voice", ["ballad", "verse", "marin", "cedar"])
def test_legacy_openai_rejects_new_only_voices_before_billing(config, transport, model, voice):
    with pytest.raises(ValueError, match="does not support voice"):
        audio.resolve_audio_settings({"provider": "openai", "model": model, "voice": voice, "text": "Hello."})
    transport[0].assert_not_called()


@pytest.mark.parametrize("model", ["tts-1", "tts-1-hd"])
@pytest.mark.parametrize("voice", ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"])
def test_legacy_openai_retains_all_nine_supported_voices(config, model, voice):
    settings = audio.resolve_audio_settings({"provider": "openai", "model": model, "voice": voice, "text": "Hello."})
    assert settings["voice"] == voice


@pytest.mark.parametrize("voice", ["ballad", "verse", "marin", "cedar"])
def test_openai_mini_tts_retains_newer_voices(config, voice):
    assert audio.resolve_audio_settings({"provider": "openai", "voice": voice, "text": "Hello."})["voice"] == voice


@pytest.mark.parametrize("model", ["eleven_v3", "eleven_v4", "eleven_v4_turbo"])
@pytest.mark.parametrize("cue", ["pause", "laugh", "sigh", "hum-tune"])
def test_eleven_rejects_known_xai_only_inline_cues_before_billing(config, transport, model, cue):
    with pytest.raises(ValueError, match="does not support the inline speech cue"):
        audio.resolve_audio_settings({"model": model, "text": f"[{cue}] Hello."})
    transport[0].assert_not_called()


@pytest.mark.parametrize("model", ["eleven_v3", "eleven_v4", "eleven_v4_turbo"])
def test_eleven_unknown_brackets_remain_exact_instead_of_becoming_closed_vocabulary(config, transport, model):
    text = "  [Chapter 1] [wistful] This is the exact script.  "
    audio.synthesize_audio(audio.resolve_audio_settings({"model": model, "text": text}))
    assert transport[1].post.call_args.kwargs["json"]["text"] == text


def test_direct_qwen_submission_cannot_bypass_instruction_rejection(config, transport):
    settings = audio.resolve_audio_settings({"provider": "qwen3-tts", "text": "Exact narration."})
    settings["instructions"] = "This backend has not established instruction support."
    with pytest.raises(ValueError, match="does not support separate instructions"):
        audio.synthesize_audio(settings)
    transport[0].assert_not_called()
