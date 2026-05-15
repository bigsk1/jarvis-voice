#!/usr/bin/env python3
"""Regression tests for secret redaction before Intelligence persistence."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

import intelligence_hooks
from intelligence import IntelligenceLayer
from intelligence_hooks import (
    record_interaction,
    update_experience_from_completion_guard,
    update_experience_from_feedback,
)
from security_utils import redact_sensitive_data, redact_sensitive_text


SECRET = "sk-testsecret12345678901234567890"


class IntelligenceRedactionTests(unittest.TestCase):
    def test_redact_sensitive_text_preserves_email_but_redacts_secrets(self):
        text = (
            "email person@example.com with api_key=sk-testsecret12345678901234567890 "
            "and Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
        )

        redacted = redact_sensitive_text(text)

        self.assertIn("person@example.com", redacted)
        self.assertNotIn("sk-testsecret", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertIn("api_key=[redacted]", redacted)
        self.assertIn("Authorization: Bearer [redacted]", redacted)

    def test_redact_sensitive_data_redacts_secret_keys_not_token_counts(self):
        data = {
            "api_key": SECRET,
            "nested": {"password": "super-secret", "input_tokens": 123},
            "message": "secret key 'dev-secret-123'",
        }

        redacted = redact_sensitive_data(data)

        self.assertEqual(redacted["api_key"], "[redacted]")
        self.assertEqual(redacted["nested"]["password"], "[redacted]")
        self.assertEqual(redacted["nested"]["input_tokens"], 123)
        self.assertNotIn("dev-secret-123", redacted["message"])

    def test_record_experience_redacts_query_context_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = IntelligenceLayer(str(Path(tmpdir) / "intel.db"))
            intel._get_embedding = lambda text: np.array([1.0, 0.5])

            exp_id = asyncio.run(
                intel.record_experience(
                    query=f"remember api_key={SECRET} and email person@example.com",
                    tools_used=["api_call"],
                    outcome={"success": True, "error": f"Authorization: Bearer {SECRET}"},
                    context={
                        "web_conversation_id": "web-redact",
                        "tool_results": {"headers": {"Authorization": f"Bearer {SECRET}"}},
                    },
                )
            )
            row = intel.conn.execute("SELECT * FROM experiences WHERE id = ?", (exp_id,)).fetchone()
            raw = json.loads(row["raw_data"])

            self.assertNotIn(SECRET, row["query"])
            self.assertIn("person@example.com", row["query"])
            self.assertNotIn(SECRET, row["raw_data"])
            self.assertEqual(raw["context"]["tool_results"]["headers"]["Authorization"], "[redacted]")

            insight_id = asyncio.run(
                intel._store_insight(
                    {
                        "is_procedural": True,
                        "knowledge_type": "procedural",
                        "preferred_tool": "api_call",
                        "applies_to": "API requests",
                        "generalizability": "medium",
                        "confidence": 0.8,
                        "why_or_why_not": f"Used token {SECRET}",
                        "insight_summary": f"For API requests, never store api_key={SECRET}.",
                    },
                    row,
                )
            )
            insight = intel.conn.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
            evidence = intel.conn.execute(
                "SELECT * FROM insight_evidence WHERE insight_id = ?",
                (insight_id,),
            ).fetchone()

            self.assertNotIn(SECRET, insight["description"])
            self.assertNotIn(SECRET, insight["reasoning"])
            self.assertNotIn(SECRET, insight["source_reflection_json"])
            self.assertNotIn(SECRET, evidence["reflection_json"])

    def test_hooks_redact_interaction_feedback_and_completion_guard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = IntelligenceLayer(str(Path(tmpdir) / "intel.db"))
            intel._get_embedding = lambda text: np.array([1.0, 0.5])

            old_layer = intelligence_hooks._intelligence_layer
            old_checked = intelligence_hooks._intelligence_checked
            intelligence_hooks._intelligence_layer = intel
            intelligence_hooks._intelligence_checked = True
            self.addCleanup(setattr, intelligence_hooks, "_intelligence_layer", old_layer)
            self.addCleanup(setattr, intelligence_hooks, "_intelligence_checked", old_checked)

            exp_id = record_interaction(
                query=f"call API with password={SECRET}",
                tools_used=["api_call"],
                result={
                    "ok": True,
                    "speech": f"Done with token {SECRET}",
                    "data": {"api_key": SECRET, "result": "ok"},
                    "tool_trace": [{"tool": "api_call", "arguments": {"Authorization": f"Bearer {SECRET}"}}],
                },
            )
            self.assertGreater(exp_id, 0)
            row = intel.conn.execute("SELECT raw_data FROM experiences WHERE id = ?", (exp_id,)).fetchone()
            self.assertNotIn(SECRET, row["raw_data"])

            self.assertTrue(
                update_experience_from_feedback(
                    exp_id,
                    2,
                    feedback_summary=f"Leaked secret {SECRET}",
                    feedback_details={"analysis": f"password={SECRET}"},
                )
            )
            self.assertTrue(
                update_experience_from_completion_guard(
                    exp_id,
                    "repaired",
                    note=f"Repaired token {SECRET}",
                    metadata={
                        "operational_correction": True,
                        "repair_result": {"raw_llm_response": f"Fixed bearer {SECRET}"},
                        "repair_data": {"headers": {"Authorization": f"Bearer {SECRET}"}},
                    },
                )
            )
            row = intel.conn.execute("SELECT raw_data FROM experiences WHERE id = ?", (exp_id,)).fetchone()
            self.assertNotIn(SECRET, row["raw_data"])
            self.assertIn("[redacted]", row["raw_data"])


if __name__ == "__main__":
    unittest.main()
