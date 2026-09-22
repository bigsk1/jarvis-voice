"""Keep Web tool completion events stable across chat-handler refactors."""

import sys
from pathlib import Path

from server_package_utils import load_server_package

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package(
    "jarvis_web_tool_events_test_server",
    PROJECT_ROOT / "jarvis-web" / "server",
)

from jarvis_web_tool_events_test_server.sockets.chat import ChatHandler  # noqa: E402


class _EventSink:
    def __init__(self):
        self.events = []

    def _emit_run_event(self, name, payload, room):
        self.events.append((name, payload, room))


def test_workflow_completion_events_keep_iteration_and_skip_metadata():
    sink = _EventSink()
    data = {
        "results": [
            {
                "tool": "search",
                "step": 1,
                "duration_ms": 20,
                "outputs": [
                    {"ok": True, "data": {"item": "first"}, "duration_ms": 7},
                    {"ok": False, "data": {"error": "unavailable"}},
                ],
            },
            {
                "tool": "filter",
                "step": 2,
                "ok": True,
                "skipped": True,
                "reason": "Condition was false",
            },
            {
                "tool": "optional",
                "step": 3,
                "skip_kind": "optional_tool_unavailable",
            },
        ]
    }

    ChatHandler._emit_completed_tool_events(
        sink, is_workflow=True, workflow_data=None, data=data, tools_used=[],
        progress_enabled=True, duration_ms=100, message_id="message-1",
        delivery_room="conversation-1",
    )

    assert [name for name, _, _ in sink.events] == ["tool:complete"] * 3
    assert [payload["workflow_step"] for _, payload, _ in sink.events] == [
        "1_0", "1_1", 2
    ]
    assert [payload["duration_ms"] for _, payload, _ in sink.events] == [7, 20, 0]
    assert sink.events[1][1]["success"] is False
    assert sink.events[2][1]["skipped"] is True
    assert sink.events[2][1]["reason"] == "Condition was false"
    assert all(room == "conversation-1" for _, _, room in sink.events)


def test_ordinary_tool_completion_events_only_emit_without_live_progress():
    sink = _EventSink()
    data = {"search": [{"item": "first"}, {"item": "second"}]}

    ChatHandler._emit_completed_tool_events(
        sink, is_workflow=False, workflow_data=None, data=data,
        tools_used=["search", "search"], progress_enabled=False,
        duration_ms=100, message_id="message-1", delivery_room="conversation-1",
    )

    assert [payload["result"] for _, payload, _ in sink.events] == data["search"]
    assert [payload["workflow_step"] for _, payload, _ in sink.events] == [0, 1]
    assert [payload["duration_ms"] for _, payload, _ in sink.events] == [50, 50]

    sink.events.clear()
    ChatHandler._emit_completed_tool_events(
        sink, is_workflow=False, workflow_data=None, data=data,
        tools_used=["search", "search"], progress_enabled=True,
        duration_ms=100, message_id="message-1", delivery_room="conversation-1",
    )
    assert sink.events == []
