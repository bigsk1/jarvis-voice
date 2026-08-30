"""Contracts for the explicit and scheduled Upcoming Movie Radar workflow."""

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
        (ROOT / "data" / "workflows" / "upcoming_movie_radar.json").read_text()
    )


def _step(workflow, tool, action=None):
    return next(
        step
        for step in workflow["steps"]
        if step["tool"] == tool and (action is None or step.get("action") == action)
    )


def test_radar_is_explicit_tmdb_first_and_requires_genre_filters():
    workflow = _workflow()
    assert workflow["allow_workflow_tool"] is False
    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": ["/upcoming_movie_radar"],
        "patterns": [],
        "keywords": [],
    }

    discover = _step(workflow, "tmdb_movies")
    assert discover["required"] is True
    assert discover["params"]["action"] == "discover"
    assert discover["params"]["request"] == "${movie_criteria}"
    assert discover["params"]["require_genres"] is True
    assert discover["params"]["release_types"] == [
        "limited_theatrical",
        "theatrical",
    ]
    assert discover["params"]["new_releases_only"] is True
    assert discover["params"]["exclude_movie_ids"] == "${notified_movie_ids}"
    assert discover["extract"]["top_tmdb_id"] == "results[0].tmdb_id"
    assert (
        discover["extract"]["primary_radar_genre"]
        == "selection_criteria.genres[0]"
    )
    assert discover["set_variables_on_success"] == {
        "radar_title": "${radar_title_prefix}/${primary_radar_genre}"
    }


def test_radar_uses_persistent_sent_history_and_acknowledges_only_sent_email():
    workflow = _workflow()
    open_space = _step(workflow, "stash", "open_space")
    list_history = _step(workflow, "stash", "list")
    acknowledge = _step(workflow, "stash", "save")
    email = _step(workflow, "send_email")

    assert open_space["params"] == {
        "space_id": "space_upcoming_movie_radar",
        "labels": ["upcoming-movie-radar", "emailed-history"],
        "scope": "user",
        "ttl_days": 3650,
    }
    assert list_history["extract"]["notified_movie_ids"] == "files[*].name"
    assert email["required"] is False
    assert email["on_fail"] == "continue"
    assert email["params"]["image_url"] == "${top_poster_url}"
    assert email["params"]["link_url"] == "${top_tmdb_url}"
    assert email["params"]["link_text"] == "View ${top_title} on TMDB"
    assert email["extract"]["email_status"] == "status"

    assert acknowledge["required"] is True
    assert "email was sent" in acknowledge["abort_speech"]
    assert "sent-history ledger" in acknowledge["abort_speech"]
    assert acknowledge["params"]["name"] == "${top_tmdb_id}"
    assert acknowledge["params"]["on_conflict"] == "overwrite"
    assert acknowledge["condition"]["all"][1] == {
        "op": "eq",
        "left": "${email_status}",
        "right": "sent",
    }


def test_radar_routes_each_primary_genre_to_its_own_bounded_canvas_page():
    workflow = _workflow()
    canvas_steps = [step for step in workflow["steps"] if step["tool"] == "canvas"]
    assert [step.get("action") for step in canvas_steps] == ["read", "create", "update"]
    discover = _step(workflow, "tmdb_movies")
    assert workflow["steps"].index(discover) < workflow["steps"].index(canvas_steps[0])
    assert workflow["variables"]["radar_title_prefix"]["value"] == (
        "Workflows/Upcoming Movie Radar"
    )
    assert canvas_steps[0]["params"]["search"] == "${radar_title}"
    assert canvas_steps[1]["params"]["title"] == "${radar_title}"
    assert canvas_steps[2]["params"]["title"] == "${radar_title}"
    assert canvas_steps[1]["condition"] == {
        "op": "not_exists",
        "left": "${existing_radar_page_id}",
    }
    assert canvas_steps[2]["condition"] == {
        "op": "exists",
        "left": "${existing_radar_page_id}",
    }
    assert canvas_steps[2]["params"]["page_id"] == "${existing_radar_page_id}"
    assert canvas_steps[2]["params"]["allow_content_shrink"] is True
    assert canvas_steps[1]["params"]["image_url"] == "${top_poster_url}"
    assert "complete replacement Markdown" in canvas_steps[2]["llm_prompt"]
    assert "no more than eight prior dated picks" in canvas_steps[2]["llm_prompt"]
    assert "Do not describe it as a personalized AI ranking" in canvas_steps[1]["llm_prompt"]
    assert "# Upcoming Movie Radar: ${primary_radar_genre}" in (
        canvas_steps[1]["llm_prompt"]
    )
    assert "do not merge another genre page" in canvas_steps[2]["llm_prompt"]


def test_radar_builds_canvas_title_from_tmdb_resolved_primary_genre():
    workflow = _workflow()
    discover = _step(workflow, "tmdb_movies")
    executor = PipelineExecutor.__new__(PipelineExecutor)
    variables = {
        "radar_title_prefix": "Workflows/Upcoming Movie Radar",
        "primary_radar_genre": "not returned",
    }

    executor._apply_output_transforms(
        discover,
        {
            "ok": True,
            "data": {
                "selection_criteria": {"genres": ["Science Fiction"]},
                "results": [{"tmdb_id": 123, "title": "Example"}],
            },
        },
        variables,
        "tmdb_movies",
        "discover",
    )
    executor._apply_variable_assignments(
        discover["set_variables_on_success"], variables
    )

    assert variables["primary_radar_genre"] == "Science Fiction"
    assert variables["radar_title"] == (
        "Workflows/Upcoming Movie Radar/Science Fiction"
    )


def test_radar_remains_available_without_optional_context_or_email_tool():
    workflow = _workflow()
    status = check_workflow_availability(
        workflow,
        available_tools={"get_time", "canvas", "stash", "tmdb_movies"},
    )
    assert status["available"] is True
    assert status["degraded"] is True
    assert status["optional_tools_skipped"] == ["brave_llm_context", "send_email"]

    missing_tmdb = check_workflow_availability(
        workflow,
        available_tools={"get_time", "canvas", "stash", "brave_llm_context", "send_email"},
    )
    assert missing_tmdb["available"] is False
    assert missing_tmdb["unavailable_tools"] == ["tmdb_movies"]


def test_radar_loader_matches_only_explicit_commands():
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)
    assert loader.match("/upcoming_movie_radar science fiction")['id'] == "upcoming_movie_radar"
