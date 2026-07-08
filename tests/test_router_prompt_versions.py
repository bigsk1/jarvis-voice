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
V2_SHA256 = "2eac90483f6908db2308d1c2cedd79d35cd7e73c70704b4a2ee18a74285dbb90"


def test_v1_is_exact_established_router_prompt_baseline():
    version, prompt = get_router_system_prompt("v1")

    assert version == "v1"
    assert len(prompt) == 31_491
    assert len(prompt.splitlines()) == 417
    assert hashlib.sha256(prompt.encode()).hexdigest() == V1_SHA256


def test_router_prompt_integrity_validation_fails_closed():
    with pytest.raises(RuntimeError, match="Router prompt v1 failed integrity validation"):
        _validate_router_prompts({"v1": ("changed", V1_SHA256)})


def test_v2_removes_only_v1_blank_lines_and_has_its_own_hash():
    _, v1 = get_router_system_prompt("v1")
    version, v2 = get_router_system_prompt("v2")

    assert version == "v2"
    assert v2 == "\n".join(line for line in v1.splitlines() if line.strip())
    assert len(v2) == 31_396
    assert len(v2.splitlines()) == 340
    assert hashlib.sha256(v2.encode()).hexdigest() == V2_SHA256


def test_bad_unselected_experiment_does_not_break_v1(monkeypatch):
    monkeypatch.setitem(router_prompts._ROUTER_PROMPTS, "v2", ("changed", V2_SHA256))

    assert get_router_system_prompt("v1")[0] == "v1"
    with pytest.raises(RuntimeError, match="Router prompt v2 failed integrity validation"):
        get_router_system_prompt("v2")


def test_prompt_selector_defaults_normalizes_and_rejects_unknown_versions():
    assert DEFAULT_ROUTER_PROMPT_VERSION == "v1"
    assert available_router_prompt_versions() == ("v1", "v2")
    assert get_router_system_prompt(None)[0] == "v1"
    assert get_router_system_prompt("  V1  ")[0] == "v1"
    assert get_router_system_prompt("  V2  ")[0] == "v2"

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


def test_web_ui_exposes_and_scopes_router_prompt_override():
    index_html = (ROOT / "jarvis-web" / "client" / "index.html").read_text()
    app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()
    chat_py = (ROOT / "jarvis-web" / "server" / "sockets" / "chat.py").read_text()

    assert 'id="setting-router-prompt-version"' in index_html
    assert "router_prompt_version: document.getElementById('setting-router-prompt-version')" in app_js
    assert "option.textContent = label" in app_js
    assert "'router_prompt_version': 'JARVIS_ROUTER_PROMPT_VERSION'" in chat_py
