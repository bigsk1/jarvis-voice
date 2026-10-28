"""Pending RSS batches survive later reads or fail atomically at capacity."""

import json
from copy import deepcopy

import pytest

from lib.rss_feeds import RSSFeedError
from lib.rss_feeds import state as state_module
from lib.rss_feeds.state import BATCH_TTL, SEEN_TTL, FeedState

NOW = 1_800_000_000.0


def batch(created_at=NOW, *, selected=False, acknowledged=False, content=""):
    result = {"created_at": created_at, "items": [{"id": "story-1", "content": content}]}
    if selected:
        result["selected_ids"] = ["story-1"]
        result["selected_at"] = created_at
    if acknowledged:
        result["acknowledged"] = True
    return result


@pytest.mark.parametrize("selected", [False, True])
def test_pending_batch_survives_more_than_five_new_reads_and_remains_usable(tmp_path, selected):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"]["original"] = batch(selected=selected)
    for index in range(8):
        with store.transaction(NOW + index + 1) as state:
            state["batches"][f"read-{index}"] = batch(NOW + index + 1)

    with store.transaction(NOW + 10) as state:
        original = state["batches"]["original"]
        assert len(state["batches"]) == 9
        assert bool(original.get("selected_ids")) is selected
        # A later workflow can select/acknowledge this exact retained batch.
        original["selected_ids"] = ["story-1"]
        original["acknowledged"] = True
    saved = json.loads(store.path.read_text())
    assert saved["batches"]["original"]["acknowledged"] is True
    assert len(saved["batches"]) == 9


def test_completed_receipt_limit_never_discards_pending_batches(tmp_path):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"]["old-selected"] = batch(NOW - 100, selected=True)
        state["batches"]["old-unselected"] = batch(NOW - 99)
        for index in range(9):
            state["batches"][f"done-{index}"] = batch(NOW - index, acknowledged=True)
    saved = json.loads(store.path.read_text())
    assert set(saved["batches"]) == {"old-selected", "old-unselected", *[f"done-{i}" for i in range(5)]}


def test_expired_pending_batches_and_seen_ids_are_pruned_normally(tmp_path):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"] = {
            "expired": batch(NOW - BATCH_TTL, selected=True),
            "still-valid": batch(NOW - BATCH_TTL + 2),
        }
        state["seen"] = {"expired": NOW - SEEN_TTL, "current": NOW}
    with store.transaction(NOW + 1) as state:
        assert set(state["batches"]) == {"still-valid"}
        assert state["seen"] == {"current": NOW}
    assert set(json.loads(store.path.read_text())["batches"]) == {"still-valid"}


def test_twenty_pending_batches_are_retained_and_next_read_fails_atomically(tmp_path):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"] = {f"pending-{index}": batch(NOW + index) for index in range(20)}
    before = store.path.read_bytes()
    with pytest.raises(RSSFeedError, match="Too many pending RSS batches"):
        with store.transaction(NOW + 30) as state:
            state["batches"]["overflow"] = batch(NOW + 30)
            state["seen"]["must-not-save"] = NOW + 30
    assert store.path.read_bytes() == before
    assert len(json.loads(before)["batches"]) == 20
    assert not list(tmp_path.glob(".rss-*"))
    # Finishing a retained batch frees a pending slot without deleting it.
    with store.transaction(NOW + 31) as state:
        state["batches"]["pending-0"]["acknowledged"] = True
        state["batches"]["replacement"] = batch(NOW + 31)
    saved = json.loads(store.path.read_text())
    assert len(saved["batches"]) == 21
    assert saved["batches"]["pending-0"]["acknowledged"]


def test_serialized_byte_capacity_failure_preserves_existing_file(tmp_path, monkeypatch):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"]["kept"] = batch()
    before = store.path.read_bytes()
    document = json.loads(before)
    document["batches"]["new"] = batch(NOW + 1, content="é" * 100)
    serialized = json.dumps(document, ensure_ascii=False)
    ceiling = len(serialized) + 1
    assert len(serialized.encode("utf-8")) > ceiling
    monkeypatch.setattr(state_module, "MAX_STATE_BYTES", ceiling)
    with pytest.raises(RSSFeedError, match="history is full"):
        with store.transaction(NOW + 1) as state:
            state["batches"]["new"] = document["batches"]["new"]
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob(".rss-*"))


def test_size_pressure_prunes_old_completed_receipts_before_pending_batches(tmp_path, monkeypatch):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"] = {
            "pending": batch(selected=True),
            "done-old": batch(NOW - 2, acknowledged=True, content="old" * 100),
            "done-new": batch(NOW - 1, acknowledged=True, content="new" * 100),
        }
    original = json.loads(store.path.read_text())
    proposed = deepcopy(original)
    proposed["batches"]["new-pending"] = batch(NOW + 1, content="x" * 400)
    proposed["batches"].pop("done-old")
    # The old file fits; adding the new pending batch requires dropping only
    # the oldest completed receipt, never either pending batch.
    ceiling = len(json.dumps(proposed, ensure_ascii=False).encode("utf-8"))
    assert store.path.stat().st_size <= ceiling
    monkeypatch.setattr(state_module, "MAX_STATE_BYTES", ceiling)
    with store.transaction(NOW + 1) as state:
        state["batches"]["new-pending"] = batch(NOW + 1, content="x" * 400)
    saved = json.loads(store.path.read_text())
    assert set(saved["batches"]) == {"pending", "new-pending", "done-new"}
    assert store.path.stat().st_size <= ceiling


def test_atomic_replace_failure_leaves_valid_previous_state_and_no_temp_file(tmp_path, monkeypatch):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["batches"]["kept"] = batch()
    before = store.path.read_bytes()

    def refuse_replace(*args):
        raise OSError("Controlled replacement failure")

    monkeypatch.setattr(state_module.os, "replace", refuse_replace)
    with pytest.raises(OSError, match="Controlled replacement failure"):
        with store.transaction(NOW + 1) as state:
            state["batches"]["new"] = batch(NOW + 1)
    assert store.path.read_bytes() == before
    assert json.loads(before)["batches"]["kept"]["items"][0]["id"] == "story-1"
    assert not list(tmp_path.glob(".rss-*"))


def test_seen_and_recent_bounds_still_apply_without_trimming_pending(tmp_path):
    store = FeedState(tmp_path, "daily_tech")
    with store.transaction(NOW) as state:
        state["seen"] = {f"story-{index}": NOW + index for index in range(5010)}
        state["recent"] = [{"id": f"story-{index}"} for index in range(50)]
        state["batches"]["pending"] = batch(selected=True)
    saved = json.loads(store.path.read_text())
    assert len(saved["seen"]) == 5000
    assert "story-0" not in saved["seen"]
    assert len(saved["recent"]) == 40
    assert saved["recent"][0]["id"] == "story-10"
    assert saved["batches"]["pending"]["selected_ids"] == ["story-1"]
