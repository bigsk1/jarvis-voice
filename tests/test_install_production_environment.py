"""Exercise the installer's dependency step without installing host packages."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_dependency_step(
    tmp_path: Path,
    *,
    locked: bool = True,
    existing_environment: bool = False,
    sync_exit: int = 0,
    repeats: int = 1,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]], Path, Path]:
    """Run actual Bash functions against a temporary checkout and a fake uv."""
    repo = tmp_path / "checkout"
    fake_bin = tmp_path / "fake-bin"
    home = tmp_path / "home"
    venv = tmp_path / "custom production environment"
    for directory in (repo, fake_bin, home):
        directory.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
    (repo / "requirements.txt").write_text("rich>=13.0.0\n", encoding="utf-8")
    if locked:
        (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    # The prefix defines functions and paths but does not run the installer's
    # system-package, config-file, setup, or service entry points.
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    functions, marker, _ = installer.partition("# --- main ---")
    assert marker, "Installer entrypoint boundary changed; review the test harness"
    harness = repo / "installer-functions.sh"
    harness.write_text(functions, encoding="utf-8")
    command_log = tmp_path / "uv-commands.jsonl"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        f"""#!{sys.executable}
import json
import os
import pathlib
import shlex
import sys

args = sys.argv[1:]
with pathlib.Path(os.environ["UV_TEST_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps({{
        "args": args,
        "cwd": os.getcwd(),
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
        "project_environment": os.environ.get("UV_PROJECT_ENVIRONMENT"),
        "jarvis_venv": os.environ.get("JARVIS_VENV"),
    }}) + "\\n")
if args[0] == "venv":
    target = pathlib.Path(args[1])
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "activate").write_text(
        "export VIRTUAL_ENV=" + shlex.quote(str(target)) + "\\n", encoding="utf-8"
    )
    raise SystemExit(0)
if args[0] == "sync":
    raise SystemExit(int(os.environ["UV_TEST_SYNC_EXIT"]))
if args[:2] == ["pip", "install"]:
    raise SystemExit(0)
raise SystemExit("Unexpected uv command: " + repr(args))
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    if existing_environment:
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "activate").write_text(
            f"export VIRTUAL_ENV={shlex.quote(str(venv))}\n", encoding="utf-8"
        )

    # Do not inherit private application settings or the operator's active venv.
    env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.defpath}",
        "JARVIS_VENV": str(venv),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "wrong inherited target"),
        "UV_TEST_LOG": str(command_log),
        "UV_TEST_SYNC_EXIT": str(sync_exit),
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"\nfor ((i=0; i<$2; i++)); do create_venv_and_sync; done',
            "installer-test",
            str(harness),
            str(repeats),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    return result, commands, repo, venv


@pytest.mark.parametrize("existing_environment", [False, True])
def test_production_sync_uses_lock_without_dev_and_the_selected_environment(
    tmp_path: Path, existing_environment: bool
) -> None:
    result, commands, repo, venv = _run_dependency_step(
        tmp_path, existing_environment=existing_environment
    )

    assert result.returncode == 0, result.stderr
    sync = commands[-1]
    assert sync["args"] == [
        "sync", "--active", "--locked", "--no-dev", "--no-install-project"
    ]
    assert sync["cwd"] == str(repo)
    assert sync["virtual_env"] == str(venv)
    assert sync["project_environment"] == str(venv)
    assert sync["jarvis_venv"] == str(venv)
    assert len(commands) == (1 if existing_environment else 2)
    if not existing_environment:
        assert commands[0]["args"][0:2] == ["venv", str(venv)]
    assert (repo / "uv.lock").read_text() == "version = 1\n"
    assert not (repo / "config").exists()


def test_stale_locked_sync_failure_stops_without_requirements_fallback(tmp_path: Path) -> None:
    result, commands, repo, _ = _run_dependency_step(
        tmp_path, existing_environment=True, sync_exit=42
    )

    assert result.returncode == 42
    assert len(commands) == 1
    assert commands[0]["args"][0] == "sync"
    assert (repo / "uv.lock").read_text() == "version = 1\n"


def test_missing_lock_uses_only_the_legacy_requirements_install(tmp_path: Path) -> None:
    result, commands, _, venv = _run_dependency_step(
        tmp_path, locked=False, existing_environment=True
    )

    assert result.returncode == 0, result.stderr
    assert len(commands) == 1
    assert commands[0]["args"] == ["pip", "install", "-r", "requirements.txt"]
    assert commands[0]["virtual_env"] == str(venv)
    assert commands[0]["project_environment"] == str(venv)


def test_reusing_environment_does_not_duplicate_the_activation_hook(tmp_path: Path) -> None:
    result, commands, _, venv = _run_dependency_step(
        tmp_path, existing_environment=True, repeats=2
    )

    assert result.returncode == 0, result.stderr
    assert len(commands) == 2
    activation = (venv / "bin" / "activate").read_text()
    assert activation.count('export UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"') == 1
    assert activation.count('export JARVIS_VENV="$VIRTUAL_ENV"') == 1
