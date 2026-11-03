"""Optional builder lifecycle, launcher isolation, and Compose storage contracts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_mode_plumbing_scripts import (
    _copy_mode_resolver,
    _docker_checkout,
    _native_checkout,
    _record_worker_commands,
    _write_executable,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("args", [("--local", "workflows"), ("workflows", "--local")])
def test_builder_native_start_is_explicit_and_mode_scoped(tmp_path, args):
    checkout, env, log = _native_checkout(tmp_path)
    result = subprocess.run([str(checkout / "bin/start"), *args], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "JARVIS_MODE=local ./bin/jarvis-workflows local" in log.read_text()
    assert "jarvis-web " not in log.read_text()


@pytest.mark.parametrize("args", [[], ["--ui-only"], ["--no-api"]])
def test_default_native_groups_do_not_launch_optional_builder(tmp_path, args):
    checkout, env, log = _native_checkout(tmp_path)
    _record_worker_commands(checkout, env)
    result = subprocess.run([str(checkout / "bin/start"), "--local", *args], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    launches = [line for line in log.read_text().splitlines() if "new-session" in line]
    assert any("jarvis-web " in line for line in launches)
    assert not any("jarvis-workflows" in line for line in launches)


def test_stop_builder_needs_no_mode_file_and_only_stops_its_session(tmp_path):
    checkout, env, log = _native_checkout(tmp_path)
    (checkout / "config/local.env").unlink()
    env.update({"TMUX_HAS_SESSION": "0", "JARVIS_MODE": "local"})
    result = subprocess.run([str(checkout / "bin/start"), "--stop-workflows"], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        "has-session -t jarvis-workflows", "kill-session -t jarvis-workflows",
    ]


def test_builder_is_in_status_and_full_stop(tmp_path):
    checkout, env, log = _native_checkout(tmp_path)
    _record_worker_commands(checkout, env)
    status = subprocess.run([str(checkout / "bin/start"), "--list"], env=env,
                            text=True, capture_output=True, timeout=10)
    assert status.returncode == 0
    assert "jarvis-workflows" in status.stdout
    env["TMUX_HAS_SESSION"] = "0"
    stop = subprocess.run([str(checkout / "bin/start"), "--stop"], env=env,
                          text=True, capture_output=True, timeout=10)
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert "kill-session -t jarvis-workflows" in log.read_text()


def test_builder_existing_opposite_mode_is_rejected(tmp_path):
    checkout, env, log = _native_checkout(tmp_path)
    env.update({"TMUX_HAS_SESSION": "0", "FAKE_HEALTH_JSON": '{"startup_mode":"cloud"}'})
    result = subprocess.run([str(checkout / "bin/start"), "workflows", "--local"], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert "already running in cloud mode" in result.stdout
    assert "new-session" not in log.read_text()


@pytest.mark.parametrize("args,expected", [
    ([], {"host": "0.0.0.0", "port": 5005, "mode": "cloud", "debug": False}),
    (["local", "--host", "127.0.0.1", "--port", "5015", "--debug"],
     {"host": "127.0.0.1", "port": 5015, "mode": "local", "debug": True}),
])
def test_builder_launcher_passes_mode_and_network_defaults_without_provider_imports(tmp_path, args, expected):
    _copy_mode_resolver(tmp_path)
    shutil.copy2(ROOT / "bin/jarvis-workflows", tmp_path / "bin")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/local.env").write_text("LLM_PROVIDER=ollama\n")
    package = tmp_path / "jarvis-workflows/server"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "app.py").write_text(
        "import json\ndef run_server(**kwargs):\n    print(json.dumps(kwargs))\n"
    )
    env = {key: value for key, value in os.environ.items() if key not in {"JARVIS_MODE", "PYTHONPATH"}}
    result = subprocess.run([sys.executable, str(tmp_path / "bin/jarvis-workflows"), *args],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == expected


def test_docker_builder_dispatch_skips_unrelated_initialization(tmp_path):
    checkout, env, log = _docker_checkout(tmp_path)
    _write_executable(checkout / "bin/jarvis-workflows",
                      '#!/bin/sh\nprintf "workflows:%s\\n" "$*" > "$DOCKER_LAUNCH_LOG"\n')
    _write_executable(checkout / "fake-bin/python", "#!/bin/sh\nexit 99\n")
    env["PATH"] = f"{checkout / 'fake-bin'}:{env['PATH']}"
    env.pop("JARVIS_SKIP_INIT")
    result = subprocess.run(["bash", str(checkout / "docker/entrypoint.sh"), "workflows"],
                            env=env, cwd=checkout, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().strip() == "workflows:local"
    assert not (checkout / "data/.docker_tool_profile_synced").exists()
    assert not list((checkout / "data").glob("*.db"))


def test_compose_builder_is_optional_and_shares_current_policy_directory():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    builder = services["jarvis-workflows"]
    assert builder["profiles"] == ["workflows"]
    assert builder["command"] == ["workflows"]
    assert builder["ports"] == ["${JARVIS_WORKFLOWS_PORT:-5005}:5005"]
    assert builder["image"] == "jarvis-voice:local"
    assert builder["restart"] == "unless-stopped"
    assert not builder.get("depends_on")
    assert "http://localhost:5005/api/status" in builder["healthcheck"]["test"]
    for name in ("jarvis-workflows", "jarvis-api", "jarvis-services"):
        assert "./jarvis-web/config:/app/jarvis-web/config:ro" in services[name]["volumes"]
        assert "./data:/app/data" in services[name]["volumes"]
        assert "./config:/app/config:ro" in services[name]["volumes"]
    mcp = yaml.safe_load((ROOT / "docker-compose.mcp.yml").read_text())["services"]["jarvis-workflows"]
    assert mcp["environment"]["JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE"] == "docker"
    assert mcp["environment"]["JARVIS_DEFER_TOOL_SYNC"] == "1"
    assert not mcp.get("volumes") and not mcp.get("build")
    ollama = yaml.safe_load((ROOT / "docker-compose.ollama.yml").read_text())["services"]["jarvis-workflows"]
    assert ollama["environment"]["JARVIS_DOCKER_OLLAMA_BASE_URL"] == "http://jarvis-ollama:11434"
    assert not ollama.get("depends_on")


@pytest.mark.parametrize("mcp,ollama", [(False, False), (True, False), (False, True), (True, True)])
def test_real_compose_render_keeps_builder_opt_in_and_socket_free(tmp_path, mcp, ollama):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI is required for config-only merge checks")
    files = ["docker-compose.yml"]
    if ollama:
        files.append("docker-compose.ollama.yml")
    if mcp:
        files.append("docker-compose.mcp.yml")
    command = [docker, "compose"]
    for filename in files:
        shutil.copy2(ROOT / filename, tmp_path / filename)
        command.extend(["-f", filename])
    env = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG") if key in os.environ}
    env.update({"JARVIS_DOCKER_SOCKET_GID": "999", "JARVIS_MODE": "local"})
    for profiles in (["--profile", "extras"], ["--profile", "workflows"]):
        result = subprocess.run([*command, *profiles, "config", "--format", "json"],
                                cwd=tmp_path, env=env, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        services = json.loads(result.stdout)["services"]
        if profiles[-1] == "extras":
            assert "jarvis-workflows" not in services
            continue
        builder = services["jarvis-workflows"]
        assert builder["environment"]["JARVIS_MODE"] == "local"
        assert builder["environment"]["JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE"] == "docker"
        assert not builder.get("depends_on")
        assert not any("docker.sock" in item["target"] for item in builder["volumes"])
        assert builder["ports"][0].get("host_ip", "0.0.0.0") == "0.0.0.0"
        policy_mount = next(item for item in builder["volumes"] if item["target"] == "/app/jarvis-web/config")
        assert policy_mount["read_only"] is True


def test_dashboard_exposes_explicit_builder_commands():
    source = (ROOT / "bin/jarvis-dashboard").read_text()
    assert '"./bin/start workflows"' in source
    assert '"./bin/start --local workflows"' in source
    assert '"./bin/start --stop-workflows"' in source
    assert "tmux capture-pane -t jarvis-workflows" in source


def test_private_builder_store_and_personal_recipes_stay_ignored():
    for filename in ("data/workflow_builder.db", "data/workflow_builder.db-wal", "data/workflows/personal/private_recipe.json"):
        result = subprocess.run(["git", "check-ignore", "--no-index", filename], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, filename
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "data/workflows/personal/" in dockerignore
    assert "data/*.db" in dockerignore and "data/*.db-*" in dockerignore
