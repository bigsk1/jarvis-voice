"""Tailscale settings diagnostics with disposable JSON and no daemon calls."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

from flask import Blueprint, Flask, jsonify
import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "jarvis-web" / "server"
PACKAGE = "jarvis_tailscale_status_test"
load_server_package(PACKAGE, SERVER)
from jarvis_tailscale_status_test.services import tailscale_status as service  # noqa: E402
detect_deployment = service._deployment


def serve_config(host="jarvis.example.test", port=443):
    return {"TCP": {str(port): {"HTTPS": True}},
            "Web": {f"{host}:{port}": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5001"}}}}}


def node_status(**self_values):
    return {"BackendState": "Running", "Self": {"DNSName": "Jarvis.Example.Test.", "Online": True, **self_values}}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(service, "_cache", None)
    monkeypatch.setattr(service, "_cache_expires", 0.0)
    monkeypatch.setattr(service, "_deployment", lambda: "native")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected real command"))


def mock_commands(monkeypatch, status=None, serve=None):
    calls = []
    status = node_status() if status is None else status
    serve = serve_config() if serve is None else serve

    def run(command, **kwargs):
        calls.append((command, kwargs))
        value = serve if command[1] == "serve" else status
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())

    monkeypatch.setattr(service.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("marker,setting,expected", [
    (None, "docker", "docker"), ("/.dockerenv", "", "docker"),
    ("/run/.containerenv", "", "docker"), (None, "", "native"),
])
def test_deployment_detection_uses_existing_env_and_container_markers(monkeypatch, marker, setting, expected):
    monkeypatch.setenv("JARVIS_DEPLOYMENT", setting)
    monkeypatch.setattr(service.Path, "exists", lambda path: str(path) == marker)
    assert detect_deployment() == expected


def test_running_node_returns_only_reduced_safe_status_and_fixed_commands(monkeypatch):
    status = node_status()
    status.update(Peer={"private-peer": {"HostName": "must-not-leak"}}, User={"private-user": {}},
                  AuthURL="https://login.example.test/private-secret", TailscaleIPs=["100.64.0.1"])
    calls = mock_commands(monkeypatch, status=status)
    result = service.get_tailscale_status()
    assert result["state"] == "running"
    assert result["backend_state"] == "Running"
    assert result["hostname"] == "jarvis.example.test"
    assert result["online"] is True
    assert result["serve"] == {"state": "configured", "error_code": None, "listeners": [
        {"hostname": "jarvis.example.test", "port": 443, "https": True, "funnel": False},
    ]}
    assert result["cached"] is False
    assert result["checked_at"]
    assert [call[0] for call in calls] == [
        ["/usr/bin/tailscale", "status", "--json", "--peers=false"],
        ["/usr/bin/tailscale", "serve", "status", "--json"],
    ]
    assert all(kwargs == {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                          "timeout": 2, "check": False} for _, kwargs in calls)
    serialized = json.dumps(result)
    for private in ("must-not-leak", "private-peer", "private-user", "private-secret", "100.64.0.1", "127.0.0.1"):
        assert private not in serialized


@pytest.mark.parametrize("deployment,expected_state,expected_error", [
    ("native", "not_installed", "cli_not_found"),
    ("docker", "unavailable", "host_status_unavailable"),
])
def test_missing_cli_does_not_claim_the_docker_host_has_no_tailscale(monkeypatch, deployment, expected_state, expected_error):
    monkeypatch.setattr(service, "_deployment", lambda: deployment)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    result = service.get_tailscale_status()
    assert (result["state"], result["error_code"]) == (expected_state, expected_error)
    assert result["online"] is None
    assert result["serve"]["state"] == "unavailable"


@pytest.mark.parametrize("backend", ["Stopped", "NeedsLogin", "NeedsMachineAuth", "Starting", "NoState"])
def test_inactive_or_unauthorized_backend_is_never_promoted_by_self_online(monkeypatch, backend):
    status = {**node_status(), "BackendState": backend}
    mock_commands(monkeypatch, status=status)
    result = service.get_tailscale_status()
    assert result["state"] == "stopped"
    assert result["backend_state"] == backend


@pytest.mark.parametrize("self_values", [{}, {"Online": None}, {"Online": "true"}, {"Online": 1}])
def test_missing_or_invalid_online_is_unknown(monkeypatch, self_values):
    mock_commands(monkeypatch, status={"BackendState": "Running", "Self": self_values})
    assert service.get_tailscale_status()["online"] is None


@pytest.mark.parametrize("response", [b"[]", b"null", b"{", b' {"BackendState": []}',
                                      b'{"BackendState":"unknown-state"}', b"x" * (service.MAX_RESPONSE_BYTES + 1)])
def test_invalid_status_fails_closed_without_serve_command(monkeypatch, response):
    calls = []
    monkeypatch.setattr(service.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0, stdout=response)
    ))
    result = service.get_tailscale_status()
    assert result["state"] == "unavailable"
    assert result["online"] is None
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "permission", "exit"])
def test_failed_status_never_exposes_cli_errors_or_claims_stopped(monkeypatch, failure):
    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 2, output=b"private timeout detail")
        if failure == "permission":
            raise PermissionError("private socket path")
        return SimpleNamespace(returncode=1, stdout=json.dumps(node_status()).encode())
    monkeypatch.setattr(service.subprocess, "run", run)
    result = service.get_tailscale_status()
    assert result["state"] == "unavailable"
    assert "private" not in json.dumps(result)


def test_serve_failure_keeps_running_node_but_exposure_unknown(monkeypatch):
    def run(command, **kwargs):
        if command[1] == "serve":
            raise subprocess.TimeoutExpired(command, 2)
        return SimpleNamespace(returncode=0, stdout=json.dumps(node_status()).encode())
    monkeypatch.setattr(service.subprocess, "run", run)
    result = service.get_tailscale_status()
    assert result["state"] == "running"
    assert result["serve"] == {"state": "unavailable", "listeners": [], "error_code": "serve_timeout"}


@pytest.mark.parametrize("configuration", [None, {}])
def test_empty_serve_configuration_is_not_configured(configuration):
    assert service.parse_serve_status(configuration) == {"state": "not_configured", "listeners": [], "error_code": None}


def test_foreground_listeners_and_funnel_grants_are_combined_by_hostname_and_port():
    config = serve_config(port=443)
    config["AllowFunnel"] = {"jarvis.example.test:443": False, "jarvis.example.test:8443": True}
    foreground = serve_config(port=8443)
    foreground["AllowFunnel"] = {"JARVIS.EXAMPLE.TEST.:443": True, "jarvis.example.test:8443": False}
    config["Foreground"] = {"disposable-session": foreground}
    result = service.parse_serve_status(config)
    assert result["state"] == "configured"
    assert [(item["port"], item["funnel"]) for item in result["listeners"]] == [(443, True), (8443, True)]


def test_public_grant_on_another_endpoint_does_not_mark_this_listener_public():
    config = serve_config()
    config["AllowFunnel"] = {"other.example.test:443": True, "jarvis.example.test:8443": True}
    assert service.parse_serve_status(config)["listeners"][0]["funnel"] is False


@pytest.mark.parametrize("endpoint", ["[::1:443", "::1:443", "jarvis.example.test", "jarvis.example.test:0"])
def test_invalid_funnel_endpoint_makes_other_exposure_unknown(endpoint):
    config = {**serve_config(), "AllowFunnel": {endpoint: True}}
    result = service.parse_serve_status(config)
    assert result["state"] == "unavailable"
    assert result["listeners"][0]["funnel"] is None


@pytest.mark.parametrize("change", [
    {"AllowFunnel": None}, {"AllowFunnel": {"jarvis.example.test:443": "false"}},
    {"AllowFunnel": {"bad-endpoint": True}}, {"Foreground": ["not-a-map"]},
    {"Foreground": {"session": "not-a-config"}}, {"UnknownExposure": True},
    {"Services": []},
])
def test_partial_malformed_exposure_never_claims_private(change):
    result = service.parse_serve_status({**serve_config(), **change})
    assert result["state"] == "unavailable"
    assert result["listeners"][0]["funnel"] is None


def test_known_public_grant_survives_other_malformed_metadata():
    config = {**serve_config(), "AllowFunnel": {"jarvis.example.test:443": True}, "Foreground": []}
    assert service.parse_serve_status(config)["listeners"][0]["funnel"] is True


@pytest.mark.parametrize("handler", [{"HTTPS": "true"}, {"HTTPS": True, "HTTP": True},
                                     {"HTTPS": True, "TCPForward": "127.0.0.1:5001"}])
def test_invalid_tcp_metadata_does_not_verify_a_private_listener(handler):
    config = serve_config()
    config["TCP"]["443"] = handler
    result = service.parse_serve_status(config)
    assert result["state"] == "unavailable"
    assert all(listener["funnel"] is None for listener in result["listeners"])


def test_http_only_serve_is_not_reported_as_https():
    config = serve_config(port=80)
    config["TCP"]["80"] = {"HTTP": True}
    assert service.parse_serve_status(config) == {"state": "configured", "listeners": [], "error_code": None}


def test_malformed_handlers_and_excessive_foreground_blocks_cannot_claim_private():
    config = serve_config()
    config["Web"]["jarvis.example.test:443"]["Handlers"]["/"] = {"Proxy": ["invalid"]}
    assert service.parse_serve_status(config)["listeners"][0]["funnel"] is None
    config = serve_config()
    config["Foreground"] = {str(index): {} for index in range(service.MAX_CONFIG_BLOCKS + 1)}
    result = service.parse_serve_status(config)
    assert result["state"] == "unavailable"
    assert result["listeners"][0]["funnel"] is None


def test_cache_refreshes_after_ttl_and_returns_independent_snapshots(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    calls = mock_commands(monkeypatch)
    first = service.get_tailscale_status()
    first["serve"]["listeners"].clear()
    now[0] = 114.9
    second = service.get_tailscale_status()
    assert second["cached"] is True and len(second["serve"]["listeners"]) == 1
    assert len(calls) == 2
    now[0] = 115.0
    assert service.get_tailscale_status()["cached"] is False
    assert len(calls) == 4


def test_concurrent_requests_share_one_probe_pair(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        time.sleep(0.02)
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            serve_config() if command[1] == "serve" else node_status()).encode())
    monkeypatch.setattr(service.subprocess, "run", run)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.get_tailscale_status(), range(8)))
    assert len(calls) == 2
    assert sum(not result["cached"] for result in results) == 1


def test_failed_probes_are_cached_too(monkeypatch):
    calls = []
    monkeypatch.setattr(service.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=1, stdout=b"private error")
    ))
    assert service.get_tailscale_status()["state"] == "unavailable"
    assert service.get_tailscale_status()["cached"] is True
    assert len(calls) == 1


def test_real_route_uses_existing_auth_gate_and_refresh_obeys_the_shared_cache(monkeypatch):
    # Execute only the production route and auth gate in a minimal Flask app.
    # Importing server.app would initialize unrelated live application services.
    app = Flask(__name__)
    blueprint = Blueprint("api", __name__, url_prefix="/api")
    scope = {"api_bp": blueprint, "jsonify": jsonify, "__package__": f"{PACKAGE}.routes"}
    routes = ast.parse((SERVER / "routes/api.py").read_text())
    route = next(item for item in routes.body if isinstance(item, ast.FunctionDef) and item.name == "get_tailscale_status_route")
    exec(compile(ast.Module(body=[route], type_ignores=[]), str(SERVER / "routes/api.py"), "exec"), scope)
    app.register_blueprint(blueprint)
    application = ast.parse((SERVER / "app.py").read_text())
    scope.update(app=app, is_auth_enabled=lambda: True,
                 get_token_from_request=lambda request: request.headers.get("Authorization"),
                 verify_token=lambda token: token == "Bearer disposable-test-token")
    for item in application.body:
        if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"PUBLIC_ROUTES", "PUBLIC_EXTENSIONS"} for target in item.targets):
            exec(compile(ast.Module(body=[item], type_ignores=[]), str(SERVER / "app.py"), "exec"), scope)
    guard = next(item for item in application.body if isinstance(item, ast.FunctionDef) and item.name == "check_auth")
    exec(compile(ast.Module(body=[guard], type_ignores=[]), str(SERVER / "app.py"), "exec"), scope)
    calls = mock_commands(monkeypatch)
    client = app.test_client()
    assert client.get("/api/tailscale/status").status_code == 401
    assert calls == []
    headers = {"Authorization": "Bearer disposable-test-token"}
    first = client.get("/api/tailscale/status", headers=headers)
    assert first.status_code == 200
    assert first.headers["Cache-Control"] == "private, no-store"
    assert first.json["cached"] is False
    assert client.get("/api/tailscale/status?refresh=1", headers=headers).json["cached"] is True
    assert len(calls) == 2
