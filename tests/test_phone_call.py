#!/usr/bin/env python3
"""Deterministic regressions for Vapi call configuration and completion."""

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import phone_call  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_phone_runtime(tmp_path, monkeypatch):
    """Never let phone regressions reach Vapi or an operator's call state."""
    monkeypatch.setattr(phone_call, "CALL_LOCK_FILE", tmp_path / "call-lock.json")
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", tmp_path / "active-call.json")
    monkeypatch.setattr(phone_call, "_recent_calls", {})
    monkeypatch.setattr(phone_call, "save_call_to_memory", Mock(return_value=False))
    monkeypatch.setattr(phone_call, "save_call_artifacts", Mock(return_value={}), raising=False)
    monkeypatch.setattr(phone_call, "get_call_canvas", Mock(return_value={}), raising=False)
    monkeypatch.setattr(phone_call, "remember_call_canvas", Mock(), raising=False)
    unexpected_requests = []
    for method in ("get", "post", "delete"):
        guard = Mock(side_effect=AssertionError("Unexpected Vapi network request"))
        monkeypatch.setattr(phone_call.requests, method, guard)
        unexpected_requests.append(guard)
    yield
    for guard in unexpected_requests:
        guard.assert_not_called()


def _set_config(monkeypatch, **values):
    monkeypatch.setattr(
        phone_call, "get_config_value", lambda key, default=None: values.get(key, default)
    )


def _response(payload):
    response = Mock(status_code=200)
    response.json.return_value = payload
    return response


def _config_value(key: str, default=None):
    if key == "VAPI_WAIT_FOR_CALL":
        return "false"
    return default


def test_in_progress_marker_persists_original_task(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call.time, "time", lambda: 123.0)

    phone_call.set_call_in_progress(
        "call-A",
        "+15550000001",
        "Alice",
        "Ask about dinner plans",
    )

    assert json.loads(marker.read_text()) == {
        "call_id": "call-A",
        "phone_number": "+15550000001",
        "recipient": "Alice",
        "task": "Ask about dinner plans",
        "started": 123.0,
    }


def test_new_call_request_saves_completed_call_with_original_task(monkeypatch):
    prior_call = {
        "call_id": "call-A",
        "phone_number": "+15550000001",
        "recipient": "Alice",
        "task": "Ask about dinner plans",
        "started": 1,
    }
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
    }
    save_call = Mock(return_value=True)
    make_call = Mock()

    monkeypatch.setattr(phone_call, "get_config_value", _config_value)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000002")
    monkeypatch.setattr(phone_call, "is_call_in_progress", lambda: prior_call)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "extract_transcript", lambda _call: "Dinner works")
    monkeypatch.setattr(phone_call, "clear_call_in_progress", Mock())
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "Bob", "task": "Check flight status"})

    assert result["data"]["call_id"] == "call-A"
    assert save_call.call_args.args[:3] == (
        "call-A",
        "Alice",
        "Ask about dinner plans",
    )
    make_call.assert_not_called()


def test_status_uses_tracked_metadata_and_clears_matching_marker(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    marker.write_text(
        json.dumps(
            {
                "call_id": "call-A",
                "phone_number": "+15550000001",
                "recipient": "Alice",
                "task": "Ask about dinner plans",
                "started": time.time(),
            }
        )
    )
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
        "transcript": "Dinner works",
        "customer": {"number": "+15550000001"},
    }
    save_call = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)

    result = phone_call.action_status({"call_id": "call-A"})

    assert save_call.call_args.args[:3] == (
        "call-A",
        "Alice",
        "Ask about dinner plans",
    )
    assert not marker.exists()
    assert result["data"]["saved_to_canvas"] is True


def test_status_preserves_different_active_call_marker(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    marker.write_text(
        json.dumps(
            {
                "call_id": "call-B",
                "phone_number": "+15550000002",
                "recipient": "Bob",
                "task": "Check flight status",
                "started": time.time(),
            }
        )
    )
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
        "transcript": "Dinner works",
        "customer": {"number": "+15550000001"},
    }
    save_call = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)

    phone_call.action_status({"call_id": "call-A"})

    assert save_call.call_args.args[:3] == (
        "call-A",
        "+15550000001",
        "Phone call",
    )
    assert marker.exists()


def test_saved_assistant_preserves_dashboard_settings_and_receives_task_variables(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_ASSISTANT_ID="saved-assistant",
        VAPI_PHONE_NUMBER_ID="outbound-number",
        VAPI_API_KEY="test-key",
        VAPI_LLM_PROVIDER="xai",
        VAPI_LLM_MODEL="configured-model-does-not-override-saved-assistant",
    )
    create_assistant = Mock()
    post = Mock(return_value=_response({"id": "call-A", "status": "queued"}))
    monkeypatch.setattr(phone_call, "create_assistant_for_call", create_assistant)
    monkeypatch.setattr(phone_call.requests, "post", post)

    result = phone_call.make_call(
        "Alice",
        "Ask about dinner",
        "Tomorrow evening",
        owner="Boss",
        phone_number="+15550000001",
    )

    create_assistant.assert_not_called()
    post.assert_called_once()
    assert post.call_args.args == (f"{phone_call.VAPI_API_BASE}/call",)
    payload = post.call_args.kwargs["json"]
    assert payload["assistantId"] == "saved-assistant"
    assert payload["phoneNumberId"] == "outbound-number"
    assert payload["customer"] == {"number": "+15550000001"}
    overrides = payload["assistantOverrides"]
    assert set(overrides) == {"variableValues"}
    assert overrides["variableValues"] == {
        "owner": "Boss",
        "task": "Ask about dinner",
        "reason": phone_call.generate_call_reason("Ask about dinner", "Tomorrow evening", "Boss"),
        "context": "Tomorrow evening",
        "recipient": "Alice",
    }
    assert not result.get("temporary_assistant_id")


def test_saved_assistant_ignores_invalid_generated_persona_and_model_settings(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="saved-assistant",
        VAPI_WAIT_FOR_CALL="false",
        VAPI_DEFAULT_PERSONA="stale-generated-persona",
        VAPI_LLM_PROVIDER="unsupported-generated-provider",
        VAPI_LLM_MODEL="unsupported-generated-model",
        VAPI_LLM_REASONING_EFFORT="max",
    )
    create_assistant = Mock()
    monkeypatch.setattr(phone_call, "create_assistant_for_call", create_assistant)
    post = Mock(return_value=_response({"id": "call-A", "status": "queued"}))
    monkeypatch.setattr(phone_call.requests, "post", post)

    result = phone_call.action_call({"recipient": "+12125550199", "task": "Ask about dinner"})

    assert result["ok"] is True
    assert result["data"]["assistant_id"] == "saved-assistant"
    create_assistant.assert_not_called()
    post.assert_called_once()
    assert post.call_args.args == (f"{phone_call.VAPI_API_BASE}/call",)
    payload = post.call_args.kwargs["json"]
    assert payload["assistantId"] == "saved-assistant"
    assert set(payload["assistantOverrides"]) == {"variableValues"}


@pytest.mark.parametrize(
    ("recipient", "expected"),
    [
        ("2125550199", "+12125550199"),
        ("212 555 0199", "+12125550199"),
        ("212-555-0199", "+12125550199"),
        ("(212) 555-0199", "+12125550199"),
        ("  (212) 555-0199  ", "+12125550199"),
        ("1-212-555-0199", "+12125550199"),
        ("+1 (212) 555-0199", "+12125550199"),
    ],
)
def test_direct_phone_numbers_normalize_without_loading_contacts(monkeypatch, recipient, expected):
    load_contacts = Mock()
    monkeypatch.setattr(phone_call, "load_contacts", load_contacts)
    monkeypatch.setattr(phone_call, "CONTACTS", {})

    assert phone_call.resolve_phone_number(recipient) == expected

    load_contacts.assert_not_called()
    assert phone_call.CONTACTS == {}


@pytest.mark.parametrize("recipient", ["ALICE", "Alice"])
def test_named_recipients_still_use_contact_lookup(monkeypatch, recipient):
    load_contacts = Mock()
    monkeypatch.setattr(phone_call, "load_contacts", load_contacts)
    monkeypatch.setattr(phone_call, "CONTACTS", {"alice": "+12125550199"})

    assert phone_call.resolve_phone_number(recipient) == "+12125550199"

    load_contacts.assert_called_once()


@pytest.mark.parametrize("recipient", ["+1abc2125550199", "212-555-0199 ext7", "212+5550199"])
def test_alphanumeric_recipient_is_not_silently_stripped_into_a_phone_number(
    monkeypatch, recipient
):
    monkeypatch.setattr(phone_call, "load_contacts", Mock())
    monkeypatch.setattr(phone_call, "CONTACTS", {})

    with pytest.raises(ValueError):
        phone_call.resolve_phone_number(recipient)


@pytest.mark.parametrize(
    ("persona", "voice_id"), [("female", "samantha-voice"), ("casual", "jay-voice")]
)
def test_unsaved_number_reaches_outbound_payload_with_selected_persona(
    monkeypatch, persona, voice_id
):
    _set_config(
        monkeypatch,
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="",
        VAPI_DEFAULT_PERSONA="female",
        VAPI_WAIT_FOR_CALL="false",
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="explicit-openai-model",
        VAPI_ELEVENLABS_KEY="true",
        VAPI_VOICE_ID="jay-voice",
        VAPI_FEMALE_VOICE_ID="samantha-voice",
        VAPI_VOICE_MODEL="eleven_v4_turbo",
    )
    load_contacts = Mock()
    monkeypatch.setattr(phone_call, "load_contacts", load_contacts)
    monkeypatch.setattr(phone_call, "CONTACTS", {})
    post = Mock(
        side_effect=[
            _response({"id": "created-for-call"}),
            _response({"id": "call-A", "status": "queued"}),
        ]
    )
    monkeypatch.setattr(phone_call.requests, "post", post)

    result = phone_call.action_call(
        {"recipient": "(212) 555-0199", "task": "Ask about dinner", "persona": persona}
    )

    assert result["ok"] is True
    assert result["data"]["phone_number"] == "+12125550199"
    assert post.call_count == 2
    assistant_request, call_request = post.call_args_list
    assert assistant_request.kwargs["json"]["voice"] == {
        "provider": "11labs",
        "voiceId": voice_id,
        "model": "eleven_v4_turbo",
    }
    assert phone_call.PERSONAS[persona]["name"] in assistant_request.kwargs["json"]["firstMessage"]
    assert call_request.kwargs["json"]["customer"]["number"] == "+12125550199"
    load_contacts.assert_not_called()
    assert phone_call.CONTACTS == {}
    phone_call.save_call_to_memory.assert_not_called()


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("xai", "explicit-xai-model"),
        ("openai", "explicit-openai-model"),
        ("deep-seek", "explicit-deepseek-model"),
    ],
)
def test_generated_assistant_honors_explicit_provider_and_model_without_sweeping(
    monkeypatch, provider, model
):
    _set_config(
        monkeypatch,
        VAPI_ASSISTANT_ID="",
        VAPI_PHONE_NUMBER_ID="outbound-number",
        VAPI_API_KEY="test-key",
        VAPI_LLM_PROVIDER=provider,
        VAPI_LLM_MODEL=model,
        VAPI_VOICEMAIL_ACTION="disabled",
    )
    post = Mock(
        side_effect=[
            _response({"id": "created-for-call"}),
            _response({"id": "call-A", "status": "queued"}),
        ]
    )
    monkeypatch.setattr(phone_call.requests, "post", post)

    result = phone_call.make_call("Alice", "Ask about dinner", phone_number="+15550000001")

    assert post.call_count == 2
    assistant_request, call_request = post.call_args_list
    assert assistant_request.args == (f"{phone_call.VAPI_API_BASE}/assistant",)
    model_config = assistant_request.kwargs["json"]["model"]
    assert model_config["provider"] == provider
    assert model_config["model"] == model
    assert "Ask about dinner" in model_config["messages"][0]["content"]
    assert call_request.args == (f"{phone_call.VAPI_API_BASE}/call",)
    assert call_request.kwargs["json"]["assistantId"] == "created-for-call"
    assert "assistantOverrides" not in call_request.kwargs["json"]
    assert result["temporary_assistant_id"] == "created-for-call"


def test_generated_assistant_honors_configured_elevenlabs_voice_and_model(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_API_KEY="test-key",
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="explicit-openai-model",
        VAPI_ELEVENLABS_KEY="credential-is-connected-in-vapi",
        VAPI_VOICE_ID="configured-voice",
        VAPI_VOICE_MODEL="eleven_v4_turbo",
    )
    post = Mock(return_value=_response({"id": "created-for-call"}))
    monkeypatch.setattr(phone_call.requests, "post", post)

    phone_call.create_assistant_for_call("default", "Boss", "Ask about dinner", "")

    assert post.call_args.kwargs["json"]["voice"] == {
        "provider": "11labs",
        "voiceId": "configured-voice",
        "model": "eleven_v4_turbo",
    }


def test_openai_reasoning_effort_is_explicitly_forwarded(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="explicit-openai-model",
        VAPI_LLM_REASONING_EFFORT="low",
    )

    model = phone_call.get_vapi_model_config("System prompt")

    assert model["reasoningEffort"] == "low"


def test_openai_reasoning_effort_does_not_leak_to_xai(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="xai",
        VAPI_LLM_MODEL="explicit-xai-model",
        VAPI_LLM_REASONING_EFFORT="low",
    )

    with pytest.raises(ValueError, match="(?i)openai"):
        phone_call.get_vapi_model_config("System prompt")


def test_luna_rejects_minimal_before_creating_an_assistant_or_dialing(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_ASSISTANT_ID="",
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_WAIT_FOR_CALL="false",
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="gpt-6-luna",
        VAPI_LLM_REASONING_EFFORT="minimal",
    )
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000001")

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert "gpt-6-luna" in result["error"]
    assert "minimal" in result["error"]
    assert phone_call.is_call_in_progress() is None


def test_luna_accepts_none_from_shared_thinking_metadata(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="gpt-6-luna",
        VAPI_LLM_REASONING_EFFORT="none",
    )

    model = phone_call.get_vapi_model_config("System prompt")

    assert model["model"] == "gpt-6-luna"
    assert model["reasoningEffort"] == "none"


def test_vapi_reasoning_validation_reads_shared_catalog_values(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="fixture-catalog-model",
        VAPI_LLM_REASONING_EFFORT="low",
    )
    metadata = Mock(
        return_value={"reasoning_effort": True, "reasoning_effort_values": ["none", "high"]}
    )
    monkeypatch.setattr(phone_call, "get_model_metadata", metadata)

    with pytest.raises(ValueError, match="fixture-catalog-model"):
        phone_call.get_vapi_model_config("System prompt")

    metadata.assert_called_once_with("openai", "fixture-catalog-model")
    metadata.return_value = {"reasoning_effort": True, "reasoning_effort_values": ["none", "low"]}

    assert phone_call.get_vapi_model_config("System prompt")["reasoningEffort"] == "low"


def test_known_model_without_thinking_effort_rejects_explicit_setting(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="fixture-no-reasoning-model",
        VAPI_LLM_REASONING_EFFORT="none",
    )
    monkeypatch.setattr(
        phone_call, "get_model_metadata", Mock(return_value={"reasoning_effort": False})
    )

    with pytest.raises(ValueError, match="fixture-no-reasoning-model"):
        phone_call.get_vapi_model_config("System prompt")


def test_unknown_vapi_model_retains_schema_supported_reasoning_values(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="future-vapi-model",
        VAPI_LLM_REASONING_EFFORT="minimal",
    )
    monkeypatch.setattr(phone_call, "get_model_metadata", Mock(return_value=None))

    model = phone_call.get_vapi_model_config("System prompt")

    assert model["model"] == "future-vapi-model"
    assert model["reasoningEffort"] == "minimal"


@pytest.mark.parametrize("phone_effort", [None, ""])
def test_omitted_phone_effort_does_not_inherit_chat_thinking_or_force_catalog_validation(
    monkeypatch, phone_effort
):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="independent-vapi-model",
        VAPI_LLM_REASONING_EFFORT=phone_effort,
        JARVIS_THINKING_EFFORT="high",
        OPENAI_REASONING_EFFORT="high",
    )
    metadata = Mock(side_effect=AssertionError("No explicit phone effort to validate"))
    monkeypatch.setattr(phone_call, "get_model_metadata", metadata)

    model = phone_call.get_vapi_model_config("System prompt")

    assert model["model"] == "independent-vapi-model"
    assert "reasoningEffort" not in model
    metadata.assert_not_called()


def test_catalog_reasoning_level_cannot_bypass_vapi_transport_enum(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="fixture-catalog-model",
        VAPI_LLM_REASONING_EFFORT="max",
    )
    monkeypatch.setattr(
        phone_call,
        "get_model_metadata",
        Mock(return_value={"reasoning_effort": True, "reasoning_effort_values": ["max"]}),
    )

    with pytest.raises(ValueError):
        phone_call.get_vapi_model_config("System prompt")


@pytest.mark.parametrize(
    ("configured", "explicit", "expected"),
    [("female", None, "female"), ("female", "casual", "casual"), ("", None, "default")],
)
def test_call_uses_configured_default_persona_unless_explicitly_selected(
    monkeypatch, configured, explicit, expected
):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="false", VAPI_DEFAULT_PERSONA=configured)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000001")
    make_call = Mock(return_value={"call_id": "call-A", "status": "queued"})
    monkeypatch.setattr(phone_call, "make_call", make_call)
    arguments = {"recipient": "Alice", "task": "Ask about dinner"}
    if explicit is not None:
        arguments["persona"] = explicit

    result = phone_call.action_call(arguments)

    assert result["ok"] is True
    assert make_call.call_args.args[3] == expected
    make_call.assert_called_once()


def test_invalid_default_persona_fails_before_assistant_creation_or_dialing(monkeypatch):
    _set_config(monkeypatch, VAPI_DEFAULT_PERSONA="unsupported-persona")
    make_call = Mock()
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert "persona" in result["error"].lower()
    make_call.assert_not_called()


def test_call_reports_vapi_list_validation_errors_without_retrying(monkeypatch):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="false")
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000001")
    message = "model.reasoningEffort minimal is not supported for exact OpenAI model gpt-6-luna"
    response = _response({"message": [message], "error": "Bad Request"})
    response.status_code = 400
    failure = phone_call.requests.exceptions.HTTPError(
        "400 Client Error: Bad Request", response=response
    )
    make_call = Mock(side_effect=failure)
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert isinstance(result["error"], str)
    assert message in result["error"]
    assert message in result["speech"]
    make_call.assert_called_once()
    assert phone_call.is_call_in_progress() is None


@pytest.mark.parametrize(
    "longest_source", ["transcript", "artifact_transcript", "messages", "artifact_messages"]
)
def test_transcript_uses_longest_complete_legacy_or_modern_source(longest_source):
    longer = "The complete conversation includes the final answer and the agreed dinner plans."
    call = {
        "transcript": "Brief preview",
        "messages": [{"role": "assistant", "message": "Hello"}],
        "artifact": {
            "transcript": "Another preview",
            "messages": [{"role": "user", "message": "Hi"}],
        },
    }
    expected = longer
    if longest_source == "transcript":
        call["transcript"] = longer
    elif longest_source == "artifact_transcript":
        call["artifact"]["transcript"] = longer
    else:
        expected = f"AI: Hello\nUser: {longer}"
        messages = [
            {"role": "system", "message": "Do not include private system instructions"},
            {"role": "assistant", "message": "Hello"},
            {"role": "customer", "message": longer},
        ]
        if longest_source == "messages":
            call["messages"] = messages
        else:
            call["artifact"]["messages"] = messages

    assert phone_call.extract_transcript(call) == expected


def test_modern_result_fields_are_normalized_for_status_and_canvas(monkeypatch):
    call = {
        "id": "call-A",
        "status": "ended",
        "startedAt": "2026-01-01T12:00:00.000Z",
        "endedAt": "2026-01-01T12:00:42.500Z",
        "endedReason": "customer-ended-call",
        "analysis": {"summary": "Alice agreed to dinner tomorrow."},
        "artifact": {"messages": [{"role": "customer", "message": "Yes, tomorrow works."}]},
    }
    save = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: call)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save)

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    assert result["data"]["summary"] == "Alice agreed to dinner tomorrow."
    assert result["data"]["transcript"] == "User: Yes, tomorrow works."
    assert result["data"]["duration"] == 42.5
    normalized = save.call_args.args[3]
    assert normalized["summary"] == "Alice agreed to dinner tomorrow."
    assert normalized["duration_seconds"] == 42.5


@pytest.mark.parametrize(
    ("timing", "expected"),
    [
        ({"duration": 12}, 12),
        (
            {"duration": 0, "startedAt": "2026-01-01T12:00:00Z", "endedAt": "2026-01-01T12:00:30Z"},
            0,
        ),
        ({"startedAt": "2026-01-01T12:00:00Z", "endedAt": "2026-01-01T12:00:30Z"}, 30),
    ],
)
def test_result_duration_prefers_explicit_seconds_and_falls_back_to_timestamps(timing, expected):
    result = phone_call.extract_call_result({"status": "ended", **timing}, "call-A")

    assert result["duration_seconds"] == expected


@pytest.mark.parametrize(
    "recording_fields",
    [
        {"recordingUrl": "https://storage.example/recording.wav?signature=temporary"},
        {"artifact": {"recordingUrl": "https://storage.example/recording.wav?signature=temporary"}},
        {
            "artifact": {
                "stereoRecordingUrl": "https://storage.example/recording.wav?signature=temporary"
            }
        },
    ],
)
def test_recording_identity_uses_stable_authenticated_endpoint(recording_fields):
    result = phone_call.extract_call_result({"id": "call-A", "status": "ended", **recording_fields})

    assert result["recording_url"] == f"{phone_call.VAPI_API_BASE}/call/call-A/mono-recording"
    assert result["recording_requires_auth"] is True
    assert "signature=temporary" not in json.dumps(result)


def test_missing_recording_does_not_advertise_download():
    result = phone_call.extract_call_result({"id": "call-A", "status": "ended"})

    assert not result["recording_url"]
    assert result["recording_requires_auth"] is False


def test_recording_without_call_identity_never_exposes_expiring_storage_link():
    result = phone_call.extract_call_result(
        {
            "status": "ended",
            "artifact": {"recordingUrl": "https://storage.example/audio?token=private"},
        }
    )

    assert not result["recording_url"]
    assert "token=private" not in json.dumps(result)


def test_wait_completion_normalizes_current_vapi_artifact_fields(monkeypatch):
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "startedAt": "2026-01-01T12:00:00Z",
            "endedAt": "2026-01-01T12:00:30Z",
            "endedReason": "customer-ended-call",
            "analysis": {"summary": "Dinner confirmed"},
            "artifact": {"messages": [{"role": "user", "message": "Dinner works"}]},
        },
    )

    result = phone_call.wait_for_call_completion("call-A", timeout=5)

    assert result["status"] == "ended"
    assert result["summary"] == "Dinner confirmed"
    assert result["transcript"] == "User: Dinner works"
    assert result["duration_seconds"] == 30
    assert result["call_failed"] is False


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [(1, '{"ok":true}'), (0, "not json"), (0, '{"ok":false,"error":"save failed"}'), (0, "{}")],
)
def test_canvas_save_reports_child_failures_truthfully(monkeypatch, returncode, stdout):
    run = Mock(return_value=subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=""))
    monkeypatch.setattr(subprocess, "run", run)

    saved = phone_call.save_call_to_canvas(
        "call-A", "Alice", "Ask about dinner", {"status": "ended", "transcript": "Hello"}
    )

    assert saved is False


def test_canvas_save_requires_confirmed_child_success(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr=""))
    monkeypatch.setattr(subprocess, "run", run)

    saved = phone_call.save_call_to_canvas(
        "call-A", "Alice", "Ask about dinner", {"status": "ended", "transcript": "Hello"}
    )

    assert saved is True
    assert run.call_args.args[0][0] == sys.executable


def test_failed_canvas_save_is_not_claimed_in_status_speech(monkeypatch):
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "transcript": "Dinner works",
            "summary": "Dinner confirmed",
        },
    )
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=False))

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    assert result["data"]["saved_to_canvas"] is False
    assert result["data"]["canvas_location"] is None
    assert "could not save" in result["speech"].lower()
    assert "already saved" not in result["speech"].lower()


def test_failed_canvas_save_is_not_claimed_after_synchronous_call(monkeypatch):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="true")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000001")
    monkeypatch.setattr(
        phone_call,
        "make_call",
        Mock(return_value={"call_id": "call-A", "status": "queued"}),
    )
    monkeypatch.setattr(
        phone_call,
        "wait_for_call_completion",
        lambda _call_id: {
            "status": "ended",
            "summary": "Dinner confirmed",
            "transcript": "Dinner works",
            "call_failed": False,
        },
    )
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=False))

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is True
    assert result["data"]["saved_to_canvas"] is False
    assert result["data"]["canvas_location"] is None
    assert "could not save" in result["speech"].lower()
    assert "full transcript saved" not in result["speech"].lower()
    assert phone_call.is_call_in_progress() is None
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "customer": {"number": "+15550000001"},
            "transcript": "Dinner works",
        },
    )
    retry_save = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", retry_save)

    retry = phone_call.action_status({"call_id": "call-A"})

    assert retry["data"]["saved_to_canvas"] is True
    assert retry_save.call_args.args[:3] == ("call-A", "Alice", "Ask about dinner")


def test_wait_timeout_retains_active_call_and_generated_assistant(monkeypatch):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="true")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000001")
    make_call = Mock(
        return_value={
            "call_id": "call-A",
            "status": "queued",
            "assistant_id": "created-for-call",
            "temporary_assistant_id": "created-for-call",
        }
    )
    monkeypatch.setattr(phone_call, "make_call", make_call)
    monkeypatch.setattr(
        phone_call,
        "wait_for_call_completion",
        lambda _call_id: {"status": "in-progress", "call_id": "call-A"},
    )
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock())

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is True
    assert result["data"]["status"] == "in-progress"
    marker = json.loads(phone_call.CALL_IN_PROGRESS_FILE.read_text())
    assert marker["call_id"] == "call-A"
    assert marker["task"] == "Ask about dinner"
    assert marker["temporary_assistant_id"] == "created-for-call"
    # A repeated request observes the same active call instead of placing another.
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: {"status": "in-progress"})
    repeated = phone_call.action_call({"recipient": "Bob", "task": "Ask about lunch"})
    assert repeated["data"]["call_id"] == "call-A"
    make_call.assert_called_once()


@pytest.mark.parametrize("terminal_status", ["ended", "failed"])
def test_terminal_status_deletes_only_assistant_owned_by_tracked_call(monkeypatch, terminal_status):
    _set_config(monkeypatch, VAPI_API_KEY="test-key", VAPI_ASSISTANT_ID="unrelated-saved-assistant")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    marker = {
        "call_id": "call-A",
        "recipient": "Alice",
        "task": "Ask about dinner",
        "started": 1000.0,
        "temporary_assistant_id": "created-for-call",
    }
    phone_call.CALL_IN_PROGRESS_FILE.write_text(json.dumps(marker))
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {"status": terminal_status, "transcript": "Goodbye"},
    )
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=True))
    delete = Mock(return_value=_response({}))
    monkeypatch.setattr(phone_call.requests, "delete", delete)

    phone_call.action_status({"call_id": "call-A"})

    delete.assert_called_once()
    assert delete.call_args.args == (f"{phone_call.VAPI_API_BASE}/assistant/created-for-call",)
    assert phone_call.is_call_in_progress() is None


def test_terminal_status_does_not_delete_saved_or_untracked_assistants(monkeypatch):
    _set_config(monkeypatch, VAPI_ASSISTANT_ID="saved-assistant")
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "transcript": "Goodbye",
            "assistantId": "somebody-elses-call-temp",
        },
    )
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=True))

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True


def test_late_call_artifacts_preserve_original_recipient_and_task(monkeypatch):
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    phone_call.set_call_in_progress("call-A", "+15550000001", "Alice", "Ask about dinner")
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        Mock(
            side_effect=[
                {"status": "ended", "customer": {"number": "+15550000001"}},
                {
                    "status": "ended",
                    "customer": {"number": "+15550000001"},
                    "artifact": {"messages": [{"role": "user", "message": "Dinner works"}]},
                },
            ]
        ),
    )
    save = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save)

    pending = phone_call.action_status({"call_id": "call-A"})

    assert pending["data"]["saved_to_canvas"] is False
    assert "no transcript" in pending["speech"].lower()
    save.assert_not_called()

    completed = phone_call.action_status({"call_id": "call-A"})

    assert completed["data"]["saved_to_canvas"] is True
    assert save.call_args.args[:3] == ("call-A", "Alice", "Ask about dinner")
    assert save.call_args.args[3]["transcript"] == "User: Dinner works"


def test_failed_canvas_save_retains_original_call_context_for_retry(monkeypatch):
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    phone_call.set_call_in_progress("call-A", "+15550000001", "Alice", "Ask about dinner")
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "customer": {"number": "+15550000001"},
            "transcript": "Dinner works",
        },
    )
    save = Mock(side_effect=[False, True])
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save)

    failed_save = phone_call.action_status({"call_id": "call-A"})
    completed = phone_call.action_status({"call_id": "call-A"})

    assert failed_save["data"]["saved_to_canvas"] is False
    assert completed["data"]["saved_to_canvas"] is True
    assert [call.args[:3] for call in save.call_args_list] == [
        ("call-A", "Alice", "Ask about dinner"),
        ("call-A", "Alice", "Ask about dinner"),
    ]


def test_new_call_can_proceed_while_prior_artifacts_are_pending(monkeypatch):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="false")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    phone_call.set_call_in_progress("call-A", "+15550000001", "Alice", "Ask about dinner")
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {"status": "ended", "customer": {"number": "+15550000001"}},
    )
    save = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save)

    phone_call.action_status({"call_id": "call-A"})

    make_call = Mock(return_value={"call_id": "call-B", "status": "queued"})
    monkeypatch.setattr(phone_call, "make_call", make_call)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000002")

    new_call = phone_call.action_call({"recipient": "Bob", "task": "Ask about lunch"})

    assert new_call["data"]["call_id"] == "call-B"
    make_call.assert_called_once()
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "customer": {"number": "+15550000001"},
            "transcript": "Dinner works",
        },
    )

    phone_call.action_status({"call_id": "call-A"})

    assert save.call_args.args[:3] == ("call-A", "Alice", "Ask about dinner")
    active_call = phone_call.is_call_in_progress()
    assert active_call is not None
    assert active_call["call_id"] == "call-B"


@pytest.mark.parametrize("caller", ["call", "status"])
@pytest.mark.parametrize("canvas_saved", [True, False])
def test_completed_call_returns_stash_artifacts_independently_of_canvas(
    monkeypatch, caller, canvas_saved
):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="true")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    normalized = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "transcript": "User: Dinner works",
        "call_failed": False,
    }
    if caller == "call":
        monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+12125550199")
        monkeypatch.setattr(
            phone_call, "make_call", Mock(return_value={"call_id": "call-A", "status": "queued"})
        )
        monkeypatch.setattr(phone_call, "wait_for_call_completion", lambda _call_id: normalized)
    else:
        phone_call.set_call_in_progress("call-A", "+12125550199", "Alice", "Ask about dinner")
        monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: normalized)
    stash_data = {
        "stash_space_id": "space_fixture",
        "transcript_saved": True,
        "transcript_status": "saved",
        "transcript_stash_ref": "stash://space_fixture/transcript",
        "audio_saved": True,
        "audio_status": "saved",
        "audio_stash_ref": "stash://space_fixture/recording",
        "stash_ref": "stash://space_fixture/recording",
        "filename": "recording.wav",
        "mime_type": "audio/wav",
    }
    save_artifacts = Mock(return_value=stash_data)
    save_canvas = Mock(return_value=canvas_saved)
    monkeypatch.setattr(phone_call, "save_call_artifacts", save_artifacts)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    if caller == "call":
        result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})
    else:
        result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    assert {key: result["data"].get(key) for key in stash_data} == stash_data
    assert result["data"]["saved_to_canvas"] is canvas_saved
    save_artifacts.assert_called_once()
    assert save_artifacts.call_args.args[0] == "call-A"
    assert save_artifacts.call_args.args[1]["recipient"] == "Alice"
    assert save_artifacts.call_args.args[1]["task"] == "Ask about dinner"
    save_canvas.assert_called_once()
    assert save_canvas.call_args.args[3]["audio_stash_ref"] == stash_data["audio_stash_ref"]


@pytest.mark.parametrize("audio_status", ["failed", "pending", "unavailable"])
def test_status_recording_failure_preserves_call_success_and_canvas_attempt(
    monkeypatch, audio_status
):
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {"status": "ended", "transcript": "Dinner works"},
    )
    monkeypatch.setattr(
        phone_call,
        "save_call_artifacts",
        Mock(
            return_value={
                "transcript_saved": True,
                "transcript_stash_ref": "stash://space_fixture/transcript",
                "audio_saved": False,
                "audio_status": audio_status,
            }
        ),
    )
    save_canvas = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    assert result["data"]["audio_saved"] is False
    assert result["data"]["audio_status"] == audio_status
    assert result["data"]["transcript_saved"] is True
    assert result["data"]["saved_to_canvas"] is True
    assert "recording" in result["speech"].lower()
    save_canvas.assert_called_once()


def test_canvas_page_includes_stash_recording_and_written_transcript_links(monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout='{"ok":true,"data":{"page_id":"page-call"}}', stderr=""
        )
    )
    monkeypatch.setattr(subprocess, "run", run)
    data = {
        "status": "ended",
        "transcript": "Dinner works",
        "stash_space_id": "space_fixture",
        "audio_saved": True,
        "audio_stash_ref": "stash://space_fixture/recording",
        "transcript_stash_ref": "stash://space_fixture/transcript",
    }

    saved = phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", data)

    assert saved is True
    payload = json.loads(run.call_args.args[0][2])
    assert payload["action"] == "create"
    assert "[Call recording](stash://space_fixture/recording)" in payload["content"]
    assert "[Written transcript](stash://space_fixture/transcript)" in payload["content"]
    phone_call.remember_call_canvas.assert_called_once()


@pytest.mark.parametrize("append_succeeds", [True, False])
def test_late_audio_appends_once_without_replacing_existing_canvas_content(
    monkeypatch, append_succeeds
):
    state = {}
    monkeypatch.setattr(phone_call, "get_call_canvas", lambda _space_id: dict(state))

    def remember(_space_id, page_id, title, audio_stash_ref=None, result_sha256=None):
        state.update(page_id=page_id, title=title)
        if audio_stash_ref:
            state["audio_stash_ref"] = audio_stash_ref
        if result_sha256:
            state["result_sha256"] = result_sha256

    monkeypatch.setattr(phone_call, "remember_call_canvas", remember)
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout='{"ok":true,"data":{"page_id":"page-call"}}', stderr=""
        )
    )
    monkeypatch.setattr(subprocess, "run", run)
    data = {
        "status": "ended",
        "transcript": "Dinner works",
        "stash_space_id": "space_fixture",
        "audio_saved": True,
        "audio_stash_ref": "stash://space_fixture/recording",
        "transcript_stash_ref": "stash://space_fixture/transcript",
    }
    initial = {**data, "audio_saved": False, "audio_stash_ref": None}
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", initial) is True
    run.reset_mock()
    run.return_value = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps({"ok": append_succeeds}), stderr=""
    )

    first = phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", data)

    assert first is append_succeeds
    payload = json.loads(run.call_args.args[0][2])
    assert payload["action"] == "append"
    assert payload["page_id"] == "page-call"
    assert "stash://space_fixture/recording" in payload["content"]
    assert "Dinner works" not in payload["content"]
    if append_succeeds:
        assert state["audio_stash_ref"] == data["audio_stash_ref"]
        assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", data) is True
        run.assert_called_once()
    else:
        assert "audio_stash_ref" not in state


@pytest.mark.parametrize("terminal_status", ["ended", "failed"])
def test_background_deadline_forces_observation_and_reports_completed_remote_work(
    monkeypatch, terminal_status
):
    _set_config(
        monkeypatch,
        VAPI_WAIT_FOR_CALL="false",
        JARVIS_BACKGROUND_DEADLINE="2200",
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="saved-assistant",
    )
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+12125550199")
    make_call = Mock(return_value={"call_id": "call-A", "status": "queued"})
    wait = Mock(
        return_value={
            "status": terminal_status,
            "transcript": "Dinner works",
            "summary": "Dinner confirmed",
        }
    )
    monkeypatch.setattr(phone_call, "make_call", make_call)
    monkeypatch.setattr(phone_call, "wait_for_call_completion", wait)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=True))
    monkeypatch.setattr(phone_call, "emit_tool_progress", Mock())

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    wait.assert_called_once_with("call-A")
    make_call.assert_called_once()
    assert result["completion"] == "completed"
    assert result["ok"] is (terminal_status == "ended")
    assert result["data"]["call_id"] == "call-A"
    assert phone_call.is_call_in_progress() is None


def test_background_observation_timeout_preserves_recovery_handle_and_never_redials(monkeypatch):
    _set_config(
        monkeypatch,
        VAPI_WAIT_FOR_CALL="false",
        JARVIS_BACKGROUND_DEADLINE="2200",
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="saved-assistant",
    )
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+12125550199")
    make_call = Mock(return_value={"call_id": "call-A", "status": "queued"})
    monkeypatch.setattr(phone_call, "make_call", make_call)
    monkeypatch.setattr(
        phone_call,
        "wait_for_call_completion",
        lambda _call_id: {"status": "in-progress", "call_id": "call-A"},
    )
    progress = Mock()
    monkeypatch.setattr(phone_call, "emit_tool_progress", progress)

    result = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert result["completion"] == "unknown"
    assert result["data"]["call_id"] == "call-A"
    assert result["data"]["task_id"] == "call-A"
    assert progress.call_args.args[0]["recovery"] == {"task_id": "call-A"}
    tracked = phone_call.is_call_in_progress()
    assert tracked is not None
    assert tracked["call_id"] == "call-A"

    repeated = phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})

    assert repeated["ok"] is False
    assert repeated["data"]["call_id"] == "call-A"
    make_call.assert_called_once()


def test_artifact_collector_exception_does_not_fail_completed_status_or_canvas(monkeypatch):
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {"status": "ended", "transcript": "Dinner works"},
    )
    monkeypatch.setattr(
        phone_call, "save_call_artifacts", Mock(side_effect=OSError("fixture storage unavailable"))
    )
    save_canvas = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    assert result["data"]["saved_to_canvas"] is True
    assert result["data"]["audio_status"] == "failed"
    save_canvas.assert_called_once()


def test_background_rejects_insufficient_observation_budget_before_starting_call(monkeypatch):
    _set_config(
        monkeypatch,
        JARVIS_BACKGROUND_DEADLINE="1149",
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="saved-assistant",
    )
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    make_call = Mock()
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "+12125550199", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert result["completion"] == "rejected"
    assert "budget" in result["error"].lower()
    make_call.assert_not_called()
    assert phone_call.is_call_in_progress() is None


@pytest.mark.parametrize("missing", ["VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID"])
def test_background_rejects_missing_call_credentials_before_starting_call(monkeypatch, missing):
    settings = {
        "JARVIS_BACKGROUND_DEADLINE": "2200",
        "VAPI_API_KEY": "fixture-key",
        "VAPI_PHONE_NUMBER_ID": "fixture-phone",
        "VAPI_ASSISTANT_ID": "saved-assistant",
        missing: "",
    }
    _set_config(monkeypatch, **settings)
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    make_call = Mock()
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "+12125550199", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert result["completion"] == "rejected"
    assert missing in result["error"]
    make_call.assert_not_called()


def test_background_rejects_invalid_generated_model_effort_before_starting_call(monkeypatch):
    _set_config(
        monkeypatch,
        JARVIS_BACKGROUND_DEADLINE="2200",
        VAPI_API_KEY="fixture-key",
        VAPI_PHONE_NUMBER_ID="fixture-phone",
        VAPI_ASSISTANT_ID="",
        VAPI_LLM_PROVIDER="openai",
        VAPI_LLM_MODEL="gpt-6-luna",
        VAPI_LLM_REASONING_EFFORT="minimal",
    )
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    make_call = Mock()
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "+12125550199", "task": "Ask about dinner"})

    assert result["ok"] is False
    assert result["completion"] == "rejected"
    assert "gpt-6-luna" in result["error"]
    assert "minimal" in result["error"]
    make_call.assert_not_called()


def test_initially_unavailable_recording_keeps_original_context_for_late_audio(monkeypatch):
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    phone_call.set_call_in_progress("call-A", "+12125550199", "Alice", "Ask about dinner")
    monkeypatch.setattr(
        phone_call,
        "get_call_status",
        lambda _call_id: {
            "status": "ended",
            "transcript": "Dinner works",
            "customer": {"number": "+12125550199"},
        },
    )
    collect = Mock(
        side_effect=[
            {"transcript_saved": True, "audio_saved": False, "audio_status": "unavailable"},
            {"transcript_saved": True, "audio_saved": True, "audio_status": "saved"},
        ]
    )
    monkeypatch.setattr(phone_call, "save_call_artifacts", collect)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=True))

    initial = phone_call.action_status({"call_id": "call-A"})
    assert initial["data"]["audio_status"] == "unavailable"
    assert phone_call.is_call_in_progress() is None

    late = phone_call.action_status({"call_id": "call-A"})

    assert late["data"]["audio_saved"] is True
    assert collect.call_args.args[1]["recipient"] == "Alice"
    assert collect.call_args.args[1]["task"] == "Ask about dinner"


@pytest.mark.parametrize("caller", ["call", "status"])
@pytest.mark.parametrize(
    "end_reason", ["customer-busy", "customer-did-not-answer", "voicemail-reached"]
)
def test_unsuccessful_callee_outcome_is_distinct_from_status_query_and_preserves_transcript(
    monkeypatch, caller, end_reason
):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="true")
    monkeypatch.setattr(phone_call.time, "time", lambda: 1000.0)
    raw_call = {
        "status": "ended", "endedReason": end_reason,
        "transcript": "AI: Hello, I am calling about dinner.",
        "customer": {"number": "+12125550199"},
    }
    if caller == "call":
        monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+12125550199")
        monkeypatch.setattr(
            phone_call, "make_call", Mock(return_value={"call_id": "call-A", "status": "queued"})
        )
        monkeypatch.setattr(
            phone_call, "wait_for_call_completion",
            lambda _call_id: phone_call.extract_call_result(raw_call, "call-A"),
        )
    else:
        phone_call.set_call_in_progress("call-A", "+12125550199", "Alice", "Ask about dinner")
        monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: raw_call)
    save_canvas = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    result = (
        phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})
        if caller == "call" else phone_call.action_status({"call_id": "call-A"})
    )

    assert result["ok"] is (caller == "status")
    if caller == "call":
        assert result["completion"] == "completed"
    assert result["data"]["call_failed"] is True
    assert result["data"]["end_reason"] == end_reason
    assert result["data"]["saved_to_canvas"] is True
    assert result["data"]["transcript"] == raw_call["transcript"]
    save_canvas.assert_called_once()
    assert save_canvas.call_args.args[:3] == ("call-A", "Alice", "Ask about dinner")


@pytest.mark.parametrize("caller", ["call", "status"])
def test_terminal_failed_call_without_transcript_does_not_create_canvas_page(monkeypatch, caller):
    _set_config(monkeypatch, VAPI_WAIT_FOR_CALL="true")
    failed_call = {"status": "failed", "endedReason": "customer-busy"}
    if caller == "call":
        monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+12125550199")
        monkeypatch.setattr(
            phone_call, "make_call", Mock(return_value={"call_id": "call-A", "status": "queued"})
        )
        monkeypatch.setattr(
            phone_call, "wait_for_call_completion",
            lambda _call_id: phone_call.extract_call_result(failed_call, "call-A"),
        )
    else:
        monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: failed_call)
    save_canvas = Mock()
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    result = (
        phone_call.action_call({"recipient": "Alice", "task": "Ask about dinner"})
        if caller == "call" else phone_call.action_status({"call_id": "call-A"})
    )

    assert result["ok"] is (caller == "status")
    assert result["data"]["saved_to_canvas"] is False
    save_canvas.assert_not_called()


def test_status_get_error_is_reported_as_query_failure_without_saving_artifacts(monkeypatch):
    monkeypatch.setattr(
        phone_call, "get_call_status", Mock(side_effect=phone_call.requests.HTTPError("HTTP 503"))
    )
    save_canvas = Mock()
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_canvas)

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is False
    assert "503" in result["error"]
    save_canvas.assert_not_called()
    phone_call.save_call_artifacts.assert_not_called()


def test_missing_recording_is_neutral_and_does_not_promise_eventual_availability(monkeypatch):
    monkeypatch.setattr(
        phone_call, "get_call_status",
        lambda _call_id: {"status": "ended", "transcript": "Dinner works"},
    )
    monkeypatch.setattr(phone_call, "save_call_artifacts", Mock(return_value={
        "transcript_saved": True, "audio_saved": False, "audio_status": "unavailable"
    }))
    monkeypatch.setattr(phone_call, "save_call_to_canvas", Mock(return_value=True))

    result = phone_call.action_status({"call_id": "call-A"})

    assert result["ok"] is True
    speech = result["speech"].lower()
    assert "no recording is available right now" in speech
    assert "could not retrieve" not in speech
    assert "failed" not in speech
    assert "will be available" not in speech


def test_late_summary_and_full_transcript_append_once_and_preserve_canvas_notes(monkeypatch):
    metadata = {}
    page = {"content": ""}
    monkeypatch.setattr(phone_call, "get_call_canvas", lambda _space_id: dict(metadata))

    def remember(_space_id, page_id, title, audio_stash_ref=None, result_sha256=None):
        metadata.update(page_id=page_id, title=title)
        if audio_stash_ref:
            metadata["audio_stash_ref"] = audio_stash_ref
        if result_sha256:
            metadata["result_sha256"] = result_sha256

    monkeypatch.setattr(phone_call, "remember_call_canvas", remember)
    mutations = []

    def run(command, **kwargs):
        payload = json.loads(command[2])
        mutations.append(payload)
        if len(mutations) == 1:
            assert payload["action"] == "create"
            page["content"] = payload["content"]
        else:
            assert payload["action"] == "append"
            assert payload["page_id"] == "page-call"
            page["content"] += "\n" + payload["content"]
        return subprocess.CompletedProcess(
            [], 0, stdout='{"ok":true,"data":{"page_id":"page-call"}}', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", run)
    initial = {
        "status": "ended", "summary": "Early summary", "transcript": "AI: Hello",
        "stash_space_id": "space_fixture", "audio_saved": False,
        "transcript_stash_ref": "stash://space_fixture/transcript",
    }
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", initial) is True
    page["content"] += "\nUser notes: Keep my checked list.\n"
    latest = {
        **initial,
        "summary": "Dinner tomorrow confirmed.",
        "transcript": "AI: Hello\nUser: Tomorrow at six works.\nAI: Dinner is confirmed.",
    }

    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", latest) is True
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", latest) is True

    assert len(mutations) == 2
    assert "Updated call results" in mutations[1]["content"]
    assert latest["summary"] in mutations[1]["content"]
    assert latest["transcript"] in mutations[1]["content"]
    assert "User notes: Keep my checked list." in page["content"]
    assert page["content"].count(latest["summary"]) == 1
    assert metadata.get("result_sha256")


def test_legacy_canvas_page_without_result_hash_receives_one_safe_append(monkeypatch):
    metadata = {"page_id": "page-call", "title": "Phone Calls/Legacy"}
    monkeypatch.setattr(phone_call, "get_call_canvas", lambda _space_id: dict(metadata))

    def remember(_space_id, page_id, title, audio_stash_ref=None, result_sha256=None):
        metadata.update(page_id=page_id, title=title, result_sha256=result_sha256)

    monkeypatch.setattr(phone_call, "remember_call_canvas", remember)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr=""))
    monkeypatch.setattr(subprocess, "run", run)
    data = {
        "status": "ended", "summary": "Dinner confirmed", "transcript": "User: Six works.",
        "stash_space_id": "space_fixture", "audio_saved": False,
    }

    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", data) is True
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", data) is True

    run.assert_called_once()
    payload = json.loads(run.call_args.args[0][2])
    assert payload["action"] == "append"
    assert payload["page_id"] == "page-call"
    assert "## Updated call results" in payload["content"]
    assert data["transcript"] in payload["content"]
    assert metadata["result_sha256"]


def test_failed_combined_results_and_audio_append_remains_retryable_without_duplicate_audio(
    monkeypatch,
):
    metadata = {}
    monkeypatch.setattr(phone_call, "get_call_canvas", lambda _space_id: dict(metadata))

    def remember(_space_id, page_id, title, audio_stash_ref=None, result_sha256=None):
        metadata.update(page_id=page_id, title=title)
        if audio_stash_ref:
            metadata["audio_stash_ref"] = audio_stash_ref
        if result_sha256:
            metadata["result_sha256"] = result_sha256

    monkeypatch.setattr(phone_call, "remember_call_canvas", remember)
    run = Mock(return_value=subprocess.CompletedProcess(
        [], 0, stdout='{"ok":true,"data":{"page_id":"page-call"}}', stderr=""
    ))
    monkeypatch.setattr(subprocess, "run", run)
    initial = {
        "status": "ended", "summary": "Early summary", "transcript": "AI: Hello",
        "stash_space_id": "space_fixture", "audio_saved": False,
    }
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", initial) is True
    initial_hash = metadata.get("result_sha256")
    assert initial_hash
    latest = {
        **initial, "summary": "Dinner confirmed", "transcript": "User: Six works.",
        "audio_saved": True, "audio_stash_ref": "stash://space_fixture/recording",
    }
    run.return_value = subprocess.CompletedProcess([], 0, stdout='{"ok":false}', stderr="")

    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", latest) is False

    assert metadata["result_sha256"] == initial_hash
    assert "audio_stash_ref" not in metadata
    run.return_value = subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr="")

    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", latest) is True
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", latest) is True

    assert run.call_count == 3
    combined = json.loads(run.call_args.args[0][2])
    assert combined["action"] == "append"
    assert "## Updated call results" in combined["content"]
    assert latest["transcript"] in combined["content"]
    assert "[Call recording](stash://space_fixture/recording)" in combined["content"]
    assert metadata["audio_stash_ref"] == latest["audio_stash_ref"]
    assert metadata["result_sha256"] != initial_hash

    revised = {**latest, "summary": "Final dinner confirmation"}
    assert phone_call.save_call_to_canvas("call-A", "Alice", "Ask about dinner", revised) is True

    text_only = json.loads(run.call_args.args[0][2])
    assert text_only["action"] == "append"
    assert revised["summary"] in text_only["content"]
    assert latest["audio_stash_ref"] not in text_only["content"]
