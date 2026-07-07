"""Isolated integration tests for native and Docker mode propagation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_compose_assigns_web_as_only_tool_sync_owner():
    compose = yaml.safe_load((ROOT / "docker-compose.mcp.yml").read_text())
    services = compose["services"]

    web = services["jarvis-web"]
    assert web["build"]["target"] == "mcp"
    assert web["environment"]["JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE"] == "docker-mcp"
    assert web["environment"]["JARVIS_MCP_SYNC_STRICT"] == "1"

    for name in (
        "jarvis-api",
        "jarvis-services",
        "jarvis-canvas",
        "jarvis-memory",
        "jarvis-intelligence",
        "jarvis-docs",
    ):
        environment = services[name]["environment"]
        assert environment["JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE"] == "docker"
        assert environment["JARVIS_DEFER_TOOL_SYNC"] == "1"


def _copy_mode_resolver(checkout: Path) -> None:
    (checkout / "bin").mkdir(parents=True, exist_ok=True)
    (checkout / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "bin" / "resolve-jarvis-mode", checkout / "bin")
    shutil.copy2(ROOT / "lib" / "jarvis_mode.py", checkout / "lib")


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def _native_checkout(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    checkout = tmp_path / "checkout"
    _copy_mode_resolver(checkout)
    shutil.copy2(ROOT / "bin" / "start", checkout / "bin")
    (checkout / "config").mkdir()
    (checkout / "config" / "local.env").write_text("LLM_PROVIDER=ollama\n")
    (checkout / "venv" / "bin").mkdir(parents=True)
    (checkout / "venv" / "bin" / "activate").write_text("")

    fake_bin = checkout / "fake-bin"
    tmux_log = checkout / "tmux.log"
    _write_executable(
        fake_bin / "tmux",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$TMUX_LOG"
if [ "${1:-}" = "has-session" ]; then
  exit "${TMUX_HAS_SESSION:-1}"
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
if [ -n "${FAKE_HEALTH_JSON:-}" ]; then
  printf '%s\n' "$FAKE_HEALTH_JSON"
else
  printf '%s\n' '{"startup_mode":"local"}'
fi
""",
    )
    _write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "JARVIS_VENV": str(checkout / "venv"),
            "TMUX_LOG": str(tmux_log),
        }
    )
    return checkout, env, tmux_log


@pytest.mark.parametrize("args", [("--local", "memory"), ("memory", "--local")])
def test_start_accepts_local_in_either_order_and_propagates_it(tmp_path, args):
    checkout, env, tmux_log = _native_checkout(tmp_path)
    result = subprocess.run(
        [str(checkout / "bin" / "start"), *args],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    log = tmux_log.read_text()
    assert "JARVIS_MODE=local ./bin/jarvis-memory local" in log


def test_start_rejects_an_existing_opposite_mode_session(tmp_path):
    checkout, env, _ = _native_checkout(tmp_path)
    env.update(
        {
            "TMUX_HAS_SESSION": "0",
            "FAKE_HEALTH_JSON": '{"startup_mode":"cloud"}',
        }
    )
    result = subprocess.run(
        [str(checkout / "bin" / "start"), "memory", "--local"],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "already running in cloud mode" in result.stdout


def test_start_fails_when_api_never_reports_requested_mode(tmp_path):
    checkout, env, tmux_log = _native_checkout(tmp_path)
    env.update(
        {
            "FAKE_HEALTH_JSON": '{"startup_mode":"cloud"}',
            "JARVIS_START_HEALTH_TIMEOUT_SECONDS": "2",
        }
    )
    result = subprocess.run(
        [str(checkout / "bin" / "start"), "--local"],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "did not become ready in local mode" in result.stdout
    log = tmux_log.read_text()
    assert "new-session -d -s jarvis-api" in log
    assert "new-session -d -s jarvis-services" not in log
    error_logs = list((checkout / "logs" / "api").glob("errors-*.jsonl"))
    assert len(error_logs) == 1
    error_entry = json.loads(error_logs[0].read_text().strip())
    assert error_entry["event"] == "service_health_timeout"
    assert error_entry["service"] == "jarvis-startup"
    assert error_entry["startup_mode"] == "local"
    assert error_entry["session"] == "jarvis-api"
    assert error_entry["timeout_seconds"] == 2
    assert error_entry["status"] == 504


def test_tui_exposes_full_local_start_with_stoppable_control_session():
    dashboard = (ROOT / "bin" / "jarvis-dashboard").read_text()
    start_script = (ROOT / "bin" / "start").read_text()
    assert 'Command("🚀 Start All Services (Local)", "./bin/start --local"' in dashboard
    assert 'session_name = "jarvis-start-all-local"' in dashboard
    assert '"jarvis-start-all-local"' in start_script


def test_tui_uses_current_memory_sync_cli_and_omits_retired_integration_tests():
    dashboard = (ROOT / "bin" / "jarvis-dashboard").read_text()
    assert "./bin/sync-memory-db.py --from cloud --to local" in dashboard
    assert "./bin/sync-memory-db.py --from local --to cloud" in dashboard
    assert "test-all-tools.sh" not in dashboard
    assert "test-all-tools-local.sh" not in dashboard
    assert "test-memory-tools.sh" not in dashboard
    assert "test_intelligence_integration.py" not in dashboard
    assert "compare-models.sh" not in dashboard


def _docker_checkout(tmp_path: Path, *, with_local_config: bool = True) -> tuple[Path, dict[str, str], Path]:
    checkout = tmp_path / "docker-checkout"
    _copy_mode_resolver(checkout)
    (checkout / "docker").mkdir()
    shutil.copy2(ROOT / "docker" / "entrypoint.sh", checkout / "docker")
    (checkout / "config").mkdir()
    if with_local_config:
        (checkout / "config" / "local.env").write_text("LLM_PROVIDER=ollama\n")

    launch_log = checkout / "launch.log"
    for service in ("web", "canvas", "memory", "intelligence", "docs"):
        _write_executable(
            checkout / "bin" / f"jarvis-{service}",
            f'#!/usr/bin/env bash\nprintf "%s:%s\\n" "{service}" "$*" >> "$DOCKER_LAUNCH_LOG"\n',
        )

    env = os.environ.copy()
    # entrypoint.sh prepends $VIRTUAL_ENV/bin (default: $JARVIS_VENV) to PATH;
    # an activated/configured host venv would shadow the test's fake `python`
    # shim in fake-bin, so the container defaults must apply instead.
    env.pop("VIRTUAL_ENV", None)
    env.pop("JARVIS_VENV", None)
    env.update(
        {
            "DOCKER_LAUNCH_LOG": str(launch_log),
            "JARVIS_APP_ROOT": str(checkout),
            "JARVIS_MODE": "local",
            "JARVIS_SKIP_INIT": "1",
        }
    )
    return checkout, env, launch_log


@pytest.mark.parametrize("service", ["web", "canvas", "memory", "intelligence", "docs"])
def test_docker_entrypoint_passes_local_mode_to_every_ui(tmp_path, service):
    checkout, env, launch_log = _docker_checkout(tmp_path)
    result = subprocess.run(
        ["bash", str(checkout / "docker" / "entrypoint.sh"), service],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert launch_log.read_text().strip() == f"{service}:local"


def test_docker_entrypoint_rejects_missing_selected_config_before_launch(tmp_path):
    checkout, env, launch_log = _docker_checkout(tmp_path, with_local_config=False)
    result = subprocess.run(
        ["bash", str(checkout / "docker" / "entrypoint.sh"), "canvas"],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "config/local.env" in result.stderr
    assert not launch_log.exists()


def test_mcp_override_base_service_defers_tool_sync_to_web(tmp_path):
    checkout, env, launch_log = _docker_checkout(tmp_path)
    fake_bin = checkout / "fake-bin"
    fake_bin.mkdir()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    python_log = checkout / "python.log"
    _write_executable(
        fake_bin / "python",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PYTHON_LOG"
exit 0
""",
    )
    env.pop("JARVIS_SKIP_INIT")
    env.update(
        {
            "JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE": "docker",
            "JARVIS_DEFER_TOOL_SYNC": "1",
            "PYTHON_LOG": str(python_log),
        }
    )

    result = subprocess.run(
        ["bash", str(checkout / "docker" / "entrypoint.sh"), "web"],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "deferring tool sync" in result.stdout
    assert "sync-tools.py" not in python_log.read_text()
    assert not (checkout / "data" / ".docker_tool_profile_synced").exists()
    assert launch_log.read_text().strip() == "web:local"


@pytest.mark.parametrize(
    ("sync_status", "warning"),
    [(4, "embedding provider unavailable"), (5, "tool sync incomplete")],
)
def test_docker_tool_sync_failure_preserves_startup_and_retry_marker(tmp_path, sync_status, warning):
    checkout, env, launch_log = _docker_checkout(tmp_path)
    fake_bin = checkout / "fake-bin"
    fake_bin.mkdir()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    _write_executable(
        fake_bin / "python",
        f"""#!/usr/bin/env bash
if [[ "$*" == *"bin/sync-tools.py"* ]]; then
  exit {sync_status}
fi
exit 0
""",
    )
    env.pop("JARVIS_SKIP_INIT")

    result = subprocess.run(
        ["bash", str(checkout / "docker" / "entrypoint.sh"), "web"],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert warning in result.stderr.lower()
    assert not (checkout / "data" / ".docker_tool_profile_synced").exists()
    assert launch_log.read_text().strip() == "web:local"


def test_native_launchers_report_tool_sync_failure_without_false_success():
    for script_name in ("jarvis-api", "jarvis-services"):
        script = (ROOT / "bin" / script_name).read_text()
        sync_block = script[script.index("# Sync tool definitions"):script.index("# Health check")]
        assert "if python3" in sync_block
        assert "Tool embedding sync incomplete" in sync_block
        assert "Existing Tool RAG vectors were preserved" in sync_block
        assert "✅ Tool embeddings updated" in sync_block


def test_embedding_health_rejects_provider_fallbacks():
    script = (ROOT / "bin" / "check-embeddings-health.py").read_text()
    assert "get_persistable_embedding" in script
    assert "provider_error" in script
    assert "Embedding provider unavailable" in script
