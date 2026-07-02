"""Regression tests for managed Bash/Zsh Jarvis shell commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "update-aliases.sh"
ALIASES = ROOT / ".jarvis-aliases"


def _run_updater(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"HOME": str(home), "SHELL": "/bin/bash"})
    return subprocess.run(
        [str(UPDATER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_bash_install_is_managed_and_idempotent(tmp_path: Path):
    first = _run_updater(tmp_path, "--shell", "bash", "--yes")
    second = _run_updater(tmp_path, "--shell", "bash", "--yes")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    bashrc = (tmp_path / ".bashrc").read_text()
    assert bashrc.count("# >>> Jarvis Voice Assistant >>>") == 1
    assert f"export JARVIS_ROOT={ROOT}" in bashrc
    assert 'source "$JARVIS_ROOT/.jarvis-aliases"' in bashrc


def test_explicit_zsh_install_targets_zshrc(tmp_path: Path):
    result = _run_updater(tmp_path, "--shell", "zsh", "--yes")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".zshrc").is_file()
    assert not (tmp_path / ".bashrc").exists()


def test_explicit_rc_file_wins_over_shell_default(tmp_path: Path):
    custom_rc = tmp_path / "custom.rc"
    result = _run_updater(
        tmp_path,
        "--shell",
        "bash",
        "--rc-file",
        str(custom_rc),
        "--yes",
    )

    assert result.returncode == 0, result.stderr
    assert "# >>> Jarvis Voice Assistant >>>" in custom_rc.read_text()
    assert not (tmp_path / ".bashrc").exists()


def test_incomplete_managed_block_is_rejected_without_rewriting(tmp_path: Path):
    bashrc = tmp_path / ".bashrc"
    original = "export KEEP_ME=yes\n# >>> Jarvis Voice Assistant >>>\n"
    bashrc.write_text(original)

    result = _run_updater(tmp_path, "--shell", "bash", "--yes")

    assert result.returncode == 2
    assert "Incomplete Jarvis managed block" in result.stderr
    assert bashrc.read_text() == original


def test_legacy_aliases_and_cli_functions_are_removed(tmp_path: Path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text(
        "alias jarvis=\"./bin/wake_jarvis.py\"\n"
        "alias jarvis-d=\"./bin/jarvis-dashboard\"\n"
        "jarvis-cli() {\n"
        "  ./orchestrator/orchestrator_v2.py cloud \"$@\"\n"
        "}\n"
        "export KEEP_ME=yes\n"
    )

    result = _run_updater(tmp_path, "--shell", "zsh", "--yes")

    assert result.returncode == 0, result.stderr
    updated = zshrc.read_text()
    assert "wake_jarvis.py" not in updated
    assert "jarvis-cli()" not in updated
    assert "export KEEP_ME=yes" in updated
    assert updated.count("# >>> Jarvis Voice Assistant >>>") == 1


def test_canonical_commands_use_current_launchers_and_external_venv():
    content = ALIASES.read_text()

    assert "wake_jarvis.py" not in content
    assert "wake_jarvis_local.py" not in content
    assert "./bin/wake-jarvis.py" in content
    assert "./bin/wake-jarvis-local.py" in content
    assert "UV_PROJECT_ENVIRONMENT" in content
    for command in (
        "jarvis-cli()",
        "jarvis-local-cli()",
        "jarvis-start()",
        "jarvis-start-local()",
        "jarvis-stop()",
        "jarvis-status()",
        "jarvis-web-local()",
        "jarvis-api-local()",
        "jarvis-help()",
    ):
        assert command in content


def test_jarvis_help_lists_operator_commands():
    result = subprocess.run(
        ["bash", "-c", f"source {ALIASES!s}; jarvis-help"],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    for command in (
        "jarvis-start-local",
        "jarvis-stop",
        "jarvis-status",
        "jarvis-web-local",
        "jarvis-api-local",
        "jarvis-cli-json",
    ):
        assert command in result.stdout


def test_service_shortcuts_forward_current_start_arguments(tmp_path: Path):
    checkout = tmp_path / "checkout"
    venv = tmp_path / "venv"
    log = tmp_path / "commands.log"
    (checkout / "bin").mkdir(parents=True)
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text("")
    start = checkout / "bin" / "start"
    start.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
    start.chmod(0o755)

    command = f"""
export JARVIS_ROOT={checkout!s}
export JARVIS_VENV={venv!s}
export COMMAND_LOG={log!s}
source {ALIASES!s}
jarvis-start
jarvis-start-local
jarvis-stop
jarvis-status
jarvis-web
jarvis-web-local
jarvis-api
jarvis-api-local
"""
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "",
        "--local",
        "--stop",
        "--list",
        "web",
        "--local web",
        "api",
        "--local api",
    ]
