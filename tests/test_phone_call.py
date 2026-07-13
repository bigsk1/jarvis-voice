#!/usr/bin/env python3
"""Regression tests for async phone-call completion state."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import phone_call  # noqa: E402


def _config_value(key: str, default=None):
    if key == "VAPI_WAIT_FOR_CALL":
        return "false"
    return default


def test_in_progress_marker_persists_original_task(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call.time, "time", lambda: 123.0)

    phone_call.set_call_in_progress(
        "call-A",
        "+15550000001",
        "Alice",
        "Ask about dinner plans",
    )

    assert json.loads(marker.read_text()) == {
        "call_id": "call-A",
        "phone_number": "+15550000001",
        "recipient": "Alice",
        "task": "Ask about dinner plans",
        "started": 123.0,
    }


def test_new_call_request_saves_completed_call_with_original_task(monkeypatch):
    prior_call = {
        "call_id": "call-A",
        "phone_number": "+15550000001",
        "recipient": "Alice",
        "task": "Ask about dinner plans",
        "started": 1,
    }
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
    }
    save_call = Mock(return_value=True)
    make_call = Mock()

    monkeypatch.setattr(phone_call, "get_config_value", _config_value)
    monkeypatch.setattr(phone_call, "resolve_phone_number", lambda _recipient: "+15550000002")
    monkeypatch.setattr(phone_call, "is_call_in_progress", lambda: prior_call)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "extract_transcript", lambda _call: "Dinner works")
    monkeypatch.setattr(phone_call, "clear_call_in_progress", Mock())
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)
    monkeypatch.setattr(phone_call, "make_call", make_call)

    result = phone_call.action_call({"recipient": "Bob", "task": "Check flight status"})

    assert result["data"]["call_id"] == "call-A"
    assert save_call.call_args.args[:3] == (
        "call-A",
        "Alice",
        "Ask about dinner plans",
    )
    make_call.assert_not_called()


def test_status_uses_tracked_metadata_and_clears_matching_marker(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    marker.write_text(
        json.dumps(
            {
                "call_id": "call-A",
                "phone_number": "+15550000001",
                "recipient": "Alice",
                "task": "Ask about dinner plans",
                "started": time.time(),
            }
        )
    )
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
        "transcript": "Dinner works",
        "customer": {"number": "+15550000001"},
    }
    save_call = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)

    result = phone_call.action_status({"call_id": "call-A"})

    assert save_call.call_args.args[:3] == (
        "call-A",
        "Alice",
        "Ask about dinner plans",
    )
    assert not marker.exists()
    assert result["data"]["saved_to_canvas"] is True


def test_status_preserves_different_active_call_marker(tmp_path, monkeypatch):
    marker = tmp_path / "phone-call-in-progress.json"
    marker.write_text(
        json.dumps(
            {
                "call_id": "call-B",
                "phone_number": "+15550000002",
                "recipient": "Bob",
                "task": "Check flight status",
                "started": time.time(),
            }
        )
    )
    ended_call = {
        "status": "ended",
        "summary": "Dinner confirmed",
        "duration": 42,
        "transcript": "Dinner works",
        "customer": {"number": "+15550000001"},
    }
    save_call = Mock(return_value=True)
    monkeypatch.setattr(phone_call, "CALL_IN_PROGRESS_FILE", marker)
    monkeypatch.setattr(phone_call, "get_call_status", lambda _call_id: ended_call)
    monkeypatch.setattr(phone_call, "save_call_to_canvas", save_call)

    phone_call.action_status({"call_id": "call-A"})

    assert save_call.call_args.args[:3] == (
        "call-A",
        "+15550000001",
        "Phone call",
    )
    assert marker.exists()
