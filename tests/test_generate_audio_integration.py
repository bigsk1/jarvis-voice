"""Foreground speech artifacts retain usable handles across Jarvis surfaces."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from config_loader import config_scope
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = "audio_integration_server"
    server = ROOT / "jarvis-web/server"
    load_server_package(package, server)
    spec = importlib.util.spec_from_file_location(
        f"{package}.services.followup_extractor", server / "services/followup_extractor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audio_followup_retains_handoff_and_provenance_without_full_script(extractor):
    audio = "stash://space_voice/f_audio"
    script = "stash://space_voice/f_script"
    result = {
        "ok": True,
        "data": {
            "provider": "elevenlabs", "model": "eleven_v3", "voice": "voice_7",
            "stash_ref": audio, "script_ref": script,
            "duration_seconds": 65.3, "mime_type": "audio/mpeg",
            "filename": "narration.mp3", "file_path": "/tmp/generated_audio/narration.mp3",
            "text": "FULL_SCRIPT_SENTINEL " * 3000,
            "api_key": "SECRET_SENTINEL",
            "saved": {"stash_ref": audio, "filename": "narration.mp3"},
        },
    }

    compact = extractor.extract_followup_data({"generate_audio": result})["generate_audio"]
    # The retained reference is immediately usable as HeyGen's audio_source.
    assert compact["stash_ref"] == audio
    assert compact["script_ref"] == script
    assert compact["provider"] == "elevenlabs"
    assert compact["model"] == "eleven_v3"
    assert compact["voice"] == "voice_7"
    assert compact["duration_seconds"] == 65.3
    assert compact["filename"] == "narration.mp3"
    assert "FULL_SCRIPT_SENTINEL" not in json.dumps(compact)
    assert "SECRET_SENTINEL" not in json.dumps(compact)
    assert json.loads(json.dumps(compact, allow_nan=False)) == compact


def test_audio_followup_keeps_script_handle_if_stash_save_only_partially_succeeded(extractor):
    compact = extractor.extract_followup_data({
        "generate_audio": {
            "ok": False, "completion": "completed", "error": "Stash audio save failed",
            "data": {"provider": "kokoro", "model": "kokoro", "voice": "af_sky",
                     "file_path": "/tmp/generated_audio/narration.wav",
                     "filename": "narration.wav", "script_ref": "stash://space_voice/f_script"},
        }
    })["generate_audio"]
    assert compact["file_path"].endswith("narration.wav")
    assert compact["script_ref"] == "stash://space_voice/f_script"
    assert compact["ok"] is False
    assert compact["completion"] == "completed"
    assert compact["error"] == "Stash audio save failed"
    assert "stash_ref" not in compact


def test_generated_speech_uses_existing_generated_media_retention(tmp_path):
    from lib.stash_helper import open_space

    with config_scope("cloud", {
        "STASH_DIR": str(tmp_path / "stash"),
        "STASH_DEFAULT_TTL_DAYS": "7", "STASH_GENERATED_MEDIA_TTL_DAYS": "45",
    }):
        space, _ = open_space(labels=["generated_audio"])
    assert space.meta["retention_policy"] == "generated_media"
    assert space.meta["ttl_days"] == 45


def test_trace_only_failed_audio_preserves_paid_recording_for_followup(extractor):
    message = "The audio was generated and saved locally, but saving all artifacts failed. Reuse the existing recording; do not regenerate it."
    recovery = {"filename": "voiceover.mp3", "file_path": "/tmp/generated_audio/voiceover.mp3",
                "audio_url": "/api/generated-audio/voiceover.mp3", "recovery_available": True,
                "saved": {"saved": True}, "save_error": message, "api_key": "SECRET_SENTINEL"}
    compact = extractor.extract_followup_data({'_tool_trace': [{
        'tool': 'generate_audio', 'ok': False, 'error': message, 'result_data': recovery,
    }]})['generate_audio']
    assert compact['ok'] is False
    assert compact['completion'] == 'completed'
    assert compact['file_path'] == recovery['file_path']
    assert compact['audio_url'] == recovery['audio_url']
    assert compact['recovery_available'] is True
    assert compact['error'] == message
    assert 'SECRET_SENTINEL' not in json.dumps(compact)


def test_trace_only_timed_out_audio_preserves_unknown_completion(extractor):
    compact = extractor.extract_followup_data({'_tool_trace': [{
        'tool': 'generate_audio', 'ok': False, 'completion': 'unknown', 'error': 'Timeout',
        'result_data': None,
    }]})['generate_audio']
    assert compact['ok'] is False
    assert compact['completion'] == 'unknown'
    assert 'stash_ref' not in compact


def test_canonical_failed_audio_is_not_duplicated_by_trace(extractor):
    result = {'ok': False, 'completion': 'completed', 'data': {'file_path': '/tmp/current.mp3'}}
    compact = extractor.extract_followup_data({'generate_audio': result, '_tool_trace': [{
        'tool': 'generate_audio', 'ok': False, 'completion': 'unknown',
        'result_data': {'file_path': '/tmp/older.mp3'},
    }]})['generate_audio']
    assert compact['completion'] == 'completed'
    assert compact['file_path'] == '/tmp/current.mp3'


@pytest.mark.parametrize(("configured", "expected"), [("180", 210), ("600", 630), ("900", 930), ("1", 31)])
def test_foreground_timeout_fits_provider_deadline_and_cleanup(configured, expected):
    from orchestrator.executor import ToolExecutor

    with config_scope("cloud", {"AUDIO_TOOL_TIMEOUT_SECONDS": configured}):
        executor = ToolExecutor.__new__(ToolExecutor)
        assert executor._get_subprocess_timeout("generate_audio") == expected


def test_invalid_timeout_is_rejected_instead_of_weakening_provider_deadline():
    from orchestrator.executor import ToolExecutor

    with config_scope("cloud", {"AUDIO_TOOL_TIMEOUT_SECONDS": "9999"}):
        executor = ToolExecutor.__new__(ToolExecutor)
        with pytest.raises(ValueError, match="1 to 900"):
            executor._get_subprocess_timeout("generate_audio")


def test_restrictive_tracked_profiles_disable_new_generator():
    paths = [ROOT / "skills/profiles/openai_only.json"]
    paths.extend((ROOT / "skills/profiles/examples").glob("*.json"))
    checked = 0
    for path in paths:
        overrides = json.loads(path.read_text())["overrides"]
        if overrides.get("generate_music") is False:
            assert overrides.get("generate_audio") is False, path
            checked += 1
    assert checked >= 10


def test_default_and_docker_profiles_leave_explicit_provider_optin_available():
    for profile in ("default", "docker", "docker-mcp"):
        overrides = json.loads((ROOT / f"skills/profiles/{profile}.json").read_text())["overrides"]
        assert "generate_audio" not in overrides


def test_example_modes_keep_speech_generation_optin():
    from dotenv import dotenv_values

    for mode in ("cloud", "local"):
        path = ROOT / f"config/{mode}.env.example"
        values = dotenv_values(path)
        assert "AUDIO_TOOL_PROVIDER" not in values
        assert "AUDIO_TOOL_VOICE" not in values
        assert '# AUDIO_TOOL_PROVIDER="elevenlabs"' in path.read_text()
