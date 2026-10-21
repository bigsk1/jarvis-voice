"""Operator checks must not accept an MCP service without Host enforcement."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("unexpected_host_status", [200, 401, 500])
def test_operator_check_rejects_missing_host_guard_before_google_calls(
    monkeypatch, unexpected_host_status
):
    spec = importlib.util.spec_from_file_location(
        "google_host_policy_operator", ROOT / "lib/google_workspace_setup.py"
    )
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    connection = Mock(url="http://localhost:8765/mcp")
    responses = [Mock(status_code=status) for status in (200, 401, unexpected_host_status)]
    connection._http_request.side_effect = responses
    monkeypatch.setattr(setup, "service_config", lambda: {})
    monkeypatch.setattr(setup, "client", lambda: connection)

    with pytest.raises(setup.SetupError, match="Host boundary check failed"):
        setup.check(live=True)

    probe = connection._http_request.call_args_list[2]
    assert probe.args == ("GET", "http://localhost:8765/health")
    assert probe.kwargs["headers"] == {
        "Host": "untrusted.invalid", "Origin": "http://untrusted.invalid"
    }
    connection.start.assert_not_called()
    connection.call_tool.assert_not_called()
    connection.stop.assert_called_once()
    for response in responses:
        response.close.assert_called_once()
