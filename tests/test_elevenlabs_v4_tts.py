"""ElevenLabs v4 boundary coverage without credentials, billing, or playback."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from tts_normalizer import (  # noqa: E402
    normalize_tts_text,
    speech_tag_options,
    strip_speech_tags_for_display,
)

from api.routes import voice  # noqa: E402


@pytest.mark.parametrize("provider,model,preserved", [
    ("elevenlabs", "eleven_v4", True),
    ("elevenlabs", "eleven_v3", True),
    ("elevenlabs", "eleven_v4_turbo", True),
    ("elevenlabs", "eleven_multilingual_v2", False),
    ("xai", "eleven_v4", False),
    ("openai", "eleven_v4", False),
])
def test_tags_follow_provider_and_model_through_repeated_normalization(provider, model, preserved):
    sample = "[CURIOUS] **Hello** [clears throat] [whispers] secret. <whisper>xAI</whisper> [laugh]"
    options = speech_tag_options(provider, model)
    speech = normalize_tts_text(sample, **options)
    assert ("[curious]" in speech) is preserved
    assert ("[clears throat]" in speech) is preserved
    assert ("[whispers]" in speech) is preserved
    assert ("<whisper>" in speech) is (provider == "xai")
    assert ("[laugh]" in speech) is (provider == "xai")
    assert normalize_tts_text(speech, **options) == speech
    display = strip_speech_tags_for_display(speech)
    assert display == "Hello secret. xAI"
    assert strip_speech_tags_for_display("[curious](https://example.test) [1, 2]") == "[curious](https://example.test) [1, 2]"
    assert normalize_tts_text("[curious](https://example.test)", **options) == "curious"


@pytest.mark.parametrize("requested_provider,model,preserved", [
    (None, "eleven_v4", True),
    ("elevenlabs", "eleven_v4", True),
    ("openai", "eleven_v4", False),
    (None, "eleven_v3", True),
    (None, "eleven_v4_turbo", True),
])
def test_voice_api_uses_request_provider_override_for_tag_preservation(tmp_path, monkeypatch, requested_provider, model, preserved):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/say.sh").touch()
    env = {"TTS_PROVIDER": "elevenlabs", "ELEVENLABS_TTS_MODEL": model}
    monkeypatch.setattr(voice, "project_root", tmp_path)
    monkeypatch.setattr(voice, "export_config_environment", lambda mode: dict(env))
    captured = []
    def run(command, **kwargs):
        captured.append(command[1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(voice.subprocess, "run", run)
    result = asyncio.run(voice.speak(voice.SpeakRequest(
        message="[whispers] Hello", tts_provider=requested_provider,
    )))
    assert result["ok"] is True
    assert captured == ["[whispers] Hello" if preserved else "Hello"]


@pytest.mark.parametrize("provider,model,expected", [
    ("elevenlabs", "eleven_v4", "[whispers] Hello"),
    ("elevenlabs", "eleven_v3", "[whispers] Hello"),
    ("elevenlabs", "eleven_v4_turbo", "[whispers] Hello"),
    ("openai", "eleven_v4", "Hello"),
    ("xai", "eleven_v4", "Hello"),
])
def test_native_normalizer_uses_loaded_environment(provider, model, expected):
    env = {"PATH": os.environ["PATH"], "TTS_PROVIDER": provider, "ELEVENLABS_TTS_MODEL": model}
    env.pop("TTS_PROVIDER_OVERRIDE", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin/tts-normalize.py"), "[whispers] Hello"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout == expected


@pytest.mark.parametrize("script", ["say.sh", "say-status.sh"])
@pytest.mark.parametrize("model", ["eleven_v4", "eleven_v4_turbo", "eleven_v3", "eleven_multilingual_v2"])
def test_native_elevenlabs_payload_matches_selected_model(tmp_path, script, model):
    for directory in ("bin", "lib", "config", "fake-bin"):
        (tmp_path / directory).mkdir()
    for name in (script, "tts-common.sh", "tts-normalize.py"):
        shutil.copy2(ROOT / "bin" / name, tmp_path / "bin" / name)
    for name in ("config_loader.sh", "tts_normalizer.py", "tts_style_tags.py"):
        shutil.copy2(ROOT / "lib" / name, tmp_path / "lib" / name)
    (tmp_path / "config/cloud.env").write_text(f"""TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=fake-key
ELEVENLABS_TTS_VOICE=custom-voice
ELEVENLABS_TTS_MODEL={"eleven_v4" if script == "say-status.sh" else model}
ELEVENLABS_STATUS_TTS_MODEL={model}
ELEVENLABS_TTS_STABILITY=0.5
ELEVENLABS_TTS_SIMILARITY_BOOST=0.8
ELEVENLABS_TTS_STYLE=0.2
ELEVENLABS_TTS_USE_SPEAKER_BOOST=true
STATUS_CACHE_ENABLED=false
STATUS_SILENCE_PAD_MS=0
AUDIO_DIR='{tmp_path / "audio"}'
RATE=48000
OUT_DEV=default
""")
    stubs = {
        "curl": '''#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  case "$1" in
    -d) printf '%s' "$2" > "$PAYLOAD_FILE"; shift 2 ;;
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'audio' > "$output"
printf '200'
''',
        "ffmpeg": '#!/usr/bin/env bash\nprintf "audio" > "${@: -1}"\n',
        "aplay": "#!/usr/bin/env bash\nexit 0\n",
        "sox": '#!/usr/bin/env bash\nprintf "audio" > "$4"\n',
    }
    for name, content in stubs.items():
        path = tmp_path / "fake-bin" / name
        path.write_text(content)
        path.chmod(0o755)
    payload_file = tmp_path / "payload.json"
    env = {"PATH": f"{tmp_path / 'fake-bin'}:{os.environ['PATH']}",
           "HOME": str(tmp_path / "home"),
           "PAYLOAD_FILE": str(payload_file), "JARVIS_HEAD_ENABLED": "false",
           "TTS_PLAYBACK_LOCK_FILE": str(tmp_path / "playback.lock")}
    env.pop("TTS_PROVIDER_OVERRIDE", None)
    subprocess.run(["bash", str(tmp_path / "bin" / script), "[whispers] Hello"],
                   env=env, capture_output=True, text=True, check=True)
    payload = json.loads(payload_file.read_text())
    assert payload["model_id"] == model
    assert payload["text"] == (
        "Hello" if script == "say-status.sh" and model == "eleven_multilingual_v2"
        else "[whispers] Hello"
    )
    expected = {"stability": 0.5, "similarity_boost": 0.8}
    if model == "eleven_multilingual_v2":
        expected.update({"style": 0.2, "use_speaker_boost": True})
    assert payload["voice_settings"] == expected


@pytest.mark.parametrize("feedback", [False, True])
def test_orchestrator_cli_speak_uses_module_config_on_json_paths(monkeypatch, feedback):
    from unittest.mock import MagicMock

    import config_loader
    import orchestrator_v2

    fake = MagicMock()
    fake.process.return_value = {"ok": True, "speech": "[whispers] Hello", "tools_used": []}
    fake.auto_context_enabled = False
    values = {"TTS_PROVIDER": "elevenlabs", "ELEVENLABS_TTS_MODEL": "eleven_v4",
              "FEEDBACK_RANDOM_ENABLED": "false"}
    monkeypatch.setattr(orchestrator_v2, "load_config", lambda mode: None)
    monkeypatch.setattr(orchestrator_v2, "get_config_value", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(config_loader, "get_config_value", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(orchestrator_v2, "Orchestrator", lambda mode: fake)
    if feedback:
        import feedback as feedback_module
        collector = MagicMock()
        collector.collect.return_value = {"rating": 3}
        monkeypatch.setattr(feedback_module, "FeedbackCollector", lambda mode: collector)
    argv = ["orchestrator_v2.py", "cloud", "hello", "--json", "--speak"]
    if feedback:
        argv.append("--feedback")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("JARVIS_JSON_MODE", "1")
    spoken = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: spoken.append(command[1]))
    orchestrator_v2.main()
    assert spoken == ["[whispers] Hello"]
