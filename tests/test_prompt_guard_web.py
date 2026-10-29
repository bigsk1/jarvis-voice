"""A security stop cannot be replayed through Web Completion Guard."""

import importlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
load_server_package("prompt_guard_web_test_server", ROOT / "jarvis-web/server")
chat = importlib.import_module("prompt_guard_web_test_server.sockets.chat")


@pytest.mark.parametrize("record", [
    {"prompt_guard_blocked": True},
    {"error_code": "prompt_injection_detected", "terminal_failure": True},
    {"data": {"prompt_guard": {"content_withheld": True}}},
    {"data": {"crawl_url": {"prompt_guard": {"content_withheld": True}}}},
])
def test_security_stop_prevents_audit_repair_and_feedback_replays(monkeypatch, record):
    handler = chat.ChatHandler.__new__(chat.ChatHandler)
    record = {"mode": "cloud", **record}
    before = deepcopy(record)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Security stops must not start an audit, repair, or feedback model")

    monkeypatch.setattr(handler, "_evaluate_completion_guard_auto", unexpected)
    monkeypatch.setattr(handler, "_start_blocking_task", unexpected)
    monkeypatch.setattr(handler, "_process_completion_guard_repair", unexpected)
    handler._run_completion_guard_auto_eval("session", record)
    handler._run_completion_guard_repair("session", record, background=True)
    # Also guard a direct internal repair entry, before provider construction.
    chat.ChatHandler._process_completion_guard_repair(handler, "session", record, "", "repair")
    assert handler._background_review_blocked(record)
    assert record == before


@pytest.mark.parametrize("accepted", [True, False])
def test_direct_completion_guard_socket_submission_cannot_replay_security_stop(monkeypatch, accepted):
    callbacks = {}

    class Socket:
        def on(self, name):
            def register(function):
                callbacks[name] = function
                return function
            return register

    handler = chat.ChatHandler.__new__(chat.ChatHandler)
    handler.socketio = Socket()
    handler.sessions = {"session": {"conversation_id": "conversation"}}
    record = {"message_id": "message", "conversation_id": "conversation", "prompt_guard_blocked": True}
    monkeypatch.setattr(handler, "_get_completion_guard_record", lambda *_args: record)
    monkeypatch.setattr(chat, "request", SimpleNamespace(sid="session"))
    events = []
    monkeypatch.setattr(chat, "emit", lambda *args, **_kwargs: events.append(args))
    handler._register_handlers()
    callbacks["completion_guard:submit"]({
        "message_id": "message", "conversation_id": "conversation", "accepted": accepted,
    })
    assert events[0][0] == "completion_guard:error"
    assert "Prompt Guard" in events[0][1]["error"]
    assert "repair_attempts" not in record and "status" not in record


def test_normal_failure_is_not_a_security_stop():
    assert not chat._prompt_guard_stopped({"ok": False, "error": "Remote timeout", "data": {}})
    assert not chat._prompt_guard_stopped({"data": {"prompt_guard": {"content_withheld": False}}})


def test_detection_during_repair_cannot_trigger_answer_synthesis():
    handler = chat.ChatHandler.__new__(chat.ChatHandler)
    rejection = {"error_code": "prompt_injection_detected", "terminal_failure": True,
                 "data": {"prompt_guard": {"content_withheld": True}}}
    assert handler._synthesize_from_existing_tool_result(None, {}, "", rejection, {}) is None
