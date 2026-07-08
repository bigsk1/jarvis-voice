"""Regression coverage for versioned Jarvis router system prompts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from router_prompt_catalog import (  # noqa: E402
    DEFAULT_ROUTER_PROMPT_VERSION,
    available_router_prompt_versions,
)
from config_loader import get_config_value  # noqa: E402
import router_prompts  # noqa: E402
from router_prompts import _validate_router_prompts, get_router_system_prompt  # noqa: E402
from router_v2 import LLMRouter  # noqa: E402


V1_SHA256 = "6c2ecbb0c032af7f7ffc70b6d093d11e918230e31ef4ddb7bfffadf9f4b4efc1"
V2_SHA256 = "cc3c7a8a8e97dd5923ecebcdd2c4ff8da1a2ad4a15a0d04199c9b31c069fce8d"
V3_SHA256 = "59c7881829f36d4966e1c41996dd5e339e41ecf08ec870958ec03cbd00362fa9"
V4_SHA256 = "56380c054f1dfb891d4a54445cf61113dab944fc10754f63cc56ce15d5c8c12f"


def test_v1_is_exact_established_router_prompt_baseline():
    version, prompt = get_router_system_prompt("v1")

    assert version == "v1"
    assert len(prompt) == 31_491
    assert len(prompt.splitlines()) == 417
    assert hashlib.sha256(prompt.encode()).hexdigest() == V1_SHA256


def test_router_prompt_integrity_validation_fails_closed():
    with pytest.raises(RuntimeError, match="Router prompt v1 failed integrity validation"):
        _validate_router_prompts({"v1": ("changed", V1_SHA256)})


def test_v2_is_compact_standalone_prompt_with_its_own_hash():
    version, v2 = get_router_system_prompt("v2")

    assert version == "v2"
    assert len(v2) == 11_977
    assert len(v2.splitlines()) == 81
    assert len(v2.split()) == 1_676
    assert v2.isascii()
    assert hashlib.sha256(v2.encode()).hexdigest() == V2_SHA256


def test_v3_is_caveman_hybrid_with_normal_output_guard_and_own_hash():
    version, v3 = get_router_system_prompt("v3")

    assert version == "v3"
    assert len(v3) == 8_580
    assert len(v3.splitlines()) == 85
    assert len(v3.split()) == 1_102
    assert v3.isascii()
    assert "NEVER imitate caveman grammar in user-facing answer" in v3
    assert "Speak normal fluent language" in v3
    assert hashlib.sha256(v3.encode()).hexdigest() == V3_SHA256


def test_v4_is_caveman_light_with_normal_output_guard_and_own_hash():
    version, v4 = get_router_system_prompt("v4")

    assert version == "v4"
    assert len(v4) == 8_849
    assert len(v4.splitlines()) == 43
    assert len(v4.split()) == 1_145
    assert "NEVER use caveman grammar in user answers" in v4
    assert "Speak normal fluent English" in v4
    assert hashlib.sha256(v4.encode()).hexdigest() == V4_SHA256


@pytest.mark.parametrize(
    "contract",
    [
        "include_schema=false",
        "mcp_server_name_tool_name",
        "acknowledge_reminders(title_search=",
        "manage_intel with action=append",
        "semantic_recall returns no results, try search_memory once",
        "update replaces the full page",
        "key=how_to_address_user",
        "generate_image stash refs",
        "check_opencode_sessions is fallback-only",
        "~/jarvis-workspace/projects/",
        "Tool confirmations: brief (",
    ],
)
def test_v2_preserves_high_risk_behavioral_contracts(contract):
    _, prompt = get_router_system_prompt("v2")
    # The final response-style limit is supplied by the unchanged runtime
    # overlay, while the other contracts live in the compact static prompt.
    if contract == "Tool confirmations: brief (":
        provider = MagicMock(model="test-model")

        def get_config(key, default=None):
            return {
                "JARVIS_ROUTER_PROMPT_VERSION": "v2",
                "JARVIS_TIMEZONE": "UTC",
                "JARVIS_RESPONSE_STYLE": "casual",
                "LLM_PROVIDER": "openai",
            }.get(key, default)

        with (
            patch("router_v2.load_config"),
            patch("router_v2.get_config_value", side_effect=get_config),
            patch.object(LLMRouter, "_create_provider", return_value=provider),
            patch("router_v2.load_model_prompt_override", return_value=None),
            patch("router_v2.append_profile_card_for_router_direct_answer", side_effect=lambda p: p),
        ):
            prompt = LLMRouter(mode="cloud", registry=MagicMock()).system_prompt
    assert contract in prompt


@pytest.mark.parametrize(
    "contract",
    [
        "Asked configured location/ZIP/timezone: answer injected value directly",
        "Asked current time/date: call get_time",
        "include_schema=false",
        "Never third recall attempt",
        "manage_intel(action=append, path=jarvis-learned-lessons.md, auto_ingest=true)",
        "acknowledge_reminders(title_search=",
        "update replaces full page",
        "key=how_to_address_user",
        "uploaded_image and generate_image stash refs",
        "check_opencode_sessions only when no usable result",
        "~/jarvis-workspace/projects/",
        "tool confirmation <=35 words",
    ],
)
def test_v3_preserves_high_risk_behavioral_contracts(contract):
    _, prompt = get_router_system_prompt("v3")
    assert contract in prompt


@pytest.mark.parametrize(
    "contract",
    [
        "Configured location/ZIP/timezone questions: answer directly from injection",
        "Current time/date: call get_time",
        "include_schema=false",
        "Never third recall attempt",
        "manage_intel(action=append, path=jarvis-learned-lessons.md, auto_ingest=true)",
        "acknowledge_reminders(title_search=",
        "update = full intentional rewrite",
        "key=how_to_address_user",
        "stash_ref from uploaded_image or uploaded_images",
        "check_opencode_sessions only on no usable result",
        "~/jarvis-workspace/projects/",
        "tool confirmations ≤35 words",
    ],
)
def test_v4_preserves_high_risk_behavioral_contracts(contract):
    _, prompt = get_router_system_prompt("v4")
    assert contract in prompt


def test_bad_unselected_experiment_does_not_break_v1(monkeypatch):
    monkeypatch.setitem(router_prompts._ROUTER_PROMPTS, "v2", ("changed", V2_SHA256))

    assert get_router_system_prompt("v1")[0] == "v1"
    with pytest.raises(RuntimeError, match="Router prompt v2 failed integrity validation"):
        get_router_system_prompt("v2")


def test_prompt_selector_defaults_normalizes_and_rejects_unknown_versions():
    assert DEFAULT_ROUTER_PROMPT_VERSION == "v1"
    assert available_router_prompt_versions() == ("v1", "v2", "v3", "v4")
    assert get_router_system_prompt(None)[0] == "v1"
    assert get_router_system_prompt("  V1  ")[0] == "v1"
    assert get_router_system_prompt("  V2  ")[0] == "v2"
    assert get_router_system_prompt("  V3  ")[0] == "v3"
    assert get_router_system_prompt("  V4  ")[0] == "v4"

    with pytest.raises(ValueError, match="Unsupported JARVIS_ROUTER_PROMPT_VERSION 'v9'"):
        get_router_system_prompt("v9")


def test_hash_helper_checks_all_and_refuses_to_rewrite_v1():
    check = subprocess.run(
        [str(ROOT / "bin" / "router-prompt-hash"), "--check-all"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout
    assert "v1: OK" in check.stdout
    assert "v2: OK" in check.stdout
    assert "v3: OK" in check.stdout
    assert "v4: OK" in check.stdout

    rewrite = subprocess.run(
        [str(ROOT / "bin" / "router-prompt-hash"), "v1", "--write"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rewrite.returncode == 2
    assert "Refusing to rewrite immutable v1" in rewrite.stderr


def test_existing_jarvis_override_namespace_can_select_prompt(monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION", "v1")

    assert get_config_value("JARVIS_ROUTER_PROMPT_VERSION", "missing") == "v1"


def test_router_initialization_selects_configured_prompt_version():
    provider = MagicMock(model="test-model")

    def get_config(key, default=None):
        return {
            "JARVIS_ROUTER_PROMPT_VERSION": "v1",
            "JARVIS_TIMEZONE": "UTC",
            "LLM_PROVIDER": "openai",
        }.get(key, default)

    with (
        patch("router_v2.load_config"),
        patch("router_v2.get_config_value", side_effect=get_config),
        patch.object(LLMRouter, "_create_provider", return_value=provider),
        patch("router_v2.load_model_prompt_override", return_value=None),
    ):
        router = LLMRouter(mode="cloud", registry=MagicMock())

    assert router.system_prompt_version == "v1"
    assert hashlib.sha256(router._system_prompt_base.encode()).hexdigest() == V1_SHA256


def test_router_initialization_can_select_v2():
    provider = MagicMock(model="test-model")

    def get_config(key, default=None):
        return {
            "JARVIS_ROUTER_PROMPT_VERSION": "v2",
            "JARVIS_TIMEZONE": "UTC",
            "LLM_PROVIDER": "openai",
        }.get(key, default)

    with (
        patch("router_v2.load_config"),
        patch("router_v2.get_config_value", side_effect=get_config),
        patch.object(LLMRouter, "_create_provider", return_value=provider),
        patch("router_v2.load_model_prompt_override", return_value=None),
    ):
        router = LLMRouter(mode="local", registry=MagicMock())

    assert router.system_prompt_version == "v2"
    assert hashlib.sha256(router._system_prompt_base.encode()).hexdigest() == V2_SHA256


def test_router_initialization_can_select_v3():
    provider = MagicMock(model="test-model")

    def get_config(key, default=None):
        return {
            "JARVIS_ROUTER_PROMPT_VERSION": "v3",
            "JARVIS_TIMEZONE": "UTC",
            "LLM_PROVIDER": "ollama",
        }.get(key, default)

    with (
        patch("router_v2.load_config"),
        patch("router_v2.get_config_value", side_effect=get_config),
        patch.object(LLMRouter, "_create_provider", return_value=provider),
        patch("router_v2.load_model_prompt_override", return_value=None),
    ):
        router = LLMRouter(mode="local", registry=MagicMock())

    assert router.system_prompt_version == "v3"
    assert hashlib.sha256(router._system_prompt_base.encode()).hexdigest() == V3_SHA256


def test_router_initialization_can_select_v4():
    provider = MagicMock(model="test-model")

    def get_config(key, default=None):
        return {
            "JARVIS_ROUTER_PROMPT_VERSION": "v4",
            "JARVIS_TIMEZONE": "UTC",
            "LLM_PROVIDER": "xai",
        }.get(key, default)

    with (
        patch("router_v2.load_config"),
        patch("router_v2.get_config_value", side_effect=get_config),
        patch.object(LLMRouter, "_create_provider", return_value=provider),
        patch("router_v2.load_model_prompt_override", return_value=None),
    ):
        router = LLMRouter(mode="cloud", registry=MagicMock())

    assert router.system_prompt_version == "v4"
    assert hashlib.sha256(router._system_prompt_base.encode()).hexdigest() == V4_SHA256


def test_web_ui_exposes_and_scopes_router_prompt_override():
    index_html = (ROOT / "jarvis-web" / "client" / "index.html").read_text()
    app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()
    chat_py = (ROOT / "jarvis-web" / "server" / "sockets" / "chat.py").read_text()

    assert 'id="setting-router-prompt-version"' in index_html
    assert "router_prompt_version: document.getElementById('setting-router-prompt-version')" in app_js
    assert "option.textContent = label" in app_js
    assert "'router_prompt_version': 'JARVIS_ROUTER_PROMPT_VERSION'" in chat_py
