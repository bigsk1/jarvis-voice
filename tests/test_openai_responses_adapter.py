#!/usr/bin/env python3
"""Unit tests for lib/openai_responses_adapter helpers."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib import openai_responses_adapter as ora  # noqa: E402
from lib.llm_provider import OpenAIProvider  # noqa: E402
from lib.model_prompt_overrides import ModelThinkingOverride  # noqa: E402


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def tearDown(self) -> None:
        keys = (
            "OPENAI_API_MODE",
            "OPENAI_RESPONSES_TOOLS",
            "OPENAI_RESPONSES_PARALLEL_TOOL_CALLS",
            "OPENAI_RESPONSES_SERVER_SIDE_TOOLS",
            "OPENAI_RESPONSES_DISABLE_SERVER_SIDE_TOOLS",
            "OPENAI_RESPONSES_WEB_SEARCH",
            "OPENAI_RESPONSES_CODE_INTERPRETER",
        )
        for k in keys:
            os.environ.pop(k, None)

    def test_chat_tools_to_responses_tools_flattens(self) -> None:
        converted = ora.chat_tools_to_responses_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "example_tool",
                        "description": "d",
                        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                    },
                }
            ]
        )
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["type"], "function")
        self.assertEqual(converted[0]["name"], "example_tool")
        self.assertEqual(converted[0]["strict"], False)

    def test_openai_provider_responses_gate_uses_keyword_tools_argument(self) -> None:
        os.environ["OPENAI_API_MODE"] = "responses"
        os.environ["OPENAI_RESPONSES_TOOLS"] = "true"
        provider = OpenAIProvider.__new__(OpenAIProvider)

        tool_spec = {
            "type": "function",
            "function": {
                "name": "example_tool",
                "description": "Example",
                "parameters": {"type": "object", "properties": {}},
            },
        }

        with mock.patch.object(
            provider,
            "_openai_chat_with_tools_responses",
            return_value=("ok", None, {}, None),
        ) as responses_call:
            result = provider.chat_with_tools(
                messages=[{"role": "user", "content": "sample routing request"}],
                tools=[tool_spec],
                system_prompt="route tools when needed",
            )

        self.assertEqual(result, ("ok", None, {}, None))
        responses_call.assert_called_once()

    def test_model_profile_allows_generic_effort_for_future_model(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "future-openai-reasoner"
        profile = ModelThinkingOverride(
            supported=True,
            disable_supported=False,
            levels=("low", "high", "max"),
            default_level="max",
            disabled_fallback_level="low",
        )

        with (
            mock.patch.dict(os.environ, {"JARVIS_THINKING_EFFORT": "high"}, clear=True),
            mock.patch.object(provider, "_model_thinking_profile", return_value=profile),
        ):
            self.assertEqual(provider._openai_reasoning_effort(), "high")

    def test_catalog_profile_preserves_openai_default_for_auto(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-5.6-sol"

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(provider._openai_reasoning_effort())

    def test_auto_allows_legacy_openai_effort_fallback(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-5.5"

        with mock.patch.dict(
            os.environ,
            {
                "JARVIS_THINKING_EFFORT": "auto",
                "OPENAI_REASONING_EFFORT": "high",
            },
            clear=True,
        ):
            self.assertEqual(provider._openai_reasoning_effort(), "high")

    def test_catalog_profiles_map_none_per_selected_openai_model(self) -> None:
        modern = OpenAIProvider.__new__(OpenAIProvider)
        modern.model = "gpt-5.4"
        original = OpenAIProvider.__new__(OpenAIProvider)
        original.model = "gpt-5-mini"

        with mock.patch.dict(
            os.environ,
            {"JARVIS_THINKING_EFFORT": "off"},
            clear=True,
        ):
            self.assertEqual(modern._openai_reasoning_effort(), "none")
            self.assertEqual(original._openai_reasoning_effort(), "minimal")

    def test_unsupported_generic_effort_is_omitted(self) -> None:
        cases = (
            ("gpt-5.5", "max"),
            ("gpt-5.6-luna", "minimal"),
            ("gpt-5-mini", "bogus"),
        )

        for model, effort in cases:
            with self.subTest(model=model, effort=effort):
                provider = OpenAIProvider.__new__(OpenAIProvider)
                provider.model = model
                with mock.patch.dict(
                    os.environ,
                    {"JARVIS_THINKING_EFFORT": effort},
                    clear=True,
                ):
                    self.assertIsNone(provider._openai_reasoning_effort())

    def test_invalid_generic_effort_does_not_fall_back_to_valid_legacy_value(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-5.5"

        with mock.patch.dict(
            os.environ,
            {
                "JARVIS_THINKING_EFFORT": "max",
                "OPENAI_REASONING_EFFORT": "high",
            },
            clear=True,
        ):
            self.assertIsNone(provider._openai_reasoning_effort())

    def test_gpt_5_4_mini_tool_skip_remains_chat_only(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-5.4-mini"

        with mock.patch.dict(
            os.environ,
            {"JARVIS_THINKING_EFFORT": "high"},
            clear=True,
        ):
            self.assertIsNone(
                provider._openai_reasoning_effort(
                    uses_tools=True,
                    use_responses_path=False,
                )
            )
            self.assertEqual(
                provider._openai_reasoning_effort(
                    uses_tools=True,
                    use_responses_path=True,
                ),
                "high",
            )

    def test_yaml_thinking_profile_wins_over_openai_catalog_profile(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.model = "gpt-5.6-sol"
        yaml_profile = ModelThinkingOverride(
            supported=True,
            disable_supported=False,
            levels=("low", "high"),
            default_level="low",
            disabled_fallback_level="low",
        )

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(
                "model_prompt_overrides.load_model_prompt_override",
                return_value=SimpleNamespace(thinking=yaml_profile),
            ),
        ):
            selected = provider._model_thinking_profile("openai")
            resolved = provider._resolve_model_thinking("openai", show_trace=True)

        self.assertIs(selected, yaml_profile)
        self.assertEqual(selected.levels, ("low", "high"))
        self.assertEqual(selected.default_level, "low")
        self.assertEqual(resolved.value, "low")
        self.assertEqual(resolved.source, "profile_default")

        # OpenAI production requests keep ``auto`` as omission even when YAML
        # declares a trace-visible default, but an explicit effort is resolved
        # against the YAML profile rather than the broader catalog profile.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(provider._openai_reasoning_effort())
        with mock.patch.dict(
            os.environ,
            {"JARVIS_THINKING_EFFORT": "high"},
            clear=True,
        ):
            self.assertEqual(provider._openai_reasoning_effort(), "high")

    def test_parse_responses_result_text_from_message_blocks(self) -> None:
        out_msg = SimpleNamespace(
            type="message",
            content=[
                SimpleNamespace(type="output_text", text="Hello from responses."),
            ],
        )
        resp = SimpleNamespace(id="resp_123", output=[out_msg], usage=None)
        text, tool, usage, srv = ora.parse_responses_result(
            resp, model="gpt-4o-mini", parallel_tool_calls_allowed=False
        )
        self.assertEqual(text, "Hello from responses.")
        self.assertIsNone(tool)
        self.assertDictEqual(srv, {})

    def test_parse_responses_function_call_and_multiple_parallel_guard(self) -> None:
        fc1 = SimpleNamespace(
            type="function_call",
            call_id="call_a",
            name="crypto_price",
            arguments=json.dumps({"coin": "btc"}),
        )
        fc2 = SimpleNamespace(
            type="function_call",
            call_id="call_b",
            name="weather",
            arguments=json.dumps({"location": "NYC"}),
        )
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            reasoning_tokens=1,
            input_tokens_details=SimpleNamespace(cached_tokens=2),
        )
        resp = SimpleNamespace(id="resp_abc", output=[fc1, fc2], usage=usage)
        text, tool, usage_info, srv = ora.parse_responses_result(
            resp,
            model="gpt-4o-mini",
            parallel_tool_calls_allowed=False,
        )
        self.assertIsNone(text)
        self.assertIsNotNone(tool)
        self.assertEqual(tool["name"], "crypto_price")
        self.assertEqual(tool["arguments"], {"coin": "btc"})
        self.assertEqual(tool["tool_call_id"], "call_a")
        self.assertEqual(tool["response_id"], "resp_abc")
        self.assertEqual(usage_info.get("reasoning_tokens"), 1)
        self.assertEqual(usage_info.get("cached_input_tokens"), 2)
        self.assertEqual(usage_info.get("cached_prompt_text_tokens"), 2)
        self.assertEqual(usage_info.get("cache_read_tokens"), 2)

    def test_accumulate_web_search_calls(self) -> None:
        item = SimpleNamespace(type="web_search_call")
        self.assertDictEqual(
            ora.accumulate_server_side_from_output([item]),
            {"SERVER_SIDE_TOOL_WEB_SEARCH": 1},
        )

    def test_builtin_tools_respect_transient_disable_flag(self) -> None:
        os.environ["OPENAI_RESPONSES_SERVER_SIDE_TOOLS"] = "true"
        os.environ["OPENAI_RESPONSES_WEB_SEARCH"] = "true"
        self.assertEqual(ora.build_openai_builtin_responses_tools()[0]["type"], "web_search")

        os.environ["OPENAI_RESPONSES_DISABLE_SERVER_SIDE_TOOLS"] = "true"
        self.assertEqual(ora.build_openai_builtin_responses_tools(), [])

    def test_code_interpreter_uses_auto_container_shape(self) -> None:
        os.environ["OPENAI_RESPONSES_SERVER_SIDE_TOOLS"] = "true"
        os.environ["OPENAI_RESPONSES_CODE_INTERPRETER"] = "true"

        def cfg(key: str, default: str = "") -> str:
            return "4g" if key == "OPENAI_RESPONSES_CODE_INTERPRETER_MEMORY_LIMIT" else str(default)

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            tools = ora.build_openai_builtin_responses_tools()

        self.assertEqual(
            tools,
            [{"type": "code_interpreter", "container": {"type": "auto", "memory_limit": "4g"}}],
        )

    def test_parse_responses_reasoning_tokens_from_output_details(self) -> None:
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=3),
        )
        resp = SimpleNamespace(id="resp_123", output=[], output_text="Done", usage=usage)
        _text, _tool, usage_info, _srv = ora.parse_responses_result(
            resp, model="gpt-4o-mini", parallel_tool_calls_allowed=False
        )
        self.assertEqual(usage_info.get("reasoning_tokens"), 3)
        self.assertEqual(usage_info.get("cached_input_tokens"), 0)


class OpenAIPromptCacheKeyTests(unittest.TestCase):
    def test_explicit_cache_key_wins(self) -> None:
        p = OpenAIProvider.__new__(OpenAIProvider)
        p._openai_api_key_material = "k"

        def cfg(key: str, default: str = "") -> str:
            return "my-stable-key" if key == "OPENAI_PROMPT_CACHE_KEY" else str(default)

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            with mock.patch("config_loader.get_bool", return_value=True):
                self.assertEqual(p._openai_prompt_cache_key_for_responses(), "my-stable-key")

    def test_explicit_cache_key_truncates_to_256(self) -> None:
        p = OpenAIProvider.__new__(OpenAIProvider)
        p._openai_api_key_material = "k"
        long_key = "x" * 300

        def cfg(key: str, default: str = "") -> str:
            return long_key if key == "OPENAI_PROMPT_CACHE_KEY" else str(default)

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            with mock.patch("config_loader.get_bool", return_value=True):
                out = p._openai_prompt_cache_key_for_responses()

        self.assertEqual(len(out), 256)

    def test_derived_disabled_returns_none(self) -> None:
        p = OpenAIProvider.__new__(OpenAIProvider)
        p._openai_api_key_material = "secret"

        def cfg(key: str, default: str = "") -> str:
            return "" if key == "OPENAI_PROMPT_CACHE_KEY" else str(default)

        def gb(key: str, default: bool = False) -> bool:
            return False if key == "OPENAI_PROMPT_CACHE_ENABLED" else default

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            with mock.patch("config_loader.get_bool", side_effect=gb):
                self.assertIsNone(p._openai_prompt_cache_key_for_responses())

    def test_derived_key_stable(self) -> None:
        p = OpenAIProvider.__new__(OpenAIProvider)
        p._openai_api_key_material = "secret-material"

        defaults = {
            "OPENAI_PROMPT_CACHE_KEY": "",
            "OPENAI_PROMPT_CACHE_NAMESPACE": "jarvis-test",
        }

        def cfg(key: str, default: str = "") -> str:
            return str(defaults[key]) if key in defaults else str(default)

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            with mock.patch("config_loader.get_bool", return_value=True):
                a = p._openai_prompt_cache_key_for_responses()
                b = p._openai_prompt_cache_key_for_responses()
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("jarvis_router_"))

    def test_retention_normalized(self) -> None:
        def cfg(key: str, default: str = "") -> str:
            return " 24 H " if key == "OPENAI_PROMPT_CACHE_RETENTION" else str(default)

        with mock.patch("config_loader.get_config_value", side_effect=cfg):
            self.assertEqual(
                OpenAIProvider._openai_prompt_cache_retention_for_responses(),
                "24h",
            )


if __name__ == "__main__":
    unittest.main()
