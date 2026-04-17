#!/usr/bin/env python3
"""Regression tests for text_summarizer compatibility and LLM fallback behavior."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MODULE_PATH = PROJECT_ROOT / "skills" / "auto-tools" / "text_summarizer.py"

spec = importlib.util.spec_from_file_location("text_summarizer_tool", MODULE_PATH)
text_summarizer = importlib.util.module_from_spec(spec)
sys.modules["text_summarizer_tool"] = text_summarizer
assert spec.loader is not None
spec.loader.exec_module(text_summarizer)


class TextSummarizerTests(unittest.TestCase):
    def test_short_summary_defaults_to_extractive(self):
        text = (
            "Artificial intelligence is transforming the world. "
            "Machine learning algorithms are becoming more sophisticated. "
            "Natural language processing helps computers understand language."
        )

        with patch.object(text_summarizer, "summarize_with_llm") as mock_llm:
            summary, meta = text_summarizer.summarize_with_strategy(
                text,
                {"operation": "summarize", "num_sentences": 2},
            )

        self.assertFalse(mock_llm.called)
        self.assertEqual(meta["summary_method"], "extractive")
        self.assertFalse(meta["llm_used"])
        self.assertTrue(summary)

    def test_long_summary_uses_llm_when_available(self):
        text = "Claude Opus 4.7 improves coding, vision, and agentic workflows. " * 120

        with patch.object(
            text_summarizer,
            "summarize_with_llm",
            return_value=("LLM summary about Opus 4.7.", {"summary_method": "llm", "llm_used": True}),
        ) as mock_llm:
            summary, meta = text_summarizer.summarize_with_strategy(
                text,
                {"operation": "summarize", "llm_min_chars": 1000},
            )

        self.assertTrue(mock_llm.called)
        self.assertEqual(summary, "LLM summary about Opus 4.7.")
        self.assertEqual(meta["summary_method"], "llm")
        self.assertTrue(meta["llm_used"])

    def test_long_summary_falls_back_to_extractive_when_llm_fails(self):
        text = "Claude Opus 4.7 improves coding, vision, and agentic workflows. " * 120

        with patch.object(
            text_summarizer,
            "summarize_with_llm",
            return_value=(None, {"summary_method": "llm", "llm_used": False, "llm_error": "offline"}),
        ):
            summary, meta = text_summarizer.summarize_with_strategy(
                text,
                {"operation": "summarize", "llm_min_chars": 1000, "num_sentences": 2},
            )

        self.assertTrue(summary)
        self.assertEqual(meta["summary_method"], "extractive")
        self.assertFalse(meta["llm_used"])
        self.assertEqual(meta["fallback_reason"], "offline")

    def test_long_summary_falls_back_when_provider_creation_fails(self):
        text = "Claude Opus 4.7 improves coding, vision, and agentic workflows. " * 120

        with patch.object(
            text_summarizer,
            "create_llm_provider",
            side_effect=RuntimeError("missing api key"),
        ):
            summary, meta = text_summarizer.summarize_with_strategy(
                text,
                {"operation": "summarize", "method": "llm", "num_sentences": 2},
            )

        self.assertTrue(summary)
        self.assertEqual(meta["summary_method"], "extractive")
        self.assertFalse(meta["llm_used"])
        self.assertEqual(meta["fallback_reason"], "missing api key")

    def test_create_llm_provider_uses_shared_configured_provider(self):
        provider = object()
        with patch(
            "llm_provider.create_configured_provider",
            return_value=("xai", "grok-test", provider),
        ) as mock_create:
            result = text_summarizer.create_llm_provider(
                {"llm_provider": "xai", "llm_model": "grok-test"}
            )

        self.assertEqual(result, ("xai", "grok-test", provider))
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["provider_override"], "xai")
        self.assertEqual(kwargs["model_override"], "grok-test")
        self.assertIn("TEXT_SUMMARIZER_LLM_PROVIDER", kwargs["provider_config_keys"])
        self.assertNotIn("STASH_SUMMARIZE_PROVIDER", kwargs["provider_config_keys"])
        self.assertIn("STASH_SUMMARIZE_MODEL", kwargs["model_config_keys"])
        self.assertNotIn("default_ollama_model", kwargs)
        self.assertTrue(kwargs["disable_server_side_tools"])

    def test_keyword_aliases_keep_existing_workflows_working(self):
        self.assertEqual(text_summarizer.normalize_operation({"action": "keywords"}), "keywords")
        keywords = text_summarizer.extract_keywords(
            "alpha beta beta gamma gamma gamma delta delta delta delta",
            top_n=2,
        )
        self.assertEqual([item["keyword"] for item in keywords], ["delta", "gamma"])


if __name__ == "__main__":
    unittest.main()
