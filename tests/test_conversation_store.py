#!/usr/bin/env python3
"""Regression tests for web conversation pin/archive metadata."""

from __future__ import annotations

import sys
import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.services.conversation_store import ConversationStore


def _set_conversation_state(
    store: ConversationStore,
    conv_id: str,
    *,
    updated_at: datetime,
    pinned: bool = False,
) -> None:
    timestamp = updated_at.isoformat()
    conv_file = store.conversations_dir / f"{conv_id}.json"
    conversation = json.loads(conv_file.read_text())
    conversation["updated_at"] = timestamp
    conversation["pinned"] = pinned
    conversation["pinned_at"] = timestamp if pinned else None
    conv_file.write_text(json.dumps(conversation, indent=2))

    for item in store._index["conversations"]:
        if item["id"] != conv_id:
            continue
        item["updated_at"] = timestamp
        item["pinned"] = pinned
        item["pinned_at"] = timestamp if pinned else None
        break
    store._save_index()


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

    def test_rename_updates_full_conversation_and_index_without_changing_state(self) -> None:
        conversation = self.store.create_conversation("Original title")
        self.store.add_message(conversation["id"], "user", "Original message")
        self.store.update_state(conversation["id"], pinned=True)

        before = self.store.get_conversation(conversation["id"])
        self.assertTrue(self.store.update_title(conversation["id"], "!@#z$A12"))

        renamed = self.store.get_conversation(conversation["id"])
        listed = self.store.list_conversations(limit=10, include_archived=True)
        summary = next(item for item in listed if item["id"] == conversation["id"])
        self.assertEqual(renamed["title"], "!@#z$A12")
        self.assertEqual(summary["title"], "!@#z$A12")
        self.assertEqual(renamed["messages"], before["messages"])
        self.assertEqual(renamed["updated_at"], before["updated_at"])
        self.assertTrue(renamed["pinned"])

    def test_cleanup_old_unpinned_preserves_pinned_and_recent_conversations(self) -> None:
        now = datetime(2026, 7, 11, 12, 0, 0)
        old_unpinned = self.store.create_conversation("Old unpinned")
        old_pinned = self.store.create_conversation("Old pinned")
        recent_unpinned = self.store.create_conversation("Recent unpinned")

        _set_conversation_state(
            self.store,
            old_unpinned["id"],
            updated_at=now - timedelta(days=120),
        )
        _set_conversation_state(
            self.store,
            old_pinned["id"],
            updated_at=now - timedelta(days=120),
            pinned=True,
        )
        _set_conversation_state(
            self.store,
            recent_unpinned["id"],
            updated_at=now - timedelta(days=10),
        )

        dry_run = self.store.cleanup_old_unpinned(
            retention_days=90,
            dry_run=True,
            now=now,
        )

        self.assertEqual([item["id"] for item in dry_run["candidates"]], [old_unpinned["id"]])
        self.assertEqual(dry_run["deleted_conversations"], 0)
        self.assertTrue((self.store.conversations_dir / f"{old_unpinned['id']}.json").exists())

        result = self.store.cleanup_old_unpinned(
            retention_days=90,
            dry_run=False,
            now=now,
        )

        self.assertEqual(result["deleted_conversations"], 1)
        self.assertFalse((self.store.conversations_dir / f"{old_unpinned['id']}.json").exists())
        self.assertTrue((self.store.conversations_dir / f"{old_pinned['id']}.json").exists())
        self.assertTrue((self.store.conversations_dir / f"{recent_unpinned['id']}.json").exists())
        remaining_ids = {item["id"] for item in self.store.list_conversations(limit=10)}
        self.assertEqual(remaining_ids, {old_pinned["id"], recent_unpinned["id"]})


if __name__ == "__main__":
    unittest.main()
