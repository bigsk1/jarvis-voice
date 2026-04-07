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
    get_model_pricing,
    get_provider_model_options,
)


class ModelCatalogTests(unittest.TestCase):
    def test_openai_options_are_newest_first(self):
        models = [entry["id"] for entry in get_provider_model_options("openai")]
        self.assertEqual(models[:4], ["gpt-5.4", "gpt-5.4-nano", "gpt-5.2", "gpt-5.2-chat-latest"])

    def test_xai_fast_model_has_2m_context(self):
        self.assertEqual(get_model_context_label("xai", "grok-4-fast"), "2M")
        self.assertEqual(get_model_context_window("xai", "grok-4-fast"), 2_000_000)

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


if __name__ == "__main__":
    unittest.main()
