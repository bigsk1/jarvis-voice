"""Audited Anthropic thinking modes and hidden-trace request budgets."""

import pytest
from config_loader import config_scope

from lib.model_catalog import get_model_metadata
from lib.thinking import get_anthropic_request_config, get_thinking_config
from lib.thinking_policy import get_catalog_thinking_profile, resolve_thinking_request


@pytest.mark.parametrize("model,disabled,between_tools", [
    ("claude-opus-5-5", False, False),
    ("claude-fable-5", False, False),
    ("claude-sonnet-5-5", False, True),
    ("claude-opus-5", True, False),
    ("claude-sonnet-5", True, False),
    ("claude-sonnet-4-6", True, False),
    ("claude-opus-4-5-20251101", True, False),
])
def test_catalog_records_audited_disable_modes(model, disabled, between_tools):
    metadata = get_model_metadata("anthropic", model)
    types = metadata["capabilities"]["thinking"]["types"]
    assert types["disabled"]["supported"] is disabled
    assert types["between_tools"]["supported"] is between_tools


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-fable-5", "claude-sonnet-5-5"])
@pytest.mark.parametrize("effort", ["low", "medium", "high", "max", "xhigh"])
def test_explicit_effort_is_preserved_without_showing_trace(model, effort):
    with config_scope("cloud", overrides={"JARVIS_THINKING_EFFORT": effort}):
        request = resolve_thinking_request(
            provider="anthropic", model=model,
            profile=get_catalog_thinking_profile("anthropic", model), show_trace=False,
        )
        config = get_anthropic_request_config(model, request.value, show_trace=request.show_trace)
    assert config["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert config["output_config"] == {"effort": effort}
    assert config["max_tokens"] == 16_384


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-fable-5"])
@pytest.mark.parametrize("setting", ["auto", "off"])
def test_always_on_models_use_low_adaptive_for_auto_or_logical_off(model, setting):
    profile = get_catalog_thinking_profile("anthropic", model)
    assert profile.disable_supported is False
    assert profile.disabled_fallback_level == "low"
    with config_scope("cloud", overrides={"JARVIS_THINKING_EFFORT": setting}):
        request = resolve_thinking_request(
            provider="anthropic", model=model, profile=profile, show_trace=False,
        )
        config = get_anthropic_request_config(model, request.value)
    assert request.value == "low"
    assert config == {
        "thinking": {"type": "adaptive", "display": "omitted"},
        "output_config": {"effort": "low"},
        "max_tokens": 16_384,
    }


@pytest.mark.parametrize("setting", ["auto", "off"])
def test_sonnet_auto_off_uses_between_tools_without_adaptive_only_fields(setting):
    model = "claude-sonnet-5-5"
    profile = get_catalog_thinking_profile("anthropic", model)
    assert profile.disable_supported is True
    with config_scope("cloud", overrides={"JARVIS_THINKING_EFFORT": setting}):
        request = resolve_thinking_request(
            provider="anthropic", model=model, profile=profile, show_trace=False,
        )
        config = get_anthropic_request_config(model, request.value)
    assert request.value is False
    assert config == {
        "thinking": {"type": "between_tools"},
        "output_config": {"effort": "low"},
        "max_tokens": 4096,
    }


@pytest.mark.parametrize("value", [None, False])
def test_request_builder_handles_direct_auto_off_for_always_on_models(value):
    config = get_anthropic_request_config("claude-opus-5-5", value)
    assert config["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert config["output_config"] == {"effort": "low"}
    assert config["max_tokens"] == 16_384


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-4-5-20250929"])
def test_legacy_models_disable_thinking_explicitly(model):
    assert get_anthropic_request_config(model, False) == {
        "thinking": {"type": "disabled"}, "max_tokens": 1024,
    }


def test_legacy_thinking_helper_keeps_summarized_display_default():
    config = get_thinking_config("anthropic", "claude-opus-5-5", effort_override="high")
    assert config["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert config["output_config"] == {"effort": "high"}


def test_unknown_model_does_not_get_guessed_thinking_parameters():
    assert get_anthropic_request_config("claude-unknown-test", True) == {"max_tokens": 1024}
