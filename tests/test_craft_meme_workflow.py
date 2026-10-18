"""Exercise the shipped meme recipe without operator settings or remote calls."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_loader import WorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "stash://space_photo/f_original"
CAPTION = "TECH SUPPORT SAID TO SIT TIGHT"


def run_workflow(
    query, *, state="succeeded", vision_ok=True, available=None, canvas_ok=True
):
    calls = []

    def execute(tool, params):
        calls.append((tool, params))
        if tool == "analyze_image":
            if not vision_ok or not params.get("image"):
                return {"ok": False, "error": "Image analysis unavailable"}
            return {"ok": True, "data": {"analysis": CAPTION}}
        if tool == "canvas":
            return {
                "ok": canvas_ok,
                "data": {"url": "/canvas/page_meme"},
                "error": None if canvas_ok else "Canvas unavailable",
            }
        assert tool == "craft_image"
        data = {"state": state, "job_id": "a" * 32}
        if state == "succeeded":
            data.update(
                stash_ref="stash://space_meme/f_png",
                mime_type="image/png",
                filename="meme.png",
                editable_project_ref="craft://" + "b" * 32 + "/" + "c" * 32,
                project_revision=1,
                document={"layers": [{"id": 2, "name": "Meme caption"}]},
            )
        return {"ok": True, "data": data}

    executor = SimpleNamespace(
        execute=execute,
        cancel_check=None,
        registry=SimpleNamespace(
            list_tools=lambda: available
            if available is not None
            else ["analyze_image", "craft_image", "canvas"]
        ),
    )
    pipeline = PipelineExecutor("cloud", executor, provider=None)
    pipeline.logger = Mock()
    workflow = json.loads(
        (ROOT / "data/workflows/craft_meme_maker.json").read_text()
    )
    return pipeline.execute(workflow, query), calls


@pytest.mark.parametrize("direction", ["", "Use the exact caption: " + CAPTION])
def test_uploaded_original_and_caption_reach_craft_unchanged(direction):
    query = (
        f"/craft_meme_maker {direction}\n\n[STASHED IMAGE]\n"
        f"Stash reference: {SOURCE}\nSource dimensions: 4032x3024\n"
        "[END STASHED IMAGE]"
    )
    result, calls = run_workflow(query)

    assert result["ok"] is True
    assert [tool for tool, _ in calls] == ["analyze_image", "craft_image", "canvas"]
    assert calls[0][1]["image"] == SOURCE
    assert "${" not in calls[0][1]["question"]
    if direction:
        assert direction in calls[0][1]["question"]
    craft = calls[1][1]
    assert craft["sources"] == [SOURCE]
    assert craft["edits"][0]["text"] == CAPTION
    assert craft["edits"][0]["placement"] == "bottom"
    data = result["data"]["results"][1]["data"]
    assert data["stash_ref"] == "stash://space_meme/f_png"
    assert data["mime_type"] == "image/png"
    assert data["editable_project_ref"].startswith("craft://")
    assert data["document"]["layers"][0]["id"] == 2
    assert "[Open PNG](stash://space_meme/f_png)" in result["speech"]
    assert "![Meme](stash://space_meme/f_png)" in calls[2][1]["content"]
    assert "![" not in result["speech"]
    assert "[Open in Canvas](/canvas/page_meme)" in result["speech"]
    assert "${" not in result["speech"]


def test_caption_direction_survives_the_vision_question_limit():
    from skills.analyze_image import _sanitize_vision_prompt

    direction = "An office joke. " * 35 + "Use the exact caption: " + CAPTION
    _result, calls = run_workflow(f"/craft_meme_maker {direction} {SOURCE}")

    sent_question = _sanitize_vision_prompt(calls[0][1]["question"])
    assert "Use the exact caption: " + CAPTION in sent_question


@pytest.mark.parametrize("state", ["queued", "running"])
def test_unfinished_render_retains_receipt_without_claiming_ready(state):
    result, calls = run_workflow(f"/craft_meme_maker {SOURCE}", state=state)

    assert result["ok"] is True
    assert state in result["speech"]
    assert "ready" not in result["speech"].lower()
    assert result["data"]["results"][1]["data"]["job_id"] == "a" * 32
    assert "meme_ref" not in result["data"]["variables"]
    assert [tool for tool, _ in calls].count("craft_image") == 1
    assert "canvas" not in [tool for tool, _ in calls]
    assert "![" not in result["speech"]


@pytest.mark.parametrize("canvas_available", [True, False])
def test_optional_canvas_failure_or_exclusion_keeps_finished_files(canvas_available):
    result, calls = run_workflow(
        f"/craft_meme_maker {SOURCE}",
        available=["analyze_image", "craft_image", "canvas"]
        if canvas_available
        else ["analyze_image", "craft_image"],
        canvas_ok=False,
    )

    assert result["ok"] is True
    assert result["data"]["variables"]["meme_ref"] == "stash://space_meme/f_png"
    assert [tool for tool, _ in calls].count("craft_image") == 1
    assert "![" not in result["speech"]
    if not canvas_available:
        assert result["data"]["degraded"] is True
        assert "canvas" not in [tool for tool, _ in calls]


@pytest.mark.parametrize("query,vision_ok", [
    ("/craft_meme_maker", True),
    (f"/craft_meme_maker {SOURCE}", False),
])
def test_missing_image_or_failed_vision_cannot_submit_a_craft_job(query, vision_ok):
    result, calls = run_workflow(query, vision_ok=vision_ok)

    assert result["ok"] is False
    assert [tool for tool, _ in calls] == ["analyze_image"]


def test_missing_gateway_tool_blocks_recipe_before_vision():
    result, calls = run_workflow(
        f"/craft_meme_maker {SOURCE}", available=["analyze_image"]
    )

    assert result["ok"] is False
    assert calls == []


def test_shared_loader_discovers_canonical_meme_command(tmp_path):
    source = ROOT / "data/workflows/craft_meme_maker.json"
    (tmp_path / source.name).write_text(source.read_text())
    loader = WorkflowLoader(str(tmp_path))

    assert loader.match("/craft_meme_maker")["id"] == "craft_meme_maker"
    assert loader.match("/craft_meme_maker Make it about coffee")["id"] == (
        "craft_meme_maker"
    )
