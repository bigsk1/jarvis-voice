"""Regression coverage for native local status-TTS request failures."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _isolated_local_status_script(
    tmp_path: Path, provider: str
) -> tuple[Path, dict[str, str], Path, Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = checkout / "bin"
    lib_dir = checkout / "lib"
    config_dir = checkout / "config"
    fake_bin = checkout / "fake-bin"
    for directory in (bin_dir, lib_dir, config_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "bin" / "say-status-local.sh", bin_dir / "say-status-local.sh")
    shutil.copy2(ROOT / "bin" / "tts-common.sh", bin_dir / "tts-common.sh")
    shutil.copy2(ROOT / "lib" / "config_loader.sh", lib_dir / "config_loader.sh")
    (config_dir / "local.env").write_text(
        f"""TTS_PROVIDER={provider}
QWEN3_TTS_URL=http://qwen.test/v1/audio/speech
QWEN3_TTS_VOICE=Jarvis
QWEN3_TTS_FORMAT=mp3
QWEN3_TTS_SPEED=1.0
KOKORO_TTS_URL=http://kokoro.test/v1/audio/speech
KOKORO_TTS_VOICE=af_sky
KOKORO_TTS_SPEED=1.0
RATE=48000
OUT_DEV=default
STATUS_CACHE_ENABLED=false
STATUS_SILENCE_PAD_MS=0
STATUS_TTS_CONNECT_TIMEOUT=5
STATUS_TTS_TIMEOUT=23
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
if [ "${FAKE_CURL_MODE:-timeout}" = "timeout" ]; then
  exit 28
fi
if [ "${FAKE_CURL_MODE:-timeout}" = "http" ]; then
  printf '{"error":"unavailable"}' > "$output"
  printf '%s' '503'
  exit 0
fi
if [ -n "$output" ]; then
  printf 'audio' > "$output"
else
  printf 'audio'
fi
printf '%s' '200'
""",
    )
    _write_executable(
        fake_bin / "ffmpeg",
        r"""#!/usr/bin/env bash
printf 'called\n' >> "$FFMPEG_LOG"
if [ "${FAKE_FFMPEG_MODE:-success}" = "fail" ]; then
  exit 1
fi
printf 'wav' > "${!#}"
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
    return bin_dir / "say-status-local.sh", env, curl_args, curl_output, ffmpeg_log


@pytest.mark.parametrize(
    ("provider", "provider_label"),
    [("qwen3-tts", "Qwen3-TTS"), ("kokoro", "Kokoro TTS")],
)
def test_local_status_providers_share_request_deadlines_and_transport_errors(
    tmp_path, provider, provider_label
):
    script, env, curl_args, curl_output, ffmpeg_log = _isolated_local_status_script(
        tmp_path, provider
    )

    result = subprocess.run(
        [str(script), "local status check", "true"],
        env={**env, "FAKE_CURL_MODE": "timeout"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert f"{provider_label} request failed (curl exit 28)" in result.stderr
    args = curl_args.read_text(encoding="utf-8").splitlines()
    assert args[args.index("--connect-timeout") + 1] == "5"
    assert args[args.index("--max-time") + 1] == "23"
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert not ffmpeg_log.exists()


@pytest.mark.parametrize(
    ("provider", "provider_label"),
    [("qwen3-tts", "Qwen3-TTS"), ("kokoro", "Kokoro TTS")],
)
def test_local_status_providers_report_http_errors_before_decode(
    tmp_path, provider, provider_label
):
    script, env, _, curl_output, ffmpeg_log = _isolated_local_status_script(
        tmp_path, provider
    )

    result = subprocess.run(
        [str(script), "local status check", "true"],
        env={**env, "FAKE_CURL_MODE": "http"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert f"{provider_label} failed (HTTP 503)" in result.stderr
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert not ffmpeg_log.exists()


@pytest.mark.parametrize(
    ("provider", "provider_label"),
    [("qwen3-tts", "Qwen3-TTS"), ("kokoro", "Kokoro TTS")],
)
def test_local_status_providers_report_decode_errors_and_clean_responses(
    tmp_path, provider, provider_label
):
    script, env, _, curl_output, ffmpeg_log = _isolated_local_status_script(
        tmp_path, provider
    )

    result = subprocess.run(
        [str(script), "local status check", "true"],
        env={
            **env,
            "FAKE_CURL_MODE": "success",
            "FAKE_FFMPEG_MODE": "fail",
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert f"{provider_label} audio decode failed" in result.stderr
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert ffmpeg_log.read_text(encoding="utf-8") == "called\n"


@pytest.mark.parametrize("provider", ["qwen3-tts", "kokoro"])
def test_local_status_providers_decode_successful_responses(tmp_path, provider):
    script, env, curl_args, curl_output, ffmpeg_log = _isolated_local_status_script(
        tmp_path, provider
    )

    result = subprocess.run(
        [str(script), "local status check", "true"],
        env={**env, "FAKE_CURL_MODE": "success"},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    args = curl_args.read_text(encoding="utf-8").splitlines()
    assert args[args.index("--connect-timeout") + 1] == "5"
    assert args[args.index("--max-time") + 1] == "23"
    response_path = curl_output.read_text(encoding="utf-8")
    assert response_path
    assert not Path(response_path).exists()
    assert ffmpeg_log.read_text(encoding="utf-8") == "called\n"
