"""Session rejection is retryable; ambiguous writes and auth failures are not."""

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import pytest
import requests
from mcp_client import MCPRemoteClient, _remote_call_budget, _RemoteCallBudget


def response(status=200, body=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {"Content-Type": "application/json"})
    result._content = json.dumps(body).encode() if body is not None else b'Session not found'
    result.raw = io.BytesIO(result._content)
    return result


def client():
    result = MCPRemoteClient("remote", "http://service/mcp", "http", {"Authorization": "Bearer configured"}, proxy_policy="off")
    result._initialized = True
    result._session_id = "old"
    return result


def test_http_session_restarts_once_and_preserves_request_headers(monkeypatch):
    connection = client()
    calls = []
    replies = iter([
        response(404), response(headers={"Mcp-Session-Id": "new"}), response(202),
        response(body={"result": {"content": [{"type": "text", "text": "Created"}]}}),
    ])
    def send(method, url, **kwargs):
        calls.append(kwargs)
        return next(replies)
    monkeypatch.setattr(connection, "_http_request", send)
    result = connection.call_tool("create", {"title": "one"})
    assert result["ok"]
    assert [c["json"]["method"] for c in calls] == ["tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert "Mcp-Session-Id" not in calls[1]["headers"]
    assert calls[2]["headers"]["Mcp-Session-Id"] == "new"
    assert calls[3]["headers"]["Mcp-Session-Id"] == "new"
    assert calls[0]["json"]["params"] == calls[3]["json"]["params"]
    assert all(c["headers"]["Authorization"] == "Bearer configured" for c in calls)


@pytest.mark.parametrize("status,body", [(401, None), (404, {"error": "Endpoint not found"}), (500, None)])
def test_unrelated_errors_do_not_replay_writes(monkeypatch, status, body):
    connection = client()
    calls = []
    def send(*args, **kwargs):
        calls.append(kwargs)
        return response(status, body)
    monkeypatch.setattr(connection, "_http_request", send)
    assert not connection.call_tool("create", {})["ok"]
    assert len(calls) == 1


def test_repeated_session_rejection_is_bounded(monkeypatch):
    connection = client()
    calls = []
    def send(*args, **kwargs):
        method = kwargs["json"]["method"]
        calls.append(method)
        if method == "initialize":
            return response(headers={"Mcp-Session-Id": "new"})
        return response(202) if method.startswith("notifications/") else response(404)
    monkeypatch.setattr(connection, "_http_request", send)
    assert not connection.call_tool("create", {})["ok"]
    assert calls.count("initialize") == 1
    assert calls.count("tools/call") == 2


def test_expired_call_cannot_initialize_after_session_rejection(monkeypatch):
    connection = client()
    calls = []
    budget = _RemoteCallBudget(time.monotonic() + 10)
    def send(*args, **kwargs):
        calls.append(kwargs)
        budget.cancelled.set()
        return response(404)
    monkeypatch.setattr(connection, "_http_request", send)
    token = _remote_call_budget.set(budget)
    try:
        with pytest.raises(requests.exceptions.Timeout):
            connection._send_request("tools/call", {"name": "create"})
    finally:
        _remote_call_budget.reset(token)
    assert len(calls) == 1


def test_tools_listing_follows_pagination_and_caches_complete_list(monkeypatch):
    connection = client()
    calls = []
    def send(method, params=None):
        calls.append(params)
        if params is None:
            return {"tools": [{"name": "first"}], "nextCursor": "page-two"}
        return {"tools": [{"name": "second"}]}
    monkeypatch.setattr(connection, "_send_request", send)
    assert connection.list_tools() == [{"name": "first"}, {"name": "second"}]
    assert connection.list_tools() == [{"name": "first"}, {"name": "second"}]
    assert calls == [None, {"cursor": "page-two"}]


def test_repeated_cursor_does_not_publish_partial_cache(monkeypatch):
    connection = client()
    monkeypatch.setattr(connection, "_send_request", lambda *a: {"tools": [{"name": "partial"}], "nextCursor": "same"})
    assert connection.list_tools() == []
    assert connection._tools_cache is None


@pytest.mark.parametrize('bad_tool', [
    None, {}, {'name': None}, {'name': 'bad', 'inputSchema': None},
    {'name': 'bad', 'inputSchema': []}, {'name': 'bad', 'inputSchema': {'properties': None}},
    {'name': 'bad', 'inputSchema': {'properties': []}},
    {'name': 'bad', 'inputSchema': {'properties': {'query': None}}},
    {'name': 'bad', 'inputSchema': {'required': None}},
    {'name': 'bad', 'description': None}, {'name': 'bad', 'annotations': ['invalid']},
])
def test_malformed_schema_does_not_hide_other_tools(monkeypatch, bad_tool):
    connection = client()
    first = {'name': 'first', 'inputSchema': {'properties': {'query': {'type': 'string'}}}}
    second = {'name': 'second'}
    monkeypatch.setattr(connection, '_send_request', lambda *_: {'tools': [first, bad_tool, second]})
    assert connection.list_tools() == [first, second]
    assert connection._tool_properties == {'first': {'query'}, 'second': set()}
    monkeypatch.setattr(connection, '_send_request', lambda *_: pytest.fail('Complete catalog should be cached'))
    assert connection.list_tools() == [first, second]
