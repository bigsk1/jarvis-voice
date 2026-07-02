#!/usr/bin/env python3
"""Regression tests for Anthropic response block handling."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from llm_provider import AnthropicProvider


class AnthropicBlockHandlingTests(unittest.TestCase):
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
        self.assertIsNone(usage)
        self.assertEqual(thinking, "A short summary.")
        self.assertEqual(captured["thinking"], {"type": "adaptive", "display": "summarized"})
        self.assertEqual(captured["output_config"], {"effort": "xhigh"})
        self.assertEqual(captured["max_tokens"], 16_384)

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
