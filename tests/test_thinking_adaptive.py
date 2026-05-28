#!/usr/bin/env python3
"""Regression tests for Anthropic adaptive thinking (Opus 4.7+)."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from thinking import get_thinking_config, is_thinking_supported, uses_adaptive_thinking


class AdaptiveThinkingTests(unittest.TestCase):
    def test_opus_4_8_uses_adaptive_thinking(self):
        self.assertTrue(uses_adaptive_thinking("anthropic", "claude-opus-4-8"))
        self.assertTrue(is_thinking_supported("anthropic", "claude-opus-4-8"))
        config = get_thinking_config("anthropic", "claude-opus-4-8")
        self.assertEqual(config["thinking"]["type"], "adaptive")
        self.assertEqual(config["output_config"]["effort"], "xhigh")
        self.assertEqual(config["max_tokens"], 64000)

    def test_opus_4_7_uses_adaptive_thinking(self):
        self.assertTrue(uses_adaptive_thinking("anthropic", "claude-opus-4-7"))
        config = get_thinking_config("anthropic", "opus-4.7")
        self.assertEqual(config["thinking"]["type"], "adaptive")

    def test_sonnet_4_5_still_uses_budget_tokens(self):
        self.assertFalse(uses_adaptive_thinking("anthropic", "claude-sonnet-4-5-20250929"))
        config = get_thinking_config("anthropic", "claude-sonnet-4-5-20250929")
        self.assertEqual(config["thinking"]["type"], "enabled")
        self.assertEqual(config["thinking"]["budget_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()
