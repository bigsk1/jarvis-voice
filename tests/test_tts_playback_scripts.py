#!/usr/bin/env python3
"""Regression tests for native TTS playback locking and retry helpers."""

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_fake_aplay(bin_dir: Path) -> Path:
    aplay = bin_dir / "aplay"
    aplay.write_text(
        """#!/bin/bash
set -euo pipefail
count_file="${APLAY_COUNT_FILE:?}"
count=0
if [ -f "$count_file" ]; then
  count="$(cat "$count_file")"
fi
next=$((count + 1))
echo "$next" > "$count_file"
if [ "${APLAY_FAIL_ALWAYS:-0}" = "1" ]; then
  exit 1
fi
if [ "$count" -eq 0 ]; then
  exit 1
fi
exit 0
"""
    )
    aplay.chmod(0o755)
    return aplay


def _run_helper(tmp_path: Path, fail_always: bool = False) -> subprocess.CompletedProcess:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_aplay(fake_bin)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not really a wav, but nonempty is enough for the helper")
    count_file = tmp_path / "aplay-count"

    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "APLAY_COUNT_FILE": str(count_file),
        "APLAY_FAIL_ALWAYS": "1" if fail_always else "0",
    })

    script = f"""
set -euo pipefail
source "{PROJECT_ROOT / 'bin' / 'tts-common.sh'}"
OUT_DEV=default
TTS_PLAYBACK_LOCK_FILE="{tmp_path / 'tts.lock'}"
TTS_PLAYBACK_RETRY_DELAY=0
TTS_PLAYBACK_ATTEMPTS=2
jarvis_tts_play_audio "{audio}"
"""
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    result.aplay_count = int(count_file.read_text()) if count_file.exists() else 0
    return result


def test_tts_playback_retries_once_then_succeeds(tmp_path):
    result = _run_helper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.aplay_count == 2


def test_tts_playback_returns_failure_after_retry(tmp_path):
    result = _run_helper(tmp_path, fail_always=True)

    assert result.returncode != 0
    assert result.aplay_count == 2
    assert "failed after 2 attempt" in result.stderr
