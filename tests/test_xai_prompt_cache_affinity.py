#!/usr/bin/env python3
"""Regression tests for xAI prompt-cache affinity wiring."""

import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from llm_provider import XAIProvider


class _FakeCompletions:
    def __init__(self, usage=None):
        self.last_kwargs = None
        self.usage = usage

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                )
            ],
            usage=self.usage,
        )


class XAIPromptCacheAffinityTests(unittest.TestCase):
    def _provider_shell(self, api_key: str = "xai-test-key") -> XAIProvider:
        provider = XAIProvider.__new__(XAIProvider)
        provider.api_key = api_key
        provider.model = "grok-test"
        provider.is_reasoning_model = False
        return provider

    def test_explicit_prompt_cache_key_wins(self):
        provider = self._provider_shell()
        with patch.dict(os.environ, {"XAI_PROMPT_CACHE_KEY": "conv_explicit"}, clear=True):
            self.assertEqual(provider._xai_prompt_cache_key(), "conv_explicit")
            self.assertEqual(provider._xai_chat_extra_headers(), {"x-grok-conv-id": "conv_explicit"})
            self.assertEqual(provider._xai_sdk_metadata(), (("x-grok-conv-id", "conv_explicit"),))

    def test_prompt_cache_key_defaults_to_stable_hashed_namespace(self):
        provider = self._provider_shell(api_key="xai-super-secret")
        with patch.dict(os.environ, {}, clear=True):
            first = provider._xai_prompt_cache_key()
            second = provider._xai_prompt_cache_key()

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("jarvis_"))
        self.assertNotIn("secret", first)

    def test_prompt_cache_can_be_disabled(self):
        provider = self._provider_shell()
        with patch.dict(os.environ, {"XAI_PROMPT_CACHE_ENABLED": "false"}, clear=True):
            self.assertIsNone(provider._xai_prompt_cache_key())
            self.assertIsNone(provider._xai_chat_extra_headers())
            self.assertIsNone(provider._xai_sdk_metadata())

    def test_chat_completions_path_sends_x_grok_conv_id_header(self):
        provider = self._provider_shell()
        completions = _FakeCompletions()
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch.dict(os.environ, {"XAI_PROMPT_CACHE_KEY": "conv_chat"}, clear=True):
            text, tool_call, usage, thinking = provider._chat_with_tools_openai_sdk(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                system_prompt="system",
            )

        self.assertEqual(text, "ok")
        self.assertIsNone(tool_call)
        self.assertIsNone(usage)
        self.assertIsNone(thinking)
        self.assertEqual(completions.last_kwargs["extra_headers"], {"x-grok-conv-id": "conv_chat"})

    def test_grok_43_reasoning_effort_is_sent_to_chat_completions(self):
        provider = self._provider_shell()
        provider.model = "grok-4.3"
        completions = _FakeCompletions()
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "low"}, clear=True):
            text, tool_call, usage, thinking = provider._chat_with_tools_openai_sdk(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                system_prompt="system",
            )

        self.assertEqual(text, "ok")
        self.assertIsNone(tool_call)
        self.assertIsNone(usage)
        self.assertIsNone(thinking)
        self.assertEqual(completions.last_kwargs["reasoning_effort"], "low")

    def test_grok_43_reasoning_effort_none_is_sent_to_chat_completions(self):
        provider = self._provider_shell()
        provider.model = "grok-4.3"
        completions = _FakeCompletions()
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "none"}, clear=True):
            text, tool_call, usage, thinking = provider._chat_with_tools_openai_sdk(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                system_prompt="system",
            )

        self.assertEqual(text, "ok")
        self.assertIsNone(tool_call)
        self.assertIsNone(thinking)
        self.assertEqual(completions.last_kwargs["reasoning_effort"], "none")

    def test_chat_completions_path_exposes_xai_cached_tokens(self):
        provider = self._provider_shell()
        completions = _FakeCompletions(
            usage=SimpleNamespace(
                prompt_tokens=13650,
                completion_tokens=42,
                prompt_tokens_details=SimpleNamespace(
                    text_tokens=13650,
                    cached_tokens=0,
                ),
            )
        )
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        text, tool_call, usage, thinking = provider._chat_with_tools_openai_sdk(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            system_prompt="system",
        )

        self.assertEqual(text, "ok")
        self.assertIsNone(tool_call)
        self.assertIsNone(thinking)
        self.assertEqual(usage["prompt_text_tokens"], 13650)
        self.assertEqual(usage["cached_prompt_text_tokens"], 0)
        self.assertEqual(usage["cache_read_tokens"], 0)

    def test_xai_sdk_usage_exposes_zero_cached_tokens(self):
        provider = self._provider_shell()
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_text_tokens=13650,
                completion_tokens=42,
                cached_prompt_text_tokens=0,
            )
        )

        usage = provider._extract_xai_sdk_usage(response)

        self.assertEqual(usage["prompt_text_tokens"], 13650)
        self.assertEqual(usage["cached_prompt_text_tokens"], 0)
        self.assertEqual(usage["cache_read_tokens"], 0)

    def test_reasoning_effort_is_only_for_grok_43_family(self):
        provider = self._provider_shell()
        provider.model = "grok-4.3-latest"

        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "high"}, clear=True):
            self.assertEqual(provider._xai_reasoning_effort(), "high")
            self.assertEqual(
                provider._xai_sdk_create_kwargs(tools=[])["reasoning_effort"],
                "high",
            )

        provider.model = "grok-4.20-reasoning"
        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "high"}, clear=True):
            self.assertIsNone(provider._xai_reasoning_effort())
            self.assertNotIn("reasoning_effort", provider._xai_sdk_create_kwargs(tools=[]))

        provider.model = "grok-build-0.1"
        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "low"}, clear=True):
            self.assertIsNone(provider._xai_reasoning_effort())
            self.assertNotIn("reasoning_effort", provider._xai_sdk_create_kwargs(tools=[]))

        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "xhigh"}, clear=True):
            self.assertIsNone(provider._xai_reasoning_effort())

    def test_xai_sdk_create_kwargs_passes_none_and_medium_strings(self):
        provider = self._provider_shell()
        provider.model = "grok-4.3"
        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "none"}, clear=True):
            self.assertEqual(provider._xai_sdk_create_kwargs(tools=[])["reasoning_effort"], "none")
        with patch.dict(os.environ, {"XAI_REASONING_EFFORT": "medium"}, clear=True):
            self.assertEqual(provider._xai_sdk_create_kwargs(tools=[])["reasoning_effort"], "medium")

    def test_xai_reasoning_model_detection_does_not_match_non_reasoning(self):
        self.assertTrue(XAIProvider._xai_model_is_reasoning("grok-4.3"))
        self.assertTrue(XAIProvider._xai_model_is_reasoning("grok-4.20-reasoning"))
        self.assertFalse(XAIProvider._xai_model_is_reasoning("grok-4.20-non-reasoning"))
        self.assertFalse(XAIProvider._xai_model_is_reasoning("grok-4.20-non-reasoning-latest"))

    def test_xai_provider_default_model_comes_from_catalog(self):
        with patch("config_loader.get_config_value", return_value="false"):
            provider = XAIProvider(api_key="xai-test-key")

        self.assertEqual(provider.model, "grok-4.3")

    def test_xai_sdk_client_init_receives_grok_conv_id_metadata(self):
        calls = []

        class FakeXAIClient:
            def __init__(self, **kwargs):
                calls.append(kwargs)

        fake_xai_sdk = types.ModuleType("xai_sdk")
        fake_xai_sdk.Client = FakeXAIClient

        with patch.dict(sys.modules, {"xai_sdk": fake_xai_sdk}), \
             patch("config_loader.get_config_value", return_value="true"), \
             patch.dict(os.environ, {"XAI_PROMPT_CACHE_KEY": "conv_sdk"}, clear=True):
            provider = XAIProvider(api_key="xai-test-key", model="grok-test")

        self.assertTrue(provider.enable_search)
        self.assertIsInstance(provider.xai_client, FakeXAIClient)
        self.assertEqual(calls[0]["metadata"], (("x-grok-conv-id", "conv_sdk"),))


if __name__ == "__main__":
    unittest.main()
