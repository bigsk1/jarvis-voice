"""Regression coverage for remote MCP SSE initialization locking."""

from __future__ import annotations

from threading import Thread

from mcp_client import MCPRemoteClient


def test_first_sse_list_tools_can_reenter_request_during_initialize(monkeypatch):
    client = MCPRemoteClient("remote-test", "https://example.test/sse", "sse")
    requests = []

    # Exercise the same recursion as a real SSE handshake without networking:
    # tools/list -> start -> initialize -> _send_request("initialize").
    monkeypatch.setattr(client, "_start_sse", client._initialize_mcp)
    monkeypatch.setattr(client, "_post_message", lambda message: None)

    def send_sse_request(request):
        requests.append(request["method"])
        if request["method"] == "tools/list":
            return {"tools": [{"name": "public_search"}]}
        return {"protocolVersion": "2024-11-05"}

    monkeypatch.setattr(client, "_send_sse_request", send_sse_request)
    result = {}
    worker = Thread(
        target=lambda: result.setdefault("tools", client.list_tools()),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive(), "first SSE tools/list deadlocked during initialization"
    assert [tool["name"] for tool in result["tools"]] == ["public_search"]
    assert requests == ["initialize", "tools/list"]


def test_force_restart_preserves_remote_reentrant_lock(monkeypatch):
    client = MCPRemoteClient("remote-test", "https://example.test/sse", "sse")
    monkeypatch.setattr(client, "stop", lambda: None)

    client._force_restart("test")

    acquired_twice = []
    with client.lock:
        with client.lock:
            acquired_twice.append(True)
    assert acquired_twice == [True]


def test_sse_reconnect_can_reinitialize_while_request_lock_is_held(monkeypatch):
    client = MCPRemoteClient("remote-test", "https://example.test/sse", "sse")
    client._initialized = True
    monkeypatch.setattr(client, "_start_sse", client._initialize_mcp)
    monkeypatch.setattr(client, "_post_message", lambda message: None)
    monkeypatch.setattr(
        client,
        "_send_sse_request",
        lambda request: {"protocolVersion": "2024-11-05"},
    )

    completed = []

    def reconnect_during_request():
        with client.lock:
            client._reconnect_sse()
        completed.append(True)

    worker = Thread(target=reconnect_during_request, daemon=True)
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive(), "SSE reconnect deadlocked during initialization"
    assert completed == [True]
