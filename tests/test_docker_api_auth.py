"""Docker auth startup validation without launching containers or services."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _checkout(tmp_path: Path, mode: str = "cloud") -> tuple[Path, dict[str, str]]:
    checkout = tmp_path / "checkout"
    for directory in ("bin", "docker", "lib", "config"):
        (checkout / directory).mkdir(parents=True)
    for name in ("config_loader.py", "jarvis_mode.py", "tool_child_environment.py", "internal_api.py"):
        shutil.copy2(ROOT / "lib" / name, checkout / "lib" / name)
    shutil.copy2(ROOT / "bin/resolve-jarvis-mode", checkout / "bin/resolve-jarvis-mode")
    shutil.copy2(ROOT / "docker/entrypoint.sh", checkout / "docker/entrypoint.sh")
    # The selected mode's false value must not override the Docker default.
    for selected in ("cloud", "local"):
        (checkout / "config" / f"{selected}.env").write_text("JARVIS_API_AUTH=false\n")
    launcher = checkout / "bin/jarvis-api"
    launcher.write_text(
        "#!/usr/bin/env python\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))\n"
        "from lib.config_loader import get_config_value, load_config\n"
        "from internal_api import get_internal_api_headers\n"
        "load_config()\n"
        "print(json.dumps({'auth': get_config_value('JARVIS_API_AUTH'), "
        "'authenticated_client': bool(get_internal_api_headers()), 'args': sys.argv[1:]}))\n"
    )
    launcher.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_") and key not in {"PYTHONPATH", "VIRTUAL_ENV"}
    }
    env.update(
        JARVIS_APP_ROOT=str(checkout),
        JARVIS_MODE=mode,
        JARVIS_SKIP_INIT="1",
        JARVIS_VENV=sys.prefix,
        VIRTUAL_ENV=sys.prefix,
    )
    return checkout, env


def _start(checkout: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(checkout / "docker/entrypoint.sh"), "api"],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("key_value", [None, "", '"   "', '"your-secure-api-key-here"'])
def test_default_auth_rejects_missing_selected_key_even_when_init_skipped(tmp_path, mode, key_value):
    checkout, env = _checkout(tmp_path, mode)
    if key_value is not None:
        with (checkout / "config" / f"{mode}.env").open("a") as config:
            config.write(f"JARVIS_API_KEY={key_value}\n")
    other = "local" if mode == "cloud" else "cloud"
    (checkout / "config" / f"{other}.env").write_text("JARVIS_API_KEY=other-mode-key\n")
    result = _start(checkout, env)
    assert result.returncode != 0
    assert "requires JARVIS_API_KEY" in result.stderr
    assert not result.stdout
    assert "other-mode-key" not in result.stderr
    assert not (checkout / "data/.docker_tool_profile_synced").exists()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_default_auth_and_internal_client_use_selected_mode_key(tmp_path, mode):
    checkout, env = _checkout(tmp_path, mode)
    (checkout / "config" / f"{mode}.env").write_text(
        "JARVIS_API_AUTH=false\nJARVIS_API_KEY=example-test-key\n"
    )
    result = _start(checkout, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "auth": "true",
        "authenticated_client": True,
        "args": ["--local"] if mode == "local" else [],
    }
    assert "example-test-key" not in result.stdout + result.stderr


def test_explicit_false_permits_local_testing_without_key(tmp_path):
    checkout, env = _checkout(tmp_path)
    env["JARVIS_OVERRIDE_JARVIS_API_AUTH"] = "false"
    result = _start(checkout, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"auth": "false", "authenticated_client": False, "args": []}


def test_key_override_uses_runtime_loader_precedence(tmp_path):
    checkout, env = _checkout(tmp_path)
    env["JARVIS_OVERRIDE_JARVIS_API_KEY"] = "override-test-key"
    result = _start(checkout, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["authenticated_client"]
    assert "override-test-key" not in result.stdout + result.stderr


@pytest.mark.parametrize("auth", ["yes", "0", " true "])
def test_invalid_auth_flag_cannot_silently_disable_auth(tmp_path, auth):
    checkout, env = _checkout(tmp_path)
    env["JARVIS_OVERRIDE_JARVIS_API_AUTH"] = auth
    result = _start(checkout, env)
    assert result.returncode != 0
    assert "must be true or false" in result.stderr
    assert not result.stdout


def test_bridge_client_requires_correct_bearer_key(monkeypatch):
    from api import server

    monkeypatch.setenv("JARVIS_OVERRIDE_JARVIS_API_AUTH", "true")
    monkeypatch.setenv("JARVIS_OVERRIDE_JARVIS_API_KEY", "bridge-test-key")
    app = FastAPI()

    @app.get("/api/private-test")
    def protected():
        return {"ok": True}

    app.add_middleware(server.APIAuthMiddleware)
    with TestClient(app, client=("172.20.0.5", 54321)) as client:
        assert client.get("/api/private-test").status_code == 401
        assert client.get(
            "/api/private-test", headers={"Authorization": "Bearer wrong-key"}
        ).status_code == 403
        assert client.get(
            "/api/private-test", headers={"Authorization": "Bearer bridge-test-key"}
        ).json() == {"ok": True}
