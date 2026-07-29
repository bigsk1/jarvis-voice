#!/usr/bin/env python3
"""Regression tests for provider-error routing and log parsing."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from provider_errors import classify_provider_error, is_provider_error_text, sanitize_provider_error
from router_v2 import LLMRouter
from jarvis_web_test_server.services.log_streamer import LogStreamer
from tool_schema import ToolSchema


class _Registry:
    def __init__(self):
        self.tools = {
            "youtube_transcript": SimpleNamespace(
                name="youtube_transcript",
                deterministic_routing={
                    "provider_error_fallbacks": [
                        {
                            "type": "regex",
                            "error_kinds": ["safety", "permission"],
                            "pattern": r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s<>)\"']+",
                            "arguments": {"url": "$match"},
                            "strip_trailing": ".,;]",
                        }
                    ]
                },
            )
        }

    def get_tool(self, name):
        return self.tools.get(name)


class ProviderErrorFallbackTests(unittest.TestCase):
    def test_provider_error_text_is_detected(self):
        raw_error = (
            "Error: Error code: 403 - {'error': 'Content violates usage guidelines. "
            "Team: 8640cd2d-39ef-44ab-a0a4-2d4fe01a9959, "
            "API key ID: 38905069-210d-42df-94c5-8caec1a5e97f, "
            "Failed check: SAFETY_CHECK_TYPE_BIO'}"
        )

        self.assertTrue(is_provider_error_text(raw_error))
        self.assertEqual(classify_provider_error(raw_error).kind, "safety")
        sanitized = sanitize_provider_error(raw_error)
        self.assertIn("Team: [redacted]", sanitized)
        self.assertIn("API key ID: [redacted]", sanitized)
        self.assertNotIn("8640cd2d", sanitized)

    def test_normal_qa_about_authentication_is_not_provider_error(self):
        self.assertFalse(
            is_provider_error_text(
                "OAuth uses authentication tokens so the server can verify each request."
            )
        )

    def test_short_qa_about_rate_limits_is_not_provider_error(self):
        self.assertFalse(
            is_provider_error_text(
                "A rate limit caps how many API requests a client can make in a time window."
            )
        )
        self.assertFalse(
            is_provider_error_text(
                "HTTP 429 too many requests means the client hit a throttle and should back off."
            )
        )

    def test_error_wrapped_rate_limit_still_detected(self):
        wrapped = "Error: Rate limit exceeded. Please retry after 30 seconds."
        self.assertTrue(is_provider_error_text(wrapped))
        self.assertEqual(classify_provider_error(wrapped).kind, "rate_limit")

        error_code = "Error code: 429 - {'error': 'too many requests'}"
        self.assertTrue(is_provider_error_text(error_code))
        self.assertEqual(classify_provider_error(error_code).kind, "rate_limit")

        sdk_type = "Error: rate_limit_exceeded"
        self.assertTrue(is_provider_error_text(sdk_type))
        self.assertEqual(classify_provider_error(sdk_type).kind, "rate_limit")

    def test_connectivity_howto_with_sdk_phrases_not_provider_error(self):
        """Regression: long markdown answers may mention gateway timeout, rate limits, etc."""
        prose = (
            "## Internet Connectivity Check Strategies\n\n"
            "Great idea—proactive connectivity checks prevent routing deadlocks. "
            "Mention gateway timeout, TCP timeouts, and service unavailable patterns. "
            "Avoid rate limits when polling. " * 6
        )
        self.assertGreater(len(prose), 400)
        self.assertFalse(is_provider_error_text(prose))

    def test_short_error_prefix_still_detected(self):
        self.assertTrue(is_provider_error_text("Error: gateway timeout"))

    def test_xai_403_permission_and_safety_payload_is_detected(self):
        """Shape from xAI when routing fails with bio safety + permission wording."""
        raw = (
            "Error code: 403 - {'code': 'The caller does not have permission to execute the "
            "specified operation', 'error': 'Content violates usage guidelines. "
            "Team: 8640cd2d-39ef-44ab-a0a4-2d4fe01a9959, API key ID: 38905069-210d-42df-94c5-8caec1a5e97f, "
            "Model: grok-4.3, Failed check: SAFETY_CHECK_TYPE_BIO'}"
        )
        self.assertTrue(is_provider_error_text(raw))
        self.assertEqual(classify_provider_error(raw).kind, "safety")

    def test_openai_style_snake_case_types_classify(self):
        self.assertTrue(is_provider_error_text("Error: insufficient_quota"))
        self.assertEqual(classify_provider_error("Error: insufficient_quota").kind, "billing")
        self.assertTrue(is_provider_error_text("Error: context_length_exceeded"))
        self.assertEqual(classify_provider_error("Error: context_length_exceeded").kind, "context")
        self.assertTrue(is_provider_error_text("Error: invalid_api_key"))
        self.assertEqual(classify_provider_error("Error: invalid_api_key").kind, "authentication")

    def test_ollama_cloud_extra_usage_402_has_specific_billing_message(self):
        raw = (
            "Error: 402 Payment Required: this model uses extra usage only "
            "(not included plan usage) and your extra usage balance is empty, "
            "add extra usage or turn on auto reload at https://ollama.com/settings "
            "(ref: 5747d205-73cb-4900-a8e6-0121c97a2be2)"
        )

        info = classify_provider_error(raw)

        self.assertTrue(is_provider_error_text(raw))
        self.assertEqual(info.kind, "billing")
        self.assertEqual(
            info.friendly_message,
            "Ollama Cloud returned 402 Payment Required: this model uses extra usage, "
            "but the extra-usage balance is empty. Add extra usage or turn on "
            "auto-reload at https://ollama.com/settings.",
        )

    def test_youtube_provider_error_routes_to_transcript_tool(self):
        router = LLMRouter.__new__(LLMRouter)
        router.registry = _Registry()

        route = router._provider_error_fallback_route(
            transcript=(
                "ok get this youtube video transcript and recap it "
                "https://www.youtube.com/watch?v=bugVEcVpH7w"
            ),
            error_text="Error: Error code: 403 - Content violates usage guidelines.",
            tool_names=[],
            usage_info=None,
        )

        self.assertIsNotNone(route)
        self.assertEqual(route["intent"], "tool")
        self.assertEqual(route["tool_name"], "youtube_transcript")
        self.assertEqual(route["arguments"]["url"], "https://www.youtube.com/watch?v=bugVEcVpH7w")
        self.assertTrue(route["provider_error_recovered"])
        self.assertEqual(route["provider_error_kind"], "safety")

    def test_provider_error_fallback_can_be_scoped_by_error_kind(self):
        router = LLMRouter.__new__(LLMRouter)
        router.registry = _Registry()

        route = router._provider_error_fallback_route(
            transcript=(
                "ok get this youtube video transcript and recap it "
                "https://www.youtube.com/watch?v=bugVEcVpH7w"
            ),
            error_text="Error: invalid api key",
            tool_names=[],
            usage_info=None,
        )

        self.assertIsNone(route)

    def test_youtube_tool_declares_provider_error_fallback_metadata(self):
        tool = ToolSchema.from_json_file(
            PROJECT_ROOT / "skills" / "auto-tools" / "youtube_transcript.tool.json"
        )

        fallbacks = tool.deterministic_routing.get("provider_error_fallbacks")

        self.assertTrue(fallbacks)
        self.assertEqual(fallbacks[0]["error_kinds"], ["safety", "permission"])
        self.assertEqual(fallbacks[0]["arguments"], {"url": "$match"})

    def test_log_streamer_handles_null_token_fields(self):
        streamer = LogStreamer(lambda entry: None)
        line = json.dumps({
            "timestamp": "2026-04-16T16:22:43.439762",
            "provider": "xai",
            "model": "grok-4.3",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "duration_ms": 1947.54,
            "success": False,
            "response": {
                "type": "text",
                "text_preview": "Error: Error code: 403",
                "tool_name": None,
            },
        })

        entry = streamer._parse_llm_entry(line, "llm")

        self.assertIsNotNone(entry)
        self.assertIn("0 tokens", entry.title)
        self.assertEqual(entry.details["input_tokens"], 0)
        self.assertEqual(entry.details["output_tokens"], 0)
        self.assertEqual(entry.level, "error")


if __name__ == "__main__":
    unittest.main()
