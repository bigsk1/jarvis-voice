#!/usr/bin/env python3
"""Tests for model-profile thinking request resolution."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from model_prompt_overrides import ModelThinkingOverride
from thinking_policy import get_catalog_thinking_profile, resolve_thinking_request


REQUIRED_PROFILE = ModelThinkingOverride(
    supported=True,
    disable_supported=False,
    levels=("low", "high", "max"),
    default_level="max",
    disabled_fallback_level="low",
)


def _resolve(monkeypatch, **kwargs):
    monkeypatch.delenv("JARVIS_THINKING_EFFORT", raising=False)
    return resolve_thinking_request(
        provider="ollama",
        model="glm-5.3:cloud",
        profile=REQUIRED_PROFILE,
        show_trace=False,
        **kwargs,
    )


def test_required_model_maps_hidden_thinking_to_low(monkeypatch):
    resolved = _resolve(monkeypatch)
    assert resolved.value == "low"
    assert resolved.show_trace is False
    assert resolved.source == "profile_hidden"


def test_required_model_uses_default_level_when_trace_is_enabled(monkeypatch):
    monkeypatch.delenv("JARVIS_THINKING_EFFORT", raising=False)
    resolved = resolve_thinking_request(
        provider="ollama",
        model="glm-5.3:cloud",
        profile=REQUIRED_PROFILE,
        show_trace=True,
    )
    assert resolved.value == "max"
    assert resolved.show_trace is True


def test_generic_effort_selects_declared_level_without_showing_trace(monkeypatch):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "high")
    resolved = resolve_thinking_request(
        provider="ollama",
        model="glm-5.3:cloud",
        profile=REQUIRED_PROFILE,
        show_trace=False,
    )
    assert resolved.value == "high"
    assert resolved.show_trace is False


def test_off_uses_required_models_safe_fallback(monkeypatch):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "off")
    resolved = resolve_thinking_request(
        provider="ollama",
        model="glm-5.3:cloud",
        profile=REQUIRED_PROFILE,
        show_trace=False,
    )
    assert resolved.value == "low"
    assert resolved.source == "configured_disabled"


def test_unsupported_effort_falls_back_without_sending_bad_value(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "medium")
    resolved = resolve_thinking_request(
        provider="ollama",
        model="glm-5.3:cloud",
        profile=REQUIRED_PROFILE,
        show_trace=False,
    )
    assert resolved.value == "low"
    assert "unsupported" in caplog.text


def test_unprofiled_model_preserves_existing_boolean_behavior(monkeypatch):
    monkeypatch.delenv("JARVIS_THINKING_EFFORT", raising=False)
    resolved = resolve_thinking_request(
        provider="ollama",
        model="ordinary-model",
        profile=None,
        show_trace=False,
        unprofiled_value=False,
    )
    assert resolved.value is False
    assert resolved.profile_used is False


def test_generic_effort_is_not_guessed_for_unprofiled_model(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "max")
    resolved = resolve_thinking_request(
        provider="ollama",
        model="ordinary-model",
        profile=None,
        show_trace=False,
        unprofiled_value=False,
    )
    assert resolved.value is False
    assert "unprofiled" in caplog.text


def test_xai_profile_uses_catalog_default_and_safe_minimum_for_required_reasoning():
    profile = get_catalog_thinking_profile("xai", "grok-4.6")

    assert profile is not None
    assert profile.disable_supported is False
    assert profile.levels == ("low", "medium", "high", "xhigh")
    assert profile.default_level == "high"
    assert profile.disabled_fallback_level == "low"


def test_xai_reasoning_only_model_without_effort_is_unprofiled():
    assert get_catalog_thinking_profile("xai", "grok-4.20-reasoning") is None


def test_xai_explicit_none_is_used_for_logical_off(monkeypatch):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "off")
    profile = get_catalog_thinking_profile("xai", "grok-4.3")

    resolved = resolve_thinking_request(
        provider="xai",
        model="grok-4.3",
        profile=profile,
        show_trace=False,
    )

    assert resolved.value == "none"
    assert resolved.source == "configured_disabled"


def test_debug_visibility_uses_request_scoped_config(monkeypatch):
    import config_loader
    from thinking import should_enable_thinking

    monkeypatch.delenv("JARVIS_OVERRIDE_JARVIS_DEBUG_THINKING", raising=False)
    monkeypatch.setenv("JARVIS_DEBUG_THINKING", "true")
    monkeypatch.setattr(
        config_loader,
        "_load_mode_config",
        lambda mode: {
            "JARVIS_DEBUG_THINKING": "false" if mode == "cloud" else "true",
        },
    )

    with config_loader.config_scope("cloud"):
        assert should_enable_thinking() is False
    with config_loader.config_scope("local"):
        assert should_enable_thinking() is True
