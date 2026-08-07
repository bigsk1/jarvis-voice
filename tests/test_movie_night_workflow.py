"""Contracts for the Trakt-backed Movie Night workflow and optional enrichment."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator"))

from orchestrator.workflow_availability import check_workflow_availability  # noqa: E402
from workflow_loader import WorkflowLoader  # noqa: E402


def _workflow():
    return json.loads((ROOT / "data" / "workflows" / "movie_night.json").read_text())


def test_movie_night_is_explicit_and_keeps_enrichment_optional():
    workflow = _workflow()
    assert workflow["triggers"] == {
        "explicit": ["/movie_night", "/what_to_watch", "/movie_picker"],
        "patterns": [],
        "keywords": [],
    }
    steps = {step["tool"]: step for step in workflow["steps"]}
    assert steps["trakt_movies"]["required"] is True
    assert steps["tmdb_movies"]["required"] is False
    assert steps["tmdb_movies"]["params"] == {
        "action": "images",
        "query": "${top_title}",
        "year": "${top_year}",
        "image_type": "all",
        "max_results": 6,
    }
    assert workflow["variables"]["tmdb_images"] == "none"
    assert workflow["variables"]["tmdb_attribution"] == "not returned"
    assert steps["serpapi_youtube_search"]["required"] is False
    assert steps["brave_llm_context"]["required"] is False
    assert steps["canvas"]["required"] is True
    assert "streaming-list signal does not identify a provider" in steps["canvas"]["llm_prompt"]
    assert "at most one poster and one backdrop" in steps["canvas"]["llm_prompt"]
    assert "do not use original_url" in steps["canvas"]["llm_prompt"]
    assert "Trakt image" not in steps["canvas"]["llm_prompt"]


def test_movie_night_runs_without_optional_enrichment_but_requires_trakt():
    workflow = _workflow()
    available = {"get_time", "trakt_movies", "canvas"}
    status = check_workflow_availability(workflow, available_tools=available)
    assert status["available"] is True
    assert status["degraded"] is True
    assert status["optional_tools_skipped"] == [
        "tmdb_movies",
        "serpapi_youtube_search",
        "brave_llm_context",
    ]

    missing_trakt = check_workflow_availability(
        workflow,
        available_tools={
            "get_time",
            "canvas",
            "tmdb_movies",
            "serpapi_youtube_search",
            "brave_llm_context",
        },
    )
    assert missing_trakt["available"] is False
    assert missing_trakt["unavailable_tools"] == ["trakt_movies"]


def test_movie_night_loader_matches_only_explicit_commands():
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)
    assert loader.match("/movie_night tense mystery")['id'] == "movie_night"
    assert loader.match("/what_to_watch funny and short")['id'] == "movie_night"
