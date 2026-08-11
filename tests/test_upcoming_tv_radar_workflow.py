"""Contracts for the explicit and scheduled Upcoming TV Radar workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator"))

from workflow_loader import WorkflowLoader  # noqa: E402

from orchestrator.pipeline_executor import PipelineExecutor  # noqa: E402
from orchestrator.workflow_availability import check_workflow_availability  # noqa: E402


def _workflow():
    return json.loads(
        (ROOT / "data" / "workflows" / "upcoming_tv_radar.json").read_text()
    )


def _step(workflow, tool, action=None):
    return next(
        step
        for step in workflow["steps"]
        if step["tool"] == tool and (action is None or step.get("action") == action)
    )


def test_tv_radar_is_explicit_tmdb_first_and_requires_genre_filters():
    workflow = _workflow()
    assert workflow["allow_workflow_tool"] is False
    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": [
            "/upcoming_tv_radar",
            "/tv_release_radar",
            "/upcoming_tv_shows",
        ],
        "patterns": [],
        "keywords": [],
    }

    discover = _step(workflow, "tmdb_tv_shows")
    assert discover["required"] is True
    assert discover["params"]["action"] == "discover"
    assert discover["params"]["request"] == "${show_criteria}"
    assert discover["params"]["require_genres"] is True
    assert discover["params"]["exclude_show_ids"] == "${notified_show_ids}"
    assert discover["extract"]["top_tmdb_id"] == "results[0].tmdb_id"
    assert (
        discover["extract"]["primary_radar_genre"]
        == "selection_criteria.genres[0]"
    )
    assert discover["set_variables_on_success"] == {
        "radar_title": "${radar_title_prefix}/${primary_radar_genre}"
    }


def test_tv_radar_uses_shared_sent_history_and_acknowledges_only_sent_email():
    workflow = _workflow()
    open_space = _step(workflow, "stash", "open_space")
    list_history = _step(workflow, "stash", "list")
    acknowledge = _step(workflow, "stash", "save")
    email = _step(workflow, "send_email")

    assert open_space["params"] == {
        "space_id": "space_upcoming_tv_radar",
        "labels": ["upcoming-tv-radar", "emailed-history"],
        "scope": "user",
        "ttl_days": 3650,
    }
    assert list_history["extract"]["notified_show_ids"] == "files[*].name"
    assert email["required"] is False
    assert email["on_fail"] == "continue"
    assert email["params"]["image_url"] == "${top_poster_url}"
    assert email["params"]["link_url"] == "${top_tmdb_url}"
    assert email["extract"]["email_status"] == "status"

    assert acknowledge["required"] is True
    assert "email was sent" in acknowledge["abort_speech"]
    assert acknowledge["params"]["name"] == "${top_tmdb_id}"
    assert acknowledge["condition"]["all"][1] == {
        "op": "eq",
        "left": "${email_status}",
        "right": "sent",
    }


def test_tv_radar_routes_each_primary_genre_to_its_own_bounded_canvas_page():
    workflow = _workflow()
    canvas_steps = [step for step in workflow["steps"] if step["tool"] == "canvas"]
    assert [step.get("action") for step in canvas_steps] == ["read", "create", "update"]
    discover = _step(workflow, "tmdb_tv_shows")
    assert workflow["steps"].index(discover) < workflow["steps"].index(canvas_steps[0])
    assert workflow["variables"]["radar_title_prefix"]["value"] == (
        "Workflows/Upcoming TV Radar"
    )
    assert canvas_steps[0]["params"]["search"] == "${radar_title}"
    assert canvas_steps[1]["params"]["title"] == "${radar_title}"
    assert canvas_steps[2]["params"]["title"] == "${radar_title}"
    assert canvas_steps[1]["condition"]["left"] == "${existing_radar_page_id}"
    assert canvas_steps[2]["params"]["page_id"] == "${existing_radar_page_id}"
    assert canvas_steps[2]["params"]["allow_content_shrink"] is True
    assert "complete replacement Markdown" in canvas_steps[2]["llm_prompt"]
    assert "no more than eight prior dated picks" in canvas_steps[2]["llm_prompt"]
    assert "# Upcoming TV Radar: ${primary_radar_genre}" in (
        canvas_steps[1]["llm_prompt"]
    )
    assert "not a new season date" in canvas_steps[2]["llm_prompt"]


def test_tv_radar_builds_canvas_title_from_tmdb_resolved_primary_genre():
    workflow = _workflow()
    discover = _step(workflow, "tmdb_tv_shows")
    executor = PipelineExecutor.__new__(PipelineExecutor)
    variables = {
        "radar_title_prefix": "Workflows/Upcoming TV Radar",
        "primary_radar_genre": "not returned",
    }

    executor._apply_output_transforms(
        discover,
        {
            "ok": True,
            "data": {
                "selection_criteria": {"genres": ["Sci-Fi & Fantasy"]},
                "results": [{"tmdb_id": 123, "title": "Example"}],
            },
        },
        variables,
        "tmdb_tv_shows",
        "discover",
    )
    executor._apply_variable_assignments(
        discover["set_variables_on_success"], variables
    )

    assert variables["primary_radar_genre"] == "Sci-Fi & Fantasy"
    assert variables["radar_title"] == (
        "Workflows/Upcoming TV Radar/Sci-Fi & Fantasy"
    )


def test_tv_radar_remains_available_without_optional_context_or_email_tool():
    workflow = _workflow()
    status = check_workflow_availability(
        workflow,
        available_tools={"get_time", "canvas", "stash", "tmdb_tv_shows"},
    )
    assert status["available"] is True
    assert status["degraded"] is True
    assert status["optional_tools_skipped"] == ["brave_llm_context", "send_email"]

    missing_tmdb = check_workflow_availability(
        workflow,
        available_tools={"get_time", "canvas", "stash", "send_email"},
    )
    assert missing_tmdb["available"] is False
    assert missing_tmdb["unavailable_tools"] == ["tmdb_tv_shows"]


def test_tv_radar_loader_matches_only_explicit_commands():
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)
    assert loader.match("/upcoming_tv_radar science fiction")["id"] == (
        "upcoming_tv_radar"
    )
    assert loader.match("/tv_release_radar comedy")["id"] == "upcoming_tv_radar"
