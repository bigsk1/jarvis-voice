#!/usr/bin/env python3
"""Regression tests for xAI native continuation helpers."""

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator
from router_v2 import LLMRouter, ProviderRouteInput


class _FakeTool:
    name = "weather"

    def to_openai_format(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Weather",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def to_anthropic_format(self):
        return {"name": self.name, "description": "Weather", "input_schema": {"type": "object"}}


class _FakeRegistry:
    tools = {"weather": _FakeTool()}

    def find_tools(self, *_args, **_kwargs):
        return [_FakeTool()]

    def get_tool(self, name):
        return self.tools.get(name)


class _RecordingProvider:
    model = "grok-test"

    def __init__(self):
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return None, {
            "name": "weather",
            "arguments": {"location": "Portland"},
            "response_id": "resp_1",
            "tool_call_id": "call_1",
        }, {"input_tokens": 1, "output_tokens": 1}, None


def _config(values):
    def fake_get_config_value(key, default=None):
        return values.get(key, default)
    return fake_get_config_value


class XAINativeContinuationTests(unittest.TestCase):
    def _orch(self, config: dict | None = None):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch.router = SimpleNamespace(
            provider_type="xai",
            model_name="grok-test",
            provider=SimpleNamespace(enable_search=True, xai_client=object()),
        )
        orch.auto_context_window = 1
        orch.auto_context_minutes = 1
        return orch

    def test_structural_route_input_sends_tool_message_without_system_prompt(self):
        orch = self._orch()
        with patch("orchestrator_v2.get_config_value", side_effect=_config({
            "XAI_SEARCH": "true",
            "XAI_STORE_MESSAGES": "true",
            "XAI_NATIVE_CONTINUATION": "true",
            "XAI_CONTINUATION_CONTEXT_MODE": "structural",
            "XAI_CONTINUATION_DELTA_MESSAGE": "false",
            "XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS": "25",
        })):
            payload = orch._build_xai_structural_route_input(
                retrieval_query="weather in Portland",
                continuation={
                    "response_id": "resp_1",
                    "tool_call_id": "call_1",
                    "result_message": "Jarvis tool result\nResult: ok",
                },
            )

        self.assertIsInstance(payload, ProviderRouteInput)
        self.assertIsNone(payload.system_prompt)
        self.assertEqual(payload.previous_response_id, "resp_1")
        self.assertEqual(payload.messages[0]["role"], "tool")
        self.assertEqual(payload.messages[0]["tool_call_id"], "call_1")
        self.assertEqual(payload.continuation_mode, "stored_structural")

    def test_continuation_validation_defaults_off(self):
        orch = self._orch()
        with patch("orchestrator_v2.get_config_value", side_effect=_config({
            "XAI_STORE_MESSAGES": "false",
            "XAI_NATIVE_CONTINUATION": "false",
        })):
            self.assertEqual(orch._xai_continuation_fallback_reason({}), "disabled")

    def test_continuation_validation_requires_sdk_search_path(self):
        orch = self._orch()
        orch.router.provider.enable_search = False
        with patch("orchestrator_v2.get_config_value", side_effect=_config({
            "XAI_SEARCH": "false",
            "XAI_STORE_MESSAGES": "true",
            "XAI_NATIVE_CONTINUATION": "true",
            "XAI_CONTINUATION_CONTEXT_MODE": "structural",
        })):
            self.assertEqual(orch._xai_continuation_fallback_reason({}), "disabled")

    def test_continuation_validation_rejects_stale_or_wrong_model(self):
        orch = self._orch()
        old = (datetime.now(orch.timezone) - timedelta(days=30)).isoformat()
        base = {
            "provider": "xai",
            "response_id": "resp_1",
            "tool_call_id": "call_1",
            "model": "grok-test",
            "response_created_at_iso": old,
            "result_message": "result",
        }
        with patch("orchestrator_v2.get_config_value", side_effect=_config({
            "XAI_SEARCH": "true",
            "XAI_STORE_MESSAGES": "true",
            "XAI_NATIVE_CONTINUATION": "true",
            "XAI_CONTINUATION_CONTEXT_MODE": "structural",
            "XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS": "25",
        })):
            self.assertEqual(orch._xai_continuation_fallback_reason(base), "response_id_expired")
            wrong_model = {**base, "response_created_at_iso": datetime.now(orch.timezone).isoformat(), "model": "other"}
            self.assertEqual(orch._xai_continuation_fallback_reason(wrong_model), "model_mismatch")

    def test_provider_result_serializer_truncates_and_preserves_handles(self):
        orch = self._orch()
        result = {
            "ok": True,
            "speech": "Created image",
            "data": {
                "filename": "image.png",
                "image_url": "https://example.com/image.png",
                "content": "x" * 5000,
            },
        }
        text, meta = orch._get_context_assembler().build_provider_tool_result_message(
            tool_name="generate_image",
            arguments={"prompt": "cat", "image_id": "img_123"},
            result=result,
            tool_call_id="call_1",
            duration_ms=123,
            max_chars=1200,
        )

        self.assertLessEqual(len(text), 1200)
        self.assertIn("image.png", text)
        self.assertIn("https://example.com/image.png", text)
        self.assertIn("call_1", text)
        self.assertTrue(meta["result_truncated"])
        result_json = text.split("Result:\n", 1)[1]
        self.assertIsInstance(json.loads(result_json), dict)

    def test_router_uses_retrieval_query_separately_from_provider_messages(self):
        provider = _RecordingProvider()
        router = LLMRouter.__new__(LLMRouter)
        router.mode = "cloud"
        router.registry = _FakeRegistry()
        router.provider = provider
        router.provider_type = "xai"
        router.model_name = "grok-test"
        router.timezone = ZoneInfo("America/Los_Angeles")
        router.prompt_override = None
        router._system_prompt_base = "system"
        router._provider_override = None
        router._model_override = None

        route_input = ProviderRouteInput(
            tool_retrieval_query="weather in Portland",
            messages=[{"role": "tool", "content": "very large tool result body", "tool_call_id": "call_1"}],
            system_prompt=None,
            previous_response_id="resp_1",
            continuation_mode="stored_structural",
        )
        with patch("router_v2.get_bool", return_value=False), \
             patch("router_v2.get_config_value", return_value=""), \
             patch("router_v2.should_enable_thinking", return_value=False, create=True):
            result = router.route(route_input)

        self.assertEqual(result["intent"], "tool")
        self.assertEqual(provider.calls[0]["messages"], route_input.messages)
        self.assertIsNone(provider.calls[0]["system_prompt"])
        self.assertEqual(provider.calls[0]["previous_response_id"], "resp_1")
        self.assertEqual(result["xai_continuation_mode"], "stored_structural")

    def test_router_system_prompt_includes_default_postal_code(self):
        router = LLMRouter.__new__(LLMRouter)
        router.timezone = ZoneInfo("America/Los_Angeles")
        router.prompt_override = None
        router._system_prompt_base = "system"
        router._provider_override = None
        router._model_override = None

        with patch("router_v2.get_config_value", side_effect=_config({
            "JARVIS_DEFAULT_LOCATION": "Portland, Oregon",
            "JARVIS_DEFAULT_POSTAL_CODE": "97201",
        })):
            prompt = router.system_prompt

        self.assertIn('use: "Portland, Oregon"', prompt)
        self.assertIn('Configured default postal/ZIP code for tools that require one: "97201"', prompt)
        self.assertIn("Use the postal/ZIP code only for tools or APIs", prompt)
        self.assertTrue(prompt.startswith("system"))
        self.assertLess(prompt.index("system"), prompt.index("RUNTIME CONTEXT FOR THIS TURN"))
        self.assertLess(prompt.index("system"), prompt.index("CURRENT DATE AND TIME"))


if __name__ == "__main__":
    unittest.main()
