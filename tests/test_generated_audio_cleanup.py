"""Standalone speech has its own retention inside the established cleanup job."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout with spaces"
    scripts = root / "bin"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "bin/cleanup-audio", scripts / "cleanup-audio")
    return root


def _old_file(path: Path, days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture artifact")
    modified = time.time() - days * 86400
    os.utime(path, (modified, modified))
    return path


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "bin/cleanup-audio"), *arguments],
        capture_output=True, text=True, timeout=10,
    )


@pytest.mark.parametrize("dry_run", [False, True])
def test_distinct_policies_cover_speech_sidecars_without_music_or_runtime_changes(checkout, dry_run):
    runtime = _old_file(checkout / "audio/cloud/tts/runtime.mp3", 45)
    generated = checkout / "data/generated_audio"
    old = [_old_file(generated / f"speech_7{suffix}", 60.5)
           for suffix in (".mp3", ".txt", ".json")]
    younger = [_old_file(generated / "speech_8.wav", 59.5),
               _old_file(generated / "speech_9.mp3", 45)]
    preserved = [*younger,
                 _old_file(generated / "unfinished.part", 120),
                 _old_file(generated / "nested/speech_10.mp3", 120),
                 _old_file(checkout / "data/generated_music/song.mp3", 120),
                 _old_file(checkout / "data/generated_videos/clip.mp4", 120),
                 _old_file(checkout / "data/stash/source.mp3", 120)]

    result = _run(checkout, *(["--dry-run"] if dry_run else []))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Retention: 30 days" in result.stdout
    assert "Retention: 60 days" in result.stdout
    assert all(path.exists() for path in preserved)
    assert runtime.exists() is dry_run
    assert all(path.exists() is dry_run for path in old)
    if dry_run:
        assert "Would remove 3 generated speech files" in result.stdout
        assert all(str(path) in result.stdout for path in old)
    else:
        assert "Removed 3 generated speech files" in result.stdout


def test_generated_cleanup_runs_without_runtime_audio_directory(checkout):
    audio = _old_file(checkout / "data/generated_audio/speech.wav", 90)
    assert not (checkout / "audio").exists()
    result = _run(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not audio.exists()


def test_runtime_days_option_does_not_shorten_generated_audio_retention(checkout):
    runtime = _old_file(checkout / "audio/local/tts/runtime.wav", 3)
    generated = _old_file(checkout / "data/generated_audio/speech.mp3", 45)
    result = _run(checkout, "--days", "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not runtime.exists()
    assert generated.exists()


def test_generated_retention_override_does_not_change_runtime_retention(checkout):
    runtime = _old_file(checkout / "audio/local/tts/runtime.wav", 45)
    generated = _old_file(checkout / "data/generated_audio/speech.mp3", 80)
    result = _run(checkout, "--generated-days", "90")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not runtime.exists()
    assert generated.exists()


@pytest.mark.parametrize("symlink_component", ["data", "data/generated_audio"])
def test_generated_cleanup_does_not_traverse_symlinked_directory(checkout, tmp_path, symlink_component):
    outside = tmp_path / "outside"
    target = _old_file(outside / ("generated_audio/keep.mp3" if symlink_component == "data" else "keep.mp3"), 120)
    link = checkout / symlink_component
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    result = _run(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.exists()
    assert link.is_symlink()
    assert "Skipped symlinked" in result.stdout


def test_generated_cleanup_skips_symlinked_files_and_child_directories(checkout, tmp_path):
    generated = checkout / "data/generated_audio"
    generated.mkdir(parents=True)
    target = _old_file(tmp_path / "outside/keep.mp3", 120)
    (generated / "linked.mp3").symlink_to(target)
    (generated / "linked_dir").symlink_to(target.parent, target_is_directory=True)
    old = _old_file(generated / "remove.wav", 120)
    result = _run(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.exists()
    assert (generated / "linked.mp3").is_symlink()
    assert not old.exists()


def test_generated_scan_failure_never_deletes_partial_candidates(checkout, tmp_path):
    old = _old_file(checkout / "data/generated_audio/speech.mp3", 120)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    find = fake_bin / "find"
    find.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == */data/generated_audio ]]; then\n'
        '    /usr/bin/find "$@"\n'
        "    exit 44\n"
        "fi\n"
        'exec /usr/bin/find "$@"\n'
    )
    find.chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    environment = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin", "TMPDIR": str(scratch)}
    result = subprocess.run(
        ["bash", str(checkout / "bin/cleanup-audio")],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 44
    assert old.exists()
    assert not list(scratch.iterdir())
    assert "Removed 1" not in result.stdout


@pytest.mark.parametrize("arguments", [
    ["--generated-days"], ["--generated-days", ""], ["--generated-days", "0"],
    ["--generated-days", "-1"], ["--generated-days", "36501"],
    ["--generated-days", "nonsense"], ["--days"], ["--days", "-1"],
])
def test_invalid_retention_fails_before_deleting_any_files(checkout, arguments):
    old = _old_file(checkout / "data/generated_audio/speech.mp3", 120)
    result = _run(checkout, *arguments)
    assert result.returncode == 2
    assert old.exists()


def test_help_describes_both_independent_retention_periods(checkout):
    result = _run(checkout, "--help")
    assert result.returncode == 0
    assert "--generated-days" in result.stdout
    assert "default: 30" in result.stdout
    assert "default: 60" in result.stdout
