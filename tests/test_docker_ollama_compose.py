"""Render the real opt-in Compose merge without starting containers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")


@pytest.fixture
def compose_checkout(tmp_path):
    # Never interpolate the operator's root .env or read private mode files.
    for name in ("docker-compose.yml", "docker-compose.ollama.yml", "docker-compose.mcp.yml"):
        shutil.copy2(ROOT / name, tmp_path / name)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT", "DOCKER_CONFIG") if key in os.environ}
    return tmp_path, env


def render(setup, *, ollama=False, mcp=False, mode="cloud", extras=False, overrides=None):
    if not DOCKER:
        pytest.skip("Docker Compose CLI is required for config-only merge checks")
    directory, env = setup
    env = {**env, "JARVIS_MODE": mode, **(overrides or {})}
    args = [DOCKER, "compose", "-f", "docker-compose.yml"]
    if ollama:
        args += ["-f", "docker-compose.ollama.yml"]
    if mcp:
        args += ["-f", "docker-compose.mcp.yml"]
        env["JARVIS_DOCKER_SOCKET_GID"] = "999"
    if extras:
        args += ["--profile", "extras"]
    result = subprocess.run(
        [*args, "config", "--format", "json"],
        cwd=directory, env=env, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_base_keeps_external_ollama_and_auth_defaults_on(compose_checkout, mode):
    config = render(compose_checkout, mode=mode, extras=True, overrides={
        "JARVIS_DOCKER_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
    })
    assert not any(name.startswith("jarvis-ollama") for name in config["services"])
    for service in config["services"].values():
        env = service["environment"]
        assert env["JARVIS_MODE"] == mode
        assert env["JARVIS_OVERRIDE_JARVIS_API_AUTH"] == "true"
        assert env["JARVIS_DOCKER_OLLAMA_BASE_URL"] == "http://host.docker.internal:11434"


def test_explicit_auth_opt_out_is_preserved(compose_checkout):
    config = render(compose_checkout, overrides={"JARVIS_DOCKER_API_AUTH": "false"})
    assert config["services"]["jarvis-api"]["environment"]["JARVIS_OVERRIDE_JARVIS_API_AUTH"] == "false"


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("mcp", [False, True])
def test_ollama_overlay_gates_all_jarvis_services_without_losing_base_settings(compose_checkout, mode, mcp):
    config = render(compose_checkout, ollama=True, mcp=mcp, mode=mode, extras=True, overrides={
        "JARVIS_DOCKER_OLLAMA_BASE_URL": "http://native-host.example:11434",
        "JARVIS_DOCKER_HELPER_LLM_BASE_URL": "http://helper.example:11434",
    })
    services = config["services"]
    applications = {name: service for name, service in services.items() if name not in {
        "jarvis-ollama", "jarvis-ollama-init",
    }}
    assert len(applications) == 9
    for service in applications.values():
        env = service["environment"]
        assert env["JARVIS_MODE"] == mode
        assert env["JARVIS_DOCKER_OLLAMA_BASE_URL"] == "http://jarvis-ollama:11434"
        assert env["JARVIS_OVERRIDE_OLLAMA_EMBEDDING_FALLBACK_URL"] == ""
        assert env["JARVIS_DOCKER_HELPER_LLM_BASE_URL"] == "http://helper.example:11434"
        assert env["JARVIS_OVERRIDE_JARVIS_API_AUTH"] == "true"
        assert service["depends_on"]["jarvis-ollama-init"]["condition"] == "service_completed_successfully"
        assert any(volume["target"] == "/app/config" and volume["read_only"] for volume in service["volumes"])

    web = services["jarvis-web"]
    assert web["depends_on"]["jarvis-api"]["condition"] == "service_started"
    assert web["depends_on"]["jarvis-canvas"]["condition"] == "service_started"
    assert web["environment"]["JARVIS_LIBRARY_WORKER_EXTERNAL"] == "1"
    assert services["jarvis-services"]["depends_on"]["jarvis-api"]["condition"] == "service_started"
    assert (web["image"] == "jarvis-voice:mcp") is mcp
    assert web["environment"]["JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE"] == ("docker-mcp" if mcp else "docker")
    assert services["jarvis-task-worker"]["profiles"] == ["extras", "background-tasks"]


def test_ollama_daemon_is_private_persistent_cpu_and_initializer_has_no_credentials_or_data(compose_checkout):
    config = render(compose_checkout, ollama=True)
    daemon = config["services"]["jarvis-ollama"]
    assert daemon["image"] == "ollama/ollama:0.40.12"
    assert not daemon.get("ports")
    assert not daemon.get("devices")
    assert not daemon.get("privileged")
    assert not daemon.get("gpus")
    assert daemon["environment"]["OLLAMA_VULKAN"] == "0"
    models = daemon["volumes"]
    assert len(models) == 1 and models[0]["type"] == "volume"
    assert models[0]["target"] == "/root/.ollama"
    assert models[0]["source"] in config["volumes"]

    init = config["services"]["jarvis-ollama-init"]
    assert init["restart"] == "no"
    assert init["depends_on"]["jarvis-ollama"]["condition"] == "service_healthy"
    assert init["entrypoint"] == ["/opt/venv/bin/python", "/app/docker/bootstrap-ollama.py"]
    assert init["read_only"]
    assert not init.get("volumes")
    assert not init.get("ports")
    assert not init.get("env_file")
    assert not any("KEY" in key or "TOKEN" in key or "PASSWORD" in key for key in init["environment"])


def test_bootstrap_tunables_are_passed_without_changing_default_stack(compose_checkout):
    values = {
        "JARVIS_DOCKER_OLLAMA_IMAGE": "ollama/ollama:custom-version",
        "JARVIS_OLLAMA_BOOTSTRAP_READY_TIMEOUT_SECONDS": "90",
        "JARVIS_OLLAMA_BOOTSTRAP_PULL_TIMEOUT_SECONDS": "1800",
        "JARVIS_OLLAMA_BOOTSTRAP_EMBED_TIMEOUT_SECONDS": "240",
    }
    config = render(compose_checkout, ollama=True, overrides=values)
    assert config["services"]["jarvis-ollama"]["image"] == values["JARVIS_DOCKER_OLLAMA_IMAGE"]
    env = config["services"]["jarvis-ollama-init"]["environment"]
    for key, value in values.items():
        if key != "JARVIS_DOCKER_OLLAMA_IMAGE":
            assert env[key] == value
