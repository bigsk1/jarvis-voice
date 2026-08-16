#!/usr/bin/env python3
"""Contract tests for shared configured text-provider construction."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import llm_provider


@pytest.fixture
def configured_values(monkeypatch):
    values = {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_MODEL": "openai-model",
        "ANTHROPIC_API_KEY": "anthropic-key",
        "ANTHROPIC_MODEL": "anthropic-model",
        "XAI_API_KEY": "xai-key",
        "XAI_MODEL": "xai-model",
        "OLLAMA_BASE_URL": "http://ollama.test:11434",
    }
    monkeypatch.setattr(
        "config_loader.get_config_value",
        lambda key, default=None: values.get(key, default),
    )
    return values


@pytest.mark.parametrize(
    ("provider_type", "expected_key", "expected_model"),
    [
        ("openai", "openai-key", "openai-model"),
        ("anthropic", "anthropic-key", "anthropic-model"),
        ("xai", "xai-key", "xai-model"),
    ],
)
def test_factory_resolves_provider_credentials_and_models(
    monkeypatch,
    configured_values,
    provider_type,
    expected_key,
    expected_model,
):
    calls = []

    def fake_create(selected, **config):
        calls.append((selected, config))
        return SimpleNamespace(model=config["model"])

    monkeypatch.setattr(llm_provider, "create_provider", fake_create)

    selected, model, provider = llm_provider.create_configured_provider(
        provider_override=provider_type,
        mode="cloud",
    )

    assert selected == provider_type
    assert model == expected_model
    assert provider.model == expected_model
    assert calls == [
        (
            provider_type,
            {
                "api_key": expected_key,
                "model": expected_model,
                **(
                    {"enable_search": None}
                    if provider_type in {"anthropic", "xai"}
                    else {}
                ),
            },
        )
    ]


@pytest.mark.parametrize("provider_type", ["anthropic", "xai"])
def test_factory_disables_native_search_without_process_global_override(
    monkeypatch,
    configured_values,
    provider_type,
):
    calls = []
    previous_xai = os.environ.get("JARVIS_OVERRIDE_XAI_SEARCH")
    previous_anthropic = os.environ.get("JARVIS_OVERRIDE_ANTHROPIC_SEARCH")

    def fake_create(selected, **config):
        calls.append((selected, config))
        return SimpleNamespace(model=config["model"])

    monkeypatch.setattr(llm_provider, "create_provider", fake_create)

    llm_provider.create_configured_provider(
        provider_override=provider_type,
        mode="cloud",
        disable_server_side_tools=True,
    )

    assert calls[0][1]["enable_search"] is False
    assert os.environ.get("JARVIS_OVERRIDE_XAI_SEARCH") == previous_xai
    assert os.environ.get("JARVIS_OVERRIDE_ANTHROPIC_SEARCH") == previous_anthropic


def test_factory_passes_explicit_mode_to_ollama_resolution(monkeypatch, configured_values):
    resolve_calls = []
    create_calls = []

    def fake_resolve(mode, model_override=None, local_fallback=None):
        resolve_calls.append((mode, model_override, local_fallback))
        return model_override or "local-model"

    def fake_create(selected, **config):
        create_calls.append((selected, config))
        return SimpleNamespace(model=config["model"])

    monkeypatch.setattr("ollama_utils.resolve_ollama_model", fake_resolve)
    monkeypatch.setattr(llm_provider, "create_provider", fake_create)

    selected, model, _ = llm_provider.create_configured_provider(
        provider_override="ollama",
        model_override="requested-model",
        mode="local",
    )

    assert selected == "ollama"
    assert model == "requested-model"
    assert resolve_calls == [("local", "requested-model", "gemma4")]
    assert create_calls == [
        (
            "ollama",
            {
                "base_url": "http://ollama.test:11434",
                "model": "requested-model",
            },
        )
    ]


def test_helper_provider_uses_dedicated_local_config_not_ollama_routing(
    monkeypatch,
    configured_values,
):
    configured_values.update(
        {
            "JARVIS_HELPER_LLM_BASE_URL": "http://127.0.0.1:11434",
            "JARVIS_HELPER_LLM_MODEL": "bigsk1/jarvis-helper:minicpm5-1b-q4_k_m-v1",
            "JARVIS_HELPER_LLM_DEVICE": "cpu",
            "JARVIS_HELPER_LLM_CONTEXT_WINDOW": "8192",
            "JARVIS_HELPER_LLM_KEEP_ALIVE": "30m",
            "JARVIS_HELPER_LLM_MAX_TOKENS": "900",
            "JARVIS_HELPER_LLM_TIMEOUT_SECONDS": "45",
            "TASK_MODEL": "cloud-task-model",
        }
    )
    calls = []

    def fake_create(selected, **config):
        calls.append((selected, config))
        return SimpleNamespace(model=config["model"])

    monkeypatch.setattr(llm_provider, "create_provider", fake_create)

    selected, model, _ = llm_provider.create_configured_provider(
        provider_override="helper",
        model_config_keys=("TASK_MODEL",),
        mode="local",
    )

    assert selected == "helper"
    assert model == "bigsk1/jarvis-helper:minicpm5-1b-q4_k_m-v1"
    assert calls == [
        (
            "ollama",
            {
                "base_url": "http://127.0.0.1:11434",
                "model": "bigsk1/jarvis-helper:minicpm5-1b-q4_k_m-v1",
                "include_localhost_fallback": False,
                "context_window": 8192,
                "num_gpu": 0,
                "keep_alive": "30m",
                "default_max_tokens": 900,
                "temperature": 0.2,
                "request_timeout": 45,
                "force_no_thinking": True,
                "force_local_daemon": True,
            },
        )
    ]


def test_helper_provider_honors_explicit_diagnostic_model_override(
    monkeypatch,
    configured_values,
):
    configured_values["JARVIS_HELPER_LLM_MODEL"] = "configured-helper"
    monkeypatch.setattr(
        llm_provider,
        "create_provider",
        lambda _selected, **config: SimpleNamespace(model=config["model"]),
    )

    selected, model, _ = llm_provider.create_configured_provider(
        provider_override="helper",
        model_override="benchmark-helper",
        mode="cloud",
    )

    assert selected == "helper"
    assert model == "benchmark-helper"


def test_helper_provider_defaults_to_versioned_registry_model(
    monkeypatch,
    configured_values,
):
    monkeypatch.setattr(
        llm_provider,
        "create_provider",
        lambda _selected, **config: SimpleNamespace(
            model=config["model"],
            base_url=config["base_url"],
        ),
    )

    selected, model, provider = llm_provider.create_configured_provider(
        provider_override="helper",
        mode="cloud",
    )

    assert selected == "helper"
    assert model == "bigsk1/jarvis-helper:minicpm5-1b-q4_k_m-v1"
    assert provider.base_url == "http://ollama.test:11434"


def test_factory_returns_provider_resolved_model(monkeypatch, configured_values):
    monkeypatch.setattr(
        llm_provider,
        "create_provider",
        lambda selected, **config: SimpleNamespace(model="oauth-resolved-model"),
    )

    selected, model, _ = llm_provider.create_configured_provider(
        provider_override="xai",
        model_override="configured-alias",
        mode="cloud",
    )

    assert selected == "xai"
    assert model == "oauth-resolved-model"


def test_task_specific_provider_and_model_keys_win_in_declared_order(
    monkeypatch,
    configured_values,
):
    configured_values.update(
        {
            "TASK_PROVIDER": "anthropic",
            "TASK_MODEL": "task-model",
            "FEEDBACK_PROVIDER": "xai",
            "FEEDBACK_MODEL": "feedback-model",
        }
    )
    calls = []

    def fake_create(selected, **config):
        calls.append((selected, config))
        return SimpleNamespace(model=config["model"])

    monkeypatch.setattr(llm_provider, "create_provider", fake_create)

    selected, model, _ = llm_provider.create_configured_provider(
        provider_config_keys=("TASK_PROVIDER", "FEEDBACK_PROVIDER", "LLM_PROVIDER"),
        model_config_keys=("TASK_MODEL", "FEEDBACK_MODEL"),
        mode="cloud",
    )

    assert selected == "anthropic"
    assert model == "task-model"
    assert calls[0][1]["api_key"] == "anthropic-key"


@pytest.mark.parametrize(
    ("provider_type", "class_name"),
    [("anthropic", "AnthropicProvider"), ("xai", "XAIProvider")],
)
def test_low_level_factory_forwards_explicit_native_search_policy(
    monkeypatch,
    provider_type,
    class_name,
):
    captured = {}

    def fake_provider(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(model=kwargs["model"])

    monkeypatch.setattr(llm_provider, class_name, fake_provider)

    provider = llm_provider.create_provider(
        provider_type,
        api_key="test-key",
        model="test-model",
        enable_search=False,
    )

    assert provider.model == "test-model"
    assert captured["enable_search"] is False
