"""A literal workflow media choice uses the existing trusted selection scope."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from config_loader import config_scope, get_config_value

import orchestrator.pipeline_executor as pipeline_module
from orchestrator.pipeline_executor import PipelineExecutor


def pipeline(execute):
    instance = object.__new__(PipelineExecutor)
    instance.mode = "cloud"
    instance.executor = SimpleNamespace(execute=execute)
    return instance


def test_recipe_heygen_selection_overrides_saved_default_only_during_step():
    seen = []

    def execute(tool, args):
        seen.append((tool, args, get_config_value("VIDEO_TOOL_PROVIDER")))
        return {"ok": True}

    with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
        pipeline(execute)._execute_workflow_tool(
            {"params": {"provider": "heygen"}}, "generate_video", {"prompt": "A scene", "provider": "xai"},
        )
        assert get_config_value("VIDEO_TOOL_PROVIDER") == "xai"
    assert seen[0][1]["provider"] == seen[0][2] == "heygen"


@pytest.mark.parametrize("declared", [None, "${provider}"])
def test_model_or_query_filled_provider_does_not_create_trusted_scope(declared):
    seen = []
    with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
        pipeline(lambda *a: seen.append(get_config_value("VIDEO_TOOL_PROVIDER")) or {"ok": True})._execute_workflow_tool(
            {"params": {"provider": declared}}, "generate_video", {"provider": "heygen"},
        )
    assert seen == ["xai"]


def test_scope_restored_when_media_step_raises():
    def fail(*args):
        assert get_config_value("VIDEO_TOOL_PROVIDER") == "heygen"
        raise RuntimeError("test failure")

    with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
        with pytest.raises(RuntimeError, match="test failure"):
            pipeline(fail)._execute_workflow_tool({"params": {"provider": "heygen"}}, "generate_video", {})
        assert get_config_value("VIDEO_TOOL_PROVIDER") == "xai"


@pytest.mark.parametrize("brief_ok", [True, False])
def test_intro_recipe_hands_stash_image_to_selected_provider_only_after_valid_brief(monkeypatch, brief_ok):
    workflow = json.loads((Path(__file__).parents[1] / "data/workflows/heygen_jarvis_intro.json").read_text())
    calls = []
    image_ref = "stash://space_image/f_image"
    video_ref = "stash://space_video/f_video"

    def execute(tool, args):
        calls.append(tool)
        if tool == "heygen":
            return {"ok": True, "data": {"wallet": {"remaining_balance": 1}}}
        if tool == "stash" and args["action"] == "save":
            return {"ok": True, "data": {"ref": "stash://space_readme/f_readme", "space_id": "space_readme", "file_id": "f_readme"}}
        if tool == "stash":
            return {"ok": True, "data": {"content": "Jarvis Voice is a self-hosted voice, chat and automation assistant."}}
        if tool == "generate_image":
            assert "JARVIS VOICE" in args["prompt"]
            return {"ok": True, "data": {"saved": {"stash_ref": image_ref}}}
        if tool == "generate_video":
            assert args["image_url"] == image_ref
            assert args["duration"] == 8
            assert get_config_value("VIDEO_TOOL_PROVIDER") == "heygen"
            return {"ok": True, "data": {"saved": {"stash_ref": video_ref}, "provider_video_id": "native-id"}}
        assert tool == "canvas"
        assert image_ref in args["content"] and video_ref in args["content"]
        return {"ok": False, "error": "Optional Canvas is unavailable"}

    provider = SimpleNamespace(chat_with_tools=lambda **kw: (
        "JARVIS VOICE. " + "Charcoal-and-jade artwork with a waveform and readable title. " * 5 if brief_ok else "",
        None, None, None,
    ))
    monkeypatch.setattr(pipeline_module, "ToolLogger", MagicMock())
    monkeypatch.setattr(pipeline_module, "LLMLogger", MagicMock())
    with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
        result = PipelineExecutor("cloud", SimpleNamespace(execute=execute), provider).execute(workflow, "/heygen_intro")
        assert get_config_value("VIDEO_TOOL_PROVIDER") == "xai"
    assert result["ok"] is brief_ok
    if brief_ok:
        assert video_ref in result["speech"]
        assert calls == ["heygen", "stash", "stash", "generate_image", "generate_video", "canvas"]
    else:
        assert calls == ["heygen", "stash", "stash"]
