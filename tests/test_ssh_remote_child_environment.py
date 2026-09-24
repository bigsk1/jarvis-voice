"""SSH subprocesses receive only the selected host's needed settings."""

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from tool_child_environment import RESTRICTED_ENV_MARKER  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402

from orchestrator.executor import ToolExecutor  # noqa: E402
from skills import ssh_remote  # noqa: E402


class _Registry:
    def __init__(self, schema):
        self.schema = schema

    def get_tool(self, name):
        return self.schema if name == "ssh_remote" else None

    def is_mcp_tool(self, _name):
        return False


@pytest.mark.parametrize(
    ("arguments", "expected_sudo"),
    [
        ({"action": "run", "host": "alpha", "command": "uptime", "sudo": True}, "ALPHA_SUDO"),
        ({"action": "multi", "host": "beta", "commands": ["uptime"], "sudo": True}, "BETA_SUDO"),
        ({"action": "apt_update", "host": "alpha"}, "ALPHA_SUDO"),
        ({"action": "run", "host": "alpha", "command": "uptime"}, None),
        ({"action": "test", "host": "alpha"}, None),
        ({"action": "list_hosts"}, None),
    ],
)
def test_ssh_child_inherits_only_selected_sudo_setting(tmp_path, monkeypatch, arguments, expected_sudo):
    config = tmp_path / "config"
    config.mkdir()
    (config / "ssh.json").write_text(json.dumps({"hosts": {
        "alpha": {"sudo_env": "ALPHA_SUDO"},
        "beta": {"sudo_env": "BETA_SUDO"},
    }}))
    original_home = str(tmp_path / "operator-home")
    source = {
        "PATH": "/usr/bin", "HOME": original_home, "JARVIS_MODE": "cloud",
        "ALPHA_SUDO": "old-alpha", "JARVIS_OVERRIDE_ALPHA_SUDO": "selected-alpha",
        "BETA_SUDO": "beta-password", "OPENAI_API_KEY": "unrelated-secret",
        "JARVIS_OVERRIDE_JARVIS_SSH_KEY_HOME": "/wrong-home",
        "SSH_AUTH_SOCK": "/tmp/test-ssh-agent.sock", "HTTP_PROXY": "http://proxy-secret",
    }
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: dict(source))
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "ssh_remote.tool.json"))
    executor = ToolExecutor(mode="cloud", registry=_Registry(schema), load_runtime_config=False)
    executor.project_root = tmp_path
    captured = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs["tool_env"])
        assert Path(captured["HOME"]).is_dir()
        return json.dumps({"ok": True, "speech": "simulated"}), "", False

    with patch("tool_process.run_local_process", side_effect=fake_run):
        result = executor.execute("ssh_remote", arguments, skip_permission_check=True)

    assert result["ok"] is True
    assert captured[RESTRICTED_ENV_MARKER] == "1"
    assert captured["JARVIS_SSH_KEY_HOME"] == original_home
    assert captured["SSH_AUTH_SOCK"] == "/tmp/test-ssh-agent.sock"
    assert not ({"OPENAI_API_KEY", "HTTP_PROXY", "JARVIS_OVERRIDE_ALPHA_SUDO",
                 "JARVIS_OVERRIDE_JARVIS_SSH_KEY_HOME"} & captured.keys())
    for name in ("ALPHA_SUDO", "BETA_SUDO"):
        assert (name in captured) is (name == expected_sudo)
    if expected_sudo == "ALPHA_SUDO":
        assert captured[expected_sudo] == "selected-alpha"
    assert captured["HOME"] != original_home
    assert not Path(captured["HOME"]).exists()


@pytest.mark.parametrize("sudo_name", [
    "JARVIS_OVERRIDE_OPENAI_API_KEY", "JARVIS_SSH_KEY_HOME", "SSH_AUTH_SOCK",
    "PATH", "JARVIS_MODE", "LOCAL_PROXY",
])
def test_invalid_host_sudo_name_fails_before_launch(tmp_path, monkeypatch, sudo_name):
    config = tmp_path / "config"
    config.mkdir()
    (config / "ssh.json").write_text(json.dumps({"hosts": {
        "alpha": {"sudo_env": sudo_name},
    }}))
    monkeypatch.setattr("orchestrator.executor.export_config_environment",
                        lambda _mode: {"PATH": "/usr/bin", "HOME": str(tmp_path)})
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "ssh_remote.tool.json"))
    executor = ToolExecutor(mode="cloud", registry=_Registry(schema), load_runtime_config=False)
    executor.project_root = tmp_path

    with patch("tool_process.run_local_process") as launch:
        result = executor.execute("ssh_remote", {
            "action": "run", "host": "alpha", "command": "uptime", "sudo": True,
        }, skip_permission_check=True)

    assert result["ok"] is False
    launch.assert_not_called()


@pytest.mark.parametrize(
    ("arguments", "config_text", "expected_speech"),
    [
        ({"action": "apt_update", "host": "alpha"}, "{not json", "SSH error:"),
        ({"action": "run", "host": "alpha", "command": "uptime", "sudo": True},
         None, "SSH configuration file not found"),
        ({"action": "multi", "host": "alpha", "commands": ["uptime"], "sudo": True},
         "{not json", "SSH error:"),
    ],
)
def test_bad_ssh_config_reaches_tool_error(tmp_path, monkeypatch, arguments,
                                           config_text, expected_speech):
    config = tmp_path / "config"
    config.mkdir()
    if config_text is not None:
        (config / "ssh.json").write_text(config_text)
    skills = tmp_path / "skills"
    skills.mkdir()
    script = skills / "ssh_remote.py"
    shutil.copyfile(ROOT / "skills" / "ssh_remote.py", script)
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "ssh_remote.tool.json"))
    schema.script_path = str(script)
    executor = ToolExecutor(mode="cloud", registry=_Registry(schema), load_runtime_config=False)
    executor.project_root = tmp_path
    executor.skills_dir = skills
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: {
        "PATH": os.pathsep.join((str(Path(sys.executable).parent), os.environ.get("PATH", ""))),
        "PYTHONPATH": str(ROOT / "lib"),
        "HOME": str(tmp_path),
    })

    result = executor.execute("ssh_remote", arguments, skip_permission_check=True)

    assert result["ok"] is False
    assert result["speech"].startswith(expected_speech)
    assert result["speech"] != "Tool ssh_remote returned invalid JSON"
    assert result["speech"] != "Error executing ssh_remote"


def test_passwordless_sudo_does_not_require_a_sudo_setting(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "ssh.json").write_text(json.dumps({"hosts": {"alpha": {}}}))
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: {
        "PATH": "/usr/bin", "HOME": str(tmp_path), "UNRELATED_SECRET": "private",
    })
    schema = ToolSchema.from_json_file(str(ROOT / "skills" / "ssh_remote.tool.json"))
    executor = ToolExecutor(mode="cloud", registry=_Registry(schema), load_runtime_config=False)
    executor.project_root = tmp_path
    captured = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs["tool_env"])
        return json.dumps({"ok": True, "speech": "simulated"}), "", False

    with patch("tool_process.run_local_process", side_effect=fake_run):
        result = executor.execute("ssh_remote", {
            "action": "run", "host": "alpha", "command": "uptime", "sudo": True,
        }, skip_permission_check=True)

    assert result["ok"] is True
    assert "UNRELATED_SECRET" not in captured


def test_restricted_ssh_key_path_uses_original_home(tmp_path, monkeypatch):
    config = tmp_path / "ssh.json"
    config.write_text(json.dumps({"hosts": {"alpha": {"host": "example.test",
                                                         "key_path": "~/.ssh/test_key"}}}))
    monkeypatch.setattr(ssh_remote, "SSH_CONFIG_PATH", config)
    monkeypatch.setenv(RESTRICTED_ENV_MARKER, "1")
    monkeypatch.setenv("HOME", str(tmp_path / "scratch"))
    monkeypatch.setenv("JARVIS_SSH_KEY_HOME", str(tmp_path / "operator"))

    assert ssh_remote.get_host_config("alpha")["key_path"] == str(tmp_path / "operator/.ssh/test_key")
