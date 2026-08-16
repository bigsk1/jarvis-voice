#!/usr/bin/env python3
import os
import sys
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))

from router_v2 import (  # noqa: E402
    ToolRetrievalSignals,
    _cap_tool_names_for_schema,
    build_tool_retrieval_signals,
    extract_current_user_request,
    _log_tool_rag_trace,
    _tool_rag_similarity_threshold,
    merge_tool_signal_names,
)


class ToolRagSignalsTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {}
        self._keys = [
            "TOOL_RAG_COMPACT_QUERY_ENABLED",
            "TOOL_RAG_CURRENT_QUERY_MAX_CHARS",
            "TOOL_RAG_CONTEXT_QUERY_MAX_CHARS",
            "TOOL_RAG_APPEND_POSITIVE_SIGNALS",
            "TOOL_RAG_EXCLUDE_NEGATIVE_SIGNALS",
            "TOOL_RAG_MIN_LEARNED_PREFER_BIAS",
            "TOOL_RAG_MIN_LEARNED_AVOID_BIAS",
            "TOOL_RAG_MEMORY_TOOL_SIGNALS_ENABLED",
            "TOOL_RAG_TRACE_ENABLED",
            "TOOL_SIMILARITY_THRESHOLD",
            "TOOL_SIMILARITY_THRESHOLD_FULL",
        ]
        for key in self._keys:
            self._saved_env[key] = os.environ.get(key)
        os.environ["TOOL_RAG_COMPACT_QUERY_ENABLED"] = "true"
        os.environ["TOOL_RAG_CURRENT_QUERY_MAX_CHARS"] = "1200"
        os.environ["TOOL_RAG_CONTEXT_QUERY_MAX_CHARS"] = "120"
        os.environ["TOOL_RAG_APPEND_POSITIVE_SIGNALS"] = "true"
        os.environ["TOOL_RAG_EXCLUDE_NEGATIVE_SIGNALS"] = "true"
        os.environ["TOOL_RAG_MIN_LEARNED_PREFER_BIAS"] = "0.40"
        os.environ["TOOL_RAG_MIN_LEARNED_AVOID_BIAS"] = "0.40"
        os.environ["TOOL_RAG_MEMORY_TOOL_SIGNALS_ENABLED"] = "false"
        os.environ["TOOL_RAG_TRACE_ENABLED"] = "true"
        os.environ["TOOL_SIMILARITY_THRESHOLD"] = "0.23"
        os.environ["TOOL_SIMILARITY_THRESHOLD_FULL"] = "0.40"

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_web_prompt_extracts_user_request_and_strong_signals(self):
        prompt = """
=== LEARNED STRATEGIES (WHAT TO DO) ===
✅ For explicit email requests with recipient and subject, use send_email directly.

=== TOOL PREFERENCES ===
  ✅ PREFER: send_email (+0.41)
  ✅ PREFER: generate_video (+0.38)

=== RECENT CONVERSATION CONTEXT ===
Jarvis [tools: youtube_video, stash]: Retrieved a video path.
=== END CONTEXT ===

Current request: [CONTEXT - Tool preference for this request]

Selected tool hints: send_email.

[END CONTEXT]

User's request: No send an email to Riley with youtube video https://example.com/watch?v=1 and include love Jordan
"""
        signals = build_tool_retrieval_signals(
            prompt,
            {"send_email", "generate_video", "youtube_video", "stash"},
        )

        self.assertEqual(signals.source, "user_request")
        self.assertTrue(signals.query.startswith("No send an email to Riley"))
        self.assertIn("send_email", signals.positive_tools)
        self.assertNotIn("generate_video", signals.positive_tools)
        self.assertIn("skipped_low_bias_prefer=generate_video:0.38", signals.notes)

    def test_intelligence_request_excludes_web_tool_hint_wrapper(self):
        prompt = """
[CONTEXT - Tool preference for this request]

Selected tool hints: brave_llm_context.
Treat this as a strong preference for this turn.

[END CONTEXT]

User's request: use brave to get the latest AI news
"""

        self.assertEqual(
            extract_current_user_request(prompt),
            "use brave to get the latest AI news",
        )

    def test_prefer_avoid_conflict_neutralizes_tool(self):
        prompt = """
=== TOOL PREFERENCES ===
  ✅ PREFER: send_email (+0.90)
  ❌ AVOID: send_email (-0.90)

Current request: email Riley
"""
        signals = build_tool_retrieval_signals(prompt, {"send_email"})

        self.assertIn("send_email", signals.conflicted_tools)
        self.assertNotIn("send_email", signals.positive_tools)
        self.assertNotIn("send_email", signals.negative_tools)

    def test_explicit_ui_hint_overrides_learned_avoid_and_survives_schema_cap(self):
        prompt = """
=== KNOWN FAILURES - AVOID THESE ===
❌ Never re-call Brave when the user says not to search again.
   → DO NOT use: brave_llm_context

=== TOOL PREFERENCES ===
  ❌ AVOID: brave_llm_context (-0.88)

[CONTEXT - Tool preference for this request]

Selected tool hints: brave_llm_context.
Treat this as a strong preference for this turn.

[END CONTEXT]

User's request: use brave to get the latest AI news
"""
        enabled = {
            "brave_llm_context",
            "mcp_brave_search_brave_web_search",
        }

        signals = build_tool_retrieval_signals(prompt, enabled)
        merged, meta = merge_tool_signal_names(
            ["mcp_brave_search_brave_web_search"],
            signals,
            enabled,
        )
        capped = _cap_tool_names_for_schema(
            merged,
            limit=1,
            positive_tools=signals.positive_tools,
        )

        self.assertEqual(signals.positive_tools, {"brave_llm_context"})
        self.assertEqual(signals.negative_tools, set())
        self.assertEqual(signals.conflicted_tools, set())
        self.assertIn(
            "explicit_tool_hints_overrode_negative=brave_llm_context",
            signals.notes,
        )
        self.assertEqual(meta["appended"], ["brave_llm_context"])
        self.assertEqual(capped, ["brave_llm_context"])

    def test_weak_avoid_signal_is_not_a_hard_exclusion(self):
        prompt = """
=== TOOL PREFERENCES ===
  ❌ AVOID: generate_image (-0.12)

Current request: can you generate an image of now that quiet night looks?
"""
        signals = build_tool_retrieval_signals(prompt, {"generate_image"})

        self.assertNotIn("generate_image", signals.negative_tools)
        self.assertIn("skipped_low_bias_avoid=generate_image:0.12", signals.notes)
        names, meta = merge_tool_signal_names(
            ["generate_image", "analyze_image"],
            signals,
            {"generate_image", "analyze_image"},
        )
        self.assertIn("generate_image", names)
        self.assertEqual(meta["negative"], [])

    def test_merge_appends_positive_and_filters_negative_non_ghost(self):
        signals = ToolRetrievalSignals(
            query="send the link",
            source="raw_request",
            positive_tools={"send_email"},
            negative_tools={"stash", "canvas"},
        )

        names, meta = merge_tool_signal_names(
            ["canvas", "stash"],
            signals,
            {"send_email", "stash", "canvas"},
            ghost_tools={"canvas"},
        )

        self.assertEqual(names, ["canvas", "send_email"])
        self.assertEqual(meta["appended"], ["send_email"])
        self.assertEqual(meta["negative"], ["canvas", "stash"])

    def test_full_fallback_is_capped_when_no_current_request_found(self):
        prompt = "=== LEARNED STRATEGIES ===\n\n✅ " + ("memory context " * 80)
        signals = build_tool_retrieval_signals(prompt, {"send_email"})

        self.assertEqual(signals.source, "full_fallback")
        self.assertLessEqual(len(signals.query), 120)

    def test_full_fallback_uses_full_threshold_even_when_capped(self):
        threshold = _tool_rag_similarity_threshold(
            transcript="full transcript " * 100,
            tool_search_query="full transcript ... [truncated]",
            signal_source="full_fallback",
        )

        self.assertEqual(threshold, 0.40)

    def test_trailing_request_after_learning_context_is_extracted(self):
        prompt = """
=== LEARNED STRATEGIES (WHAT TO DO) ===
(Based on 3 successful patterns)

✅ Prefer crypto_price tool for direct cryptocurrency price inquiries.
   → Applies to: Queries about current prices of cryptocurrencies

=== TOOL PREFERENCES ===
  ✅ PREFER: crypto_price (+2.35)

(Overall confidence in these insights: 100%)

whats the current price of solana?
"""
        signals = build_tool_retrieval_signals(prompt, {"crypto_price"})

        self.assertEqual(signals.source, "trailing_request")
        self.assertEqual(signals.query, "whats the current price of solana?")

    def test_original_user_request_tail_stops_before_tool_context(self):
        prompt = """
Original user request: === LEARNED STRATEGIES (WHAT TO DO) ===
(Based on 1 successful pattern)

✅ Prefer send_email for direct email requests.

=== TOOL PREFERENCES ===
  ✅ PREFER: send_email (+1.00)

can you send email to Sarah about the video?

Tools executed so far:

1. youtube_video
   Result: {"ok": true, "title": "Video"}
"""
        signals = build_tool_retrieval_signals(prompt, {"send_email", "youtube_video"})

        self.assertEqual(signals.source, "original_user_request_tail")
        self.assertEqual(signals.query, "can you send email to Sarah about the video?")

    def test_trace_logger_writes_jsonl_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_router = Path(tmp) / "orchestrator" / "router_v2.py"
            fake_router.parent.mkdir(parents=True)
            fake_router.write_text("")
            with patch("router_v2.__file__", str(fake_router)):
                _log_tool_rag_trace(
                    mode="cloud",
                    provider="xai",
                    model="test-model",
                    transcript="Current request: email Riley",
                    query="email Riley",
                    threshold=0.23,
                    retrieval_limit=15,
                    signal_source="current_request",
                    signal_meta={"positive": ["send_email"], "negative": [], "conflicted": [], "appended": []},
                    signal_notes=[],
                    ranked_tools=[{"name": "send_email", "similarity": 0.55}],
                    final_tools=["search_memory", "send_email"],
                    ghost_tools=["search_memory"],
                    excluded_tools=[],
                    router_prompt_version="v1",
                    system_prompt_chars=31_491,
                    system_prompt_est_tokens=7_873,
                    system_prompt_sent=True,
                    tool_schema_chars=1234,
                    tool_schema_est_tokens=309,
                    tool_schema_top=[{"name": "send_email", "chars": 900, "est_tokens": 225}],
                    retrieval_mode="keyword_fallback",
                    semantic_disabled_reason="embedding fingerprint mismatch",
                )

            files = list((Path(tmp) / "logs" / "tool-rag").glob("tool-rag-*.jsonl"))
            self.assertEqual(len(files), 1)
            entry = json.loads(files[0].read_text().strip())
            self.assertEqual(entry["signal_source"], "current_request")
            self.assertEqual(entry["final_tools"], ["search_memory", "send_email"])
            self.assertEqual(entry["ranked_tools"][0]["name"], "send_email")
            self.assertEqual(entry["router_prompt_version"], "v1")
            self.assertEqual(entry["system_prompt_est_tokens"], 7_873)
            self.assertTrue(entry["system_prompt_sent"])
            self.assertEqual(entry["tool_schema_est_tokens"], 309)
            self.assertEqual(entry["tool_schema_top"][0]["name"], "send_email")
            self.assertEqual(entry["final_schema_limit"], 15)
            self.assertEqual(entry["retrieval_mode"], "keyword_fallback")
            self.assertEqual(
                entry["semantic_disabled_reason"],
                "embedding fingerprint mismatch",
            )


if __name__ == "__main__":
    unittest.main()
