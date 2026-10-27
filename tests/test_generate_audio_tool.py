"""Speech artifacts are reusable files, separate from runtime playback and music."""

import importlib
import io
import json
import sys
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest
from config_loader import config_scope
from remote_completion import RemoteCompletionError
from stash_helper import safe_resolve_file

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    module = importlib.import_module("skills.generate_audio")
    monkeypatch.setattr(module, "load_config", lambda: None)
    monkeypatch.setattr(module, "get_project_root", lambda: tmp_path)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(b"\x80" * (8000 * 45))
    synthesize = Mock(return_value={
        "audio_bytes": stream.getvalue(), "mime_type": "audio/wav", "extension": "wav",
        "duration_seconds": 45.0,
    })
    monkeypatch.setattr(module, "synthesize_audio", synthesize)
    with config_scope("cloud", {
        "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "fixture-key",
        "ELEVENLABS_TTS_VOICE": "fixture-voice", "ELEVENLABS_TTS_MODEL": "eleven_v3",
        "STASH_DIR": str(tmp_path / "stash"),
    }):
        yield module, synthesize, tmp_path


def test_longer_recording_and_exact_script_save_locally_and_to_stash_without_music_catalog(tool):
    module, synthesize, root = tool
    script = "  Hello, Andrew!\nKeep every word — and punctuation.  "
    result = module.run({"text": script, "title": "A / useful 🎤 voiceover"})
    assert result["ok"] and result["completion"] == "completed"
    data = result["data"]
    assert data["duration_seconds"] == 45
    assert data["provider"] == "elevenlabs"
    assert data["voice"] == "fixture-voice"
    assert synthesize.call_args.args[0]["text"] == script
    assert synthesize.call_count == 1
    assert Path(data["file_path"]).parent == root / "data/generated_audio"
    assert Path(data["file_path"]).read_bytes() == synthesize.return_value["audio_bytes"]
    assert Path(data["script_path"]).read_text() == script
    audio = safe_resolve_file(stash_ref=data["stash_ref"])
    text = safe_resolve_file(stash_ref=data["script_ref"])
    assert Path(audio["path"]).read_bytes() == synthesize.return_value["audio_bytes"]
    assert Path(text["path"]).read_text() == script
    assert not list(root.rglob("audio_catalog.json"))
    assert not (root / "data/generated_music").exists()
    assert "autoplay" not in json.dumps(result)
    assert "fixture-key" not in json.dumps(result)


def test_repeating_a_request_generates_new_artifacts_without_cache(tool):
    module, synthesize, _ = tool
    first = module.run({"text": "Same text."})
    second = module.run({"text": "Same text."})
    assert first["ok"] and second["ok"]
    assert synthesize.call_count == 2
    assert first["data"]["stash_ref"] != second["data"]["stash_ref"]
    assert first["data"]["file_path"] != second["data"]["file_path"]


def test_delivery_instructions_saved_separately_from_exact_script(tool):
    module, synthesize, _ = tool
    with config_scope("cloud", {
        "AUDIO_TOOL_PROVIDER": "openai", "OPENAI_API_KEY": "fixture-key",
        "STASH_DIR": str(tool[2] / "stash"),
    }):
        result = module.run({"text": "  Hello there.  ", "instructions": " Warm, calm delivery. "})
        assert result["ok"]
        data = result["data"]
        assert synthesize.call_args.args[0]["instructions"] == " Warm, calm delivery. "
        assert data["instructions"] == " Warm, calm delivery. "
        assert Path(data["script_path"]).read_text() == "  Hello there.  "
        metadata = json.loads(Path(data["file_path"]).with_suffix(".json").read_text())
        assert metadata["instructions"] == " Warm, calm delivery. "
        space, _ = module.open_space(space_id=data["space_id"])
        stash_metadata = space.meta
        assert any(entry.get("instructions") == " Warm, calm delivery. " for entry in stash_metadata["files"])


def test_native_speech_tags_survive_artifact_saving(tool):
    module, synthesize, _ = tool
    script = "[whispering] A quiet greeting. [laughs]"
    result = module.run({"text": script})
    assert result["ok"]
    assert synthesize.call_args.args[0]["text"] == script
    assert Path(result["data"]["script_path"]).read_text() == script
    assert Path(safe_resolve_file(stash_ref=result["data"]["script_ref"])["path"]).read_text() == script


def test_stash_failure_preserves_audio_and_script_without_retrying(tool, monkeypatch):
    module, synthesize, _ = tool
    monkeypatch.setattr(module, "open_space", Mock(side_effect=OSError("private storage detail")))
    result = module.run({"text": "Save this recording."})
    assert result["ok"] is False
    assert result["completion"] == "completed"
    assert Path(result["data"]["file_path"]).is_file()
    assert Path(result["data"]["script_path"]).read_text() == "Save this recording."
    assert "private storage detail" not in json.dumps(result)
    assert "stash_ref" not in result["data"]
    data = result["data"]
    assert data["recovery_available"] is True
    assert data["audio_url"] == f"/api/generated-audio/{data['filename']}"
    receipt = json.loads(Path(data["file_path"]).with_suffix(".json").read_text())
    assert receipt["save_error"] == data["save_error"]
    assert receipt["file_path"] == data["file_path"]
    assert synthesize.call_count == 1


@pytest.mark.parametrize("arguments", [
    [], {}, {"text": " "}, {"text": 42}, {"text": "Hello", "play": True},
    {"text": "Hello", "voice": []}, {"text": "Hello", "title": "a" * 201},
    {"text": "a" * 5001},
])
def test_bad_arguments_never_generate_audio(tool, arguments):
    module, synthesize, _ = tool
    result = module.run(arguments)
    assert not result["ok"] and result["completion"] == "rejected"
    synthesize.assert_not_called()


@pytest.mark.parametrize("error,expected", [
    (RemoteCompletionError("Audio provider returned HTTP 400", "rejected"), "rejected"),
    (RuntimeError("sensitive transport data"), "unknown"),
])
def test_error_keeps_truthful_completion_and_does_not_replay(tool, error, expected):
    module, synthesize, _ = tool
    synthesize.side_effect = error
    result = module.run({"text": "Hello."})
    assert not result["ok"] and result["completion"] == expected
    assert "sensitive transport data" not in json.dumps(result)
    assert synthesize.call_count == 1


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_executor_environment_contains_audio_settings_but_no_unrelated_secrets(tmp_path, monkeypatch, mode):
    from tool_schema import ToolSchema

    from orchestrator.executor import ToolExecutor

    monkeypatch.syspath_prepend(str(ROOT / "orchestrator"))
    schema = ToolSchema.from_json_file(str(ROOT / "skills/generate_audio.tool.json"))

    class Registry:
        def get_tool(self, name):
            return schema if name == "generate_audio" else None

        def is_mcp_tool(self, name):
            return False

    source = {
        "PATH": "/usr/bin", "HOME": str(tmp_path / "operator"), "JARVIS_MODE": mode,
        "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "speech-key",
        "AUDIO_TOOL_VOICE": "tool-voice", "ELEVENLABS_TTS_VOICE": "reply-voice",
        "QWEN3_TTS_FORMAT": "wav", "XAI_TTS_CODEC": "mp3",
        "HEYGEN_API_KEY": "do-not-inherit", "GROKBOT_WEBHOOK_KEY": "do-not-inherit",
        "TTS_PROVIDER": "kokoro", "UNRELATED_SECRET": "do-not-inherit",
    }
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: dict(source))
    monkeypatch.setattr("orchestrator.executor.get_logger", lambda _mode: Mock())
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["tool_env"])
        assert Path(captured["HOME"]).is_dir()
        return json.dumps({"ok": True, "speech": "Created recording."}), "", False

    monkeypatch.setattr("tool_process.run_local_process", run)
    executor = ToolExecutor(mode=mode, registry=Registry(), load_runtime_config=False)
    result = executor.execute("generate_audio", {"text": "Hello."}, skip_permission_check=True)
    assert result["ok"]
    assert captured["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
    assert captured["AUDIO_TOOL_VOICE"] == "tool-voice"
    assert captured["ELEVENLABS_TTS_VOICE"] == "reply-voice"
    assert captured["QWEN3_TTS_FORMAT"] == "wav"
    assert captured["XAI_TTS_CODEC"] == "mp3"
    assert not {"HEYGEN_API_KEY", "GROKBOT_WEBHOOK_KEY", "UNRELATED_SECRET", "TTS_PROVIDER"} & captured.keys()
    assert captured["HOME"] != source["HOME"]
    assert not Path(captured["HOME"]).exists()
