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
from tts_style_tags import XAI_INLINE_SPEECH_TAGS, XAI_WRAPPING_SPEECH_TAGS


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
    def test_shopping_fallback_keeps_prices_and_links_from_repeated_calls(self):
        from context_assembler import ContextAssembler

        assembler = ContextAssembler.__new__(ContextAssembler)
        extracted = assembler.extract_useful_data(
            {
                "serpapi_amazon_search": [
                    {
                        "query": "lithium UPS 800W",
                        "results_count": 1,
                        "results": [{
                            "title": "800W lithium UPS",
                            "price": "$209.99",
                            "url": "https://www.amazon.com/dp/example-one",
                        }],
                    },
                    {
                        "query": "pure sine UPS",
                        "results_count": 1,
                        "results": [{
                            "title": "1000W sine wave UPS",
                            "price": "$239.95",
                            "url": "https://www.amazon.com/dp/example-two",
                        }],
                    },
                ]
            },
            has_text_summarizer_summary_for_ref=lambda _data, _ref: False,
        )

        self.assertIn('"title":"800W lithium UPS","price":"$209.99","url":"https://www.amazon.com/dp/example-one"', extracted)
        self.assertIn('"title":"1000W sine wave UPS","price":"$239.95","url":"https://www.amazon.com/dp/example-two"', extracted)

    def test_generic_result_rows_keep_useful_fields_without_credentials(self):
        from context_assembler import ContextAssembler

        assembler = ContextAssembler.__new__(ContextAssembler)
        extracted = assembler.extract_useful_data(
            {"other_search": {"results": [{
                "name": "Battery backup", "price": 129.0,
                "link": "https://example.test/product", "status": "available",
                "api_key": "do-not-show",
            }]}},
            has_text_summarizer_summary_for_ref=lambda _data, _ref: False,
        )

        self.assertIn('"name":"Battery backup"', extracted)
        self.assertIn('"price":"129.0"', extracted)
        self.assertIn('"link":"https://example.test/product"', extracted)
        self.assertIn('"status":"available"', extracted)
        self.assertNotIn("do-not-show", extracted)

    def test_unregistered_result_list_keeps_candidate_fields(self):
        from context_assembler import ContextAssembler

        assembler = ContextAssembler.__new__(ContextAssembler)
        extracted = assembler.extract_useful_data(
            {"new_provider": {"inventory": [{
                "title": "Portable UPS", "price": "$299",
                "url": "https://example.test/ups",
            }]}},
            has_text_summarizer_summary_for_ref=lambda _data, _ref: False,
        )

        self.assertIn('"title":"Portable UPS","price":"$299","url":"https://example.test/ups"', extracted)

    def test_failed_only_followup_context_keeps_provider_diagnosis(self):
        from context_assembler import ContextAssembler

        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler._safe_iso_to_local_datetime = lambda _value: None
        from datetime import timezone
        assembler.timezone = timezone.utc
        rendered = assembler.format_conversation_context("What failed?", [{
            "role": "assistant",
            "content": "The request failed.",
            "tools_used": [],
            "tool_results": {"provider_incidents": {"calls": [{
                "tool": "serpapi_google_shopping_light",
                "call_index": 0,
                "incident": {"status": "investigating"},
            }]}},
        }])

        self.assertIn("serpapi_google_shopping_light", rendered)
        self.assertIn("investigating", rendered)

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


def test_elevenlabs_instruction_is_scoped_to_v4_and_toggle():
    from tts_normalizer import ELEVENLABS_INLINE_SPEECH_TAGS
    formatter = ResponseFormatter(
        provider=_FailIfCalledProvider(), prompt_override=None,
        extract_useful_data_fn=lambda _data: "",
    )
    for provider, model, enabled, expected in (
        ("elevenlabs", "eleven_v4", "true", True),
        ("elevenlabs", "eleven_v4_turbo", "true", True),
        ("elevenlabs", "eleven_v4_turbo", "off", False),
        ("elevenlabs", "eleven_v4", "off", False),
        ("elevenlabs", "eleven_v3", "true", False),
        ("elevenlabs", "eleven_multilingual_v2", "true", False),
        ("openai", "eleven_v4", "true", False),
        ("xai", "eleven_v4", "true", False),
    ):
        values = {
            "TTS_PROVIDER": provider, "ELEVENLABS_TTS_MODEL": model,
            "ELEVENLABS_TTS_STYLE_TAGS_ENABLED": enabled,
        }
        with patch("response_formatter.get_config_value", side_effect=lambda k, d="": values.get(k, d)):
            instruction = formatter.tts_style_tags_instruction()
        assert ("ElevenLabs v4" in instruction) is expected
        if expected:
            for tag in ELEVENLABS_INLINE_SPEECH_TAGS:
                assert f"[{tag}]" in instruction
            assert "tool arguments" in instruction
            assert "<whisper>" not in instruction
