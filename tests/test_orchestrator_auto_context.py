#!/usr/bin/env python3
"""Tests for orchestrator auto-context prompt assembly."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


def _sqlite_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class OrchestratorAutoContextTests(unittest.TestCase):
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
