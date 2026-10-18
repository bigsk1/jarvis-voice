"""Verify staged media creation using the shipped recipe and simulated services."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_loader import WorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "stash://space_photo/f_original"
PUNCHLINE = "THIS MEETING COULD HAVE BEEN A NAP"
JOB_IDS = {"intro": "a" * 32, "outro": "b" * 32, "trailer": "c" * 32}
TOOLS = ["analyze_image", "craft_motion", "craft_video", "canvas"]


def run_trailer(
    query=None, *, states=None, fail_at=None, missing_ref=None, canvas_available=True,
    canvas_ok=True,
):
    states = states or {}
    calls = []
    motion_calls = 0

    def execute(tool, params):
        nonlocal motion_calls
        calls.append((tool, params))
        if tool == "analyze_image":
            if fail_at == "vision" or not params.get("image"):
                return {"ok": False, "error": "Image analysis unavailable"}
            return {"ok": True, "data": {"analysis": PUNCHLINE}}
        if tool == "canvas":
            return {
                "ok": canvas_ok, "data": {"url": "/canvas/page_trailer"},
                "error": None if canvas_ok else "Canvas unavailable",
            }
        if tool == "craft_motion":
            stage = "intro" if motion_calls == 0 else "outro"
            motion_calls += 1
        else:
            assert tool == "craft_video"
            stage = "trailer"
        data = {"state": states.get(stage, "succeeded"), "job_id": JOB_IDS[stage]}
        if fail_at == stage:
            return {"ok": False, "error": "Craft observation interrupted", "data": data}
        if data["state"] == "succeeded" and missing_ref != stage:
            extension = "mp4" if stage == "trailer" else "png"
            data.update(
                stash_ref=f"stash://space_trailer/f_{stage}",
                filename=f"{stage}.{extension}",
                mime_type="video/mp4" if stage == "trailer" else "image/png",
            )
            if stage == "trailer":
                data.update(
                    editable_project_ref="craft://" + "d" * 32 + "/" + "e" * 32,
                    project_revision=1,
                    document={"duration": 10, "overlays": [{"clip": 4, "layer": 0}]},
                )
        return {"ok": True, "data": data}

    available = TOOLS if canvas_available else TOOLS[:-1]
    executor = SimpleNamespace(
        execute=execute, cancel_check=None,
        registry=SimpleNamespace(list_tools=lambda: available),
    )
    pipeline = PipelineExecutor("cloud", executor, provider=None)
    pipeline.logger = Mock()
    workflow = json.loads((ROOT / "data/workflows/craft_meme_trailer.json").read_text())
    result = pipeline.execute(
        workflow, query if query is not None else f"/craft_meme_trailer {SOURCE}"
    )
    return result, calls


@pytest.mark.parametrize("direction", ["", "Use the exact punchline: " + PUNCHLINE])
def test_photo_to_ten_second_trailer_uses_valid_staged_sources(direction):
    query = (
        f"/craft_meme_trailer {direction}\n\n[IMAGE SOURCES]\n"
        f"Image 1: {SOURCE} — source 4032x3024 pixels; preview 1024x768 pixels\n"
        "[END IMAGE SOURCES]"
    )
    result, calls = run_trailer(query)

    assert result["ok"] is True
    assert [tool for tool, _ in calls] == [
        "analyze_image", "craft_motion", "craft_motion", "craft_video", "canvas"
    ]
    for tool, params in calls:
        schema = json.loads((ROOT / "skills" / f"{tool}.tool.json").read_text())
        Draft202012Validator(schema["parameters"]).validate(params)
    assert calls[0][1]["image"] == SOURCE
    if direction:
        assert direction in calls[0][1]["question"]
    assert all(params["output"] == "png" for _, params in calls[1:3])
    assert calls[2][1]["text"] == PUNCHLINE
    movie = calls[3][1]
    assert movie["sources"] == [
        "stash://space_trailer/f_intro", SOURCE, "stash://space_trailer/f_outro"
    ]
    lengths = [clip["end"] - clip["start"] for clip in movie["clips"]]
    assert lengths == [2, 5, 3]
    assert sum(lengths) == 10
    caption = movie["video_edits"][0]
    assert caption["start"] == lengths[0]
    assert caption["duration"] == lengths[1]
    assert movie["output"] == "mp4"
    assert (movie["width"], movie["height"], movie["fps"]) == (1280, 720, 24)
    data = result["data"]["results"][3]["data"]
    assert data["editable_project_ref"].startswith("craft://")
    assert data["document"]["overlays"][0]["clip"] == 4
    assert "[Play MP4](stash://space_trailer/f_trailer)" in result["speech"]
    assert "${" not in result["speech"]


@pytest.mark.parametrize("state", ["queued", "running"])
@pytest.mark.parametrize("stage,render_count", [("intro", 1), ("outro", 2), ("trailer", 3)])
def test_running_render_preserves_job_and_stops_later_submissions(stage, render_count, state):
    result, calls = run_trailer(states={stage: state})

    assert result["ok"] is True
    renders = [params for tool, params in calls if tool.startswith("craft_")]
    assert len(renders) == render_count
    assert "canvas" not in [tool for tool, _ in calls]
    assert state in result["speech"] and JOB_IDS[stage] in result["speech"]
    assert "ready" not in result["speech"]
    assert "[Play MP4]" not in result["speech"]
    assert "${" not in result["speech"]


@pytest.mark.parametrize("stage,render_count", [("intro", 1), ("outro", 2), ("trailer", 3)])
def test_success_without_artifact_cannot_feed_another_render(stage, render_count):
    result, calls = run_trailer(missing_ref=stage)

    assert result["ok"] is True
    assert len([tool for tool, _ in calls if tool.startswith("craft_")]) == render_count
    assert "canvas" not in [tool for tool, _ in calls]
    assert "[Play MP4]" not in result["speech"]


@pytest.mark.parametrize("stage,render_count", [("intro", 1), ("outro", 2), ("trailer", 3)])
def test_failed_render_retains_receipt_and_never_repeats_a_submission(stage, render_count):
    result, calls = run_trailer(fail_at=stage)

    assert result["ok"] is False
    assert len([tool for tool, _ in calls if tool.startswith("craft_")]) == render_count
    assert result["data"]["results"][-1]["data"]["job_id"] == JOB_IDS[stage]
    assert "canvas" not in [tool for tool, _ in calls]


@pytest.mark.parametrize("canvas_available", [True, False])
def test_failed_or_unavailable_canvas_keeps_completed_movie_and_project(canvas_available):
    result, calls = run_trailer(canvas_available=canvas_available, canvas_ok=False)

    assert result["ok"] is True
    assert result["data"]["variables"]["trailer_ref"] == "stash://space_trailer/f_trailer"
    assert result["data"]["variables"]["editable_project_ref"].startswith("craft://")
    assert len([tool for tool, _ in calls if tool.startswith("craft_")]) == 3
    if not canvas_available:
        assert result["data"]["degraded"] is True
        assert "canvas" not in [tool for tool, _ in calls]


@pytest.mark.parametrize("query,fail_at", [
    ("/craft_meme_trailer", None),
    (f"/craft_meme_trailer {SOURCE}", "vision"),
])
def test_missing_photo_or_vision_failure_prevents_all_renders(query, fail_at):
    result, calls = run_trailer(query, fail_at=fail_at)

    assert result["ok"] is False
    assert [tool for tool, _ in calls] == ["analyze_image"]


def test_shared_loader_discovers_trailer_recipe(tmp_path):
    source = ROOT / "data/workflows/craft_meme_trailer.json"
    (tmp_path / source.name).write_text(source.read_text())

    assert WorkflowLoader(str(tmp_path)).match("/craft_meme_trailer")["id"] == (
        "craft_meme_trailer"
    )
