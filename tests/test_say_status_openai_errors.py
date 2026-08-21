"""Regression coverage for native OpenAI status-TTS request failures."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _isolated_status_script(
    tmp_path: Path,
) -> tuple[Path, dict[str, str], Path, Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = checkout / "bin"
    lib_dir = checkout / "lib"
    config_dir = checkout / "config"
    fake_bin = checkout / "fake-bin"
    for directory in (bin_dir, lib_dir, config_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "bin" / "say-status.sh", bin_dir / "say-status.sh")
    shutil.copy2(ROOT / "bin" / "tts-common.sh", bin_dir / "tts-common.sh")
    shutil.copy2(ROOT / "lib" / "config_loader.sh", lib_dir / "config_loader.sh")
    (config_dir / "cloud.env").write_text(
        """TTS_PROVIDER=openai
OPENAI_API_KEY=test-key
TTS_MODEL=gpt-4o-mini-tts
VOICE=onyx
TTS_INSTRUCTIONS=neutral
RATE=48000
OUT_DEV=default
STATUS_CACHE_ENABLED=false
STATUS_SILENCE_PAD_MS=0
OPENAI_TTS_CONNECT_TIMEOUT=7
OPENAI_TTS_TIMEOUT=37
""",
        encoding="utf-8",
    )

    curl_args = checkout / "curl-args.txt"
    curl_output = checkout / "curl-output.txt"
    ffmpeg_log = checkout / "ffmpeg-called.txt"
    _write_executable(
        fake_bin / "curl",
        r"""#!/usr/bin/env bash
printf '%s\n' "$@" > "$CURL_ARGS_FILE"
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s' "$output" > "$CURL_OUTPUT_FILE"
if [ "${FAKE_CURL_MODE:-http}" = "timeout" ]; then
  exit 28
fi
if [ "${FAKE_CURL_MODE:-http}" = "success" ]; then
  if [ -n "$output" ]; then
    printf 'audio' > "$output"
  else
    printf 'audio'
  fi
  printf '%s' '200'
  exit 0
fi
if [ -n "$output" ]; then
  printf '%s' '{"error":"invalid_api_key"}' > "$output"
else
  printf '%s' '{"error":"invalid_api_key"}'
fi
printf '%s' '401'
""",
    )
    _write_executable(
        fake_bin / "ffmpeg",
        r"""#!/usr/bin/env bash
printf 'called\n' >> "$FFMPEG_LOG"
if [ "${FAKE_CURL_MODE:-http}" = "success" ]; then
  printf 'wav' > "${!#}"
  exit 0
fi
cat >/dev/null
exit 1
""",
    )
    _write_executable(fake_bin / "aplay", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(checkout / "home"),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CURL_ARGS_FILE": str(curl_args),
            "CURL_OUTPUT_FILE": str(curl_output),
            "FFMPEG_LOG": str(ffmpeg_log),
        }
    )
    return bin_dir / "say-status.sh", env, curl_args, curl_output, ffmpeg_log


def _assert_request_deadlines(curl_args: Path) -> None:
    args = curl_args.read_text(encoding="utf-8").splitlines()
    assert args[args.index("--connect-timeout") + 1] == "7"
    assert args[args.index("--max-time") + 1] == "37"


def test_openai_status_tts_reports_http_error_and_cleans_response(tmp_path):
    script, env, curl_args, curl_output, ffmpeg_log = _isolated_status_script(tmp_path)

    result = subprocess.run(
        [str(script), "status check", "true"],
        env={**env, "FAKE_CURL_MODE": "http"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "OpenAI TTS failed (HTTP 401)" in result.stderr
    _assert_request_deadlines(curl_args)
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert not ffmpeg_log.exists()


def test_openai_status_tts_reports_transport_timeout(tmp_path):
    script, env, curl_args, _, _ = _isolated_status_script(tmp_path)

    result = subprocess.run(
        [str(script), "status check", "true"],
        env={**env, "FAKE_CURL_MODE": "timeout"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "OpenAI TTS request failed (curl exit 28)" in result.stderr
    _assert_request_deadlines(curl_args)


def test_openai_status_tts_decodes_successful_response(tmp_path):
    script, env, curl_args, curl_output, ffmpeg_log = _isolated_status_script(tmp_path)

    result = subprocess.run(
        [str(script), "status check", "true"],
        env={**env, "FAKE_CURL_MODE": "success"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    _assert_request_deadlines(curl_args)
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert ffmpeg_log.read_text(encoding="utf-8") == "called\n"
