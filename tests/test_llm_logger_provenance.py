#!/usr/bin/env python3
"""Regression tests for routing provenance fields in llm-calls logs."""

import json
import tempfile
import unittest
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from llm_logger import LLMLogger


class LLMLoggerProvenanceTests(unittest.TestCase):
    def test_status_call_metadata_is_persisted_without_routing_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            metadata = {
                "status_task_id": "task-1",
                "status_request_id": 3,
                "status_call_index": 2,
                "status_tool": "weather",
            }
            logger.log_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                prompt_type="status_update",
                messages=[{"role": "user", "content": "Checking weather"}],
                response_text="Checking the latest forecast",
                tool_call=None,
                usage_info={"input_tokens": 40, "output_tokens": 6, "total_tokens": 46},
                thinking=None,
                duration_ms=25,
                call_metadata=metadata,
            )

            entry = json.loads(logger.log_file.read_text().strip())
            self.assertEqual(entry["prompt_type"], "status_update")
            self.assertEqual(entry["call_metadata"], metadata)
            self.assertEqual(entry["total_tokens"], 46)

    def test_log_llm_call_persists_routing_provenance_and_flat_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            provenance = {
                "tool_policy": "none",
                "tool_rag_skipped": True,
                "auto_context": {
                    "enabled": False,
                    "source": "none",
                    "applied": False,
                },
                "memory_injection": {
                    "enabled": True,
                    "injected": False,
                    "threshold": 0.52,
                    "limit": 2,
                    "candidate_count": 3,
                    "injected_count": 0,
                    "top_candidates": [{"key": "gift_memory", "score": 0.41}],
                },
                "learning_insights": {
                    "injected": True,
                    "insight_count": 2,
                    "insight_descriptions": ["Prefer serpapi_amazon_search first."],
                },
            }
            logger.log_llm_call(
                provider="xai",
                model="grok-test",
                prompt_type="routing",
                messages=[{"role": "user", "content": "test"}],
                response_text="hello",
                tool_call=None,
                usage_info=None,
                thinking=None,
                duration_ms=12.5,
                mode="cloud",
                user_query="test query",
                routing_provenance=provenance,
                error=None,
            )

            lines = logger.log_file.read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["routing_provenance"], provenance)
            self.assertEqual(entry["routing_provenance"]["tool_policy"], "none")
            self.assertTrue(entry["routing_provenance"]["tool_rag_skipped"])
            self.assertFalse(entry["auto_context_applied"])
            self.assertFalse(entry["memory_injected"])
            self.assertEqual(entry["memory_candidate_count"], 3)
            self.assertEqual(entry["memory_injected_count"], 0)
            self.assertTrue(entry["learning_insights_injected"])
            self.assertEqual(entry["learning_insight_count"], 2)

    def test_openai_responses_cache_fields_do_not_set_xai_continuation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            provenance = {
                "provider_route": {
                    "provider_continuation_mode": "responses_structural",
                    "provider_previous_response_id_present": True,
                    "provider_previous_response_id_used": True,
                    "openai_responses_continuation_mode": "responses_structural",
                    "openai_responses_previous_id_present": True,
                    "openai_responses_previous_id_used": True,
                    "openai_prompt_cache_key_set": True,
                }
            }
            logger.log_llm_call(
                provider="openai",
                model="gpt-5.4-mini",
                prompt_type="routing",
                messages=[],
                response_text=None,
                tool_call={"name": "semantic_recall", "arguments": {}},
                usage_info={
                    "input_tokens": 12520,
                    "output_tokens": 43,
                    "total_tokens": 12563,
                    "cached_input_tokens": 1024,
                    "cached_prompt_text_tokens": 1024,
                    "cache_read_tokens": 1024,
                    "cache_hit": True,
                },
                thinking=None,
                duration_ms=12.5,
                mode="cloud",
                user_query="test query",
                routing_provenance=provenance,
                error=None,
            )

            entry = json.loads(logger.log_file.read_text().strip())
            self.assertEqual(entry["openai_cached_input_tokens"], 1024)
            self.assertEqual(entry["cached_input_tokens"], 1024)
            self.assertEqual(entry["cached_prompt_text_tokens"], 1024)
            self.assertTrue(entry["openai_cache_hit"])
            self.assertTrue(entry["openai_responses_previous_id_used"])
            self.assertTrue(entry["provider_previous_response_id_used"])
            self.assertNotIn("xai_previous_response_id_used", entry)
            self.assertNotIn("xai_continuation_mode", entry)

    def test_xai_logs_do_not_include_openai_specific_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            provenance = {
                "provider_route": {
                    "provider_continuation_mode": "stored_structural",
                    "provider_previous_response_id_present": True,
                    "provider_previous_response_id_used": True,
                    "xai_continuation_mode": "stored_structural",
                    "xai_previous_response_id_present": True,
                    "xai_previous_response_id_used": True,
                }
            }
            logger.log_llm_call(
                provider="xai",
                model="grok-test",
                prompt_type="routing",
                messages=[],
                response_text="ok",
                tool_call=None,
                usage_info={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "prompt_text_tokens": 10,
                    "cached_prompt_text_tokens": 4,
                    "server_side_tools": {"SERVER_SIDE_TOOL_WEB_SEARCH": 1},
                },
                thinking=None,
                duration_ms=12.5,
                mode="cloud",
                user_query="test query",
                routing_provenance=provenance,
                error=None,
            )

            entry = json.loads(logger.log_file.read_text().strip())
            self.assertEqual(entry["xai_cached_prompt_text_tokens"], 4)
            self.assertTrue(entry["xai_previous_response_id_used"])
            self.assertEqual(entry["xai_search_calls"], 1)
            self.assertNotIn("openai_cached_input_tokens", entry)
            self.assertNotIn("openai_responses_previous_id_used", entry)
            self.assertNotIn("openai_server_side_tool_calls", entry)

    def test_anthropic_cache_cost_breakdown_is_flattened_for_auditing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            logger.log_llm_call(
                provider="anthropic",
                model="claude-fable-5",
                prompt_type="routing",
                messages=[],
                response_text="hello",
                tool_call=None,
                usage_info={
                    "input_tokens": 660,
                    "output_tokens": 76,
                    "total_tokens": 25_209,
                    "cost_usd": 0.316313,
                    "cache_creation_tokens": 24_473,
                    "cache_creation_5m_tokens": 24_473,
                    "cache_creation_1h_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_cost_usd": 0.305913,
                    "cache_read_cost_usd": 0.0,
                    "cache_cost_usd": 0.305913,
                },
                thinking=None,
                duration_ms=12.5,
                mode="cloud",
                user_query="hello",
                error=None,
            )

            entry = json.loads(logger.log_file.read_text().strip())
            self.assertEqual(entry["cache_creation_tokens"], 24_473)
            self.assertEqual(entry["cache_creation_5m_tokens"], 24_473)
            self.assertEqual(entry["cache_write_cost_usd"], 0.305913)
            self.assertEqual(entry["cost_usd"], 0.316313)


if __name__ == "__main__":
    unittest.main()
