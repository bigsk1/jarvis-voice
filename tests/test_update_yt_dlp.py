"""Regression tests for bin/update-yt-dlp."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "update-yt-dlp"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_harness(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    repo = tmp_path / "repo"
    fake_bin = tmp_path / "fake-bin"
    venv = tmp_path / "jarvis-venv"
    repo.mkdir()
    fake_bin.mkdir()
    (venv / "bin").mkdir(parents=True)

    (repo / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "1.0.0"\n'
        'dependencies = ["yt-dlp>=2026.6.9"]\n',
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("yt-dlp>=2026.6.9\n", encoding="utf-8")
    (repo / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "yt-dlp"\nversion = "2026.6.9"\n',
        encoding="utf-8",
    )

    state_path = tmp_path / "installed-version.txt"
    state_path.write_text("2026.6.9", encoding="utf-8")
    command_log = tmp_path / "uv-commands.log"

    fake_python = venv / "bin" / "python"
    _write_executable(
        fake_python,
        f"""#!/usr/bin/env python3
import pathlib
import sys

state = pathlib.Path({str(state_path)!r})
if sys.argv[1:2] == ['-c']:
    print(state.read_text().strip())
    raise SystemExit(0)
if sys.argv[1:3] == ['-m', 'yt_dlp']:
    output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1] + '.en.srt')
    output.write_text('1\\n00:00:00,000 --> 00:00:01,000\\nSmoke test\\n')
    raise SystemExit(0)
raise SystemExit(2)
""",
    )

    fake_uv = fake_bin / "uv"
    _write_executable(
        fake_uv,
        f"""#!/usr/bin/env python3
import pathlib
import sys

repo = pathlib.Path({str(repo)!r})
state = pathlib.Path({str(state_path)!r})
log = pathlib.Path({str(command_log)!r})
with log.open('a', encoding='utf-8') as handle:
    handle.write(' '.join(sys.argv[1:]) + '\\n')

if sys.argv[1:4] == ['lock', '--upgrade-package', 'yt-dlp']:
    lock = repo / 'uv.lock'
    lock.write_text(lock.read_text().replace('2026.6.9', '2026.7.4'))
    raise SystemExit(0)
if sys.argv[1:3] == ['pip', 'install']:
    requirement = sys.argv[-1]
    state.write_text(requirement.split('==', 1)[1])
    raise SystemExit(0)
raise SystemExit(2)
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    return repo, venv, command_log, env


def test_updates_lock_and_only_installs_exact_yt_dlp_version(tmp_path: Path):
    repo, venv, command_log, env = _make_harness(tmp_path)
    pyproject_before = (repo / "pyproject.toml").read_text()
    requirements_before = (repo / "requirements.txt").read_text()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--venv",
            str(venv),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Updated uv.lock: 2026.6.9 -> 2026.7.4" in result.stdout
    assert "No uv sync was run" in result.stdout
    commands = command_log.read_text(encoding="utf-8")
    assert "lock --upgrade-package yt-dlp" in commands
    assert f"pip install --python {venv / 'bin' / 'python'} yt-dlp==2026.7.4" in commands
    assert " sync " not in f" {commands} "
    assert " --exact " not in f" {commands} "
    assert (repo / "pyproject.toml").read_text() == pyproject_before
    assert (repo / "requirements.txt").read_text() == requirements_before


def test_optional_smoke_url_requires_an_srt_transcript(tmp_path: Path):
    repo, venv, _, env = _make_harness(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--venv",
            str(venv),
            "--smoke-url",
            "https://www.youtube.com/watch?v=example1234",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Transcript smoke test passed" in result.stdout


def test_refuses_to_overwrite_a_dirty_lock(tmp_path: Path):
    repo, venv, command_log, env = _make_harness(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "uv.lock"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "lock",
        ],
        cwd=repo,
        check=True,
    )
    with (repo / "uv.lock").open("a", encoding="utf-8") as handle:
        handle.write("\n# pending edit\n")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--venv",
            str(venv),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "uv.lock already has staged or unstaged changes" in result.stderr
    assert not command_log.exists()
