"""Regression coverage for JSON-safe direct cloud question scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_project(tmp_path: Path, script_name: str) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / script_name.replace(".sh", "")
    bin_dir = root / "bin"
    fake_bin = root / "fake-bin"
    (root / "lib").mkdir(parents=True)
    (root / "config").mkdir()
    bin_dir.mkdir()
    fake_bin.mkdir()

    shutil.copy2(PROJECT_ROOT / "bin" / script_name, bin_dir / script_name)
    shutil.copy2(PROJECT_ROOT / "lib" / "config_loader.sh", root / "lib" / "config_loader.sh")
    _write_executable(
        bin_dir / "tts-normalize.py",
        "#!/usr/bin/env python3\nimport sys\nprint(sys.argv[1])\n",
    )
    if script_name == "question-mic.sh":
        _write_executable(
            bin_dir / "stt.py",
            "#!/usr/bin/env python3\nprint('What does \\\"test\\\" mean?')\n",
        )
    (root / "config" / "cloud.env").write_text(
        """OPENAI_API_KEY=test-key
OPENAI_MODEL=test-model
STT_MODEL=test-stt
TTS_MODEL=test-tts
VOICE=alloy
TTS_INSTRUCTIONS=calm
SYSTEM_PROMPT="You are Jarvis."
AUDIO_DIR=$HOME/audio
IN_DEV=default
OUT_DEV=default
RATE=16000
CHAN=1
PRE_SIL=0.1
POST_SIL=0.1
MAX_RECORD_TIME=1
""",
        encoding="utf-8",
    )

    payload_path = root / "chat-payload.json"
    _write_executable(
        fake_bin / "curl",
        """#!/bin/bash
url=""
payload=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -d) payload="$2"; shift 2 ;;
    -o) output="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
case "$url" in
  */audio/transcriptions)
    printf '%s\n' '{"text":"What does \\"test\\" mean?"}'
    ;;
  */chat/completions)
    printf '%s' "$payload" > "$CHAT_PAYLOAD_CAPTURE"
    printf '%s\n' '{"choices":[{"message":{"content":"A test answer"}}]}'
    ;;
  */audio/speech)
    printf 'audio' > "$output"
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "sox",
        """#!/bin/bash
if [ "$1" = "-t" ]; then
  head -c 30000 /dev/zero > "${10}"
else
  cp "$1" "$4"
fi
""",
    )
    _write_executable(
        fake_bin / "ffmpeg",
        """#!/bin/bash
output="${!#}"
printf 'wav' > "$output"
""",
    )
    _write_executable(fake_bin / "file", "#!/bin/bash\nprintf '%s\n' 'audio/mpeg'\n")
    _write_executable(fake_bin / "aplay", "#!/bin/bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(root / "home"),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CHAT_PAYLOAD_CAPTURE": str(payload_path),
        }
    )
    return bin_dir / script_name, env, payload_path


@pytest.mark.parametrize("script_name", ["question.sh", "question-mic.sh"])
def test_direct_question_scripts_json_escape_quoted_input(tmp_path, script_name):
    script, env, payload_path = _fake_project(tmp_path, script_name)
    args = [str(script)]
    if script_name == "question.sh":
        args.append('What does "test" mean?')

    completed = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["messages"][1]["content"] == 'What does "test" mean?'
