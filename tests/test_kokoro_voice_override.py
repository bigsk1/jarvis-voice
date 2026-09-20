"""The Voice API's Kokoro voice choice reaches the native TTS request."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from api.routes import voice


ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _isolated_voice_scripts(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    checkout = tmp_path / "checkout"
    for directory in ("bin", "lib", "config", "fake-bin"):
        (checkout / directory).mkdir(parents=True)

    for script in ("say.sh", "say-local.sh", "tts-common.sh"):
        shutil.copy2(ROOT / "bin" / script, checkout / "bin" / script)
    shutil.copy2(ROOT / "lib" / "config_loader.sh", checkout / "lib" / "config_loader.sh")

    for mode, provider in (("cloud", "openai"), ("local", "qwen3-tts")):
        (checkout / "config" / f"{mode}.env").write_text(
            f"""TTS_PROVIDER={provider}
KOKORO_TTS_URL=http://kokoro.invalid/v1/audio/speech
KOKORO_TTS_VOICE=af_nicole
KOKORO_TTS_SPEED=1.0
AUDIO_DIR="{checkout / 'audio'}"
RATE=48000
OUT_DEV=default
""",
            encoding="utf-8",
        )

    fake_bin = checkout / "fake-bin"
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  case "$1" in
    -d) printf '%s' "$2" > "$KOKORO_PAYLOAD_FILE"; shift 2 ;;
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'raw-audio' > "$output"
printf '200'
""",
    )
    _write_executable(
        fake_bin / "ffmpeg", '#!/usr/bin/env bash\nprintf "wav" > "${@: -1}"\n'
    )
    _write_executable(fake_bin / "sox", '#!/usr/bin/env bash\nprintf "wav" > "$4"\n')
    _write_executable(fake_bin / "aplay", "#!/usr/bin/env bash\nexit 0\n")

    payload_file = checkout / "kokoro-payload.json"
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(checkout / "home"),
        "KOKORO_PAYLOAD_FILE": str(payload_file),
        "TTS_PLAYBACK_LOCK_FILE": str(checkout / "playback.lock"),
        "JARVIS_HEAD_ENABLED": "false",
    }
    return checkout, env, payload_file


@pytest.mark.parametrize("mode", ("cloud", "local"))
@pytest.mark.parametrize(
    ("requested_voice", "expected_voice"),
    (("af_sky", "af_sky"), (None, "af_nicole")),
)
def test_voice_api_kokoro_request_uses_requested_voice_after_config_load(
    tmp_path, monkeypatch, mode, requested_voice, expected_voice
):
    checkout, env, payload_file = _isolated_voice_scripts(tmp_path)
    monkeypatch.setattr(voice, "project_root", checkout)
    monkeypatch.setattr(voice, "export_config_environment", lambda _mode: dict(env))

    response = asyncio.run(
        voice.speak(
            voice.SpeakRequest(
                message="Hello",
                mode=mode,
                tts_provider="kokoro",
                voice=requested_voice,
            )
        )
    )

    assert response["ok"] is True
    assert response["voice"] == requested_voice
    assert json.loads(payload_file.read_text(encoding="utf-8"))["voice"] == expected_voice
