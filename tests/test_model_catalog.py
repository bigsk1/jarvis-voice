#!/usr/bin/env python3
"""
Regression tests for the shared model catalog.

Run:
    python3 tests/test_model_catalog.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.model_catalog import (
    get_default_model_id,
    get_model_context_label,
    get_model_context_window,
    get_model_metadata,
    get_model_pricing,
    get_provider_fallback_model,
    get_provider_model_options,
)


class ModelCatalogTests(unittest.TestCase):
    def test_openai_options_are_newest_first(self):
        models = [entry["id"] for entry in get_provider_model_options("openai")]
        self.assertEqual(models[:4], ["gpt-5.4", "gpt-5.4-nano", "gpt-5.2", "gpt-5.2-chat-latest"])

    def test_xai_options_match_current_catalog(self):
        models = [entry["id"] for entry in get_provider_model_options("xai")]
        self.assertEqual(
            models[:2],
            ["grok-4.20-reasoning", "grok-4.20-non-reasoning-latest"],
        )
        self.assertNotIn("grok-4-fast", models)
        self.assertEqual(get_model_context_label("xai", "grok-4.20-reasoning"), "2M")
        self.assertEqual(get_model_context_window("xai", "grok-4.20-reasoning"), 2_000_000)

    def test_xai_reasoning_option_uses_api_model_id(self):
        models = [entry["id"] for entry in get_provider_model_options("xai")]
        self.assertIn("grok-4-1-fast-reasoning-latest", models)
        self.assertNotIn("grok-4-1-reasoning-latest", models)

        metadata = get_model_metadata("xai", "grok-4-1-reasoning-latest")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "grok-4-1-fast-reasoning-latest")

    def test_grok_4_20_variant_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("xai", "grok-4.20-reasoning"), 2_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4-20-reasoning-latest"), 2_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.20-non-reasoning-latest"), 2_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4-20-non-reasoning"), 2_000_000)
        pricing = get_model_pricing("xai", "grok-4.20-reasoning")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 2.00)
        self.assertEqual(pricing["cached"], 0.20)

    def test_dated_openai_variant_resolves_to_family_metadata(self):
        self.assertEqual(get_model_context_window("openai", "gpt-5.4-nano-2026-03-17"), 400_000)
        pricing = get_model_pricing("openai", "gpt-5.4-nano-2026-03-17")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 0.20)
        self.assertEqual(pricing["output"], 1.25)

    def test_catalog_defaults_are_explicit(self):
        self.assertEqual(get_default_model_id("openai"), "gpt-5.4-nano")
        self.assertEqual(get_default_model_id("xai"), "grok-4-1-fast-non-reasoning-latest")
        self.assertEqual(get_default_model_id("anthropic"), "claude-sonnet-4-5-20250929")

    def test_exact_id_beats_alias_when_names_overlap(self):
        metadata = get_model_metadata("anthropic", "claude-4-5")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-4-5")

    def test_latest_suffix_falls_back_to_family_match(self):
        metadata = get_model_metadata("xai", "grok-4-1-fast-non-reasoning-latest")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "grok-4-1-fast-non-reasoning-latest")
        family = get_model_metadata("xai", "grok-4-1-fast-non-reasoning-2026-04-01")
        self.assertIsNotNone(family)
        self.assertEqual(family["id"], "grok-4-1-fast-non-reasoning-latest")

    def test_unknown_provider_default_warns_and_returns_empty(self):
        with self.assertLogs("lib.model_catalog", level="WARNING") as captured:
            result = get_default_model_id("not-a-provider")
        self.assertEqual(result, "")
        self.assertTrue(any("Unknown provider requested" in line for line in captured.output))

    def test_unknown_provider_metadata_warns_and_returns_none(self):
        with self.assertLogs("lib.model_catalog", level="WARNING") as captured:
            result = get_model_metadata("not-a-provider", "some-model")
        self.assertIsNone(result)
        self.assertTrue(any("Unknown provider requested for model metadata" in line for line in captured.output))

    def test_ollama_fallback_default_can_be_overridden(self):
        self.assertEqual(get_provider_fallback_model("ollama"), "qwen3.5:latest")
        self.assertEqual(
            get_provider_fallback_model("ollama", local_default="qwen3:latest"),
            "qwen3:latest",
        )


if __name__ == "__main__":
    unittest.main()
