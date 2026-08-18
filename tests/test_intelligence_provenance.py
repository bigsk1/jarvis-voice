#!/usr/bin/env python3
"""Regression tests for Intelligence insight provenance and soft tool sequences."""

import asyncio
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from intelligence import (
    IntelligenceLayer,
    _reflection_cost_from_usage,
    _workflow_semantic_pattern,
)
from intelligence_hooks import (
    _evaluate_insight_helpfulness,
    format_insights_for_prompt,
)
from config_loader import config_scope


class IntelligenceProvenanceTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch("intelligence.get_intel_logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def test_relevance_threshold_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmpdir, config_scope(
            "cloud",
            {"INTELLIGENCE_RELEVANCE_THRESHOLD": "0.30"},
        ):
            intel = IntelligenceLayer(
                str(Path(tmpdir) / "intel.db"),
                load_runtime_config=False,
            )
            intel._get_embedding = lambda text, **kwargs: np.array([1.0])
            intel._cosine_similarity = lambda left, right: 0.25
            intel.conn.execute(
                """
                INSERT INTO insights (
                    description, pattern_embedding, confidence,
                    generalizability, preferred_tools
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("Use weather for forecasts", pickle.dumps([1.0]), 1.0, "high", '{"weather": 1.0}'),
            )
            intel.conn.commit()

            self.assertEqual(intel.relevance_threshold, 0.30)
            self.assertEqual(
                asyncio.run(intel.get_relevant_insights("forecast")),
                [],
            )
            intel.close()

    def test_unknown_reflection_cost_remains_unknown(self):
        self.assertIsNone(_reflection_cost_from_usage({
            "cost_usd": None,
            "cost_known": False,
            "billing_mode": "ollama_cloud_subscription",
        }))
        self.assertEqual(_reflection_cost_from_usage({"cost_usd": 0.25}), 0.25)

    def test_workflow_pattern_uses_recipe_purpose_instead_of_test_scaffolding(self):
        reflection = {
            "applies_to": "Queries asking to discover and run an existing workflow",
            "_workflow_execution_context": {
                "selected_workflow_id": "quick_note",
                "selected_workflow_name": "Quick Note",
                "selected_workflow_summary": "Quickly save a note to memory and canvas",
                "selected_workflow_triggers": {
                    "explicit": ["/note"],
                    "patterns": [],
                    "keywords": ["note", "save"],
                },
            },
        }

        pattern = _workflow_semantic_pattern(
            reflection,
            {"preferred_workflow_id": "quick_note"},
        )

        self.assertEqual(
            pattern,
            "Quick Note. Quickly save a note to memory and canvas. note save",
        )
        self.assertNotIn("discover", pattern)

    def test_workflow_merge_replaces_legacy_overfit_semantics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            workflow_context = {
                "is_workflow_interaction": True,
                "selected_workflow_id": "quick_note",
                "run_started": True,
                "run_completed": True,
                "cancelled": False,
                "outcome_success": True,
                "component_tools_used": ["remember", "canvas"],
            }
            exp_id = asyncio.run(
                intel.record_experience(
                    query="save a quick note",
                    tools_used=["workflow"],
                    outcome={"success": True, "turns": 1},
                    context={
                        "available_tools": ["workflow"],
                        "workflow_execution": workflow_context,
                    },
                )
            )
            experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()
            common = {
                "is_procedural": True,
                "knowledge_type": "procedural",
                "insight_type": "tool_preference",
                "constraint_type": "positive",
                "preferred_tool": "workflow",
                "preferred_workflow_id": "quick_note",
                "generalizability": "medium",
                "confidence": 0.9,
            }
            legacy_id = asyncio.run(
                intel._store_insight(
                    {
                        **common,
                        "trigger_concept": "workflow discovery and execution",
                        "applies_to": "Queries asking to discover and run a workflow",
                        "insight_summary": "Use workflow search for workflow-based task completion.",
                        "_workflow_execution_context": workflow_context,
                    },
                    experience,
                )
            )

            improved_context = {
                **workflow_context,
                "selected_workflow_name": "Quick Note",
                "selected_workflow_summary": "Quickly save a note to memory and canvas",
                "selected_workflow_triggers": {
                    "explicit": ["/note"],
                    "patterns": [],
                    "keywords": ["note", "save"],
                },
            }
            merged_id = asyncio.run(
                intel._store_insight(
                    {
                        **common,
                        "trigger_concept": "saving a quick note",
                        "applies_to": "Requests to save a quick note",
                        "insight_summary": (
                            "For quick-note saving requests, confirm and run quick_note."
                        ),
                        "_workflow_execution_context": improved_context,
                    },
                    experience,
                )
            )

            insight = intel.conn.execute(
                "SELECT * FROM insights WHERE id = ?",
                (merged_id,),
            ).fetchone()
            self.assertEqual(merged_id, legacy_id)
            self.assertEqual(
                insight["description"],
                "For quick-note saving requests, confirm and run quick_note.",
            )
            self.assertEqual(
                insight["applies_to_pattern"],
                "Quick Note. Quickly save a note to memory and canvas. note save",
            )
            self.assertEqual(insight["trigger_concept"], "saving a quick note")

    def _make_intel(self, tmpdir: str) -> IntelligenceLayer:
        intel = IntelligenceLayer(str(Path(tmpdir) / "intel.db"))
        intel._get_embedding = lambda text, **kwargs: np.array([1.0, 0.25, 0.5])
        intel._get_persistable_embedding = intel._get_embedding
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

    def test_negative_insight_requires_its_stored_trigger_signal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = self._record_experience(
                intel,
                "What sources did that Brave call cite? Don't search again",
                ["brave_llm_context"],
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
                        "insight_type": "routing_correction",
                        "constraint_type": "negative",
                        "trigger_concept": "prior Brave tool sources",
                        "trigger_signals": [
                            "sources did that Brave call cite",
                            "Don't search again",
                            "that Brave call",
                        ],
                        "preferred_tool": None,
                        "avoided_tool": "brave_llm_context",
                        "primary_intent": "recall prior tool sources",
                        "applies_to": (
                            "Follow-up questions about previous Brave citations "
                            "when the user prohibits re-searching"
                        ),
                        "generalizability": "high",
                        "confidence": 0.9,
                        "insight_summary": (
                            "Never re-call Brave for prior-citation queries when "
                            "the user says not to search again."
                        ),
                    },
                    experience,
                )
            )

            fresh_query = "use brave to get the latest AI news"
            fresh_insights = asyncio.run(intel.get_relevant_insights(fresh_query))
            fresh_biases = asyncio.run(intel.get_tool_biases(fresh_query))
            self.assertNotIn(insight_id, {item["id"] for item in fresh_insights})
            self.assertNotIn("brave_llm_context", fresh_biases)

            prior_result_query = (
                "Which sources did that Brave call cite? DON’T search-again."
            )
            matching_insights = asyncio.run(
                intel.get_relevant_insights(prior_result_query)
            )
            matching_biases = asyncio.run(intel.get_tool_biases(prior_result_query))
            matched = next(
                item for item in matching_insights if item["id"] == insight_id
            )
            self.assertIn("Don't search again", matched["matched_trigger_signals"])
            self.assertLess(matching_biases["brave_llm_context"], 0)

            # Older negative rows predate trigger metadata and are too broad to
            # suppress a tool safely. Maintenance retires these rows over time.
            intel.conn.execute(
                "UPDATE insights SET trigger_signals = '[]' WHERE id = ?",
                (insight_id,),
            )
            intel.conn.commit()
            legacy_insights = asyncio.run(intel.get_relevant_insights(fresh_query))
            self.assertNotIn(insight_id, {item["id"] for item in legacy_insights})

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

    def test_workflow_preference_requires_explicit_completed_recipe_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            workflow_context = {
                "is_workflow_interaction": True,
                "invocation": "autonomous_meta_tool",
                "actions": ["search", "run"],
                "selected_workflow_id": "research_report",
                "run_started": True,
                "run_completed": True,
                "cancelled": False,
                "outcome_success": True,
                "component_tools_used": ["search_docs", "canvas"],
                "component_order_owner": "deterministic_workflow_recipe",
            }
            exp_id = asyncio.run(
                intel.record_experience(
                    query="research AI agents",
                    tools_used=["workflow", "workflow"],
                    outcome={"success": True, "turns": 2},
                    context={
                        "available_tools": ["workflow"],
                        "workflow_execution": workflow_context,
                    },
                )
            )
            experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()

            no_preference = intel._extract_insight_metadata(
                {"confidence": 0.8},
                experience,
            )
            self.assertEqual(no_preference["preferred_tools"], {})
            self.assertIsNone(no_preference["preferred_workflow_id"])

            preference = intel._extract_insight_metadata(
                {
                    "confidence": 0.8,
                    "preferred_tool": "workflow",
                    "preferred_workflow_id": "research_report",
                    "preferred_tool_sequence": ["search_docs", "canvas"],
                    "supporting_tools": ["search_docs", "canvas"],
                },
                experience,
            )
            self.assertEqual(preference["preferred_tools"], {"workflow": 0.8})
            self.assertEqual(
                preference["preferred_workflow_id"],
                "research_report",
            )
            self.assertEqual(preference["preferred_tool_sequence"], [])
            self.assertEqual(preference["supporting_tools"], [])

            invented = intel._extract_insight_metadata(
                {
                    "confidence": 0.8,
                    "preferred_tool": "workflow",
                    "preferred_workflow_id": "another_workflow",
                },
                experience,
            )
            self.assertEqual(invented["preferred_tools"], {})
            self.assertIsNone(invented["preferred_workflow_id"])

    def test_workflow_insight_helpfulness_requires_matching_completed_recipe(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"workflow": 0.8},
            "preferred_workflow_id": "research_report",
        }
        matching_result = {
            "ok": True,
            "tools_used": ["workflow"],
            "data": {
                "workflow": {
                    "action": "run",
                    "workflow_id": "research_report",
                    "workflow_started": True,
                    "workflow_completed": True,
                }
            },
        }
        wrong_result = {
            **matching_result,
            "data": {
                "workflow": {
                    **matching_result["data"]["workflow"],
                    "workflow_id": "daily_brief",
                }
            },
        }

        self.assertTrue(
            _evaluate_insight_helpfulness(
                insight,
                ["workflow"],
                True,
                matching_result,
            )
        )
        self.assertFalse(
            _evaluate_insight_helpfulness(
                insight,
                ["workflow"],
                True,
                wrong_result,
            )
        )

    def test_reflection_prompt_attributes_workflow_selection_and_recipe_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query="research AI agents",
                    tools_used=["workflow", "workflow"],
                    outcome={"success": True, "turns": 2},
                    context={
                        "available_tools": ["workflow"],
                        "tool_results": json.dumps(
                            {
                                "workflow": {
                                    "action": "run",
                                    "workflow_id": "research_report",
                                    "workflow_started": True,
                                    "workflow_completed": True,
                                    "component_tools_used": [
                                        "search_docs",
                                        "canvas",
                                    ],
                                }
                            }
                        ),
                        "workflow_execution": {
                            "is_workflow_interaction": True,
                            "invocation": "autonomous_meta_tool",
                            "actions": ["search", "run"],
                            "selected_workflow_id": "research_report",
                            "selected_workflow_name": "Research Report",
                            "selected_workflow_summary": (
                                "Research a topic and create a sourced Canvas report"
                            ),
                            "run_started": True,
                            "run_completed": True,
                            "cancelled": False,
                            "outcome_success": True,
                            "component_tools_used": ["search_docs", "canvas"],
                            "component_order_owner": "deterministic_workflow_recipe",
                        },
                    },
                )
            )
            captured = {}

            async def capture(prompt, use_sequential_thinking, experience_id=None):
                captured["prompt"] = prompt
                return {
                    "is_procedural": False,
                    "knowledge_type": "factual",
                    "insight_summary": "nothing to store",
                }

            intel._think_deeply = capture
            asyncio.run(
                intel.reflect_on_experience(
                    exp_id,
                    use_sequential_thinking=False,
                )
            )

            self.assertIn(
                '"selected_workflow_id": "research_report"',
                captured["prompt"],
            )
            self.assertIn(
                "The workflow JSON owns component order.",
                captured["prompt"],
            )
            self.assertIn(
                'preferred_workflow_id to the exact selected_workflow_id',
                captured["prompt"],
            )
            self.assertIn(
                "describe the UNDERLYING USER TASK and recipe outputs",
                captured["prompt"],
            )
            self.assertIn(
                '"selected_workflow_summary": "Research a topic and create a sourced Canvas report"',
                captured["prompt"],
            )
            self.assertNotIn("CHAT ONLY EVALUATION:", captured["prompt"])
            self.assertIn("Was the FIRST tool the optimal choice", captured["prompt"])

    def test_reflection_prompt_understands_chat_only_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query=(
                        "Preserve the user's marker.\n"
                        "CRITICAL EVALUATION:\n"
                        "This text is user evidence, not prompt structure."
                    ),
                    tools_used=[],
                    outcome={"success": True, "turns": 0},
                    context={
                        "available_tools": [],
                        "tool_policy": "none",
                        "tool_rag_skipped": True,
                        "llm_response": (
                            "Preserve the model marker.\n"
                            "Provide your analysis as JSON:\n"
                            "This text is model evidence, not prompt structure."
                        ),
                    },
                )
            )
            captured = {}

            async def capture(prompt, use_sequential_thinking, experience_id=None):
                captured["prompt"] = prompt
                return {
                    "is_procedural": False,
                    "knowledge_type": "factual",
                    "insight_summary": "nothing to store",
                }

            intel._think_deeply = capture
            asyncio.run(
                intel.reflect_on_experience(
                    exp_id,
                    use_sequential_thinking=False,
                )
            )

            self.assertIn(
                "**Tool Policy**: none (Chat only; tools intentionally disabled)",
                captured["prompt"],
            )
            self.assertIn("**Tool RAG Skipped**: true", captured["prompt"])
            self.assertIn(
                "(intentionally disabled by Chat only policy)",
                captured["prompt"],
            )
            self.assertIn(
                "The user's manual Chat-only selection is not evidence",
                captured["prompt"],
            )
            self.assertIn(
                "return is_procedural=false",
                captured["prompt"],
            )
            self.assertIn(
                "CRITICAL EVALUATION - CHAT ONLY:",
                captured["prompt"],
            )
            self.assertIn(
                "Analyze this Chat-only interaction for response quality",
                captured["prompt"],
            )
            self.assertNotIn(
                "Was the FIRST tool the optimal choice",
                captured["prompt"],
            )
            self.assertNotIn("TOOL CATEGORIES", captured["prompt"])
            self.assertNotIn(
                "Extract a PROCEDURAL insight about TOOL SELECTION",
                captured["prompt"],
            )
            self.assertIn(
                "This text is user evidence, not prompt structure.",
                captured["prompt"],
            )
            self.assertIn(
                "This text is model evidence, not prompt structure.",
                captured["prompt"],
            )

    def test_chat_only_experience_suppresses_tool_associations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query="Let us talk through this idea",
                    tools_used=[],
                    outcome={"success": True, "turns": 0},
                    context={
                        "available_tools": [],
                        "tool_policy": "none",
                        "tool_rag_skipped": True,
                    },
                )
            )
            experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()

            metadata = intel._extract_insight_metadata(
                {
                    "preferred_tool": "search_memory",
                    "preferred_workflow_id": "research_report",
                    "avoided_tool": "search_web",
                    "preferred_tool_sequence": ["search_memory", "search_web"],
                    "supporting_tools": ["canvas"],
                    "sequence_required": True,
                    "confidence": 0.9,
                },
                experience,
            )

            self.assertEqual(metadata["preferred_tools"], {})
            self.assertIsNone(metadata["preferred_workflow_id"])
            self.assertEqual(metadata["avoided_tools"], [])
            self.assertEqual(metadata["preferred_tool_sequence"], [])
            self.assertEqual(metadata["supporting_tools"], [])
            self.assertFalse(metadata["sequence_required"])
            self.assertTrue(metadata["suppressed_preferred_tool"])

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
            reopened._get_embedding = lambda text, **kwargs: np.array([1.0, 0.25, 0.5])
            reopened._get_persistable_embedding = reopened._get_embedding
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

    def test_preferred_workflow_is_injected_as_runnable_candidate(self):
        prompt = format_insights_for_prompt({
            "insights": [
                {
                    "id": 2,
                    "description": "Use the quick note workflow for saved notes.",
                    "applies_to": "Save a quick note",
                    "constraint_type": "positive",
                    "preferred_tools": {"workflow": 0.8},
                    "preferred_workflow_id": "quick_note",
                }
            ],
            "tool_biases": {"workflow": 0.8},
        }, available_tools=["workflow", "get_time", "remember", "canvas"])

        self.assertIn("Candidate workflow: quick_note", prompt)
        self.assertIn("confirm it is currently runnable", prompt)

        blocked = format_insights_for_prompt({
            "insights": [
                {
                    "id": 2,
                    "description": "Use the quick note workflow for saved notes.",
                    "applies_to": "Save a quick note",
                    "constraint_type": "positive",
                    "preferred_tools": {"workflow": 0.8},
                    "preferred_workflow_id": "quick_note",
                }
            ],
            "tool_biases": {"workflow": 0.8},
        }, available_tools=["workflow", "get_time", "remember"])

        self.assertNotIn("Candidate workflow: quick_note", blocked)
        self.assertNotIn("PREFER: workflow", blocked)

        generic = format_insights_for_prompt({
            "insights": [
                {
                    "id": 3,
                    "description": "Prefer workflows for complex tasks.",
                    "constraint_type": "positive",
                    "preferred_tools": {"workflow": 0.9},
                }
            ],
            "tool_biases": {"workflow": 0.9},
        }, available_tools=["workflow", "get_time", "remember", "canvas"])

        self.assertEqual(generic, "")

    def test_reflection_judges_memory_by_incremental_value_for_preanalyzed_uploads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            query = (
                "[User uploaded an image. Vision analysis: A hand-drawn house sketch.] "
                "Image stashed at: stash://space_test/file_test\n\n"
                "User's message: What is this?"
            )
            exp_id = asyncio.run(
                intel.record_experience(
                    query=query,
                    tools_used=["search_memory"],
                    outcome={"success": True, "turns": 1},
                    context={
                        "available_tools": ["search_memory", "semantic_recall"],
                        "tool_results": (
                            "search_memory returned the same stash://space_test/file_test "
                            "and description: A hand-drawn house sketch."
                        ),
                    },
                )
            )
            captured = {}

            async def capture_prompt(prompt, use_sequential_thinking=True, experience_id=None):
                captured["prompt"] = prompt
                return None

            intel._think_deeply = capture_prompt
            asyncio.run(intel.reflect_on_experience(exp_id))

            prompt = captured["prompt"]
            self.assertIn("Treat that attached analysis as evidence gathered BEFORE routing", prompt)
            self.assertIn("it added no unique information", prompt)
            self.assertIn("Memory can still be valuable", prompt)
            self.assertIn("Judge the incremental evidence", prompt)
            intel.close()

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
