"""Behavioral tests for the manual Linux-VT Jarvis Head kiosk wrapper."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

from lib import config_loader

ROOT = Path(__file__).resolve().parents[1]
KIOSK = ROOT / "bin" / "kiosk.sh"
HEAD = ROOT / "bin" / "jarvis-head"


def _write_command(bin_dir: Path, name: str, body: str) -> None:
    command = bin_dir / name
    command.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
    command.chmod(0o755)


def _fake_environment(tmp_path: Path) -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    (dev_root / "tty1").symlink_to("/dev/null")
    (dev_root / "tty8").symlink_to("/dev/null")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "JARVIS_HEAD_KIOSK_VT=8\nJARVIS_HEAD_CELL_ASPECT=0.45\n"
    )

    _write_command(
        fake_bin,
        "sudo",
        """
echo "sudo|$*" >> "$KIOSK_TEST_LOG"
if [[ "${1:-}" == "-v" ]]; then
    exit 0
fi
exec "$@"
""",
    )
    _write_command(
        fake_bin,
        "systemctl",
        """
echo "systemctl|$*" >> "$KIOSK_TEST_LOG"
case "${1:-}" in
    show)
        if [[ " $* " == *" --value "* ]]; then
            echo "${FAKE_UNIT_STATE:-inactive}"
        else
            echo "SubState=running"
            echo "MainPID=4242"
            echo "ExecMainStatus=0"
        fi
        ;;
    is-active)
        if [[ "$*" == *"getty@tty"* ]]; then
            [[ "${FAKE_GETTY_ACTIVE:-false}" == "true" ]] && exit 0
            exit 3
        fi
        [[ "${FAKE_UNIT_STATE:-inactive}" == "active" ]] && exit 0
        exit 3
        ;;
    reset-failed|stop)
        exit 0
        ;;
esac
""",
    )
    _write_command(
        fake_bin,
        "systemd-run",
        'echo "systemd-run|$*" >> "$KIOSK_TEST_LOG"',
    )
    _write_command(fake_bin, "fgconsole", "echo 1")
    _write_command(
        fake_bin,
        "openvt",
        'echo "openvt|$*" >> "$KIOSK_TEST_LOG"',
    )
    _write_command(
        fake_bin,
        "chvt",
        'echo "chvt|$*" >> "$KIOSK_TEST_LOG"',
    )
    _write_command(
        fake_bin,
        "runuser",
        'echo "runuser|$*" >> "$KIOSK_TEST_LOG"',
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "KIOSK_TEST_LOG": str(log),
            "JARVIS_HEAD_KIOSK_DEV_ROOT": str(dev_root),
            "JARVIS_HEAD_KIOSK_CONFIG_DIR": str(config_dir),
        }
    )
    return env


def _run(tmp_path: Path, *args: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = _fake_environment(tmp_path)
    env.update(overrides)
    return subprocess.run(
        [str(KIOSK), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_start_creates_bounded_transient_unit_for_unused_vt(tmp_path: Path):
    result = _run(tmp_path, "start", "--", "--fps", "45", "--color", "green")

    assert result.returncode == 0, result.stderr
    assert "started on tty8" in result.stdout
    commands = (tmp_path / "commands.log").read_text().splitlines()
    launch = next(line for line in commands if line.startswith("systemd-run|"))
    assert "--unit=jarvis-head-kiosk.service" in launch
    assert "--property=KillMode=control-group" in launch
    assert "--property=CPUQuota=50%" in launch
    assert "--property=MemoryMax=256M" in launch
    assert "__session" in launch
    assert "0.45" in launch
    assert "--fps 45 --color green" in launch
    assert pwd.getpwuid(os.getuid()).pw_name in launch


def test_stop_uses_systemd_control_group_and_status_is_read_only(tmp_path: Path):
    resumed = _run(tmp_path / "resume", "start", FAKE_UNIT_STATE="active")
    assert resumed.returncode == 0, resumed.stderr
    assert "switched to tty8" in resumed.stdout
    resume_commands = (tmp_path / "resume" / "commands.log").read_text()
    assert "chvt|8" in resume_commands
    assert "systemd-run|" not in resume_commands

    stopped = _run(tmp_path / "stop", "stop", FAKE_UNIT_STATE="active")

    assert stopped.returncode == 0, stopped.stderr
    assert "kiosk stopped" in stopped.stdout
    stop_commands = (tmp_path / "stop" / "commands.log").read_text()
    assert "systemctl|stop jarvis-head-kiosk.service" in stop_commands

    status = _run(tmp_path / "status", "status", FAKE_UNIT_STATE="active")
    assert status.returncode == 0, status.stderr
    assert "Jarvis Head kiosk: active" in status.stdout
    assert "MainPID=4242" in status.stdout
    status_commands = (tmp_path / "status" / "commands.log").read_text()
    assert "sudo|" not in status_commands


def test_primary_console_and_occupied_target_are_refused(tmp_path: Path):
    primary = _run(tmp_path / "primary", "start", JARVIS_HEAD_KIOSK_VT="1")
    assert primary.returncode == 2
    assert "tty1 is reserved" in primary.stderr

    occupied = _run(tmp_path / "occupied", "start", FAKE_GETTY_ACTIVE="true")
    assert occupied.returncode == 2
    assert "active getty" in occupied.stderr

    relative_socket = _run(
        tmp_path / "relative-socket",
        "start",
        JARVIS_HEAD_SOCKET="relative/head.sock",
    )
    assert relative_socket.returncode == 2
    assert "absolute path" in relative_socket.stderr


def test_session_returns_to_original_vt_when_head_exits(tmp_path: Path):
    env = _fake_environment(tmp_path)
    user = pwd.getpwuid(os.getuid())
    result = subprocess.run(
        [
            str(KIOSK),
            "__session",
            user.pw_name,
            str(user.pw_uid),
            user.pw_dir,
            "8",
            "1",
            "",
            "0.4",
            "120",
            "cloud",
            "--",
            "--fps",
            "30",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "commands.log").read_text().splitlines()
    openvt = next(line for line in commands if line.startswith("openvt|"))
    assert "-c 8 -s -w -- runuser -u" in openvt
    assert str(ROOT / "bin" / "jarvis-head") in openvt
    assert "--fps 30" in openvt
    assert commands[-1] == "chvt|1"


def test_direct_display_hydrates_only_head_config_without_losing_explicit_env(
    monkeypatch,
):
    module_name = "test_jarvis_head_launcher_config"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HEAD))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, launcher)
    spec.loader.exec_module(launcher)

    loaded: list[Path] = []

    def fake_load_env_file(path):
        loaded.append(Path(path))
        return {
            "JARVIS_HEAD_CELL_ASPECT": "0.9",
            "JARVIS_HEAD_IDLE_TIMEOUT": "90",
            "OPENAI_API_KEY": "must-not-enter-kiosk-env",
        }

    monkeypatch.setenv("JARVIS_HEAD_CELL_ASPECT", "0.4")
    monkeypatch.delenv("JARVIS_HEAD_IDLE_TIMEOUT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config_loader, "load_env_file", fake_load_env_file)

    with pytest.raises(SystemExit) as exc:
        launcher.main(["--help"])

    assert exc.value.code == 0
    assert loaded == [ROOT / "config" / "cloud.env"]
    assert os.environ["JARVIS_HEAD_CELL_ASPECT"] == "0.4"
    assert os.environ["JARVIS_HEAD_IDLE_TIMEOUT"] == "90"
    assert "OPENAI_API_KEY" not in os.environ


def test_display_launcher_falls_back_to_legacy_operator_environment(
    monkeypatch, tmp_path: Path
):
    module_name = "test_jarvis_head_launcher_python"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HEAD))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, launcher)
    spec.loader.exec_module(launcher)

    repo_venv = tmp_path / "repo-venv"
    legacy_venv = tmp_path / "legacy-venv"
    legacy_python = legacy_venv / "bin" / "python"
    legacy_python.parent.mkdir(parents=True)
    legacy_python.touch()
    monkeypatch.setattr(launcher, "REPO_VENV", repo_venv)
    monkeypatch.setattr(launcher, "REPO_PYTHON", repo_venv / "bin" / "python")
    monkeypatch.setattr(launcher, "LEGACY_VENV", legacy_venv)
    monkeypatch.setattr(launcher, "LEGACY_PYTHON", legacy_python)

    assert launcher._display_python() == (legacy_venv, legacy_python)

    repo_python = repo_venv / "bin" / "python"
    repo_python.parent.mkdir(parents=True)
    repo_python.touch()
    assert launcher._display_python() == (repo_venv, repo_python)
