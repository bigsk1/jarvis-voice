"""Regression coverage for durable Tool RAG sync status."""

import json

from lib.tool_sync_status import (
    read_tool_sync_status,
    record_tool_sync_failure,
    record_tool_sync_success,
)


def test_tool_sync_failure_persists_until_success(tmp_path):
    failure = record_tool_sync_failure(
        "cloud",
        exit_code=4,
        reason="embedding provider unavailable",
        usable_tool_count=17,
        project_root=tmp_path,
    )

    loaded = read_tool_sync_status("cloud", project_root=tmp_path)
    assert loaded == failure
    assert loaded["status"] == "failed"
    assert loaded["has_usable_index"] is True
    assert loaded["event_id"]

    success = record_tool_sync_success(
        "cloud",
        usable_tool_count=18,
        project_root=tmp_path,
    )

    assert read_tool_sync_status("cloud", project_root=tmp_path) == success
    assert success["status"] == "ok"
    assert success["event_id"] != failure["event_id"]


def test_tool_sync_status_is_mode_specific_and_valid_json(tmp_path):
    record_tool_sync_failure(
        "local",
        exit_code=5,
        reason="one tool failed",
        usable_tool_count=0,
        project_root=tmp_path,
    )

    assert read_tool_sync_status("cloud", project_root=tmp_path) is None
    local = read_tool_sync_status("local", project_root=tmp_path)
    assert local["has_usable_index"] is False

    status_path = tmp_path / "data" / ".tool_sync_status_local.json"
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "failed"


def test_missing_corrupt_or_incomplete_status_is_not_treated_as_failure(tmp_path):
    status_path = tmp_path / "data" / ".tool_sync_status_cloud.json"
    status_path.parent.mkdir(parents=True)

    assert read_tool_sync_status("cloud", project_root=tmp_path) is None

    status_path.write_text("not json", encoding="utf-8")
    assert read_tool_sync_status("cloud", project_root=tmp_path) is None

    status_path.write_text(
        json.dumps({"mode": "cloud", "status": "failed"}),
        encoding="utf-8",
    )
    assert read_tool_sync_status("cloud", project_root=tmp_path) is None
