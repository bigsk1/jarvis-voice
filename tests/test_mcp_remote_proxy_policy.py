"""Remote MCP proxy policies apply to handshake, notifications and tool calls."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import http_client
import pytest
import requests
from mcp_client import MCPManager, MCPRemoteClient


def configure(monkeypatch, values):
    monkeypatch.setattr(http_client, "get_config_value", lambda key, default=None: values.get(key, default))


def test_remote_prefer_uses_secondary_proxy_for_every_http_message(monkeypatch):
    configure(monkeypatch, {
        # A per-server policy must override this without mutating it.
        "JARVIS_TOOL_PROXY_POLICY": "off",
        "LOCAL_PROXY": "http://primary.test:8001",
        "LOCAL_PROXY2": "http://secondary.test:8002",
    })
    calls = []

    def request(method, url, **kwargs):
        calls.append((kwargs["json"].get("method"), dict(kwargs["proxies"])))
        if kwargs["proxies"]["https"] == "http://primary.test:8001":
            raise requests.exceptions.ProxyError("primary unavailable")
        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.iter_lines.return_value = []
        response.json.return_value = {"result": {
            "tools": [{"name": "lookup"}],
            "content": [{"type": "text", "text": '{"verdict":"unknown"}'}],
        }}
        return response

    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="prefer")
    assert client.list_tools() == [{"name": "lookup"}]
    assert client.call_tool("lookup", {})["ok"] is True
    assert [method for method, _ in calls] == [
        "initialize", "initialize", "notifications/initialized", "notifications/initialized",
        "tools/list", "tools/list", "tools/call", "tools/call",
    ]
    assert client.get_proxy_log_metadata() == {
        "policy": "prefer", "used": True, "basis": "http_request", "slot": "LOCAL_PROXY2",
    }
    assert http_client.get_proxy_policy() == "off"


def test_remote_prefer_can_fall_back_direct_and_logs_that_route(monkeypatch):
    configure(monkeypatch, {"LOCAL_PROXY": "http://user:password@primary.test:8001"})
    calls = []

    def request(method, url, **kwargs):
        calls.append(dict(kwargs["proxies"]))
        if kwargs["proxies"]["https"]:
            raise requests.exceptions.ProxyError("unavailable")
        return Mock(status_code=200)

    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="prefer")
    client._http_request("POST", client.url, json={})
    assert calls[-1] == {"http": None, "https": None, "all": None}
    metadata = client.get_proxy_log_metadata()
    assert metadata["used"] is False
    assert metadata["direct_reason"] == "fallback_after_proxy_failed"
    assert "password" not in json.dumps(metadata)
    assert "primary.test" not in json.dumps(metadata)


@pytest.mark.parametrize("configured", [False, True])
def test_remote_require_never_calls_direct(monkeypatch, configured):
    configure(monkeypatch, {"LOCAL_PROXY": "http://primary.test:8001"} if configured else {})
    request = Mock(side_effect=requests.exceptions.ProxyError("unavailable"))
    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="require")
    with pytest.raises(requests.exceptions.ProxyError):
        client._http_request("POST", client.url)
    assert request.call_count == int(configured)
    if configured:
        assert request.call_args.kwargs["proxies"]["https"] == "http://primary.test:8001"


def test_remote_off_is_direct_even_with_other_proxy_settings(monkeypatch):
    configure(monkeypatch, {"JARVIS_TOOL_PROXY_POLICY": "require", "LOCAL_PROXY": "http://primary.test:8001"})
    request = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/sse", "sse", proxy_policy="off")
    client._http_request("GET", client.url, stream=True)
    assert request.call_args.kwargs["proxies"] == {"http": None, "https": None, "all": None}
    assert client.get_proxy_log_metadata()["direct_reason"] == "policy_off"


def test_remote_omitted_policy_preserves_existing_requests_path(monkeypatch):
    request = Mock()
    monkeypatch.setattr("mcp_client.requests.post", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http")
    client._http_request("POST", client.url, json={})
    request.assert_called_once_with(client.url, json={})
    assert client.get_proxy_log_metadata()["used"] is None


def test_remote_prefer_labels_secondary_slot_when_primary_is_unconfigured(monkeypatch):
    configure(monkeypatch, {"LOCAL_PROXY2": "http://secondary.test:8002"})
    request = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="prefer")
    client._http_request("POST", client.url)
    assert client.get_proxy_log_metadata()["slot"] == "LOCAL_PROXY2"


def test_manager_passes_shipped_malwarebytes_proxy_policy_to_client(tmp_path):
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parent.parent / "config/mcp-servers.json").read_text())
    isolated = tmp_path / "mcp.json"
    isolated.write_text(json.dumps({"mcpServers": {"malwarebytes": config["mcpServers"]["malwarebytes"]}}))
    manager = MCPManager(str(isolated))
    assert manager.servers["malwarebytes"].proxy_policy == "prefer"


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_executor_and_remote_worker_keep_selected_mode_proxy_and_only_declared_header(tmp_path, monkeypatch, mode):
    import config_loader
    from config_loader import config_scope

    from orchestrator.executor import ToolExecutor

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for selected in ("cloud", "local"):
        (config_dir / f"{selected}.env").write_text(
            f"LOCAL_PROXY=http://{selected}.test:8111\nLOCAL_PROXY2=\n"
            f"ZZ_DECLARED_KEY={selected}-key\nZZ_UNRELATED_SECRET=UNRELATED_SECRET_SENTINEL\n"
        )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("LOCAL_PROXY", "http://startup.test:8110")
    for key in ("LOCAL_PROXY", "LOCAL_PROXY2", "ZZ_DECLARED_KEY"):
        monkeypatch.delenv(f"JARVIS_OVERRIDE_{key}", raising=False)
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"remote": {
        "type": "http", "url": "https://example.test/mcp", "proxy_policy": "prefer",
        "headers": {"Authorization": "Bearer ${ZZ_DECLARED_KEY}"},
        "env": {"SHOULD_BE_IGNORED": "${ZZ_UNRELATED_SECRET}"},
    }}}))
    captured = []

    def request(method, url, **kwargs):
        captured.append(kwargs)
        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.json.return_value = {"result": {"content": [{"type": "text", "text": "done"}]}}
        return response

    monkeypatch.setattr(http_client.requests, "request", request)
    with config_scope(mode):
        client = MCPManager(str(path)).servers["remote"]
        client._initialized = True
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.mode = mode
        executor.registry = SimpleNamespace(
            mcp_clients={"remote": client}, get_mcp_info=lambda name: ("remote", "lookup"),
        )
        executor.logger = Mock()
        result = executor._execute_mcp_tool("mcp_remote_lookup", {})
    assert result["ok"]
    assert captured[0]["proxies"]["https"] == f"http://{mode}.test:8111"
    assert captured[0]["headers"]["Authorization"] == f"Bearer {mode}-key"
    assert "UNRELATED_SECRET_SENTINEL" not in json.dumps(captured)
    assert "SHOULD_BE_IGNORED" not in json.dumps(captured)
    assert client._call_budgets == {}


def test_proxy_attempts_leave_time_for_direct_fallback(monkeypatch):
    configure(monkeypatch, {
        "LOCAL_PROXY": "http://primary.test:8001", "LOCAL_PROXY2": "http://secondary.test:8002",
    })
    elapsed = [0.0]
    monkeypatch.setattr(http_client.time, "monotonic", lambda: elapsed[0])
    timeouts = []

    def request(method, url, **kwargs):
        timeouts.append(kwargs["timeout"])
        if kwargs["proxies"]["https"]:
            elapsed[0] += 5
            raise requests.exceptions.ReadTimeout("proxy did not answer")
        return Mock(status_code=200)

    monkeypatch.setattr(http_client.requests, "request", request)
    http_client.http_request(
        "POST", "https://example.test", timeout=30, proxy_policy="prefer",
        proxy_timeout=(3, 5), deadline=12,
    )
    assert timeouts == [(3, 5), (3, 5), (2, 2)]


def test_exhausted_deadline_prevents_another_route_attempt(monkeypatch):
    configure(monkeypatch, {
        "LOCAL_PROXY": "http://primary.test:8001", "LOCAL_PROXY2": "http://secondary.test:8002",
    })
    elapsed = [0.0]
    monkeypatch.setattr(http_client.time, "monotonic", lambda: elapsed[0])
    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs["proxies"]["https"])
        elapsed[0] = 12
        raise requests.exceptions.ReadTimeout("proxy did not answer")

    monkeypatch.setattr(http_client.requests, "request", request)
    with pytest.raises(requests.exceptions.Timeout, match="deadline"):
        http_client.http_request(
            "POST", "https://example.test", proxy_policy="prefer",
            proxy_timeout=(3, 5), deadline=12,
        )
    assert calls == ["http://primary.test:8001"]


def test_timed_out_remote_worker_cannot_later_retry_another_proxy(monkeypatch):
    configure(monkeypatch, {
        "LOCAL_PROXY": "http://primary.test:8001", "LOCAL_PROXY2": "http://secondary.test:8002",
    })
    monkeypatch.setenv("MCP_TOOL_CALL_TIMEOUT_SECONDS", "1")
    entered, release, finished = Event(), Event(), Event()
    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs["proxies"]["https"])
        entered.set()
        assert release.wait(3)
        raise requests.exceptions.ReadTimeout("late failure")

    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="prefer")
    client._initialized = True
    send_request = client._send_request

    def send(*args):
        try:
            return send_request(*args)
        finally:
            finished.set()

    monkeypatch.setattr(client, "_send_request", send)
    try:
        result = client.call_tool("lookup", {})
        assert entered.is_set()
        assert result["ok"] is False
        assert "timed out" in result["error"]
    finally:
        release.set()
        assert finished.wait(1)
    assert calls == ["http://primary.test:8001"]


def test_executor_timeout_does_not_wait_for_blocked_mcp_worker(monkeypatch):
    from orchestrator.executor import ToolExecutor

    monkeypatch.setenv("MCP_EXECUTOR_TIMEOUT_SECONDS", "1")
    entered, release, finished = Event(), Event(), Event()

    def call(name, arguments):
        entered.set()
        try:
            assert release.wait(3)
            return {"ok": True}
        finally:
            finished.set()

    client = SimpleNamespace(call_tool=call, _force_restart=Mock())
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.mode = "cloud"
    executor.registry = SimpleNamespace(
        mcp_clients={"remote": client}, get_mcp_info=lambda name: ("remote", "lookup"),
    )
    executor.logger = Mock()
    try:
        result = executor._execute_mcp_tool("mcp_remote_lookup", {})
        assert entered.is_set()
        assert not finished.is_set(), "executor waited for the timed-out worker"
        assert result["error"] == "Executor timeout after 1s"
        client._force_restart.assert_called_once()
    finally:
        release.set()
        assert finished.wait(1)


def test_sse_listener_keeps_config_scope_without_inheriting_tool_deadline(monkeypatch):
    import time

    import mcp_client
    from config_loader import config_scope, get_config_value

    client = MCPRemoteClient("test", "https://example.test/sse", "sse")
    observed = {}

    def listener():
        observed["proxy"] = get_config_value("LOCAL_PROXY")
        observed["budget"] = mcp_client._remote_call_budget.get()
        client._sse_connected.set()

    monkeypatch.setattr(client, "_sse_listener", listener)
    monkeypatch.setattr(client, "_initialize_mcp", lambda: None)
    token = mcp_client._remote_call_budget.set(mcp_client._RemoteCallBudget(time.monotonic() + 35))
    try:
        with config_scope("local", overrides={"LOCAL_PROXY": "http://local.test:8111"}):
            client.start()
        client.stop()
    finally:
        mcp_client._remote_call_budget.reset(token)
    assert observed == {"proxy": "http://local.test:8111", "budget": None}


def test_outer_timeout_cancels_remote_budget_before_late_proxy_failure(monkeypatch):
    from orchestrator.executor import ToolExecutor

    configure(monkeypatch, {
        "LOCAL_PROXY": "http://primary.test:8001", "LOCAL_PROXY2": "http://secondary.test:8002",
    })
    monkeypatch.setenv("MCP_EXECUTOR_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("MCP_TOOL_CALL_TIMEOUT_SECONDS", "35")
    release, finished = Event(), Event()
    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs["proxies"]["https"])
        assert release.wait(3)
        raise requests.exceptions.ReadTimeout("late proxy failure")

    monkeypatch.setattr(http_client.requests, "request", request)
    client = MCPRemoteClient("test", "https://example.test/mcp", "http", proxy_policy="prefer")
    client._initialized = True
    original = client.call_tool

    def call(*args):
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(client, "call_tool", call)
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.mode = "cloud"
    executor.registry = SimpleNamespace(
        mcp_clients={"remote": client}, get_mcp_info=lambda name: ("remote", "lookup"),
    )
    executor.logger = Mock()
    try:
        result = executor._execute_mcp_tool("mcp_remote_lookup", {})
        assert result["error"] == "Executor timeout after 1s"
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(1)
    assert calls == ["http://primary.test:8001"]
