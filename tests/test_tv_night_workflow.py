"""Contracts for the Trakt-backed TV Night workflow and optional enrichment."""

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
    return json.loads((ROOT / "data" / "workflows" / "tv_night.json").read_text())


def test_tv_night_is_explicit_and_keeps_enrichment_optional():
    workflow = _workflow()
    assert workflow["triggers"] == {
        "explicit": ["/tv_night", "/what_show_to_watch", "/tv_picker"],
        "patterns": [],
        "keywords": [],
    }
    steps = {step["tool"]: step for step in workflow["steps"]}
    assert steps["trakt_tv_shows"]["required"] is True
    assert steps["trakt_account"]["required"] is False
    assert steps["trakt_account"]["params"]["action"] == "tv_night_context"
    assert steps["trakt_account"]["params"]["public_candidates"] == "${show_candidates}"
    assert steps["trakt_account"]["params"]["ignore_watched"] is True
    assert steps["trakt_account"]["extract"]["show_candidates"] == "eligible_public_candidates"
    assert steps["trakt_account"]["extract"]["top_title"] == "enrichment_title"
    assert steps["tmdb_tv_shows"]["required"] is False
    assert steps["tmdb_tv_shows"]["params"] == {
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

    prompt = steps["canvas"]["llm_prompt"]
    assert "Runtime means typical episode runtime only" in prompt
    assert "streaming-list signal does not identify a provider" in prompt
    assert "at most one poster and one backdrop" in prompt
    assert "do not use original_url" in prompt
    assert "Copy every returned source URL byte-for-byte" in prompt
    assert "Trakt image" not in prompt
    assert "Recommend only from those eligible lists" in prompt
    assert "${watched_filter_applied}" in prompt
    assert "raw watched rows" in prompt
    assert "https://www.https://" in steps["canvas"]["llm_output_validation"]["reject_patterns"]


def test_tv_night_runs_without_optional_enrichment_but_requires_trakt():
    workflow = _workflow()
    available = {"get_time", "trakt_tv_shows", "canvas"}
    status = check_workflow_availability(workflow, available_tools=available)
    assert status["available"] is True
    assert status["degraded"] is True
    assert status["optional_tools_skipped"] == [
        "trakt_account",
        "tmdb_tv_shows",
        "serpapi_youtube_search",
        "brave_llm_context",
    ]

    missing_trakt = check_workflow_availability(
        workflow,
        available_tools={
            "get_time",
            "canvas",
            "trakt_account",
            "tmdb_tv_shows",
            "serpapi_youtube_search",
            "brave_llm_context",
        },
    )
    assert missing_trakt["available"] is False
    assert missing_trakt["unavailable_tools"] == ["trakt_tv_shows"]


def test_tv_night_loader_matches_only_explicit_commands():
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)
    assert loader.match("/tv_night tense mystery")['id'] == "tv_night"
    assert loader.match("/what_show_to_watch funny and short")['id'] == "tv_night"
    assert loader.match("/tv_picker a completed drama")['id'] == "tv_night"
