"""Voice lookup makes only bounded read-only calls and retains exact IDs."""

import json
from unittest.mock import Mock

import audio_voices as catalog
import pytest
import requests


@pytest.fixture
def config(monkeypatch):
    values = {
        "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "private-key",
        "OPENAI_API_KEY": "private-openai-key", "XAI_API_KEY": "private-xai-key",
        "QWEN3_TTS_URL": "http://127.0.0.1:8881/v1/audio/speech",
        "KOKORO_TTS_URL": "http://kokoro.local:8880/prefix/v1/audio/speech",
    }
    monkeypatch.setattr("audio_generation.get_config_value", lambda key, default="": values.get(key, default))
    return values


@pytest.fixture
def transport(monkeypatch):
    response = Mock(status_code=200, headers={})
    response.iter_content.return_value = [json.dumps({"voices": []}).encode()]
    session = Mock()
    session.get.return_value = response
    factory = Mock(return_value=session)
    monkeypatch.setattr(catalog, "get_session", factory)
    return factory, session, response


def _body(response, value):
    response.iter_content.return_value = [json.dumps(value).encode()]


def test_elevenlabs_account_catalog_preserves_exact_id_and_safe_metadata(config, transport):
    _body(transport[2], {"voices": [{"voice_id": "ExactVoice_ID123", "name": "Samantha",
        "description": "Natural voice", "labels": {"language": "en", "accent": "American", "gender": "female", "private": "do-not-return"},
        "preview_url": "https://cdn.elevenlabs.io/preview.mp3", "hidden": "private-key"}], "has_more": False})
    result = catalog.list_audio_voices({"search": "Samantha"})
    assert result["provider"] == "elevenlabs" and result["source"] == "live_account"
    assert result["items"] == [{"provider": "elevenlabs", "id": "ExactVoice_ID123", "voice_id": "ExactVoice_ID123", "name": "Samantha",
        "description": "Natural voice", "language": "en", "accent": "American", "gender": "female", "preview_url": "https://cdn.elevenlabs.io/preview.mp3"}]
    assert result["count"] == 1 and result["has_more"] is False
    args, kwargs = transport[1].get.call_args
    assert args == ("https://api.elevenlabs.io/v2/voices",)
    assert kwargs["params"]["search"] == "Samantha"
    assert kwargs["params"]["page_size"] == 50
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (5, 15)
    assert kwargs["headers"] == {"xi-api-key": "private-key"}
    assert "private" not in json.dumps(result)
    transport[0].assert_called_once_with(use_proxy=False, retries=0)
    assert transport[1].trust_env is False
    transport[1].post.assert_not_called()
    transport[1].close.assert_called_once()
    transport[2].close.assert_called_once()


def test_elevenlabs_extra_defaults_and_remote_pagination_drop_no_voices(config, transport):
    first = {"voices": [{"voice_id": f"v{i:03}", "name": f"Name{i:03}"} for i in range(75)], "has_more": True, "next_page_token": "remote-page-two"}
    second = {"voices": [{"voice_id": "final", "name": "Final"}], "has_more": False}

    def request(*args, **kwargs):
        _body(transport[2], second if kwargs["params"].get("next_page_token") else first)
        return transport[2]

    transport[1].get.side_effect = request
    result = catalog.list_audio_voices({"limit": 20})
    ids = [row["id"] for row in result["items"]]
    iterations = 0
    while result["has_more"]:
        result = catalog.list_audio_voices({"limit": 20, "cursor": result["next_cursor"]})
        ids.extend(row["id"] for row in result["items"])
        iterations += 1
        assert iterations < 10
    assert ids == [f"v{i:03}" for i in range(75)] + ["final"]


def test_xai_includes_builtins_then_paginated_custom_voices(config, transport):
    def request(url, **kwargs):
        if url.endswith("/tts/voices"):
            data = {"voices": [{"voice_id": "eve", "name": "Eve", "gender": "female"}]}
        elif kwargs["params"].get("pagination_token"):
            data = {"voices": [{"voice_id": "customtwo", "name": "Narrator Two"}], "pagination_token": None}
        else:
            data = {"voices": [{"voice_id": "customone", "name": "Narrator One"}], "pagination_token": "next"}
        _body(transport[2], data)
        return transport[2]

    transport[1].get.side_effect = request
    result = catalog.list_audio_voices({"provider": "xai", "limit": 2})
    assert [row["id"] for row in result["items"]] == ["eve", "customone"]
    assert [row["kind"] for row in result["items"]] == ["builtin", "custom"]
    assert result["has_more"]
    next_page = catalog.list_audio_voices({"provider": "xai", "limit": 2, "cursor": result["next_cursor"]})
    assert [row["id"] for row in next_page["items"]] == ["customtwo"]
    assert not next_page["has_more"]
    assert transport[1].get.call_args.kwargs["headers"] == {"Authorization": "Bearer private-xai-key"}


def test_xai_denied_custom_catalog_retains_builtins_and_reports_partial(config, transport):
    def request(url, **kwargs):
        if url.endswith("/tts/voices"):
            transport[2].status_code = 200
            _body(transport[2], {"voices": [{"voice_id": "eve", "name": "Eve"}]})
        else:
            transport[2].status_code = 403
        return transport[2]

    transport[1].get.side_effect = request
    result = catalog.list_audio_voices({"provider": "xai"})
    assert result["items"][0]["voice_id"] == "eve"
    assert result["partial"] is True and "HTTP 403" in result["warning"]
    assert not result["has_more"]


@pytest.mark.parametrize("provider,payload,endpoint,expected", [
    ("qwen3-tts", {"voices": ["Jarvis", "Samantha", "Lucy"]}, "http://127.0.0.1:8881/v1/voices", "Samantha"),
    ("kokoro", {"voices": [{"id": "af_samantha", "name": "Samantha"}, {"id": "am_adam", "name": "Adam"}]}, "http://kokoro.local:8880/prefix/v1/audio/voices", "af_samantha"),
    ("qwen3-tts", {"data": [{"id": "Samantha", "name": "Samantha"}]}, "http://127.0.0.1:8881/v1/voices", "Samantha"),
])
def test_local_catalog_formats_and_search(config, transport, provider, payload, endpoint, expected):
    _body(transport[2], payload)
    result = catalog.list_audio_voices({"provider": provider, "search": "samantha"})
    assert result["source"] == "live_server"
    assert [item["voice_id"] for item in result["items"]] == [expected]
    assert transport[1].get.call_args.args == (endpoint,)
    assert transport[1].get.call_args.kwargs["headers"] == {}


def test_openai_uses_documented_model_aware_builtin_list_no_http(config, transport):
    result = catalog.list_audio_voices({"provider": "openai"})
    assert result["source"] == "documented_builtin"
    assert result["model"] == "gpt-4o-mini-tts"
    assert {item["id"] for item in result["items"]} == set(catalog._OPENAI_VOICES)
    legacy = catalog.list_audio_voices({"provider": "openai", "model": "tts-1"})
    assert {item["id"] for item in legacy["items"]} < {item["id"] for item in result["items"]}
    transport[0].assert_not_called()


def test_openai_local_pagination_and_filter(config, transport):
    first = catalog.list_audio_voices({"provider": "openai", "limit": 2})
    assert first["count"] == 2 and first["has_more"]
    second = catalog.list_audio_voices({"provider": "openai", "limit": 2, "cursor": first["next_cursor"]})
    assert not {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]}
    match = catalog.list_audio_voices({"provider": "openai", "search": "onyx"})
    assert [item["voice_id"] for item in match["items"]] == ["onyx"]


@pytest.mark.parametrize("args", [
    {"limit": 51}, {"limit": True}, {"limit": 0}, {"limit": "5"}, {"provider": "unknown"},
    {"provider": []}, {"search": "x" * 201}, {"search": None}, {"model": "../bad"},
    {"cursor": "bogus"}, {"text": "Not a generation call"}, [],
])
def test_invalid_args_never_call_provider(config, transport, args):
    with pytest.raises(ValueError):
        catalog.list_audio_voices(args)
    transport[0].assert_not_called()


@pytest.mark.parametrize("change", ["provider", "search", "model"])
def test_cursor_is_bound_to_provider_search_model(config, transport, change):
    first = catalog.list_audio_voices({"provider": "openai", "limit": 1})
    arguments = {"provider": "openai", "cursor": first["next_cursor"]}
    arguments[change] = {"provider": "xai", "search": "different", "model": "tts-1"}[change]
    with pytest.raises(ValueError, match="cursor"):
        catalog.list_audio_voices(arguments)
    transport[0].assert_not_called()


@pytest.mark.parametrize("remove,provider", [
    ("AUDIO_TOOL_PROVIDER", "openai"), ("OPENAI_API_KEY", "openai"),
    ("ELEVENLABS_API_KEY", "elevenlabs"), ("XAI_API_KEY", "xai"),
    ("QWEN3_TTS_URL", "qwen3-tts"), ("KOKORO_TTS_URL", "kokoro"),
])
def test_unconfigured_provider_rejected_without_http(config, transport, remove, provider):
    config.pop(remove)
    with pytest.raises(ValueError):
        catalog.list_audio_voices({"provider": provider})
    transport[0].assert_not_called()


def test_provider_specific_model_default_does_not_cross_provider(config, transport):
    config["AUDIO_TOOL_MODEL"] = "eleven_v3"
    assert catalog.list_audio_voices({"provider": "openai"})["model"] == "gpt-4o-mini-tts"


@pytest.mark.parametrize("header", [True, False])
def test_bounded_json_and_cleanup(config, transport, monkeypatch, header):
    monkeypatch.setattr(catalog, "MAX_CATALOG_BYTES", 5)
    transport[2].headers = {"Content-Length": "6"} if header else {}
    transport[2].iter_content.return_value = [b"aaa", b"bbb"]
    with pytest.raises(RuntimeError, match="2 MiB"):
        catalog.list_audio_voices({})
    transport[1].close.assert_called_once()
    transport[2].close.assert_called_once()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
def test_http_failure_never_exposes_response_or_credentials(config, transport, status):
    transport[2].status_code = status
    transport[2].text = "private-key signed-url private-error"
    with pytest.raises(RuntimeError) as error:
        catalog.list_audio_voices({})
    assert str(error.value) == f"Voice catalog returned HTTP {status}"
    assert "private" not in str(error.value)
    transport[1].get.assert_called_once()
    transport[1].post.assert_not_called()
    transport[1].close.assert_called_once()
    transport[2].close.assert_called_once()


def test_transport_error_redacted(config, transport):
    transport[1].get.side_effect = requests.ConnectionError("private-key @ private-url")
    with pytest.raises(RuntimeError, match="connection failed") as error:
        catalog.list_audio_voices({})
    assert "private" not in str(error.value)
    transport[1].close.assert_called_once()


@pytest.mark.parametrize("preview", [
    "http://cdn.example.com/a.mp3", "https://user:private@cdn.example.com/a.mp3",
    "https://127.0.0.1/a.mp3", "https://192.168.1.1/a.mp3", "https://localhost/a.mp3",
    "https://foo.internal/a.mp3", "https://cdn.example.com:8443/a.mp3", "javascript:alert(1)",
])
def test_nonpublic_or_authenticated_previews_omitted(config, transport, preview):
    _body(transport[2], {"voices": [{"voice_id": "safevoice", "name": "Safe", "preview_url": preview}], "has_more": False})
    result = catalog.list_audio_voices({})
    assert "preview_url" not in result["items"][0]


def test_malformed_pagination_is_not_silently_truncated(config, transport):
    _body(transport[2], {"voices": [], "has_more": True})
    with pytest.raises(RuntimeError, match="next-page"):
        catalog.list_audio_voices({})


def test_delivery_capabilities_follow_effective_provider_model(config, transport):
    config["ELEVENLABS_TTS_MODEL"] = "eleven_v3"
    result = catalog.list_audio_voices({})
    assert result["model"] == "eleven_v3"
    assert result["delivery_capabilities"]["inline_tags_supported"] is True
    assert "[whispering]" in result["delivery_capabilities"]["inline_tag_examples"]
    openai = catalog.list_audio_voices({"provider": "openai"})
    assert openai["delivery_capabilities"]["instructions_supported"] is True
    legacy = catalog.list_audio_voices({"provider": "openai", "model": "tts-1"})
    assert legacy["delivery_capabilities"]["instructions_supported"] is False


def test_xai_search_is_applied_to_builtins_and_customs(config, transport):
    def request(url, **kwargs):
        data = {"voices": [{"voice_id": "eve", "name": "Eve"}]} if url.endswith("/tts/voices") else {
            "voices": [{"voice_id": "narrator", "name": "Warm Narrator", "accent": "British"}], "pagination_token": None}
        _body(transport[2], data)
        return transport[2]

    transport[1].get.side_effect = request
    result = catalog.list_audio_voices({"provider": "xai", "search": "british"})
    assert [item["voice_id"] for item in result["items"]] == ["narrator"]
    assert not result["has_more"]


def test_malformed_json_and_list_shapes_are_safe_errors(config, transport):
    transport[2].iter_content.return_value = [b"not-json private-provider-data"]
    with pytest.raises(RuntimeError, match="unreadable JSON") as error:
        catalog.list_audio_voices({})
    assert "private" not in str(error.value)
    _body(transport[2], {"private": "provider-data"})
    with pytest.raises(RuntimeError, match="unsupported voice list"):
        catalog.list_audio_voices({})


def test_filters_and_page_offsets_never_drop_local_voices(config, transport):
    _body(transport[2], {"voices": [f"voice{i:03}" for i in range(120)]})
    result = catalog.list_audio_voices({"provider": "qwen3-tts", "limit": 50})
    ids = [item["voice_id"] for item in result["items"]]
    while result["has_more"]:
        result = catalog.list_audio_voices({"provider": "qwen3-tts", "limit": 50, "cursor": result["next_cursor"]})
        ids.extend(item["voice_id"] for item in result["items"])
    assert ids == [f"voice{i:03}" for i in range(120)]


def test_read_only_adapters_disable_retry_status_exceptions(config, transport):
    catalog.list_audio_voices({})
    for call in transport[1].mount.call_args_list:
        retry = call.args[1].max_retries
        assert retry.total == 0
        assert not retry.is_retry("GET", 429)


@pytest.mark.parametrize("provider", ["qwen3-tts", "kokoro"])
def test_local_unicode_voice_ids_preserved_exactly(config, transport, provider):
    identifier = "Élodie_日本語 🎙️"
    _body(transport[2], {"voices": [identifier, "invalid\nname", "x" * 161]})
    result = catalog.list_audio_voices({"provider": provider})
    assert [item["voice_id"] for item in result["items"]] == [identifier]
    assert result["items"][0]["id"] == identifier


def test_eleven_search_filters_extra_defaults_with_recognized_labels(config, transport):
    _body(transport[2], {"voices": [
        {"voice_id": "default1", "name": "Default voice"},
        {"voice_id": "target", "name": "Samantha", "labels": {"age": "young", "use_case": "narration"}},
    ], "has_more": False})
    result = catalog.list_audio_voices({"search": "young"})
    assert [item["id"] for item in result["items"]] == ["target"]
    assert "labels" not in result["items"][0]
    assert "age" not in result["items"][0]


def test_eleven_filtered_page_offsets_preserve_all_matches(config, transport):
    rows = [{"voice_id": f"voice{i:03}", "name": "Target" if i % 2 else "Other"} for i in range(75)]
    _body(transport[2], {"voices": rows, "has_more": False})
    result = catalog.list_audio_voices({"search": "Target", "limit": 20})
    ids = [item["id"] for item in result["items"]]
    assert result["has_more"]
    result = catalog.list_audio_voices({"search": "Target", "limit": 20, "cursor": result["next_cursor"]})
    ids.extend(item["id"] for item in result["items"])
    assert ids == [f"voice{i:03}" for i in range(75) if i % 2]
    assert not result["has_more"]


def test_unsupported_eleven_model_rejected_before_lookup(config, transport):
    with pytest.raises(ValueError, match="Unsupported ElevenLabs speech model"):
        catalog.list_audio_voices({"model": "made-up-model"})
    transport[0].assert_not_called()
