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
    def test_log_llm_call_persists_routing_provenance_and_flat_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = LLMLogger(log_dir=tmpdir)
            provenance = {
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
                    "insight_descriptions": ["Prefer serpapi_search first."],
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
            self.assertFalse(entry["auto_context_applied"])
            self.assertFalse(entry["memory_injected"])
            self.assertEqual(entry["memory_candidate_count"], 3)
            self.assertEqual(entry["memory_injected_count"], 0)
            self.assertTrue(entry["learning_insights_injected"])
            self.assertEqual(entry["learning_insight_count"], 2)


if __name__ == "__main__":
    unittest.main()
