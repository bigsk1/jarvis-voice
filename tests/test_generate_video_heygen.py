"""Optional HeyGen provider wiring without paid requests or local credentials."""

import ast
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Optional
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def video_runtime(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    spec = importlib.util.spec_from_file_location("heygen_video_test_skill", ROOT / "skills/generate_video.py")
    assert spec and spec.loader
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)
    values = {"VIDEO_TOOL_PROVIDER": "heygen", "HEYGEN_API_KEY": "synthetic-test-key"}
    def getter(key, default=None):
        return values.get(key, default)
    monkeypatch.setattr(video, "get_config_value", getter)
    monkeypatch.setattr(video, "load_config", lambda: None)
    availability = importlib.import_module("tool_availability")
    monkeypatch.setattr(availability, "get_config_value", getter)
    config = importlib.import_module("config_loader")
    monkeypatch.setattr(config, "get_config_value", getter)
    monkeypatch.setattr(video, "GENERATED_VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(video, "VIDEO_CATALOG_FILE", tmp_path / "video_catalog.json")
    result = {
        "provider": "heygen", "model": "heygen-video-1", "duration": 5, "status": "completed",
        "aspect_ratio": "16:9", "resolution": "768p", "video_url": "https://output.example/clip.mp4",
        "from_image": False, "has_audio": True, "provider_video_id": "native-video-123",
        "receipt_stash_ref": "stash://space_receipt/f_receipt", "estimated_cost_usd": 0.09,
    }
    client = Mock()
    client.generate_clip.return_value = result

    def safe_error(error):
        return {"ok": False, "completion": "unknown", "speech": "HeyGen request could not complete.",
                "error": "HeyGen request could not complete.",
                "data": {"recovery": getattr(error, "recovery", {})}}

    core = SimpleNamespace(HeyGenClient=Mock(return_value=client), heygen_error_result=Mock(side_effect=safe_error))
    monkeypatch.setitem(sys.modules, "heygen_client", core)
    saved = {"saved": True, "filename": "heygen_model_native-video-123.mp4", "path": str(tmp_path / "heygen_model_native-video-123.mp4"),
             "stash_ref": "stash://space_video/f_video", "space_id": "space_video"}
    media = SimpleNamespace(save_result=Mock(return_value={"ok": True, "data": {
        **result, "saved": saved, "stash_ref": saved["stash_ref"], "file_path": saved["path"],
        "filename": saved["filename"], "mime_type": "video/mp4",
    }}))
    monkeypatch.setitem(sys.modules, "heygen_media", media)
    monkeypatch.setitem(sys.modules, "memory_db", SimpleNamespace(MemoryDB=Mock()))
    return SimpleNamespace(video=video, values=values, client=client, core=core, result=result,
                           availability=availability, config=config, media=media, saved=saved)


@pytest.mark.parametrize("image", [None, "stash://space_upload/f_photo"])
def test_provider_dispatch_preserves_image_and_exact_model(video_runtime, image):
    runtime = video_runtime
    result = runtime.video.generate_video("A small animation", image_url=image, model="heygen-video-1")
    assert result == runtime.result
    runtime.client.generate_clip.assert_called_once_with(
        "A small animation", duration=5, aspect_ratio="16:9", resolution="720p",
        image_source=image, model="heygen-video-1",
    )


@pytest.mark.parametrize("key", [None, "", "  "])
def test_missing_key_fails_before_constructing_client(video_runtime, key):
    runtime = video_runtime
    runtime.values["HEYGEN_API_KEY"] = key
    with pytest.raises(runtime.video.RemoteCompletionError, match="HEYGEN_API_KEY") as caught:
        runtime.video.generate_video("A clip", provider="heygen")
    assert caught.value.completion == "rejected"
    runtime.core.HeyGenClient.assert_not_called()
    runtime.client.generate_clip.assert_not_called()


@pytest.mark.parametrize("model", [False, 0, [], {}, ["heygen-video-1"], {"model": "heygen-video-1"}])
def test_explicit_nonstring_model_never_falls_back_to_paid_default(video_runtime, model):
    runtime = video_runtime
    with pytest.raises(runtime.video.RemoteCompletionError, match="model must be a string") as caught:
        runtime.video.generate_video("A clip", model=model)
    assert caught.value.completion == "rejected"
    runtime.core.HeyGenClient.assert_not_called()
    runtime.client.generate_clip.assert_not_called()


@pytest.mark.parametrize("provider", ["unknown-provider", "", False, 0, [], {}])
def test_invalid_effective_provider_never_constructs_or_submits(video_runtime, provider):
    runtime = video_runtime
    runtime.values["VIDEO_TOOL_PROVIDER"] = provider
    with pytest.raises(ValueError, match="Unsupported video provider"):
        runtime.video.generate_video("A clip")
    runtime.core.HeyGenClient.assert_not_called()
    runtime.client.generate_clip.assert_not_called()


@pytest.mark.parametrize("provider", ["xai", "gemini"])
@pytest.mark.parametrize("arguments", [
    {"aspect_ratio": "21:9"}, {"resolution": "768p"}, {"resolution": "2k"}, {"resolution": " 2K "},
])
def test_heygen_only_formats_cannot_buy_coerced_video_from_saved_provider(video_runtime, monkeypatch, provider, arguments):
    runtime = video_runtime
    runtime.values.update(VIDEO_TOOL_PROVIDER=provider, XAI_API_KEY="fixture-xai", GEMINI_API_KEY="fixture-gemini")
    xai = Mock()
    gemini = Mock()
    monkeypatch.setattr(runtime.video, "generate_video_xai", xai)
    monkeypatch.setattr(runtime.video, "generate_video_gemini", gemini)
    with pytest.raises(runtime.video.RemoteCompletionError, match="does not support") as failure:
        runtime.video.generate_video("A clip", provider="heygen", **arguments)
    assert failure.value.completion == "rejected"
    xai.assert_not_called()
    gemini.assert_not_called()
    runtime.core.HeyGenClient.assert_not_called()


@pytest.mark.parametrize("arguments", [{"aspect_ratio": "21:9"}, {"resolution": "768p"}, {"resolution": "2k"}])
def test_heygen_keeps_its_new_formats(video_runtime, arguments):
    runtime = video_runtime
    assert runtime.video.generate_video("A clip", **arguments) == runtime.result
    assert runtime.client.generate_clip.call_args.kwargs.items() >= arguments.items()


@pytest.mark.parametrize("unsupported", [{"video_url": "https://input.example/clip.mp4"}, {"negative_prompt": "avoid blur"}])
def test_unsupported_edit_modes_never_submit(video_runtime, unsupported):
    with pytest.raises(video_runtime.video.RemoteCompletionError, match="not supported"):
        video_runtime.video.generate_video("A clip", **unsupported)
    video_runtime.client.generate_clip.assert_not_called()


def test_only_heygen_key_makes_generic_tool_available(video_runtime):
    manifest = json.loads((ROOT / "skills/generate_video.tool.json").read_text())
    result = video_runtime.availability.check_tool_availability(manifest)
    assert result.available and result.configured_providers == ["heygen"]


def test_main_keeps_native_receipt_actual_resolution_and_cost(video_runtime, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["generate_video.py", json.dumps({"prompt": "A clip", "provider": "heygen", "save": False})])
    video_runtime.video.main()
    output = json.loads(capsys.readouterr().out)
    assert output["ok"]
    for key in ("provider_video_id", "receipt_stash_ref", "estimated_cost_usd", "resolution"):
        assert output["data"][key] == video_runtime.result[key]
    assert output["data"]["has_audio"] is True


def test_submission_error_keeps_recovery_without_echoing_exception(video_runtime, monkeypatch, capsys):
    error = RuntimeError("sensitive provider diagnostic")
    error.recovery = {"provider_video_id": "native-existing", "receipt_stash_ref": "stash://space_receipt/f_existing"}
    video_runtime.client.generate_clip.side_effect = error
    monkeypatch.setattr(sys, "argv", ["generate_video.py", json.dumps({"prompt": "A clip", "provider": "heygen"})])
    with pytest.raises(SystemExit) as stopped:
        video_runtime.video.main()
    assert stopped.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["completion"] == "unknown" and output["data"]["recovery"] == error.recovery
    assert "sensitive provider diagnostic" not in json.dumps(output)
    assert video_runtime.client.generate_clip.call_count == 1


def test_collection_failure_retains_completed_provider_identity(video_runtime, monkeypatch, capsys):
    video_runtime.media.save_result.side_effect = ValueError("signed output URL failed")
    monkeypatch.setattr(sys, "argv", ["generate_video.py", json.dumps({"prompt": "A clip", "provider": "heygen"})])
    with pytest.raises(SystemExit):
        video_runtime.video.main()
    output = json.loads(capsys.readouterr().out)
    assert output["completion"] == "completed"
    assert output["data"]["provider_video_id"] == "native-video-123"
    assert output["data"]["receipt_stash_ref"] == "stash://space_receipt/f_receipt"
    assert video_runtime.client.generate_clip.call_count == 1


def test_main_reuses_shared_collector_and_keeps_artifact_and_source_metadata(video_runtime, monkeypatch, capsys):
    runtime = video_runtime
    legacy = Mock(side_effect=AssertionError("HeyGen must use the idempotent collector"))
    monkeypatch.setattr(runtime.video, "download_video", legacy)
    monkeypatch.setattr(runtime.video, "save_to_stash", legacy)
    runtime.result["from_image"] = True
    runtime.media.save_result.return_value["data"]["from_image"] = True
    args = {"prompt": "Animate this image", "provider": "heygen", "image_url": "stash://space_upload/f_photo"}
    monkeypatch.setattr(sys, "argv", ["generate_video.py", json.dumps(args)])
    runtime.video.main()
    output = json.loads(capsys.readouterr().out)
    runtime.media.save_result.assert_called_once_with(runtime.result, args["prompt"])
    legacy.assert_not_called()
    assert output["data"]["saved"] == runtime.saved
    assert output["data"]["stash_ref"] == runtime.saved["stash_ref"]
    assert output["data"]["filename"] == "heygen_model_native-video-123.mp4"
    assert output["data"]["source_image"] == args["image_url"]
    assert output["data"]["generated_from"] == "image" and output["data"]["has_audio"]


def test_saved_catalog_keeps_heygen_provenance_when_stash_index_is_unavailable(video_runtime, monkeypatch, tmp_path):
    stash = importlib.import_module("stash_helper")
    monkeypatch.setattr(stash, "open_space", Mock(side_effect=OSError("temporary stash failure")))
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    result = video_runtime.video.save_to_stash(path, "A clip", video_runtime.result)
    assert result["saved"] and not result["stash"]
    entry = json.loads(video_runtime.video.VIDEO_CATALOG_FILE.read_text())[path.name]
    assert entry["provider"] == "HeyGen" and entry["model"] == "heygen-video-1"


def test_fastapi_generate_schema_accepts_heygen_without_import_side_effects():
    source = ast.parse((ROOT / "api/routes/generated_videos.py").read_text())
    definition = next(item for item in source.body if isinstance(item, ast.ClassDef) and item.name == "GenerateRequest")
    namespace = {"BaseModel": BaseModel, "Field": Field, "Literal": Literal, "Optional": Optional}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "<GenerateRequest>", "exec"), namespace)
    request = namespace["GenerateRequest"](prompt="A clip", provider="heygen", resolution="768p")
    assert request.provider == "heygen" and request.resolution == "768p"


@pytest.fixture
def video_api_runtime(tmp_path):
    """Exercise the real endpoint body without importing service startup config."""
    import asyncio
    import math
    import subprocess
    import tempfile

    children = importlib.import_module("tool_child_environment")
    source = ast.parse((ROOT / "api/routes/generated_videos.py").read_text())
    definitions = [item for item in source.body if getattr(item, "name", None) in {
        "GenerateRequest", "GenerateResponse", "generate_video",
    }]
    for definition in definitions:
        if isinstance(definition, ast.AsyncFunctionDef):
            definition.decorator_list = []
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "generate_video.tool.json").write_text((ROOT / "skills/generate_video.tool.json").read_text())
    state = SimpleNamespace(
        environment={"PATH": "/synthetic/runtime/bin", "VIDEO_TOOL_PROVIDER": "xai",
                     "HEYGEN_API_KEY": "synthetic-heygen", "JARVIS_MODE": "cloud",
                     "UNRELATED_SECRET": "must-not-reach-child"},
        launches=[],
        response=SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"ok": True, "data": {"provider": "heygen"}})),
        launch_error=None,
    )

    async def launch(command, *args, **kwargs):
        assert command is subprocess.run
        assert Path(kwargs["env"]["HOME"]).is_dir()
        state.launches.append((args, kwargs))
        if state.launch_error:
            raise state.launch_error
        return state.response

    namespace = {"BaseModel": BaseModel, "Field": Field, "Literal": Literal, "Optional": Optional,
                 "PROJECT_ROOT": tmp_path, "json": json, "math": math, "tempfile": tempfile,
                 "subprocess": subprocess, "sys": sys,
                 "run_in_threadpool": launch,
                 "export_config_environment": Mock(side_effect=lambda mode: dict(state.environment)),
                 "parse_child_environment_policy": children.parse_child_environment_policy,
                 "restrict_child_environment": children.restrict_child_environment}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "<generated video endpoint>", "exec"), namespace)

    def invoke(**arguments):
        request = namespace["GenerateRequest"](prompt="A clip", **arguments)
        return asyncio.run(namespace["generate_video"](request))

    state.invoke = invoke
    return state


def test_fastapi_provider_override_has_restricted_environment_and_temporary_home(video_api_runtime):
    runtime = video_api_runtime
    output = runtime.invoke(provider="heygen")
    assert output.ok
    (arguments, options), = runtime.launches
    env = options["env"]
    assert env["VIDEO_TOOL_PROVIDER"] == "heygen"
    assert env["HEYGEN_API_KEY"] == "synthetic-heygen"
    assert env["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
    assert "UNRELATED_SECRET" not in env and "JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER" not in env
    assert runtime.environment["VIDEO_TOOL_PROVIDER"] == "xai"
    assert not Path(env["HOME"]).exists()
    assert options["timeout"] == 480
    assert arguments[0][0] == sys.executable


@pytest.mark.parametrize("wait,expected", [("1200", 1080), ("-1", 180), ("nan", 480), ("invalid", 480)])
def test_fastapi_heygen_observation_budget_is_bounded(video_api_runtime, wait, expected):
    runtime = video_api_runtime
    runtime.environment["HEYGEN_WAIT_SECONDS"] = wait
    assert runtime.invoke(provider="heygen").ok
    assert runtime.launches[0][1]["timeout"] == expected


def test_fastapi_unconfigured_heygen_never_launches(video_api_runtime):
    runtime = video_api_runtime
    runtime.environment["HEYGEN_API_KEY"] = " "
    output = runtime.invoke(provider="heygen")
    assert not output.ok and output.completion == "rejected"
    assert "HEYGEN_API_KEY" in output.error
    assert not runtime.launches


def test_fastapi_preserves_existing_provider_default_and_timeout(video_api_runtime):
    runtime = video_api_runtime
    assert runtime.invoke().ok
    assert runtime.launches[0][1]["env"]["VIDEO_TOOL_PROVIDER"] == "xai"
    assert runtime.launches[0][1]["timeout"] == 600


def test_fastapi_nonzero_exit_preserves_remote_receipt_and_completion(video_api_runtime):
    runtime = video_api_runtime
    recovery = {"provider_video_id": "native-video-123", "receipt_stash_ref": "stash://space_receipt/f_receipt"}
    runtime.response.returncode = 1
    runtime.response.stderr = "untrusted diagnostic with sensitive credentials"
    runtime.response.stdout = json.dumps({"ok": False, "completion": "unknown", "error": "Check this existing job", "data": recovery})
    output = runtime.invoke(provider="heygen")
    assert not output.ok and output.completion == "unknown" and output.data == recovery
    assert output.error == "Check this existing job"
    assert "sensitive credentials" not in output.model_dump_json()


def test_fastapi_timeout_cleans_home_and_does_not_suggest_regeneration(video_api_runtime):
    import subprocess

    runtime = video_api_runtime
    runtime.launch_error = subprocess.TimeoutExpired("python3", 480)
    output = runtime.invoke(provider="heygen")
    assert not output.ok and output.completion == "unknown"
    assert "check the existing job" in output.error
    assert len(runtime.launches) == 1
    assert not Path(runtime.launches[0][1]["env"]["HOME"]).exists()
