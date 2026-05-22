#!/usr/bin/env python3
"""
Regression tests for intelligence-layer handling of provider-native server-side tools.

Run:
    python3 tests/test_intelligence_server_side_tools.py
"""

import sys
import types
import unittest
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

fake_numpy = types.ModuleType("numpy")
fake_numpy.ndarray = list
sys.modules.setdefault("numpy", fake_numpy)

import intelligence_hooks
from intelligence_hooks import (
    _evaluate_insight_helpfulness,
    extract_user_correction_signals,
    normalize_server_side_tools_for_reflection,
    record_user_correction_shadow_candidate,
    update_experience_from_user_correction,
    update_experience_from_feedback,
)
from intelligence import should_suppress_preferred_tool_for_native_search
from orchestrator_v2 import Orchestrator


class IntelligenceServerSideToolsTests(unittest.TestCase):
    def _install_fake_intel(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outcome_success BOOLEAN,
                user_satisfied BOOLEAN,
                had_to_retry BOOLEAN,
                had_to_clarify BOOLEAN,
                raw_data TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE reflection_queue (
                experience_id INTEGER,
                priority REAL DEFAULT 0.5
            )
        """)

        class FakeIntel:
            pass

        fake_intel = FakeIntel()
        fake_intel.conn = conn

        old_layer = intelligence_hooks._intelligence_layer
        old_checked = intelligence_hooks._intelligence_checked
        intelligence_hooks._intelligence_layer = fake_intel
        intelligence_hooks._intelligence_checked = True
        self.addCleanup(setattr, intelligence_hooks, "_intelligence_layer", old_layer)
        self.addCleanup(setattr, intelligence_hooks, "_intelligence_checked", old_checked)
        return conn

    def _insert_experience(self, conn, raw_data=None, outcome_success=1, user_satisfied=0, had_to_retry=0, priority=0.4):
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO experiences (outcome_success, user_satisfied, had_to_retry, had_to_clarify, raw_data)
            VALUES (?, ?, ?, 0, ?)
        """, (
            outcome_success,
            user_satisfied,
            had_to_retry,
            json.dumps(raw_data or {}),
        ))
        exp_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO reflection_queue (experience_id, priority) VALUES (?, ?)",
            (exp_id, priority),
        )
        conn.commit()
        return exp_id

    def test_normalize_server_side_tools_for_reflection(self):
        normalized = normalize_server_side_tools_for_reflection({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_VIEW_IMAGE": 1,
            "SERVER_SIDE_TOOL_CODE_INTERPRETER": 1,
        })

        self.assertEqual(
            normalized,
            ["native:x_search", "native:x_search", "native:view_image", "native:code_interpreter"]
        )

    def test_extract_user_correction_signals(self):
        signals = extract_user_correction_signals("No, what I meant was Portland OR, not Portland ME")

        self.assertTrue(signals["is_correction"])
        self.assertTrue(signals["had_to_clarify"])
        self.assertIn("clarification", signals["categories"])

    def test_extract_user_correction_ignores_topic_pivot(self):
        signals = extract_user_correction_signals("I meant to ask about something else entirely")

        self.assertFalse(signals["is_correction"])
        self.assertEqual(signals["categories"], [])

    def test_user_correction_marks_previous_experience_for_reflection(self):
        conn = self._install_fake_intel()
        exp_id = self._insert_experience(
            conn,
            raw_data={"context": {"final_speech": "Portland, Maine details"}},
            outcome_success=1,
            user_satisfied=1,
            had_to_retry=0,
            priority=0.2,
        )

        updated = update_experience_from_user_correction(
            previous_experience_id=exp_id,
            correction_query="No, I meant Portland OR, not Portland ME.",
        )

        self.assertTrue(updated)
        row = conn.execute("SELECT * FROM experiences WHERE id = ?", (exp_id,)).fetchone()
        self.assertEqual(row["outcome_success"], 0)
        self.assertEqual(row["user_satisfied"], 0)
        self.assertEqual(row["had_to_retry"], 1)
        self.assertEqual(row["had_to_clarify"], 1)

        raw_data = json.loads(row["raw_data"])
        self.assertEqual(raw_data["user_correction"]["latest"]["source"], "next_turn_user_correction")
        self.assertTrue(raw_data["user_signals"]["cross_turn_correction"])

        priority = conn.execute(
            "SELECT priority FROM reflection_queue WHERE experience_id = ?",
            (exp_id,),
        ).fetchone()["priority"]
        self.assertEqual(priority, 0.9)

    def test_shadow_candidate_persists_link_to_previous_experience(self):
        conn = self._install_fake_intel()
        previous_id = self._insert_experience(
            conn,
            raw_data={"context": {"final_speech": "Portland, Maine details"}},
            outcome_success=1,
            user_satisfied=1,
            had_to_retry=0,
            priority=0.2,
        )
        current_id = self._insert_experience(
            conn,
            raw_data={},
            outcome_success=1,
            user_satisfied=0,
            had_to_retry=0,
            priority=0.2,
        )

        updated = record_user_correction_shadow_candidate(
            current_experience_id=current_id,
            previous_experience_id=previous_id,
            correction_query="No, I meant Portland OR, not Portland ME.",
        )

        self.assertTrue(updated)
        row = conn.execute("SELECT raw_data FROM experiences WHERE id = ?", (current_id,)).fetchone()
        raw_data = json.loads(row["raw_data"])
        self.assertEqual(
            raw_data["user_correction_shadow"]["latest"]["previous_experience_id"],
            previous_id,
        )
        self.assertEqual(raw_data["user_signals"]["previous_experience_id_candidate"], previous_id)
        self.assertTrue(raw_data["user_signals"]["cross_turn_correction_candidate"])

        previous_row = conn.execute(
            "SELECT outcome_success FROM experiences WHERE id = ?",
            (previous_id,),
        ).fetchone()
        self.assertEqual(previous_row["outcome_success"], 1)

    def test_suppresses_external_search_preference_when_native_search_was_used(self):
        experience = {
            "final_tool": "mcp_brave_search_brave_web_search",
            "raw_data": '{"context":{"provider_native_tools_used":["native:x_search"]}}',
        }
        reflection = {
            "preferred_tool": "mcp_brave_search_brave_web_search",
            "insight_summary": "Use X-targeted search first for recent X media lookups.",
        }

        self.assertTrue(
            should_suppress_preferred_tool_for_native_search(reflection, experience)
        )

    def test_does_not_suppress_non_search_tool_preference(self):
        experience = {
            "final_tool": "canvas",
            "raw_data": '{"context":{"provider_native_tools_used":["native:web_search"]}}',
        }
        reflection = {
            "preferred_tool": "canvas",
            "insight_summary": "Save the final comparison to canvas after research.",
        }

        self.assertFalse(
            should_suppress_preferred_tool_for_native_search(reflection, experience)
        )

    def test_positive_insight_requires_preferred_tool_usage_when_present(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_news_search": 1.0},
        }

        self.assertFalse(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=["mcp_brave_search_brave_web_search"],
                outcome_success=True,
                result={"ok": True},
            )
        )

    def test_positive_insight_success_with_preferred_tool_is_helpful(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_web_search": 1.0},
        }

        self.assertTrue(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=["mcp_brave_search_brave_web_search"],
                outcome_success=True,
                result={
                    "ok": True,
                    "tool_trace": [
                        {"tool": "mcp_brave_search_brave_web_search", "ok": True},
                    ],
                },
            )
        )

    def test_positive_insight_with_preferred_tool_failure_is_not_helpful_after_recovery(self):
        insight = {
            "constraint_type": "positive",
            "preferred_tools": {"mcp_brave_search_brave_news_search": 1.0},
        }

        self.assertFalse(
            _evaluate_insight_helpfulness(
                insight,
                tools_used=[
                    "mcp_brave_search_brave_news_search",
                    "mcp_brave_search_brave_web_search",
                ],
                outcome_success=True,
                result={
                    "ok": True,
                    "tool_trace": [
                        {
                            "tool": "mcp_brave_search_brave_news_search",
                            "ok": False,
                            "error": "Invalid arguments for tool brave_news_search",
                        },
                        {"tool": "mcp_brave_search_brave_web_search", "ok": True},
                    ],
                },
            )
        )

    def test_tool_trace_argument_sanitizer_redacts_and_truncates(self):
        sanitized = Orchestrator._sanitize_tool_trace_value({
            "query": "short search",
            "api_key": "secret-value",
            "headers": {"Authorization": "Bearer secret"},
            "prompt": "x" * 400,
            "items": list(range(25)),
        })

        self.assertEqual(sanitized["query"], "short search")
        self.assertEqual(sanitized["api_key"], "[redacted]")
        self.assertEqual(sanitized["headers"]["Authorization"], "[redacted]")
        self.assertTrue(sanitized["prompt"].endswith("... [truncated]"))
        self.assertEqual(len(sanitized["items"]), 21)
        self.assertEqual(sanitized["items"][-1], "[truncated 5 more item(s)]")

    def test_feedback_low_rating_marks_failure_and_preserves_completion_guard_metadata(self):
        conn = self._install_fake_intel()
        exp_id = self._insert_experience(
            conn,
            raw_data={
                "completion_guard": {"status": "accepted", "note": "looked fine"},
                "context": {"final_speech": "Old answer"},
            },
            outcome_success=1,
            user_satisfied=1,
            had_to_retry=0,
            priority=0.2,
        )

        updated = update_experience_from_feedback(
            experience_id=exp_id,
            feedback_rating=2,
            feedback_summary="Missed the user's actual request.",
            feedback_details={
                "issues": [{"category": "accuracy", "description": "Wrong target"}],
                "analysis": "The answer was fluent but incorrect.",
                "completion_guard_status": "accepted",
            },
        )

        self.assertTrue(updated)
        row = conn.execute("SELECT * FROM experiences WHERE id = ?", (exp_id,)).fetchone()
        self.assertEqual(row["outcome_success"], 0)
        self.assertEqual(row["user_satisfied"], 0)
        self.assertEqual(row["had_to_retry"], 1)

        raw_data = json.loads(row["raw_data"])
        self.assertEqual(raw_data["completion_guard"]["status"], "accepted")
        self.assertEqual(raw_data["feedback"]["latest"]["rating"], 2)
        self.assertEqual(raw_data["feedback"]["latest"]["summary"], "Missed the user's actual request.")
        self.assertEqual(raw_data["feedback"]["latest"]["completion_guard_status"], "accepted")

        priority = conn.execute(
            "SELECT priority FROM reflection_queue WHERE experience_id = ?",
            (exp_id,),
        ).fetchone()["priority"]
        self.assertEqual(priority, 0.8)

    def test_feedback_high_rating_marks_satisfied_without_erasing_repair_signal(self):
        conn = self._install_fake_intel()
        exp_id = self._insert_experience(
            conn,
            raw_data={"completion_guard": {"status": "repaired"}},
            outcome_success=1,
            user_satisfied=0,
            had_to_retry=1,
            priority=0.85,
        )

        updated = update_experience_from_feedback(
            experience_id=exp_id,
            feedback_rating=5,
            feedback_summary="Settled answer is good.",
        )

        self.assertTrue(updated)
        row = conn.execute("SELECT * FROM experiences WHERE id = ?", (exp_id,)).fetchone()
        self.assertEqual(row["outcome_success"], 1)
        self.assertEqual(row["user_satisfied"], 1)
        self.assertEqual(row["had_to_retry"], 1)

        raw_data = json.loads(row["raw_data"])
        self.assertEqual(raw_data["completion_guard"]["status"], "repaired")
        self.assertEqual(raw_data["feedback"]["latest"]["rating"], 5)


if __name__ == "__main__":
    unittest.main()
