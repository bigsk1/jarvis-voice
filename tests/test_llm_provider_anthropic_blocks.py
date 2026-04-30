#!/usr/bin/env python3
"""Regression tests for Anthropic response block handling."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from llm_provider import AnthropicProvider


class AnthropicBlockHandlingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
