"""Latency, cancellation, and context-budget coverage for status updates."""

import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import status_updater


class FakeSummarizer:
    def __init__(self, *, enabled=True, delay=0.0, result="Dynamic progress"):
        self.enabled = enabled
        self.delay = delay
        self.result = result

    def is_enabled(self):
        return self.enabled

    def summarize(self, context, tool_name=None, event_type="progress", call_metadata=None):
        time.sleep(self.delay)
        return self.result


def make_updater(summarizer, *, debounce_ms=10, deadline_ms=50):
    config = {
        "STATUS_UPDATES_ENABLED": "true",
        "JARVIS_RESPONSE_STYLE": "casual",
    }
    integers = {
        "STATUS_UPDATE_INTERVAL": 0,
        "STATUS_UPDATE_DEBOUNCE_MS": debounce_ms,
        "STATUS_LLM_DEADLINE_MS": deadline_ms,
    }
    with (
        patch.object(status_updater, "get_config_value", side_effect=lambda key, default="": config.get(key, default)),
        patch.object(status_updater, "get_int", side_effect=lambda key, default=0: integers.get(key, default)),
        patch.object(status_updater, "StatusSummarizer", return_value=summarizer),
        patch.object(status_updater, "log_status_event"),
    ):
        updater = status_updater.StatusUpdater(mode="cloud")
    updater.phrases.get_phrase = MagicMock(return_value="Static fallback")
    return updater


def capture_speech(updater):
    spoken = []
    ready = threading.Event()

    def speak(message, blocking=False):
        spoken.append(message)
        ready.set()

    updater._speak = speak
    return spoken, ready


def test_slow_status_llm_never_blocks_tool_path_and_falls_back_once():
    updater = make_updater(
        FakeSummarizer(delay=0.20, result="Late dynamic phrase"),
        debounce_ms=10,
        deadline_ms=40,
    )
    spoken, ready = capture_speech(updater)

    started = time.monotonic()
    assert updater.update(
        category="searching",
        tool_name="mcp_brave_search_brave_web_search",
        context={"phase": "starting", "arguments": {"query": "current weather"}},
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.05
    assert ready.wait(0.15)
    assert spoken == ["Static fallback"]
    time.sleep(0.15)
    assert spoken == ["Static fallback"]
    updater.mark_complete()


def test_fast_dynamic_phrase_wins_before_deadline():
    updater = make_updater(
        FakeSummarizer(delay=0.005, result="Checking the latest forecast"),
        debounce_ms=20,
        deadline_ms=100,
    )
    spoken, ready = capture_speech(updater)

    updater.update(
        category="fetching",
        tool_name="weather",
        context={"phase": "starting", "arguments": {"location": "Portland"}},
    )

    assert ready.wait(0.15)
    assert spoken == ["Checking the latest forecast"]
    updater.mark_complete()


def test_completion_suppresses_debounced_static_status():
    updater = make_updater(FakeSummarizer(enabled=False), debounce_ms=80, deadline_ms=100)
    spoken, _ = capture_speech(updater)

    updater.update(category="task_start", tool_name="get_time")
    updater.mark_complete()
    time.sleep(0.12)

    assert spoken == []


def test_superseded_debounced_status_does_not_rate_limit_next_tool():
    updater = make_updater(FakeSummarizer(enabled=False), debounce_ms=30, deadline_ms=100)
    updater.interval = 60
    updater.phrases.get_phrase = MagicMock(side_effect=["First tool", "Second tool"])
    spoken, ready = capture_speech(updater)

    assert updater.update(category="task_start", tool_name="first_tool")
    assert updater.update(category="task_start", tool_name="second_tool")

    assert ready.wait(0.15)
    assert spoken == ["Second tool"]
    updater.mark_complete()


def test_status_context_is_bounded_and_redacts_sensitive_arguments():
    updater = make_updater(FakeSummarizer(enabled=False))
    updater.turn_number = 2
    updater.task_start_time = time.time() - 35

    context = updater._build_minimal_context(
        "api_call",
        "multi_turn",
        {
            "arguments": {
                "query": "password=hunter2 quarterly report",
                "url": "https://example.com/private?token=secret",
                "api_key": "private-key",
                "headers": {"Authorization": "Bearer private"},
                "recipient_email": "private@example.com",
            },
            "previous_outcome": "token=private-token Download completed",
        },
    )

    assert len(context) <= 500
    assert "hunter2" not in context
    assert "private-key" not in context
    assert "private-token" not in context
    assert "private@example.com" not in context
    assert "https://example.com" in context
    assert "Step 2" in context


def test_mark_complete_terminates_native_status_process_group():
    updater = make_updater(FakeSummarizer(enabled=False))
    process = MagicMock(pid=4321)
    process.poll.return_value = None
    updater._speech_process = process

    with patch.object(status_updater.os, "killpg") as killpg:
        updater.mark_complete()

    killpg.assert_called_once_with(4321, signal.SIGTERM)
    assert updater._speech_process is None


def test_set_turn_clears_stale_last_context():
    captured = []

    class TrackingSummarizer(FakeSummarizer):
        def summarize(self, context, tool_name=None, event_type="progress", call_metadata=None):
            captured.append(context)
            return "Fresh phrase"

    updater = make_updater(TrackingSummarizer(), debounce_ms=10, deadline_ms=100)
    _, ready = capture_speech(updater)

    updater.update(
        category="searching",
        tool_name="web_search",
        context={"arguments": {"query": "first turn weather"}},
    )
    assert ready.wait(0.2)
    assert "first turn weather" in captured[-1]

    captured.clear()
    ready.clear()
    updater.set_turn(2)
    updater.update(category="fetching", tool_name="weather")

    assert ready.wait(0.2)
    assert captured
    assert "first turn weather" not in captured[-1]


def test_status_lifecycle_logs_started_discarded_and_turn_summary():
    updater = make_updater(
        FakeSummarizer(delay=0.08, result="Late dynamic phrase"),
        debounce_ms=30,
        deadline_ms=100,
    )

    updater.reset()
    updater.update(category="searching", tool_name="web_search")
    time.sleep(0.01)
    updater.mark_complete()
    time.sleep(0.10)

    events = [call.args[0] for call in updater._log_event.call_args_list]
    assert "turn_started" in events
    assert "status_llm_started" in events
    assert "turn_completed" in events
    assert "status_llm_discarded" in events

    summary = next(
        call.kwargs
        for call in updater._log_event.call_args_list
        if call.args[0] == "turn_completed"
    )
    assert summary["llm_started"] == 1
    assert summary["llm_in_flight"] == 1
