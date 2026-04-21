#!/usr/bin/env python3
"""Regression tests for Intelligence insight provenance and soft tool sequences."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from intelligence import IntelligenceLayer
from intelligence_hooks import format_insights_for_prompt


class IntelligenceProvenanceTests(unittest.TestCase):
    def _make_intel(self, tmpdir: str) -> IntelligenceLayer:
        intel = IntelligenceLayer(str(Path(tmpdir) / "intel.db"))
        intel._get_embedding = lambda text: np.array([1.0, 0.25, 0.5])
        return intel

    def _record_experience(self, intel: IntelligenceLayer, query: str, tools: list[str]):
        return asyncio.run(
            intel.record_experience(
                query=query,
                tools_used=tools,
                outcome={"success": True, "turns": len(tools)},
                context={
                    "web_conversation_id": "web-abc123",
                    "available_tools": ["youtube_transcript", "youtube_video", "send_email"],
                },
            )
        )

    def test_store_insight_records_source_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = self._record_experience(
                intel,
                "email this youtube video to my wife",
                ["youtube_video", "send_email"],
            )
            experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()

            insight_id = asyncio.run(
                intel._store_insight(
                    {
                        "is_procedural": True,
                        "knowledge_type": "procedural",
                        "insight_type": "tool_preference",
                        "constraint_type": "positive",
                        "trigger_concept": "send youtube video",
                        "trigger_signals": ["send", "email", "youtube"],
                        "preferred_tool": "send_email",
                        "preferred_tool_sequence": ["youtube_video", "send_email"],
                        "supporting_tools": ["youtube_video"],
                        "sequence_required": False,
                        "primary_intent": "send video link by email",
                        "applies_to": "Sending YouTube links to contacts",
                        "generalizability": "medium",
                        "confidence": 0.8,
                        "insight_summary": "For sending YouTube links, use send_email as the primary action tool.",
                    },
                    experience,
                )
            )

            insight = intel.conn.execute(
                "SELECT * FROM insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
            evidence = intel.conn.execute(
                "SELECT * FROM insight_evidence WHERE insight_id = ?",
                (insight_id,),
            ).fetchone()

            self.assertEqual(insight["source_experience_id"], exp_id)
            self.assertEqual(insight["source_web_conversation_id"], "web-abc123")
            self.assertEqual(json.loads(insight["source_tool_sequence"]), ["youtube_video", "send_email"])
            self.assertEqual(json.loads(insight["preferred_tools"]), {"send_email": 0.8})
            self.assertEqual(json.loads(insight["preferred_tool_sequence"]), ["youtube_video", "send_email"])
            self.assertEqual(json.loads(insight["supporting_tools"]), ["youtube_video"])
            self.assertEqual(json.loads(insight["trigger_signals"]), ["send", "email", "youtube"])
            self.assertEqual(insight["sequence_required"], 0)
            self.assertEqual(evidence["action"], "created")
            self.assertEqual(evidence["experience_id"], exp_id)
            self.assertEqual(evidence["web_conversation_id"], "web-abc123")

    def test_record_experience_stamps_raw_context_experience_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query="hello",
                    tools_used=[],
                    outcome={"success": True, "turns": 0},
                    context={"experience_id": None, "web_conversation_id": "web-raw"},
                )
            )
            raw = intel.conn.execute(
                "SELECT raw_data FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()["raw_data"]
            raw_data = json.loads(raw)

            self.assertEqual(raw_data["context"]["experience_id"], exp_id)
            self.assertEqual(raw_data["context"]["web_conversation_id"], "web-raw")

    def test_migration_backfills_raw_context_and_guard_experience_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "intel.db"
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query="hello",
                    tools_used=[],
                    outcome={"success": True, "turns": 0},
                    context={"experience_id": None},
                )
            )
            raw_data = {
                "query": "hello",
                "context": {"experience_id": None},
                "completion_guard": {"status": "accepted", "experience_id": None},
            }
            intel.conn.execute(
                "UPDATE experiences SET raw_data = ? WHERE id = ?",
                (json.dumps(raw_data), exp_id),
            )
            intel.conn.commit()
            intel.close()

            reopened = IntelligenceLayer(str(db_path))
            reopened._get_embedding = lambda text: np.array([1.0, 0.25, 0.5])
            raw = reopened.conn.execute(
                "SELECT raw_data FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()["raw_data"]
            repaired = json.loads(raw)

            self.assertEqual(repaired["context"]["experience_id"], exp_id)
            self.assertEqual(repaired["completion_guard"]["experience_id"], exp_id)
            reopened.close()

    def test_similar_insight_with_different_preferred_tool_does_not_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            first_exp_id = self._record_experience(
                intel,
                "what is this youtube video about",
                ["youtube_transcript"],
            )
            first_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (first_exp_id,),
            ).fetchone()
            second_exp_id = self._record_experience(
                intel,
                "email this youtube video to my wife",
                ["send_email"],
            )
            second_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (second_exp_id,),
            ).fetchone()

            base = {
                "is_procedural": True,
                "knowledge_type": "procedural",
                "insight_type": "tool_preference",
                "constraint_type": "positive",
                "trigger_concept": "youtube video",
                "applies_to": "YouTube video requests",
                "generalizability": "medium",
                "confidence": 0.9,
                "insight_summary": "For YouTube video requests, choose the tool that matches the user's primary intent.",
            }
            first_id = asyncio.run(
                intel._store_insight(
                    {**base, "preferred_tool": "youtube_transcript"},
                    first_experience,
                )
            )
            second_id = asyncio.run(
                intel._store_insight(
                    {**base, "preferred_tool": "send_email", "primary_intent": "send video link by email"},
                    second_experience,
                )
            )

            self.assertNotEqual(first_id, second_id)
            insight_count = intel.conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            evidence_count = intel.conn.execute("SELECT COUNT(*) FROM insight_evidence").fetchone()[0]
            self.assertEqual(insight_count, 2)
            self.assertEqual(evidence_count, 2)

    def test_merge_backfills_blank_source_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            first_exp_id = self._record_experience(
                intel,
                "get bitcoin price and make a canvas",
                ["crypto_price", "canvas"],
            )
            first_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (first_exp_id,),
            ).fetchone()

            reflection = {
                "is_procedural": True,
                "knowledge_type": "procedural",
                "insight_type": "tool_preference",
                "constraint_type": "positive",
                "trigger_concept": "crypto price canvas",
                "trigger_signals": ["bitcoin price", "canvas"],
                "preferred_tool": "crypto_price",
                "preferred_tool_sequence": ["crypto_price", "canvas"],
                "sequence_required": True,
                "primary_intent": "live crypto prices + canvas visualization",
                "applies_to": "Crypto price and canvas requests",
                "generalizability": "medium",
                "confidence": 0.9,
                "insight_summary": "For crypto price + canvas requests, sequence crypto_price then canvas.",
            }

            insight_id = asyncio.run(intel._store_insight(reflection, first_experience))
            intel.conn.execute(
                """
                UPDATE insights
                SET source_experience_id = NULL,
                    source_web_conversation_id = NULL,
                    source_query = NULL,
                    source_tool_sequence = NULL,
                    source_reflection_json = NULL
                WHERE id = ?
                """,
                (insight_id,),
            )
            intel.conn.commit()

            second_exp_id = asyncio.run(
                intel.record_experience(
                    query="can you get current solana price and create a canvas page",
                    tools_used=["crypto_price", "canvas"],
                    outcome={"success": True, "turns": 2},
                    context={"web_conversation_id": "web-new456"},
                )
            )
            second_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (second_exp_id,),
            ).fetchone()

            merged_id = asyncio.run(intel._store_insight(reflection, second_experience))
            insight = intel.conn.execute(
                "SELECT * FROM insights WHERE id = ?",
                (merged_id,),
            ).fetchone()
            evidence_count = intel.conn.execute(
                "SELECT COUNT(*) FROM insight_evidence WHERE insight_id = ?",
                (merged_id,),
            ).fetchone()[0]

            self.assertEqual(merged_id, insight_id)
            self.assertEqual(evidence_count, 2)
            self.assertEqual(insight["source_experience_id"], second_exp_id)
            self.assertEqual(insight["source_web_conversation_id"], "web-new456")
            self.assertIn("current solana price", insight["source_query"])
            self.assertEqual(json.loads(insight["source_tool_sequence"]), ["crypto_price", "canvas"])

    def test_non_required_sequence_is_not_injected_into_routing_prompt(self):
        prompt = format_insights_for_prompt({
            "insights": [
                {
                    "id": 1,
                    "description": "Use send_email as the primary action for sending video links.",
                    "applies_to": "Sending YouTube links",
                    "constraint_type": "positive",
                    "preferred_tools": {"send_email": 0.8},
                    "preferred_tool_sequence": ["youtube_video", "send_email"],
                    "sequence_required": False,
                }
            ],
            "tool_biases": {"send_email": 0.8},
        }, available_tools=["youtube_video", "send_email"])

        self.assertIn("PREFER: send_email", prompt)
        self.assertNotIn("youtube_video → send_email", prompt)

    def test_required_sequence_is_injected_into_routing_prompt(self):
        prompt = format_insights_for_prompt({
            "insights": [
                {
                    "id": 1,
                    "description": "Use the two-step lookup when the second tool requires the first result.",
                    "applies_to": "Dependent tool workflows",
                    "constraint_type": "positive",
                    "preferred_tools": {"youtube_video": 0.8},
                    "preferred_tool_sequence": ["youtube_transcript", "youtube_video"],
                    "sequence_required": True,
                }
            ],
            "tool_biases": {"youtube_video": 0.8},
        }, available_tools=["youtube_transcript", "youtube_video"])

        self.assertIn("Required sequence: youtube_transcript → youtube_video", prompt)

    def test_suppressed_native_search_preference_does_not_merge_into_old_search_tool_bias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            first_exp_id = asyncio.run(
                intel.record_experience(
                    query="fresh movie listings",
                    tools_used=["mcp_brave_search_brave_web_search"],
                    outcome={"success": True, "turns": 1},
                    context={"web_conversation_id": "web-old"},
                )
            )
            first_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (first_exp_id,),
            ).fetchone()
            second_exp_id = asyncio.run(
                intel.record_experience(
                    query="fresh movie listings",
                    tools_used=["mcp_brave_search_brave_web_search"],
                    outcome={"success": True, "turns": 1},
                    context={
                        "web_conversation_id": "web-native",
                        "provider_native_tools_used": ["native:x_search"],
                    },
                )
            )
            second_experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (second_exp_id,),
            ).fetchone()

            reflection = {
                "is_procedural": True,
                "knowledge_type": "procedural",
                "insight_type": "tool_preference",
                "constraint_type": "positive",
                "trigger_concept": "fresh web lookup",
                "preferred_tool": "mcp_brave_search_brave_web_search",
                "applies_to": "Fresh web lookups",
                "generalizability": "medium",
                "confidence": 0.8,
                "insight_summary": "For fresh web lookups, prefer the decisive evidence path.",
            }

            first_id = asyncio.run(intel._store_insight(reflection, first_experience))
            second_id = asyncio.run(intel._store_insight(reflection, second_experience))

            self.assertNotEqual(first_id, second_id)
            second = intel.conn.execute(
                "SELECT preferred_tools, source_web_conversation_id FROM insights WHERE id = ?",
                (second_id,),
            ).fetchone()
            self.assertEqual(json.loads(second["preferred_tools"]), {})
            self.assertEqual(second["source_web_conversation_id"], "web-native")


if __name__ == "__main__":
    unittest.main()
