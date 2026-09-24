"""Pending Web notifications survive a page reload after their first delivery."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
load_server_package("jarvis_proactive_snapshot_test", ROOT / "jarvis-web/server")

from jarvis_proactive_snapshot_test.services import proactive_service  # noqa: E402
from jarvis_proactive_snapshot_test.sockets import chat  # noqa: E402


def test_pending_snapshot_ignores_notified_cache(monkeypatch):
    alert = {"id": 41, "title": "Weather watch", "status": "pending"}
    reminder = {"id": 73, "title": "Review backup", "status": "triggered"}

    def fake_get(url, **_kwargs):
        key, items = ("alerts", [alert]) if url.endswith("/api/alerts") else ("reminders", [reminder])
        return SimpleNamespace(status_code=200, json=lambda: {key: items})

    monkeypatch.setattr(proactive_service.requests, "get", fake_get)
    monkeypatch.setattr(proactive_service, "get_internal_api_base_url", lambda: "http://jarvis-api")
    monkeypatch.setattr(proactive_service, "get_internal_api_headers", lambda: {})
    service = proactive_service.ProactiveService(notified_alerts={41}, notified_reminders={73})

    result = service.poll_and_notify()

    assert result["new_alerts"] == []
    assert result["new_reminders"] == []
    assert result["snapshot"] == {
        "alerts": [alert], "reminders": [reminder], "counts": {"alerts": 1, "reminders": 1},
    }
    assert service.get_pending_counts() == {"alerts": 1, "reminders": 1}


def test_subscribe_and_check_send_persisted_items_to_this_client(monkeypatch):
    class Socket:
        def __init__(self):
            self.handlers = {}

        def on(self, event):
            def register(handler):
                self.handlers[event] = handler
                return handler
            return register

    snapshot = {
        "alerts": [{"id": 41, "title": "Weather watch"}],
        "reminders": [],
        "counts": {"alerts": 1, "reminders": 0},
    }
    service = SimpleNamespace(
        get_pending_snapshot=lambda: snapshot,
        poll_and_notify=lambda: {
            "new_alerts": [], "new_reminders": [],
            "counts": snapshot["counts"], "snapshot": snapshot,
        },
    )
    monkeypatch.setattr(proactive_service, "get_proactive_service", lambda: service)
    emitted = []
    monkeypatch.setattr(chat, "emit", lambda event, data: emitted.append((event, data)))
    socket = Socket()
    handler = object.__new__(chat.ChatHandler)
    handler.socketio = socket
    handler._register_handlers()
    app = Flask(__name__)

    with app.test_request_context():
        request.sid = "browser-session"
        socket.handlers["proactive:subscribe"]({})
        assert ("proactive:snapshot", snapshot) in emitted
        assert ("proactive:counts", snapshot["counts"]) in emitted

        emitted.clear()
        socket.handlers["proactive:check"]({})
        assert ("proactive:snapshot", snapshot) in emitted
        assert ("proactive:counts", snapshot["counts"]) in emitted
