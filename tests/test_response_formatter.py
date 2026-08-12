#!/usr/bin/env python3
"""Regression tests for extracted orchestrator response formatting helpers."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator
from response_formatter import ResponseFormatter
from tts_normalizer import XAI_INLINE_SPEECH_TAGS, XAI_WRAPPING_SPEECH_TAGS


class _FailIfCalledProvider:
    def chat(self, *_args, **_kwargs):
        raise AssertionError("provider.chat should not be called")

    def chat_with_tools(self, *_args, **_kwargs):
        raise AssertionError("provider.chat_with_tools should not be called")


class _ErrorProvider:
    def chat(self, *_args, **_kwargs):
        return "Error: invalid_api_key"

    def chat_with_tools(self, *_args, **_kwargs):
        return "Error: invalid_api_key", None, None


class ResponseFormatterTests(unittest.TestCase):
    def test_xai_tts_instruction_exposes_full_supported_vocabulary_only_for_xai(self):
        formatter = ResponseFormatter(
            provider=_FailIfCalledProvider(),
            prompt_override=None,
            extract_useful_data_fn=lambda _data: "",
        )

        with patch(
            "response_formatter.get_config_value",
            side_effect=lambda key, default="": {
                "TTS_PROVIDER": "xai",
                "XAI_TTS_STYLE_TAGS_ENABLED": "true",
            }.get(key, default),
        ):
            instruction = formatter.xai_tts_style_tags_instruction()

        for tag in XAI_INLINE_SPEECH_TAGS:
            self.assertIn(f"[{tag}]", instruction)
        for tag in XAI_WRAPPING_SPEECH_TAGS:
            self.assertIn(f"<{tag}>...</{tag}>", instruction)
        self.assertNotIn("<shout>", instruction)

        with patch(
            "response_formatter.get_config_value",
            side_effect=lambda key, default="": {
                "TTS_PROVIDER": "openai",
                "XAI_TTS_STYLE_TAGS_ENABLED": "true",
            }.get(key, default),
        ):
            self.assertEqual(formatter.xai_tts_style_tags_instruction(), "")

    def test_single_turn_short_response_passthrough(self):
        formatter = ResponseFormatter(
            provider=_FailIfCalledProvider(),
            prompt_override=None,
            extract_useful_data_fn=lambda _data: "",
        )

        raw = "Solana is $85.93 right now."
        self.assertEqual(formatter.format_single_turn_casual("what is solana?", raw), raw)

    def test_natural_response_falls_back_to_tool_speech_on_provider_error(self):
        formatter = ResponseFormatter(
            provider=_ErrorProvider(),
            prompt_override=None,
            extract_useful_data_fn=lambda _data: "",
        )

        result = formatter.format_natural_response(
            "set a reminder",
            "create_reminder",
            {
                "data": {"formatted_time": "Thursday, May 1 at 6:00 PM PDT"},
                "speech": "Reminder set for Thursday, May 1 at 6:00 PM PDT.",
            },
        )

        self.assertEqual(result, "Reminder set for Thursday, May 1 at 6:00 PM PDT.")

    def test_max_turns_summary_uses_extracted_data_fallback_on_provider_error(self):
        formatter = ResponseFormatter(
            provider=_ErrorProvider(),
            prompt_override=None,
            extract_useful_data_fn=lambda _data: "Top picks: Copper River, Thirsty Lion, BJ's Brewhouse.",
        )

        result = formatter.format_max_turns_summary(
            "best date night spots nearby",
            ["search_places", "weather"],
            {"search_places": [{"name": "Copper River"}]},
            10,
        )

        self.assertEqual(result, "Top picks: Copper River, Thirsty Lion, BJ's Brewhouse.")

    def test_orchestrator_lazy_response_formatter_supports_new_without_init(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.router = SimpleNamespace(provider=_FailIfCalledProvider())
        orch.prompt_override = None

        formatter = orch._get_response_formatter()

        self.assertIsInstance(formatter, ResponseFormatter)
        self.assertEqual(
            orch._format_single_turn_casual("what time is it?", "It is 6 PM."),
            "It is 6 PM.",
        )


if __name__ == "__main__":
    unittest.main()
