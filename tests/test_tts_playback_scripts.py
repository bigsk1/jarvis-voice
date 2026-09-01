#!/usr/bin/env python3
"""Regression tests for native TTS playback locking and retry helpers."""

import os
import signal
import subprocess
import time
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
if [ -n "${PLAYBACK_EVENT_LOG:-}" ]; then
  echo "aplay|$next" >> "$PLAYBACK_EVENT_LOG"
fi
if [ "${APLAY_BLOCK_FIRST:-0}" = "1" ] && mkdir "${APLAY_BLOCK_CLAIM:?}" 2>/dev/null; then
  touch "${APLAY_BLOCK_STARTED:?}"
  while [ ! -f "${APLAY_BLOCK_RELEASE:?}" ]; do
    sleep 0.01
  done
fi
if [ "${APLAY_FAIL_ALWAYS:-0}" = "1" ]; then
  exit 1
fi
if [ "${APLAY_SUCCEED_FIRST:-0}" = "1" ]; then
  exit 0
fi
if [ "$count" -eq 0 ]; then
  exit 1
fi
exit 0
"""
    )
    aplay.chmod(0o755)
    return aplay


def _write_fake_head_emitter(bin_dir: Path) -> Path:
    emitter = bin_dir / "jarvis-head-emitter"
    emitter.write_text(
        """#!/bin/bash
set -euo pipefail
event="${2:-}"
shift 2 || true
playback_id=""
ok=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --playback-id) playback_id="$2"; shift 2 ;;
    --ok) ok="$2"; shift 2 ;;
    *) shift ;;
  esac
done
echo "emit|$event|$playback_id|$ok" >> "${PLAYBACK_EVENT_LOG:?}"
if [ "${HEAD_EMITTER_FAIL:-0}" = "1" ]; then
  exit 19
fi
exit 0
"""
    )
    emitter.chmod(0o755)
    return emitter


def _run_helper(
    tmp_path: Path,
    fail_always: bool = False,
    *,
    head_enabled: bool = False,
    emitter_fail: bool = False,
) -> subprocess.CompletedProcess:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_aplay(fake_bin)
    emitter = _write_fake_head_emitter(fake_bin)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not really a wav, but nonempty is enough for the helper")
    count_file = tmp_path / "aplay-count"
    event_log = tmp_path / "events.log"

    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "APLAY_COUNT_FILE": str(count_file),
        "APLAY_FAIL_ALWAYS": "1" if fail_always else "0",
        "HEAD_EMITTER_FAIL": "1" if emitter_fail else "0",
        "JARVIS_HEAD_ENABLED": "true" if head_enabled else "false",
        "PLAYBACK_EVENT_LOG": str(event_log),
    })

    script = f"""
set -euo pipefail
source "{PROJECT_ROOT / 'bin' / 'tts-common.sh'}"
jarvis_head_emit_command() {{ "{emitter}" emit "$@"; }}
OUT_DEV=default
TTS_PLAYBACK_LOCK_FILE="{tmp_path / 'tts.lock'}"
TTS_PLAYBACK_RETRY_DELAY=0
TTS_PLAYBACK_ATTEMPTS=2
jarvis_tts_play_audio "{audio}"
"""
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    result.aplay_count = int(count_file.read_text()) if count_file.exists() else 0
    result.playback_events = event_log.read_text().splitlines() if event_log.exists() else []
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


def test_disabled_head_never_invokes_emitter(tmp_path):
    result = _run_helper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.aplay_count == 2
    assert result.playback_events == ["aplay|1", "aplay|2"]


def test_each_locked_aplay_attempt_gets_unique_matching_events(tmp_path):
    result = _run_helper(tmp_path, head_enabled=True)

    assert result.returncode == 0, result.stderr
    assert result.aplay_count == 2
    assert len(result.playback_events) == 6
    first_speak, first_aplay, first_end, retry_speak, retry_aplay, retry_end = (
        result.playback_events
    )
    assert first_aplay == "aplay|1"
    assert retry_aplay == "aplay|2"

    first_id = first_speak.split("|")[2]
    retry_id = retry_speak.split("|")[2]
    assert first_speak.startswith("emit|speak|")
    assert retry_speak.startswith("emit|speak|")
    assert first_id and retry_id and first_id != retry_id
    assert first_end == f"emit|speak_end|{first_id}|false"
    assert retry_end == f"emit|speak_end|{retry_id}|true"


def test_terminated_playback_emits_matching_failed_end(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_aplay(fake_bin)
    emitter = _write_fake_head_emitter(fake_bin)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"nonempty")
    event_log = tmp_path / "events.log"
    started = tmp_path / "aplay-started"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "APLAY_COUNT_FILE": str(tmp_path / "aplay-count"),
            "APLAY_BLOCK_FIRST": "1",
            "APLAY_BLOCK_CLAIM": str(tmp_path / "first-claim"),
            "APLAY_BLOCK_STARTED": str(started),
            "APLAY_BLOCK_RELEASE": str(tmp_path / "never-release"),
            "APLAY_SUCCEED_FIRST": "1",
            "JARVIS_HEAD_ENABLED": "true",
            "PLAYBACK_EVENT_LOG": str(event_log),
        }
    )
    script = f"""
set -euo pipefail
source "{PROJECT_ROOT / 'bin' / 'tts-common.sh'}"
jarvis_head_emit_command() {{ "{emitter}" emit "$@"; }}
OUT_DEV=default
TTS_PLAYBACK_LOCK_FILE="{tmp_path / 'tts.lock'}"
TTS_PLAYBACK_ATTEMPTS=1
jarvis_tts_play_audio "{audio}"
"""

    process = subprocess.Popen(
        ["bash", "-c", script],
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    while not started.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists(), "fake aplay never started"

    os.killpg(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5) != 0

    deadline = time.monotonic() + 2
    events: list[str] = []
    while time.monotonic() < deadline:
        events = event_log.read_text().splitlines() if event_log.exists() else []
        if any(line.startswith("emit|speak_end|") for line in events):
            break
        time.sleep(0.01)

    speak = next(line for line in events if line.startswith("emit|speak|"))
    playback_id = speak.split("|")[2]
    assert f"emit|speak_end|{playback_id}|false" in events


def test_emitter_failure_cannot_change_retry_or_playback_status(tmp_path):
    success = _run_helper(
        tmp_path / "success",
        head_enabled=True,
        emitter_fail=True,
    )
    failure = _run_helper(
        tmp_path / "failure",
        fail_always=True,
        head_enabled=True,
        emitter_fail=True,
    )

    assert success.returncode == 0
    assert success.aplay_count == 2
    assert failure.returncode != 0
    assert failure.aplay_count == 2


def test_waiting_playback_does_not_emit_until_it_holds_the_lock(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_aplay(fake_bin)
    emitter = _write_fake_head_emitter(fake_bin)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"nonempty")
    event_log = tmp_path / "events.log"
    started = tmp_path / "first-started"
    release = tmp_path / "release-first"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "APLAY_COUNT_FILE": str(tmp_path / "aplay-count"),
            "APLAY_BLOCK_FIRST": "1",
            "APLAY_BLOCK_CLAIM": str(tmp_path / "first-claim"),
            "APLAY_BLOCK_STARTED": str(started),
            "APLAY_BLOCK_RELEASE": str(release),
            "APLAY_SUCCEED_FIRST": "1",
            "JARVIS_HEAD_ENABLED": "true",
            "PLAYBACK_EVENT_LOG": str(event_log),
        }
    )
    script = f"""
set -euo pipefail
source "{PROJECT_ROOT / 'bin' / 'tts-common.sh'}"
jarvis_head_emit_command() {{ "{emitter}" emit "$@"; }}
OUT_DEV=default
TTS_PLAYBACK_LOCK_FILE="{tmp_path / 'tts.lock'}"
TTS_PLAYBACK_ATTEMPTS=1
jarvis_tts_play_audio "{audio}"
"""

    first = subprocess.Popen(["bash", "-c", script], env=env)
    deadline = time.monotonic() + 5
    while not started.exists() and first.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists(), "first playback never reached fake aplay"

    second = subprocess.Popen(["bash", "-c", script], env=env)
    time.sleep(0.15)
    before_release = event_log.read_text().splitlines()
    assert sum(line.startswith("emit|speak|") for line in before_release) == 1

    release.touch()
    assert first.wait(timeout=5) == 0
    assert second.wait(timeout=5) == 0
    completed = event_log.read_text().splitlines()
    assert sum(line.startswith("emit|speak|") for line in completed) == 2
