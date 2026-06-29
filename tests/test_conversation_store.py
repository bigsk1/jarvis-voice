#!/usr/bin/env python3
"""Regression tests for web conversation pin/archive metadata."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.services.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pinned_conversations_sort_above_unpinned(self) -> None:
        first = self.store.create_conversation("First chat")
        second = self.store.create_conversation("Second chat")

        self.store.update_state(first["id"], pinned=True)

        listed = self.store.list_conversations(limit=10, include_archived=True)
        self.assertEqual(listed[0]["id"], first["id"])
        self.assertTrue(listed[0]["pinned"])
        self.assertEqual(listed[1]["id"], second["id"])

    def test_archived_conversations_can_be_hidden_but_still_listed(self) -> None:
        active = self.store.create_conversation("Active chat")
        archived = self.store.create_conversation("Archived chat")

        self.store.update_state(archived["id"], archived=True)

        visible = self.store.list_conversations(limit=10, include_archived=False)
        all_items = self.store.list_conversations(limit=10, include_archived=True)

        self.assertEqual([item["id"] for item in visible], [active["id"]])
        self.assertEqual({item["id"] for item in all_items}, {active["id"], archived["id"]})
        archived_item = next(item for item in all_items if item["id"] == archived["id"])
        self.assertTrue(archived_item["archived"])

    def test_archiving_clears_pinned_state(self) -> None:
        conversation = self.store.create_conversation("Pinned then archived")
        self.store.update_state(conversation["id"], pinned=True)

        updated = self.store.update_state(conversation["id"], archived=True)
        self.assertIsNotNone(updated)
        self.assertFalse(updated["pinned"])
        self.assertTrue(updated["archived"])

        full = self.store.get_conversation(conversation["id"])
        self.assertFalse(full["pinned"])
        self.assertTrue(full["archived"])


if __name__ == "__main__":
    unittest.main()
