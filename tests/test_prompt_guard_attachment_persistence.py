"""Confirmed attachment blocks persist source identities without changing chat activity."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
from server_package_utils import load_server_package  # noqa: E402

load_server_package("jarvis_web_pg_persistence_server", PROJECT_ROOT / "jarvis-web/server")

from jarvis_web_pg_persistence_server.services.conversation_store import (  # noqa: E402
    ConversationStore,
)

from lib.background_tasks import TaskStore  # noqa: E402

DIGEST = "a" * 64
REFERENCE = "stash://space_web_text_" + "1" * 32 + "/f_" + DIGEST[:12]
SECOND_DIGEST = "b" * 64
SECOND_REFERENCE = "stash://space_web_text_" + "2" * 32 + "/f_" + SECOND_DIGEST[:12]


@pytest.fixture
def stores(tmp_path):
    directory = tmp_path / "conversations"
    tasks = TaskStore(tmp_path / "tasks.db")
    first = ConversationStore(directory, background_tasks=tasks)
    second = ConversationStore(directory, background_tasks=tasks)
    return first, second


def attachment(reference=REFERENCE, digest=DIGEST, kind="text"):
    return {"kind": kind, "stash_ref": reference, "sha256": digest, "filename": "fixture.txt"}


def save_source(store, *, role="user", sources=None):
    conversation = store.create_conversation("Original title")
    store.add_message(conversation["id"], role, "Review these sources.", data={
        "attachments": [attachment()] if sources is None else sources,
        "unrelated": {"value": "keep"},
    })
    return conversation["id"]


def raw_conversation(store, conv_id):
    path = store.conversations_dir / f"{conv_id}.json"
    return path, json.loads(path.read_text())


def test_verified_block_survives_other_instance_reload_without_changing_activity(stores):
    first, second = stores
    conv_id = save_source(first)
    first.update_state(conv_id, pinned=True, archived=True)
    path, before = raw_conversation(first, conv_id)
    before_index = first._index_file.read_bytes()
    listeners = Mock()
    first.add_index_listener(listeners)

    assert first.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is True
    saved = json.loads(path.read_text())
    assert saved.pop("prompt_guard_withheld_text") == {REFERENCE: DIGEST}
    assert saved == before
    assert first._index_file.read_bytes() == before_index
    listeners.assert_not_called()

    restored = second.get_conversation(conv_id, reconcile=False)
    assert restored["prompt_guard_withheld_text"] == {REFERENCE: DIGEST}
    assert restored["updated_at"] == before["updated_at"]
    serialized = json.dumps(restored["prompt_guard_withheld_text"])
    assert "fixture.txt" not in serialized and "Review these sources" not in serialized


def test_matching_marker_is_idempotent_and_does_not_rewrite_file(stores, monkeypatch):
    first, second = stores
    conv_id = save_source(first)
    assert first.withhold_text_attachment(conv_id, REFERENCE, DIGEST)
    path, _ = raw_conversation(first, conv_id)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    write = Mock(side_effect=AssertionError("An existing marker must not rewrite the document"))
    monkeypatch.setattr(second, "_write_conversation", write)

    assert second.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is True
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    write.assert_not_called()


@pytest.mark.parametrize("conv_id,reference,digest", [
    ("missing", REFERENCE, DIGEST), ("../escape", REFERENCE, DIGEST), (None, REFERENCE, DIGEST),
    ("saved", "stash://space_web_text_bad/f_123", DIGEST),
    ("saved", "https://example.test/source", DIGEST), ("saved", None, DIGEST),
    ("saved", REFERENCE, "a" * 63), ("saved", REFERENCE, "a" * 65),
    ("saved", REFERENCE, "g" * 64), ("saved", REFERENCE, DIGEST + "\n"),
    ("saved", REFERENCE, None), ("saved", REFERENCE, True),
    ("saved", REFERENCE, DIGEST.upper()), ("saved", REFERENCE, SECOND_DIGEST),
    ("saved", SECOND_REFERENCE, DIGEST),
])
def test_invalid_or_unmatched_identity_does_not_persist(stores, conv_id, reference, digest):
    first, _ = stores
    saved_id = save_source(first)
    selected_id = saved_id if conv_id == "saved" else conv_id
    path, before = raw_conversation(first, saved_id)
    index = first._index_file.read_bytes()
    assert first.withhold_text_attachment(selected_id, reference, digest) is False
    assert json.loads(path.read_text()) == before
    assert first._index_file.read_bytes() == index


@pytest.mark.parametrize("role,source", [
    ("assistant", attachment()), ("user", attachment(kind="pdf")),
    ("user", {"kind": "text", "stash_ref": REFERENCE}),
    ("user", {"kind": "text", "sha256": DIGEST}),
    ("user", None),
])
def test_only_saved_user_text_attachments_can_receive_marker(stores, role, source):
    first, _ = stores
    conv_id = save_source(first, role=role, sources=[source])
    path, before = raw_conversation(first, conv_id)
    assert first.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is False
    assert json.loads(path.read_text()) == before


def test_concurrent_store_writes_preserve_both_source_markers_and_other_state(stores):
    first, second = stores
    conv_id = save_source(first, sources=[attachment(), attachment(SECOND_REFERENCE, SECOND_DIGEST)])
    _, before = raw_conversation(first, conv_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(first.withhold_text_attachment, conv_id, REFERENCE, DIGEST)
        two = executor.submit(second.withhold_text_attachment, conv_id, SECOND_REFERENCE, SECOND_DIGEST)
        assert one.result(timeout=10) is True and two.result(timeout=10) is True
    _, restored = raw_conversation(first, conv_id)
    assert restored.pop("prompt_guard_withheld_text") == {REFERENCE: DIGEST, SECOND_REFERENCE: SECOND_DIGEST}
    assert restored == before


def test_saved_hash_change_does_not_reuse_an_old_marker(stores):
    first, second = stores
    conv_id = save_source(first)
    assert first.withhold_text_attachment(conv_id, REFERENCE, DIGEST)
    path, original = raw_conversation(first, conv_id)
    updated = deepcopy(original)
    changed_digest = DIGEST[:-1] + "b"
    updated["messages"][0]["data"]["attachments"][0]["sha256"] = changed_digest
    first._write_conversation(updated)

    assert second.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is False
    assert second.withhold_text_attachment(conv_id, REFERENCE, changed_digest) is True
    restored = json.loads(path.read_text())
    assert restored["prompt_guard_withheld_text"] == {REFERENCE: changed_digest}


def test_marker_does_not_reconcile_or_mutate_a_running_turn(stores):
    first, _ = stores
    conv_id = save_source(first)
    path, conversation = raw_conversation(first, conv_id)
    conversation["run"] = {"message_id": "synthetic-run", "status": "running"}
    first._write_conversation(conversation)
    assert first.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is True
    restored = json.loads(path.read_text())
    assert restored["run"] == conversation["run"]
    assert restored["updated_at"] == conversation["updated_at"]


def test_current_generation_must_still_contain_matching_saved_source(stores):
    first, second = stores
    conv_id = save_source(first)
    assert first.clear_conversation(conv_id)
    path, cleared = raw_conversation(first, conv_id)
    assert second.withhold_text_attachment(conv_id, REFERENCE, DIGEST) is False
    assert json.loads(path.read_text()) == cleared
