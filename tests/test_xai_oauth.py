#!/usr/bin/env python3
"""Regression coverage for Grok CLI OAuth authentication."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import xai_oauth  # noqa: E402
import feedback  # noqa: E402
from llm_provider import XAIProvider  # noqa: E402
from status_llm import StatusSummarizer  # noqa: E402


def _write_auth(path: Path, *, mode: int = 0o600, expires_at: str = "2099-01-01T00:00:00Z"):
    path.write_text(json.dumps({
        "https://auth.x.ai::account-id": {
            "key": "private-bearer-token",
            "refresh_token": "private-refresh-token",
            "expires_at": expires_at,
        }
    }))
    path.chmod(mode)


def test_oauth_auth_file_requires_owner_only_permissions(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, mode=0o644)

    with pytest.raises(xai_oauth.XaiOAuthError, match="chmod 600"):
        xai_oauth.load_xai_oauth_credentials(auth_file)


def test_oauth_status_never_exposes_tokens(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)

    with (
        patch.object(xai_oauth, "get_xai_oauth_auth_file", return_value=auth_file),
        patch.object(xai_oauth, "get_grok_cli_version", return_value="0.2.82"),
    ):
        status = xai_oauth.get_xai_oauth_status()

    serialized = json.dumps(status)
    assert status["signed_in"] is True
    assert status["connection"] == "oauth"
    assert "private-bearer-token" not in serialized
    assert "private-refresh-token" not in serialized


def test_auth_mode_auto_prefers_key_then_oauth():
    with patch.object(xai_oauth, "_config_value", return_value="auto"):
        assert xai_oauth.get_xai_auth_mode("xai-key") == "api_key"
        assert xai_oauth.get_xai_auth_mode("") == "oauth"
    assert xai_oauth.get_xai_auth_mode("xai-key", "oauth") == "oauth"


def test_expired_session_refresh_is_delegated_to_cli(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, expires_at="2000-01-01T00:00:00Z")
    expired = xai_oauth.load_xai_oauth_credentials(auth_file, allow_expired=True)
    refreshed = xai_oauth.XaiOAuthCredentials(
        token="new-private-token",
        account_id="account-id",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        auth_file=auth_file,
        mtime_ns=auth_file.stat().st_mtime_ns,
    )
    with (
        patch.object(xai_oauth, "load_xai_oauth_credentials", return_value=expired),
        patch.object(xai_oauth, "refresh_xai_oauth_credentials", return_value=refreshed) as refresh,
    ):
        result = xai_oauth.get_fresh_xai_oauth_credentials()

    assert result is refreshed
    refresh.assert_called_once_with()


def test_model_discovery_filters_coding_agent_models():
    output = """You are logged in with grok.com.
Default model: grok-composer-2.5-fast

Available models:
  * grok-composer-2.5-fast (default)
  - grok-build
"""
    result = subprocess.CompletedProcess(["grok", "models"], 0, stdout=output, stderr="")
    xai_oauth._MODEL_CACHE = None
    with (
        patch.object(xai_oauth, "get_grok_cli_path", return_value="/usr/bin/grok"),
        patch.object(xai_oauth.subprocess, "run", return_value=result),
    ):
        models = xai_oauth.discover_xai_oauth_models(use_cache=False)

    assert [model["id"] for model in models] == ["grok-build"]
    assert models[0]["context"] == "256K"
    assert models[0]["auth"] == "oauth"
    assert xai_oauth.get_xai_oauth_model("grok-build-0.1") == "grok-build"


def test_operator_can_allow_new_advertised_chat_model_without_code_change():
    output = """Available models:
  * grok-composer-2.5-fast (default)
  - grok-build
  - grok-next-chat
"""
    result = subprocess.CompletedProcess(["grok", "models"], 0, stdout=output, stderr="")

    def config_value(name, default=""):
        return {
            "XAI_OAUTH_ALLOWED_MODELS": "grok-build,grok-next-chat,grok-composer-2.5-fast",
            "XAI_OAUTH_MODEL": "grok-next-chat",
        }.get(name, default)

    xai_oauth._MODEL_CACHE = None
    with (
        patch.object(xai_oauth, "_config_value", side_effect=config_value),
        patch.object(xai_oauth, "get_grok_cli_path", return_value="/usr/bin/grok"),
        patch.object(xai_oauth.subprocess, "run", return_value=result),
    ):
        models = xai_oauth.discover_xai_oauth_models(use_cache=False)

    assert [model["id"] for model in models] == ["grok-build", "grok-next-chat"]


def test_native_search_config_requires_api_key_auth():
    def oauth_config(name, default=""):
        return {
            "XAI_SEARCH": "true",
            "XAI_AUTH_MODE": "oauth",
            "XAI_API_KEY": "configured-but-ignored",
        }.get(name, default)

    with patch.object(xai_oauth, "_config_value", side_effect=oauth_config):
        assert xai_oauth.xai_native_search_configured("configured-but-ignored") is False

    def api_config(name, default=""):
        return {
            "XAI_SEARCH": "true",
            "XAI_AUTH_MODE": "api_key",
            "XAI_API_KEY": "configured",
        }.get(name, default)

    with patch.object(xai_oauth, "_config_value", side_effect=api_config):
        assert xai_oauth.xai_native_search_configured("configured") is True


def test_feedback_does_not_claim_native_search_for_oauth():
    def feedback_config(name, default=""):
        return {
            "LLM_PROVIDER": "xai",
            "XAI_API_KEY": "configured-but-ignored",
        }.get(name, default)

    with (
        patch.object(feedback, "get_config_value", side_effect=feedback_config),
        patch.object(xai_oauth, "xai_native_search_configured", return_value=False),
    ):
        assert feedback._feedback_native_search_enabled({}, None) is False

    assert feedback._feedback_native_search_enabled(
        {"SERVER_SIDE_TOOL_WEB_SEARCH": 1},
        None,
    ) is True


class _FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(function=SimpleNamespace(
                    name="weather",
                    arguments='{"location":"Portland"}',
                ))],
            ))],
            usage=SimpleNamespace(
                prompt_tokens=200,
                completion_tokens=10,
                total_tokens=400,
                prompt_tokens_details=SimpleNamespace(text_tokens=200, cached_tokens=128),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=190),
            ),
        )


class _FakeOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions())
        self.instances.append(self)


def test_provider_uses_oauth_proxy_and_subscription_usage(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    credentials = xai_oauth.XaiOAuthCredentials(
        token="private-bearer-token",
        account_id="account-id",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        auth_file=auth_file,
        mtime_ns=auth_file.stat().st_mtime_ns,
    )
    fake_openai_module = SimpleNamespace(OpenAI=_FakeOpenAI)

    with (
        patch.dict(sys.modules, {"openai": fake_openai_module}),
        patch.object(xai_oauth, "get_fresh_xai_oauth_credentials", return_value=credentials),
        patch.object(xai_oauth, "get_grok_cli_version", return_value="0.2.82"),
        patch.dict(os.environ, {"XAI_SEARCH": "false"}),
    ):
        provider = XAIProvider(
            api_key="api-key-must-not-win",
            model="grok-build-0.1",
            auth_mode="oauth",
        )
        text, tool, usage, thinking = provider.chat_with_tools(
            [{"role": "user", "content": "weather"}],
            [{"type": "function", "function": {
                "name": "weather",
                "parameters": {"type": "object", "properties": {}},
            }}],
        )

    assert provider.model == "grok-build"
    assert provider.auth_mode == "oauth"
    client_kwargs = _FakeOpenAI.instances[-1].kwargs
    assert client_kwargs["api_key"] == "private-bearer-token"
    assert client_kwargs["base_url"] == xai_oauth.XAI_OAUTH_BASE_URL
    assert client_kwargs["default_headers"]["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert client_kwargs["default_headers"]["x-grok-model-override"] == "grok-build"
    assert text is None
    assert tool == {"name": "weather", "arguments": {"location": "Portland"}}
    assert thinking is None
    assert usage["cost_usd"] is None
    assert usage["cost_known"] is False
    assert usage["billing_mode"] == "xai_oauth_subscription"
    assert usage["reasoning_tokens"] == 190
    assert usage["total_tokens"] == 400


def test_status_summarizer_calls_xai_oauth_provider_without_api_key():
    calls = []

    class Provider:
        def chat(self, message, system_prompt=None, max_tokens=None):
            calls.append((message, system_prompt, max_tokens))
            return "Still working through it"

    summarizer = StatusSummarizer.__new__(StatusSummarizer)
    summarizer.enabled = True
    summarizer.provider = "xai"
    summarizer.api_key = None
    summarizer.xai_provider = Provider()
    summarizer.system_prompt = "status system"
    summarizer.max_tokens = 30

    result = summarizer.summarize("Processing records", tool_name="memory")

    assert result == "Still working through it"
    assert len(calls) == 1


def test_oauth_401_refreshes_with_cli_and_retries_once(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    refreshed = xai_oauth.XaiOAuthCredentials(
        token="refreshed-private-token",
        account_id="account-id",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        auth_file=auth_file,
        mtime_ns=auth_file.stat().st_mtime_ns,
    )

    class AuthError(RuntimeError):
        status_code = 401

    class FailingCompletions:
        def create(self, **_kwargs):
            raise AuthError("expired")

    expected = object()

    class SuccessfulCompletions:
        def create(self, **_kwargs):
            return expected

    class RefreshedOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = SimpleNamespace(completions=SuccessfulCompletions())

    provider = XAIProvider.__new__(XAIProvider)
    provider.auth_mode = "oauth"
    provider.model = "grok-build"
    provider.api_key = "expired-private-token"
    provider._oauth_auth_file = None
    provider._oauth_auth_mtime_ns = None
    provider._oauth_cli_version = "0.2.82"
    provider._oauth_account_id = "account-id"
    provider._openai_class = RefreshedOpenAI
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )

    with patch.object(
        xai_oauth,
        "refresh_xai_oauth_credentials",
        return_value=refreshed,
    ) as refresh:
        result = provider._xai_completion_create(model="grok-build", messages=[])

    assert result is expected
    assert provider.api_key == "refreshed-private-token"
    refresh.assert_called_once_with()


def test_stash_summary_uses_xai_oauth_provider(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    credentials = xai_oauth.XaiOAuthCredentials(
        token="private-bearer-token",
        account_id="account-id",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        auth_file=auth_file,
        mtime_ns=auth_file.stat().st_mtime_ns,
    )

    class _FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Archived key facts"))],
                usage=None,
            )

    fake_openai_module = SimpleNamespace(
        OpenAI=lambda **_kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=_FakeCompletions())
        )
    )

    sys.path.insert(0, str(ROOT / "skills"))
    import stash  # noqa: E402

    with (
        patch.dict(sys.modules, {"openai": fake_openai_module}),
        patch.object(xai_oauth, "get_fresh_xai_oauth_credentials", return_value=credentials),
        patch.object(xai_oauth, "get_grok_cli_version", return_value="0.2.82"),
        patch.dict(os.environ, {
            "LLM_PROVIDER": "xai",
            "XAI_AUTH_MODE": "oauth",
            "XAI_API_KEY": "",
            "XAI_SEARCH": "false",
        }),
    ):
        result = stash.summarize_content_with_llm("long article content", "archive.txt")

    assert result == "Archived key facts"


def test_stash_summary_strips_provider_confidence_annotation():
    sys.path.insert(0, str(ROOT / "skills"))
    import stash  # noqa: E402

    provider = SimpleNamespace(
        chat=lambda *_args, **_kwargs: "Archived key facts\n\\confidence{80}"
    )
    with patch(
        "llm_provider.create_configured_provider",
        return_value=("xai", "grok-build", provider),
    ):
        result = stash.summarize_content_with_llm("long article", "archive.txt")

    assert result == "Archived key facts"
