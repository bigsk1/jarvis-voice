"""Regression tests for the public Trakt TV-show tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))

from trakt_tv_shows import (  # noqa: E402
    TraktClient,
    execute_action,
    extract_reference_candidates,
    normalize_show,
)


def _json_response(payload, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def _show(title: str, trakt_id: int, *, genres=None, rating=8.0, votes=2000):
    slug = title.lower().replace(" ", "-")
    return {
        "title": title,
        "year": 2024,
        "ids": {
            "trakt": trakt_id,
            "slug": f"{slug}-2024",
            "imdb": f"tt{trakt_id:07d}",
            "tmdb": trakt_id + 1000,
            "tvdb": trakt_id + 2000,
        },
        "overview": f"Overview for {title}",
        "first_aired": "2024-01-01T00:00:00.000Z",
        "runtime": 52,
        "network": "Example Network",
        "status": "returning series",
        "aired_episodes": 10,
        "rating": rating,
        "votes": votes,
        "genres": genres or ["drama"],
        "images": {"poster": ["walter-r2.trakt.tv/not-for-hotlinking.webp"]},
    }


def test_normalize_show_omits_trakt_images_and_marks_episode_runtime():
    normalized = normalize_show(
        {"watchers": 42, "show": _show("Example Series", 7)},
        source="trending",
    )

    assert normalized is not None
    assert normalized["title"] == "Example Series"
    assert normalized["episode_runtime_minutes"] == 52
    assert normalized["network"] == "Example Network"
    assert normalized["trakt_url"] == "https://trakt.tv/shows/example-series-2024"
    assert normalized["imdb_url"] == "https://www.imdb.com/title/tt0000007/"
    assert "images" not in normalized
    assert normalized["external_content_trust"] == "untrusted"


def test_reference_parser_understands_favorite_shows_and_series():
    assert extract_reference_candidates(
        'Find something like "Severance" and "Dark" but with short episodes'
    )[:2] == ["Severance", "Dark"]
    assert extract_reference_candidates(
        "My favorite shows are The Expanse, Silo; I want thoughtful science fiction"
    )[:2] == ["The Expanse", "Silo"]


def test_recommend_blends_related_and_public_show_lists_with_videos():
    client = TraktClient("test-client-id")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        client.request_count += 1
        if path == "/search/show":
            return [{"type": "show", "show": _show("Severance", 1, genres=["drama", "mystery"])}]
        if path.endswith("/related"):
            return [
                _show("Related Match", 2, genres=["drama", "mystery"], rating=8.6),
                _show("Severance", 1),
            ]
        if path == "/shows/trending":
            return [{"watchers": 50, "show": _show("Related Match", 2)}]
        if path == "/shows/streaming/weekly":
            return [{"rank": 1, "show": _show("Streaming Pick", 3, genres=["mystery"])}]
        if path == "/shows/popular":
            return [_show("Popular Pick", 4, genres=["comedy"])]
        if path.endswith("/videos"):
            return [
                {
                    "title": "Official Trailer",
                    "url": "https://youtube.com/watch?v=trailer123",
                    "site": "youtube",
                    "type": "trailer",
                    "official": True,
                }
            ]
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "recommend",
                "request": "A tense mystery like Severance",
                "reference_titles": ["Severance"],
                "max_results": 3,
                "include_videos": True,
                "video_limit": 1,
            },
        )

    assert data["results_count"] == 2
    assert data["top_results"][0]["title"] == "Related Match"
    assert data["top_results"][0]["related_to"] == ["Severance"]
    assert data["top_results"][0]["trailer_url"].endswith("trailer123")
    assert data["runtime_scope"] == "episode"
    assert data["streaming_provider_data"] == "not returned"
    assert any(path == "/shows/streaming/weekly" for path, _ in calls)


def test_recommend_applies_episode_runtime_locally():
    client = TraktClient("test-client-id")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        client.request_count += 1
        if path in {"/shows/trending", "/shows/streaming/weekly", "/shows/popular"}:
            short = _show("Short Episodes", 10, genres=["science-fiction"])
            short["runtime"] = 30
            long = _show("Long Episodes", 11, genres=["science-fiction"])
            long["runtime"] = 75
            return [short, long]
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "recommend",
                "request": "Science fiction with short episodes",
                "max_results": 5,
                "include_videos": False,
            },
        )

    assert [show["title"] for show in data["results"]] == ["Short Episodes"]
    assert data["filters_used"]["runtimes"] == "1-35"
    assert all("runtimes" not in params for _, params in calls)


def test_manifest_uses_shared_client_id_and_proxy_policy():
    manifest = json.loads((ROOT / "skills" / "trakt_tv_shows.tool.json").read_text())

    assert manifest["availability"]["all_of_env"] == ["TRAKT_API_KEY"]
    assert manifest["proxy_policy"] == "prefer"
    assert "TRAKT_CLIENT_SECRET" not in json.dumps(manifest)
    assert "recommend" in manifest["parameters"]["properties"]["action"]["enum"]
    assert "episode-runtime" in manifest["parameters"]["properties"]["runtimes"]["description"]


def test_client_requests_proxy_chain_and_uses_tv_user_agent():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _json_response([])

    client = TraktClient("test-client-id", request_func=fake_request)

    assert client.get("/shows/trending", {"limit": 1}) == []
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.trakt.tv/shows/trending"
    assert kwargs["use_proxy"] is True
    assert kwargs["fallback_on_proxy_fail"] is True
    assert kwargs["headers"]["User-Agent"] == "JarvisVoice/TraktTVShows-1.0"
