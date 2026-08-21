"""Regression coverage for timezone-safe deep-memory date filtering."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import skills.deep_memory_search as deep_memory_search
from skills.deep_memory_search import (
    parse_date_filter,
    search_canvas_pages,
    search_intel_folder,
    search_memory_db,
    search_stash_spaces,
    search_terminal_conversations,
    search_web_conversations,
)

APP_TZ = ZoneInfo("America/Los_Angeles")
FIXED_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=APP_TZ)
CUTOFF = datetime(2026, 8, 21, 0, 0, tzinfo=APP_TZ)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("today", datetime(2026, 8, 21, 0, 0, tzinfo=APP_TZ)),
        ("week", datetime(2026, 8, 14, 12, 0, tzinfo=APP_TZ)),
        ("month", datetime(2026, 7, 22, 12, 0, tzinfo=APP_TZ)),
        ("year", datetime(2025, 8, 21, 12, 0, tzinfo=APP_TZ)),
        ("2026-08-21", datetime(2026, 8, 21, 0, 0, tzinfo=APP_TZ)),
        ("2026-08-21T07:00:00Z", datetime(2026, 8, 21, 0, 0, tzinfo=APP_TZ)),
    ],
)
def test_parse_date_filter_returns_aware_app_time(value, expected):
    with patch.object(deep_memory_search, "now_local", return_value=FIXED_NOW):
        assert parse_date_filter(value) == expected


def test_database_sources_compare_naive_utc_timestamps_with_aware_cutoff():
    class FakeDb:
        last_semantic_search_meta = {
            "retrieval_mode": "hybrid",
            "semantic_disabled_reason": None,
        }

        def search_memory(self, query, limit):
            return [
                {
                    "id": 1,
                    "key": "old-memory",
                    "value": query,
                    "created_at": "2026-08-21 06:30:00",
                },
                {
                    "id": 2,
                    "key": "new-memory",
                    "value": query,
                    "created_at": "2026-08-21 07:30:00",
                },
            ]

        def search_conversations(self, query, limit):
            return [
                {
                    "id": 3,
                    "user_query": query,
                    "timestamp": "2026-08-21 06:30:00",
                },
                {
                    "id": 4,
                    "user_query": query,
                    "timestamp": "2026-08-21 07:30:00",
                },
            ]

        def close(self):
            pass

    with patch.object(deep_memory_search, "get_memory_db", return_value=FakeDb()):
        memories, _ = search_memory_db("timezone token", 10, "keyword", CUTOFF)
        conversations = search_terminal_conversations("timezone token", 10, CUTOFF)

    assert [item["id"] for item in memories] == [2]
    assert [item["id"] for item in conversations] == [4]


def test_file_sources_apply_one_aware_cutoff_to_mixed_timestamp_formats(
    tmp_path: Path,
    monkeypatch,
):
    token = "deep_memory_date_filter_token"

    web_dir = tmp_path / "data" / "web_conversations"
    canvas_dir = tmp_path / "data" / "canvas"
    stash_dir = tmp_path / "data" / "stash"
    intel_dir = tmp_path / "jarvis-intel"
    for directory in (web_dir, canvas_dir, stash_dir, intel_dir):
        directory.mkdir(parents=True)

    for name, created_at in (
        ("old", "2026-08-20T23:30:00"),
        ("new", "2026-08-21T00:30:00"),
    ):
        (web_dir / f"{name}.json").write_text(json.dumps({
            "id": f"{name}-web",
            "title": token,
            "created_at": created_at,
            "messages": [{"role": "user", "content": token}],
        }))

    for name, created in (
        ("old", "2026-08-21T06:30:00Z"),
        ("new", "2026-08-21T07:30:00Z"),
    ):
        (canvas_dir / f"{name}.json").write_text(json.dumps({
            "id": f"{name}-canvas",
            "title": token,
            "content": token,
            "created": created,
        }))
        space_dir = stash_dir / f"{name}-space"
        space_dir.mkdir()
        (space_dir / "meta.json").write_text(json.dumps({
            "space_id": f"{name}-space",
            "labels": [token],
            "created_at": created,
            "files": [],
        }))

    for name, timestamp in (
        ("old", datetime(2026, 8, 21, 6, 30, tzinfo=ZoneInfo("UTC"))),
        ("new", datetime(2026, 8, 21, 7, 30, tzinfo=ZoneInfo("UTC"))),
    ):
        path = intel_dir / f"{name}.md"
        path.write_text(token)
        os.utime(path, (timestamp.timestamp(), timestamp.timestamp()))

    monkeypatch.setattr(deep_memory_search, "PROJECT_ROOT", tmp_path)

    web_results = search_web_conversations(token, 10, CUTOFF)
    canvas_results = search_canvas_pages(token, 10, CUTOFF)
    stash_results = search_stash_spaces(token, 10, CUTOFF)
    intel_results = search_intel_folder(token, 10, CUTOFF)

    assert [item["conversation_id"] for item in web_results] == ["new-web"]
    assert [item["page_id"] for item in canvas_results] == ["new-canvas"]
    assert [item["space_id"] for item in stash_results] == ["new-space"]
    assert [item["file"] for item in intel_results] == ["new.md"]
