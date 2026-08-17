#!/usr/bin/env python3
"""Tests for orchestrator auto-context prompt assembly."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


def _sqlite_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class OrchestratorAutoContextTests(unittest.TestCase):
    def test_auto_memory_injects_precise_keyword_match_independent_of_dense_threshold(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            def get_addressing_preferences(self, limit, session_id=None):
                return []

            def fts_search(self, transcript, limit):
                return []

            def fts_search_precise(self, transcript, limit):
                return [
                    {
                        "id": 4312,
                        "key": "atlas_failover_phrase",
                        "value": "The Atlas lab failover phrase is silver harbor.",
                        "category": "fact",
                        "source": "remember",
                        "metadata": {"memory_type": "fact"},
                        "importance": 8,
                        "updated_at": _sqlite_utc(datetime.now(timezone.utc)),
                    }
                ]

            def semantic_search(self, query, limit, similarity_threshold):
                return []

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "true",
                "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
            }
            return values.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()), patch(
            "orchestrator_v2.get_config_value", side_effect=fake_get_config_value
        ), patch("orchestrator_v2.get_int", side_effect=lambda key, default=0: 2), patch(
            "orchestrator_v2.get_float", return_value=0.95
        ):
            bundle = orch._get_relevant_memories_bundle(
                "What is the Atlas lab failover phrase?"
            )

        self.assertTrue(bundle["meta"]["injected"])
        self.assertIn("atlas_failover_phrase", bundle["context"])
        self.assertIn("memory_id: 4312", bundle["context"])
        self.assertIn("keyword_exact", bundle["context"])

    def test_auto_memory_meta_reports_candidates_when_none_are_injected(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            def get_addressing_preferences(self, limit, session_id=None):
                return []

            def fts_search(self, transcript, limit):
                return []

            def semantic_search(self, query, limit, similarity_threshold):
                return [
                    {
                        "key": "gift_query_memory",
                        "value": "animal gift idea notes",
                        "category": "conversation",
                        "source": "user_conversation",
                        "similarity": 0.40,
                        "importance": 5,
                        "updated_at": _sqlite_utc(datetime.now(timezone.utc) - timedelta(days=20)),
                    }
                ]

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "true",
            }
            return values.get(key, default)

        def fake_get_int(key, default=0):
            values = {
                "AUTO_MEMORY_LIMIT": 2,
                "AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT": 0,
            }
            return values.get(key, default)

        def fake_get_float(key, default=0.0):
            values = {
                "AUTO_MEMORY_SIMILARITY_THRESHOLD": 0.52,
            }
            return values.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()), \
             patch("orchestrator_v2.get_config_value", side_effect=fake_get_config_value), \
             patch("orchestrator_v2.get_int", side_effect=fake_get_int), \
             patch("orchestrator_v2.get_float", side_effect=fake_get_float):
            bundle = orch._get_relevant_memories_bundle("animal birthday gift")

        self.assertEqual(bundle["context"], "")
        self.assertTrue(bundle["meta"]["enabled"])
        self.assertFalse(bundle["meta"]["injected"])
        self.assertEqual(bundle["meta"]["candidate_count"], 1)
        self.assertEqual(bundle["meta"]["injected_count"], 0)
        self.assertEqual(bundle["meta"]["top_candidates"][0]["key"], "gift_query_memory")

    def test_auto_memory_type_filter_overfetches_and_keeps_eligible_facts(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            def __init__(self):
                self.semantic_limit = None

            def get_addressing_preferences(self, limit, session_id=None):
                return []

            def fts_search(self, transcript, limit):
                return []

            def semantic_search(self, query, limit, similarity_threshold):
                self.semantic_limit = limit
                artifact_rows = [
                    {
                        "key": f"stash_item_{idx}",
                        "value": f"Generated image {idx}. STASH: stash://space/file{idx}",
                        "category": "stash_artifact",
                        "source": "generate_image",
                        "metadata": {"stash_ref": f"stash://space/file{idx}", "type": "image"},
                        "similarity": 0.95,
                        "importance": 5,
                        "updated_at": _sqlite_utc(datetime.now(timezone.utc)),
                    }
                    for idx in range(8)
                ]
                fact_row = {
                    "key": "durable_fact",
                    "value": "Jarvis should preserve this eligible fact.",
                    "category": "fact",
                    "source": "remember",
                    "metadata": {"memory_type": "fact"},
                    "similarity": 0.90,
                    "importance": 8,
                    "updated_at": _sqlite_utc(datetime.now(timezone.utc)),
                }
                return artifact_rows + [fact_row]

        fake_db = FakeDb()

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "false",
                "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
            }
            return values.get(key, default)

        def fake_get_int(key, default=0):
            values = {
                "AUTO_MEMORY_LIMIT": 2,
                "AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT": 0,
            }
            return values.get(key, default)

        def fake_get_float(key, default=0.0):
            values = {
                "AUTO_MEMORY_SIMILARITY_THRESHOLD": 0.42,
            }
            return values.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=fake_db), \
             patch("orchestrator_v2.get_config_value", side_effect=fake_get_config_value), \
             patch("orchestrator_v2.get_int", side_effect=fake_get_int), \
             patch("orchestrator_v2.get_float", side_effect=fake_get_float):
            bundle = orch._get_relevant_memories_bundle("durable fact")

        self.assertEqual(fake_db.semantic_limit, 10)
        self.assertIn("durable_fact", bundle["context"])
        self.assertNotIn("stash_item_", bundle["context"])

    def test_active_preference_uses_session_and_suppresses_profile_card_duplicates(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch.web_conversation_id = "web-conversation-123"
        orch.session_id = "jarvis-session-456"
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            requested_session_id = None

            def get_addressing_preferences(self, limit, session_id=None):
                self.requested_session_id = session_id
                return [
                    {
                        "id": 77,
                        "key": "how_to_address_user",
                        "value": "Call me Joe",
                        "category": "preference",
                        "source": "user_conversation",
                        "metadata": {
                            "memory_type": "preference",
                            "preference_slot": "how_to_address_user",
                            "preference_scope": "session",
                        },
                        "preference_slot": "how_to_address_user",
                        "preference_scope": "session",
                        "importance": 7,
                        "updated_at": _sqlite_utc(datetime.now(timezone.utc)),
                    }
                ]

            def fts_search(self, transcript, limit):
                return []

            def fts_search_precise(self, transcript, limit):
                return [
                    {
                        "id": 88,
                        "key": "Core Identity - Name",
                        "value": "Boss",
                        "category": "personal",
                        "source": "intel/user-profile.md",
                        "metadata": {"memory_type": "fact"},
                        "importance": 9,
                    }
                ]

            def semantic_search(self, query, limit, similarity_threshold):
                return [
                    {
                        "id": 89,
                        "key": "preferred_name",
                        "value": "Call me Old Name",
                        "category": "preference",
                        "source": "remember",
                        "metadata": {"memory_type": "preference"},
                        "similarity": 0.99,
                        "importance": 10,
                    }
                ]

        fake_db = FakeDb()

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "false",
                "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
            }
            return values.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=fake_db), patch(
            "orchestrator_v2.get_config_value", side_effect=fake_get_config_value
        ), patch("orchestrator_v2.get_int", return_value=4), patch(
            "orchestrator_v2.get_float", return_value=0.42
        ):
            bundle = orch._get_relevant_memories_bundle("How should you address me?")

        assert fake_db.requested_session_id == "web-conversation-123"
        self.assertIn("Call me Joe", bundle["context"])
        self.assertIn("active_pref slot=how_to_address_user scope=session", bundle["context"])
        self.assertIn("current user request wins", bundle["context"])
        self.assertNotIn("Call me Old Name", bundle["context"])
        self.assertNotIn("Core Identity - Name", bundle["context"])

    def test_inactive_scoped_preference_cannot_reenter_through_semantic_search(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch.session_id = "current-session"
        orch.web_conversation_id = None
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            def get_addressing_preferences(self, limit, session_id=None):
                return []

            def fts_search(self, transcript, limit):
                return []

            def fts_search_precise(self, transcript, limit):
                return []

            def semantic_search(self, query, limit, similarity_threshold):
                return [
                    {
                        "id": 101,
                        "key": "preference_override:response_style:session:old",
                        "value": "Talk like a pirate",
                        "category": "preference",
                        "source": "user_conversation",
                        "metadata": {
                            "memory_type": "preference",
                            "preference_slot": "response_style",
                            "preference_scope": "session",
                            "preference_session_id": "different-session",
                        },
                        "similarity": 0.99,
                        "importance": 10,
                    }
                ]

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "false",
                "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
            }
            return values.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()), patch(
            "orchestrator_v2.get_config_value", side_effect=fake_get_config_value
        ), patch("orchestrator_v2.get_int", return_value=4), patch(
            "orchestrator_v2.get_float", return_value=0.42
        ):
            bundle = orch._get_relevant_memories_bundle("Please use pirate style")

        self.assertFalse(bundle["meta"]["injected"])
        self.assertNotIn("Talk like a pirate", bundle["context"])

    def test_all_four_active_preferences_are_additional_to_retrieval_limit(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.timezone = ZoneInfo("America/Los_Angeles")
        orch.session_id = "current-session"
        orch.web_conversation_id = None
        orch._safe_iso_to_local_datetime = lambda value: None

        class FakeDb:
            requested_preference_limit = None

            def get_addressing_preferences(self, limit, session_id=None):
                self.requested_preference_limit = limit
                slots = [
                    ("how_to_address_user", "Call me Joe", "session"),
                    ("response_style", "Use pirate phrasing", "temporary"),
                    ("preferred_language", "Use Australian English", "persistent"),
                    ("response_tone", "Be direct and humorous", "persistent"),
                ]
                return [
                    {
                        "id": 200 + index,
                        "key": slot,
                        "value": value,
                        "category": "preference",
                        "source": "user_conversation",
                        "metadata": {
                            "memory_type": "preference",
                            "preference_slot": slot,
                            "preference_scope": scope,
                        },
                        "preference_slot": slot,
                        "preference_scope": scope,
                        "importance": 8,
                        "updated_at": _sqlite_utc(datetime.now(timezone.utc)),
                    }
                    for index, (slot, value, scope) in enumerate(slots)
                ]

            def fts_search(self, transcript, limit):
                return []

            def fts_search_precise(self, transcript, limit):
                return [
                    {
                        "id": 301 + index,
                        "key": f"keyword_fact_{index}",
                        "value": f"Retrieved fact {index}",
                        "category": "fact",
                        "source": "remember",
                        "metadata": {"memory_type": "fact"},
                        "importance": 5,
                    }
                    for index in range(1, 4)
                ]

            def semantic_search(self, query, limit, similarity_threshold):
                return []

        fake_db = FakeDb()

        def fake_get_config_value(key, default=None):
            values = {
                "AUTO_MEMORY_INJECTION_ENABLED": "true",
                "AUTO_MEMORY_RECENCY_ENABLED": "false",
                "AUTO_MEMORY_TYPE_FILTER_ENABLED": "true",
                "USER_PROFILE_CARD_ENABLED": "true",
            }
            return values.get(key, default)

        def fake_get_int(key, default=0):
            return {
                "AUTO_MEMORY_LIMIT": 2,
                "AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT": 4,
            }.get(key, default)

        with patch("orchestrator_v2.get_memory_db", return_value=fake_db), patch(
            "orchestrator_v2.get_config_value", side_effect=fake_get_config_value
        ), patch("orchestrator_v2.get_int", side_effect=fake_get_int), patch(
            "orchestrator_v2.get_float", return_value=0.42
        ):
            bundle = orch._get_relevant_memories_bundle("Tell me the retrieved facts")

        self.assertEqual(fake_db.requested_preference_limit, 4)
        for expected in (
            "Call me Joe",
            "Use pirate phrasing",
            "Use Australian English",
            "Be direct and humorous",
            "Retrieved fact 1",
            "Retrieved fact 2",
        ):
            self.assertIn(expected, bundle["context"])
        self.assertNotIn("Retrieved fact 3", bundle["context"])
        self.assertEqual(bundle["meta"]["limit"], 2)
        self.assertEqual(bundle["meta"]["injected_count"], 6)

    def test_auto_context_instructions_are_compact_and_tool_agnostic(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.auto_context_window = 2
        orch.auto_context_minutes = 5

        class FakeDb:
            def get_recent_conversations(self, limit):
                return [
                    {
                        "timestamp": _sqlite_utc(datetime.now(timezone.utc)),
                        "user_query": "what is solana?",
                        "jarvis_response": "Solana is currently $85.93.",
                        "tools_used": json.dumps(["crypto_price"]),
                        "success": True,
                        "metadata": json.dumps({"model": "test-model", "tool_count": 1}),
                    }
                ]

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()):
            context = orch._build_conversation_context("Can you list my current reminders?")

        self.assertIn("=== CURRENT USER QUERY ===", context)
        self.assertIn("Can you list my current reminders?", context)
        self.assertEqual(
            context.count("- Continue multi-step workflows seamlessly"),
            1,
        )
        self.assertNotIn("check_tool_logs", context)
        self.assertNotIn("get_recent_conversations", context)

    def test_auto_context_filters_sqlite_naive_timestamps_as_utc(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.auto_context_window = 3
        orch.auto_context_minutes = 5
        now = datetime.now(timezone.utc)

        class FakeDb:
            def get_recent_conversations(self, limit):
                return [
                    {
                        "timestamp": _sqlite_utc(now - timedelta(minutes=10)),
                        "user_query": "old query should not appear",
                        "jarvis_response": "old response",
                        "tools_used": None,
                        "success": True,
                        "metadata": None,
                    },
                    {
                        "timestamp": _sqlite_utc(now - timedelta(minutes=2)),
                        "user_query": "recent query should appear",
                        "jarvis_response": "recent response",
                        "tools_used": None,
                        "success": True,
                        "metadata": None,
                    },
                ]

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()):
            context = orch._build_conversation_context("current query")

        self.assertIn("recent query should appear", context)
        self.assertNotIn("old query should not appear", context)

    def test_auto_context_returns_current_query_when_all_rows_are_stale(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.auto_context_window = 2
        orch.auto_context_minutes = 5
        old = _sqlite_utc(datetime.now(timezone.utc) - timedelta(minutes=10))

        class FakeDb:
            def get_recent_conversations(self, limit):
                return [
                    {
                        "timestamp": old,
                        "user_query": "old query",
                        "jarvis_response": "old response",
                        "tools_used": None,
                        "success": True,
                        "metadata": None,
                    }
                ]

        with patch("orchestrator_v2.get_memory_db", return_value=FakeDb()):
            context = orch._build_conversation_context("current query")

        self.assertEqual(context, "current query")


if __name__ == "__main__":
    unittest.main()
