#!/usr/bin/env python3
"""Regression tests for Anthropic response block handling."""

import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from llm_provider import AnthropicProvider
from model_prompt_overrides import ModelThinkingOverride


class AnthropicBlockHandlingTests(unittest.TestCase):
    def test_web_search_is_direct_when_parallel_tool_use_is_disabled(self):
        captured = {}

        def create(**params):
            captured.update(params)
            return SimpleNamespace(
                usage=None,
                content=[SimpleNamespace(type="text", text="Hello!")],
            )

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-sonnet-5"
        provider.enable_search = True
        provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))

        text, tool_call, usage, thinking = provider.chat_with_tools(
            [{"role": "user", "content": "Hey, how are you?"}],
            [
                {
                    "name": "remember",
                    "description": "Save a fact.",
                    "input_schema": {"type": "object"},
                }
            ],
        )

        web_search = next(
            tool for tool in captured["tools"] if tool.get("name") == "web_search"
        )
        self.assertEqual(web_search["type"], "web_search_20260209")
        self.assertEqual(web_search["allowed_callers"], ["direct"])
        self.assertEqual(
            captured["tool_choice"],
            {"type": "auto", "disable_parallel_tool_use": True},
        )
        self.assertEqual(text, "Hello!")
        self.assertIsNone(tool_call)
        self.assertIsNone(usage)
        self.assertIsNone(thinking)

    def test_tool_requests_disable_parallel_tool_use(self):
        captured = {}

        def create(**params):
            captured.update(params)
            return SimpleNamespace(
                usage=None,
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="remember",
                        input={"fact": "Prefers tea"},
                    )
                ],
            )

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-test"
        provider.enable_search = False
        provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))

        _text, tool_call, _usage, _thinking = provider.chat_with_tools(
            [{"role": "user", "content": "Remember that I prefer tea."}],
            [
                {
                    "name": "remember",
                    "description": "Save a fact.",
                    "input_schema": {"type": "object"},
                }
            ],
        )

        self.assertEqual(
            captured["tool_choice"],
            {"type": "auto", "disable_parallel_tool_use": True},
        )
        self.assertEqual(tool_call["name"], "remember")

    def test_multiple_tool_blocks_warn_and_keep_first_for_sequential_router(self):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-test"
        provider.enable_search = False
        provider.client = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    usage=None,
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="remember",
                            input={"fact": "Prefers tea"},
                        ),
                        SimpleNamespace(
                            type="tool_use",
                            name="calendar",
                            input={"action": "list"},
                        ),
                    ],
                )
            )
        )

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            _text, tool_call, _usage, _thinking = provider.chat_with_tools(
                [{"role": "user", "content": "Remember this and check my calendar."}],
                [
                    {
                        "name": "remember",
                        "description": "Save a fact.",
                        "input_schema": {"type": "object"},
                    },
                    {
                        "name": "calendar",
                        "description": "List calendar events.",
                        "input_schema": {"type": "object"},
                    },
                ],
            )

        self.assertEqual(tool_call["name"], "remember")
        self.assertEqual(tool_call["additional_tool_call_count"], 1)
        self.assertIn("Anthropic returned multiple client-side tool calls", stderr.getvalue())

    @patch.dict("os.environ", {"ANTHROPIC_EFFORT": ""})
    def test_fable_debug_thinking_uses_catalog_adaptive_config(self):
        captured = {}

        def create(**params):
            captured.update(params)
            return SimpleNamespace(
                usage=None,
                content=[
                    SimpleNamespace(type="thinking", thinking="A short summary."),
                    SimpleNamespace(type="text", text="Done"),
                ],
            )

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-fable-5"
        provider.enable_search = False
        provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))

        text, tool_call, usage, thinking = provider.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            [],
            enable_thinking=True,
        )

        self.assertEqual(text, "Done")
        self.assertIsNone(tool_call)
        self.assertEqual(usage["reasoning_effort_sent"], "xhigh")
        self.assertEqual(thinking, "A short summary.")
        self.assertEqual(captured["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertEqual(captured["output_config"], {"effort": "xhigh"})
        self.assertEqual(captured["max_tokens"], 16_384)

    @patch.dict("os.environ", {"JARVIS_THINKING_EFFORT": "low"}, clear=False)
    def test_profile_effort_generates_reasoning_but_keeps_trace_hidden(self):
        captured = {}

        def create(**params):
            captured.update(params)
            return SimpleNamespace(
                usage=None,
                content=[
                    SimpleNamespace(type="thinking", thinking="Private trace."),
                    SimpleNamespace(type="text", text="Done"),
                ],
            )

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-fable-5"
        provider.enable_search = False
        provider.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        profile = ModelThinkingOverride(
            supported=True,
            disable_supported=True,
            levels=("low", "medium", "high", "max", "xhigh"),
            default_level="xhigh",
        )

        with patch.object(provider, "_model_thinking_profile", return_value=profile):
            text, _tool_call, usage, thinking = provider.chat_with_tools(
                [{"role": "user", "content": "hello"}],
                [],
                enable_thinking=False,
            )

        self.assertEqual(text, "Done")
        self.assertEqual(captured["output_config"], {"effort": "low"})
        self.assertEqual(usage["reasoning_effort_sent"], "low")
        self.assertIsNone(thinking)

    def test_collects_all_text_blocks_in_order(self):
        blocks = [
            SimpleNamespace(type="text", text="This feature was "),
            SimpleNamespace(type="text", text="documented just 20 hours ago."),
        ]

        self.assertEqual(
            AnthropicProvider._collect_anthropic_text_blocks(blocks),
            "This feature was documented just 20 hours ago.",
        )

    def test_ignores_non_text_blocks_while_preserving_text(self):
        blocks = [
            SimpleNamespace(type="text", text="First paragraph.\n\n"),
            SimpleNamespace(type="server_tool_use", name="web_search"),
            SimpleNamespace(type="text", text="Second paragraph."),
        ]

        self.assertEqual(
            AnthropicProvider._collect_anthropic_text_blocks(blocks),
            "First paragraph.\n\nSecond paragraph.",
        )

    def test_fable_usage_total_includes_model_aware_cache_creation_cost(self):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-fable-5"
        provider.enable_search = False
        provider.client = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=660,
                        output_tokens=76,
                        cache_creation_input_tokens=24_473,
                        cache_read_input_tokens=0,
                        cache_creation=SimpleNamespace(
                            ephemeral_5m_input_tokens=24_473,
                            ephemeral_1h_input_tokens=0,
                        ),
                        server_tool_use=None,
                    ),
                    content=[SimpleNamespace(type="text", text="Hello")],
                )
            )
        )

        text, tool_call, usage, thinking = provider.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            [],
        )

        self.assertEqual(text, "Hello")
        self.assertIsNone(tool_call)
        self.assertIsNone(thinking)
        self.assertEqual(usage["total_tokens"], 25_209)
        self.assertEqual(usage["base_cost_usd"], 0.0104)
        self.assertEqual(usage["cache_write_cost_usd"], 0.305913)
        self.assertEqual(usage["cost_usd"], 0.316313)
        self.assertEqual(usage["cache_savings_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
