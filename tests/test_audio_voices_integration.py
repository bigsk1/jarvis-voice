"""Read-only voice lookup keeps usable identities across execution and follow-ups."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from config_loader import config_scope
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "skills/audio_voices.tool.json"


@pytest.fixture(autouse=True)
def preserve_import_path(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = "audio_voice_integration_server"
    server = ROOT / "jarvis-web/server"
    load_server_package(package, server)
    spec = importlib.util.spec_from_file_location(
        f"{package}.services.followup_extractor", server / "services/followup_extractor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lookup_followup_keeps_provider_voice_and_preview_without_private_fields(extractor):
    preview = "https://example.test/preview.mp3?public_token=" + "a" * 600
    voice = {"provider": "elevenlabs", "voice_id": "voice_7", "id": "voice_7",
             "name": "British narrator", "preview_url": preview, "language": "en",
             "kind": "cloned", "gender": "female", "accent": "British",
             "description": "A calm British narrator", "email": "PRIVATE_SENTINEL",
             "api_key": "SECRET_SENTINEL", "raw": {"data": "PRIVATE_SENTINEL"}}
    payload = {"provider": "elevenlabs", "current_provider": "elevenlabs",
               "source": "live_account", "count": 2, "has_more": True,
               "next_cursor": "opaque-next-page", "model": "eleven_v3",
               "items": [voice, {**voice, "voice_id": "voice_8", "id": "voice_8"}],
               "account_email": "PRIVATE_SENTINEL",
               "delivery_capabilities": {"instructions_supported": False,
                                         "inline_tags_supported": True,
                                         "inline_tag_examples": ["[whispers]"],
                                         "api_key": "SECRET_SENTINEL"}}
    compact = extractor.extract_followup_data(
        {"audio_voices": {"ok": True, "data": payload}}, max_candidates=1
    )["audio_voices"]
    assert compact["provider"] == "elevenlabs"
    assert compact["source"] == "live_account"
    assert compact["model"] == "eleven_v3"
    assert compact["next_cursor"] == "opaque-next-page"
    assert compact["has_more"] is True
    assert compact["count"] == 2
    assert compact["candidates_truncated"] is True
    assert compact["candidates"] == [{key: value for key, value in voice.items()
                                       if key not in {"email", "api_key", "raw"}}]
    assert compact["candidates"][0]["preview_url"] == preview
    assert compact["delivery_capabilities"] == {"instructions_supported": False,
                                                 "inline_tags_supported": True,
                                                 "inline_tag_examples": ["[whispers]"]}
    assert "PRIVATE_SENTINEL" not in json.dumps(compact)
    assert "SECRET_SENTINEL" not in json.dumps(compact)
    assert json.loads(json.dumps(compact, allow_nan=False)) == compact


def test_lookup_followup_preserves_empty_and_partial_catalog_state(extractor):
    compact = extractor.extract_followup_data({"audio_voices": {"ok": True, "data": {
        "provider": "xai", "current_provider": "xai", "source": "live_account",
        "count": 0, "has_more": False, "items": [], "partial": True,
        "warning": "Custom voice listing is unavailable; only built-in voices were searched.",
    }}})["audio_voices"]
    assert compact["count"] == 0
    assert compact["has_more"] is False
    assert compact["candidates"] == []
    assert compact["partial"] is True
    assert "Custom voice" in compact["warning"]


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_lookup_normal_child_environment_drops_runtime_voice_and_unrelated_secrets(tmp_path, monkeypatch, mode):
    from tool_schema import ToolSchema

    from orchestrator.executor import ToolExecutor

    monkeypatch.syspath_prepend(str(ROOT / "orchestrator"))
    schema = ToolSchema.from_json_file(str(MANIFEST))

    class Registry:
        def get_tool(self, name):
            return schema if name == "audio_voices" else None

        def is_mcp_tool(self, name):
            return False

    source = {
        "PATH": "/usr/bin", "HOME": str(tmp_path / "operator"), "JARVIS_MODE": mode,
        "AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "speech-key",
        "AUDIO_TOOL_MODEL": "eleven_v3", "ELEVENLABS_TTS_MODEL": "eleven_v3",
        "OPENAI_API_KEY": "openai-key", "TTS_MODEL": "gpt-4o-mini-tts",
        "QWEN3_TTS_URL": "http://localhost:8881/v1/audio/speech",
        "KOKORO_TTS_URL": "http://localhost:8882/v1/audio/speech",
        "HEYGEN_API_KEY": "do-not-inherit", "STASH_DIR": "/tmp/private-stash",
        "ELEVENLABS_TTS_VOICE": "reply-voice", "TTS_PROVIDER": "kokoro",
        "UNRELATED_SECRET": "do-not-inherit",
    }
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: dict(source))
    monkeypatch.setattr("orchestrator.executor.get_logger", lambda _mode: Mock())
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["tool_env"])
        assert Path(captured["HOME"]).is_dir()
        assert kwargs["timeout"] == 90
        return json.dumps({"ok": True, "data": {"provider": "elevenlabs", "items": []}}), "", False

    monkeypatch.setattr("tool_process.run_local_process", run)
    executor = ToolExecutor(mode=mode, registry=Registry(), load_runtime_config=False)
    result = executor.execute("audio_voices", {"search": "British"}, skip_permission_check=True)
    assert result["ok"]
    assert captured["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
    assert captured["ELEVENLABS_API_KEY"] == "speech-key"
    assert captured["AUDIO_TOOL_MODEL"] == "eleven_v3"
    assert captured["QWEN3_TTS_URL"].endswith("/v1/audio/speech")
    assert not {"HEYGEN_API_KEY", "STASH_DIR", "ELEVENLABS_TTS_VOICE",
                "TTS_PROVIDER", "UNRELATED_SECRET"} & captured.keys()
    assert captured["HOME"] != source["HOME"]
    assert not Path(captured["HOME"]).exists()


@pytest.mark.parametrize("provider,key", [
    ("elevenlabs", "ELEVENLABS_API_KEY"), ("openai", "OPENAI_API_KEY"),
    ("xai", "XAI_API_KEY"), ("qwen3-tts", "QWEN3_TTS_URL"), ("kokoro", "KOKORO_TTS_URL"),
])
def test_lookup_availability_requires_optin_and_selected_provider_configuration(provider, key):
    from tool_availability import check_tool_availability

    manifest = json.loads(MANIFEST.read_text())
    settings = {"AUDIO_TOOL_PROVIDER": "", "ELEVENLABS_API_KEY": "", "OPENAI_API_KEY": "",
                "XAI_API_KEY": "", "QWEN3_TTS_URL": "", "KOKORO_TTS_URL": ""}
    with config_scope("cloud", {**settings, key: "configured-value"}):
        assert not check_tool_availability(manifest).available
    with config_scope("cloud", {**settings, "AUDIO_TOOL_PROVIDER": provider}):
        assert not check_tool_availability(manifest).available
    with config_scope("cloud", {**settings, "AUDIO_TOOL_PROVIDER": provider, key: "configured-value"}):
        assert check_tool_availability(manifest).available


def test_lookup_does_not_use_another_configured_provider_to_bypass_missing_default():
    from tool_availability import check_tool_availability

    with config_scope("cloud", {"AUDIO_TOOL_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "",
                                "OPENAI_API_KEY": "configured-value"}):
        assert not check_tool_availability(json.loads(MANIFEST.read_text())).available


def test_restrictive_profiles_disable_lookup_with_generator():
    paths = [ROOT / "skills/profiles/openai_only.json", *(ROOT / "skills/profiles/examples").glob("*.json")]
    for path in paths:
        overrides = json.loads(path.read_text())["overrides"]
        if overrides.get("generate_audio") is False:
            assert overrides.get("audio_voices") is False, path
    assert "execution" not in json.loads(MANIFEST.read_text())


def test_lookup_wrapper_reports_catalog_without_generating(monkeypatch):
    module = importlib.import_module("skills.audio_voices")
    catalog = importlib.import_module("audio_voices")
    monkeypatch.setattr(module, "load_config", lambda: None)
    lookup = Mock(return_value={"provider": "kokoro", "source": "live_server", "count": 1,
                               "items": [{"provider": "kokoro", "voice_id": "af_sky", "name": "Sky"}]})
    monkeypatch.setattr(catalog, "list_audio_voices", lookup)
    result = module.run({"provider": "kokoro", "search": "Sky"})
    assert result["ok"]
    assert result["data"]["items"][0]["voice_id"] == "af_sky"
    assert "No audio was generated" in result["speech"]
    lookup.assert_called_once_with({"provider": "kokoro", "search": "Sky"})


def test_lookup_wrapper_hides_transport_secrets(monkeypatch):
    module = importlib.import_module("skills.audio_voices")
    catalog = importlib.import_module("audio_voices")
    monkeypatch.setattr(module, "load_config", lambda: None)
    monkeypatch.setattr(catalog, "list_audio_voices", Mock(side_effect=RuntimeError("SECRET_SENTINEL")))
    result = module.run({})
    assert result["ok"] is False
    assert "SECRET_SENTINEL" not in json.dumps(result)
    assert "no audio was generated" in result["error"]


def test_lookup_wrapper_reports_catalog_permission_failure_without_raw_response(monkeypatch):
    module = importlib.import_module("skills.audio_voices")
    catalog = importlib.import_module("audio_voices")
    monkeypatch.setattr(module, "load_config", lambda: None)
    monkeypatch.setattr(catalog, "list_audio_voices", Mock(side_effect=catalog.AudioVoiceCatalogError(403)))
    result = module.run({})
    assert result["ok"] is False
    assert "HTTP 403" in result["error"]
    assert "voice-listing access" in result["error"]


def test_lookup_executes_in_real_restricted_child_without_calling_openai(monkeypatch):
    from tool_schema import ToolSchema

    from orchestrator.executor import ToolExecutor

    schema = ToolSchema.from_json_file(str(MANIFEST))

    class Registry:
        def get_tool(self, name):
            return schema if name == "audio_voices" else None

        def is_mcp_tool(self, name):
            return False

    monkeypatch.setattr("orchestrator.executor.get_logger", lambda _mode: Mock())
    monkeypatch.syspath_prepend(str(ROOT / "orchestrator"))
    with config_scope("cloud", {"AUDIO_TOOL_PROVIDER": "openai", "OPENAI_API_KEY": "fixture-only-key",
                                "AUDIO_TOOL_MODEL": "gpt-4o-mini-tts"}):
        executor = ToolExecutor(mode="cloud", registry=Registry(), load_runtime_config=False)
        result = executor.execute("audio_voices", {"search": "alloy", "limit": 1},
                                  skip_permission_check=True)
    assert result["ok"], result
    assert result["data"]["source"] == "documented_builtin"
    assert result["data"]["items"][0]["voice_id"] == "alloy"
    assert "fixture-only-key" not in json.dumps(result)
