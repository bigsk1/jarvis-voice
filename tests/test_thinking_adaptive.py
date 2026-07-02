#!/usr/bin/env python3
"""Regression tests for Anthropic adaptive thinking (Opus 4.7+)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from thinking import get_thinking_config, is_thinking_supported, uses_adaptive_thinking


class AdaptiveThinkingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ANTHROPIC_EFFORT": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_opus_4_8_uses_adaptive_thinking(self):
        self.assertTrue(uses_adaptive_thinking("anthropic", "claude-opus-4-8"))
        self.assertTrue(is_thinking_supported("anthropic", "claude-opus-4-8"))
        config = get_thinking_config("anthropic", "claude-opus-4-8")
        self.assertEqual(config["thinking"]["type"], "adaptive")
        self.assertEqual(config["output_config"]["effort"], "xhigh")
        self.assertEqual(config["max_tokens"], 16384)

    def test_opus_4_7_uses_adaptive_thinking(self):
        self.assertTrue(uses_adaptive_thinking("anthropic", "claude-opus-4-7"))
        config = get_thinking_config("anthropic", "opus-4.7")
        self.assertEqual(config["thinking"]["type"], "adaptive")

    def test_sonnet_5_uses_adaptive_thinking(self):
        self.assertTrue(uses_adaptive_thinking("anthropic", "claude-sonnet-5"))
        self.assertTrue(uses_adaptive_thinking("anthropic", "sonnet-5"))
        self.assertTrue(is_thinking_supported("anthropic", "claude-sonnet-5"))
        config = get_thinking_config("anthropic", "claude-sonnet-5")
        self.assertEqual(config["thinking"]["type"], "adaptive")
        self.assertEqual(config["output_config"]["effort"], "xhigh")
        self.assertEqual(config["max_tokens"], 16384)

    def test_fable_5_uses_catalog_adaptive_thinking(self):
        self.assertTrue(is_thinking_supported("anthropic", "claude-fable-5"))
        self.assertTrue(uses_adaptive_thinking("anthropic", "fable-5"))
        config = get_thinking_config("anthropic", "claude-fable-5")
        self.assertEqual(config["thinking"]["type"], "adaptive")
        self.assertEqual(config["output_config"]["effort"], "xhigh")

    def test_sonnet_4_6_uses_supported_max_effort(self):
        config = get_thinking_config("anthropic", "sonnet-4.6")
        self.assertEqual(config["thinking"]["type"], "adaptive")
        self.assertEqual(config["output_config"]["effort"], "max")

    def test_supported_effort_override_is_preserved(self):
        with patch.dict(os.environ, {"ANTHROPIC_EFFORT": "low"}):
            config = get_thinking_config("anthropic", "claude-fable-5")
        self.assertEqual(config["output_config"]["effort"], "low")

    def test_unsupported_effort_falls_back_to_model_maximum(self):
        with patch.dict(os.environ, {"ANTHROPIC_EFFORT": "xhigh"}):
            config = get_thinking_config("anthropic", "claude-sonnet-4-6")
        self.assertEqual(config["output_config"]["effort"], "max")

    def test_unknown_or_provider_owned_models_are_not_catalog_thinking_models(self):
        self.assertFalse(is_thinking_supported("anthropic", "claude-future-99"))
        self.assertFalse(is_thinking_supported("openai", "o3-mini"))
        self.assertFalse(is_thinking_supported("ollama", "deepseek-r1"))

    def test_sonnet_4_5_still_uses_budget_tokens(self):
        self.assertFalse(uses_adaptive_thinking("anthropic", "claude-sonnet-4-5-20250929"))
        config = get_thinking_config("anthropic", "claude-sonnet-4-5-20250929")
        self.assertEqual(config["thinking"]["type"], "enabled")
        self.assertEqual(config["thinking"]["budget_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()
