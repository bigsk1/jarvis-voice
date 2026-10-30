"""Phone subprocesses retain call/Canvas settings without chat-provider secrets."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from config_loader import config_scope
from tool_availability import check_tool_availability
from tool_child_environment import restrict_child_environment
from tool_schema import ToolSchema

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "skills/phone_call.tool.json"


@pytest.fixture(autouse=True)
def preserve_import_path(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))


def _call_settings(mode):
    return {
        "VAPI_API_KEY": f"fixture-{mode}-vapi-key",
        "VAPI_PHONE_NUMBER_ID": f"{mode}-phone",
        "VAPI_ASSISTANT_ID": f"{mode}-assistant",
        "VAPI_DEFAULT_PERSONA": "female",
        "VAPI_LLM_PROVIDER": "openai",
        "VAPI_LLM_MODEL": f"{mode}-phone-model",
        "VAPI_LLM_REASONING_EFFORT": "minimal",
        "VAPI_VOICE_ID": f"{mode}-voice",
        "VAPI_VOICE_MODEL": "eleven_v4_turbo",
        "VAPI_FEMALE_VOICE_ID": f"{mode}-female-voice",
        "VAPI_ELEVENLABS_KEY": "true",
        "VAPI_VOICEMAIL_ACTION": "hangup",
        "VAPI_WAIT_FOR_CALL": "true",
        "VAPI_WAIT_TIMEOUT": "900",
        "OWNER_NAME": "Fixture owner",
        "PHONE_CONTACTS": '{"fixture":"+15550000001"}',
        "ELEVENLABS_VOICE_ID": "legacy-fallback-voice",
        "ELEVENLABS_TTS_VOICE": "alternate-fallback-voice",
        "CANVAS_INTERNAL_URL": f"http://{mode}-canvas.example.test:8890",
        "CANVAS_PUBLIC_URL": f"https://{mode}-canvas.example.test",
        "STASH_DIR": f"/tmp/fixture-{mode}-stash",
        "STASH_DEFAULT_TTL_DAYS": "7",
        "STASH_SOURCE_ARTIFACT_TTL_DAYS": "120",
        "OLLAMA_BASE_URL": f"http://{mode}-embedding.example.test:11434",
        "OLLAMA_EMBEDDING_FALLBACK_URL": f"http://{mode}-fallback.example.test:11434",
        "OLLAMA_EMBEDDING_MODEL": "fixture-embedding-model",
        "OLLAMA_EMBEDDING_MODEL_DIGEST": "fixture-digest",
        "OLLAMA_EMBEDDING_CONTEXT_WINDOW": "2048",
        "OLLAMA_API_KEY": f"fixture-{mode}-embedding-key",
    }


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_phone_executor_child_keeps_effective_call_and_canvas_environment(
    tmp_path, monkeypatch, mode
):
    from orchestrator.executor import ToolExecutor

    monkeypatch.syspath_prepend(str(ROOT / "orchestrator"))
    schema = ToolSchema.from_json_file(str(MANIFEST))

    class Registry:
        def get_tool(self, name):
            return schema if name == "phone_call" else None

        def is_mcp_tool(self, name):
            return False

    expected = _call_settings(mode)
    unrelated = {
        "OPENAI_API_KEY": "unrelated-openai-key",
        "XAI_API_KEY": "unrelated-xai-key",
        "ANTHROPIC_API_KEY": "unrelated-anthropic-key",
        "ELEVENLABS_API_KEY": "unrelated-elevenlabs-key",
        "JARVIS_LLM_PROVIDER": "xai",
        "OLLAMA_CLOUD_MODEL": "unrelated-chat-model",
        "UNRELATED_SECRET": "unrelated-secret",
        "JARVIS_OVERRIDE_OPENAI_API_KEY": "unrelated-request-key",
    }
    source = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "operator-home"),
        "JARVIS_MODE": mode,
        **expected,
        **unrelated,
        "VAPI_LLM_MODEL": "stale-phone-model",
        "JARVIS_OVERRIDE_VAPI_LLM_MODEL": expected["VAPI_LLM_MODEL"],
    }
    monkeypatch.setattr(
        "orchestrator.executor.export_config_environment", lambda _mode: dict(source)
    )
    monkeypatch.setattr("orchestrator.executor.get_logger", lambda _mode: Mock())
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["tool_env"])
        assert Path(captured["HOME"]).is_dir()
        return json.dumps({"ok": True, "data": {"status": "ended"}}), "", False

    monkeypatch.setattr("tool_process.run_local_process", run)
    executor = ToolExecutor(mode=mode, registry=Registry(), load_runtime_config=False)

    result = executor.execute(
        "phone_call", {"action": "status", "call_id": "fixture-call"}, skip_permission_check=True
    )

    assert result["ok"] is True
    assert schema.child_environment_names is not None
    assert {key: captured.get(key) for key in expected} == expected
    assert captured["JARVIS_MODE"] == mode
    assert captured["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
    assert not unrelated.keys() & captured.keys()
    assert not any(key.startswith("JARVIS_OVERRIDE_") for key in captured)
    assert captured["HOME"] != source["HOME"]
    assert not Path(captured["HOME"]).exists()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_nested_canvas_load_config_preserves_restriction_without_reading_mode_files(tmp_path, mode):
    schema = ToolSchema.from_json_file(str(MANIFEST))
    assert schema.child_environment_names is not None
    settings = _call_settings(mode)
    env = restrict_child_environment(
        {"PATH": "/usr/bin:/bin", "JARVIS_MODE": mode, **settings},
        schema.child_environment_names,
        home=str(tmp_path),
    )
    # Exercise Canvas's actual CLI/config entry point in a fresh interpreter.
    # Its network/mutation boundary is replaced, and any mode-file reload fails.
    script = """
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path[:0] = [str(root / 'lib'), str(root / 'skills')]
import config_loader

def forbidden_reload(*args, **kwargs):
    raise AssertionError('A restricted Canvas child reread private mode files')

config_loader._load_mode_config = forbidden_reload
import canvas

def create_page(*args, **kwargs):
    return {'ok': True, 'data': {
        'mode': config_loader.get_active_config_mode(),
        'marker': os.environ.get('JARVIS_RESTRICTED_TOOL_ENV'),
        'canvas_url': canvas.get_canvas_internal_url(),
        'embedding_model': config_loader.get_config_value('OLLAMA_EMBEDDING_MODEL'),
        'vapi_model': config_loader.get_config_value('VAPI_LLM_MODEL'),
        'chat_key_present': bool(config_loader.get_config_value('OPENAI_API_KEY')),
    }}

canvas.create_page = create_page
sys.argv = ['canvas.py', json.dumps({'action': 'create', 'title': 'Fixture', 'content': 'Fixture'})]
canvas.main()
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(ROOT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )

    assert json.loads(child.stdout) == {
        "ok": True,
        "data": {
            "mode": mode,
            "marker": "1",
            "canvas_url": settings["CANVAS_INTERNAL_URL"],
            "embedding_model": settings["OLLAMA_EMBEDDING_MODEL"],
            "vapi_model": settings["VAPI_LLM_MODEL"],
            "chat_key_present": False,
        },
    }


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_phone_manifest_remains_discoverable_without_outbound_call_credentials(mode):
    manifest = json.loads(MANIFEST.read_text())
    schema = ToolSchema.from_json_file(str(MANIFEST))
    with config_scope(mode, {"VAPI_API_KEY": "", "VAPI_PHONE_NUMBER_ID": ""}):
        availability = check_tool_availability(manifest)

    assert availability.available is True
    assert {"status", "contacts"} <= set(schema.parameters["properties"]["action"]["enum"])
