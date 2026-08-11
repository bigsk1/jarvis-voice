"""Regression tests for the public Trakt movie tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))

from trakt_movies import (  # noqa: E402
    TraktClient,
    _candidate_score,
    _infer_excluded_genres,
    _infer_genres,
    _infer_runtime_filter,
    _select_diverse_candidates,
    execute_action,
    extract_reference_candidates,
    normalize_movie,
)


def _json_response(payload, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def _movie(title: str, trakt_id: int, *, genres=None, rating=7.5, votes=1000):
    slug = title.lower().replace(" ", "-")
    return {
        "title": title,
        "year": 2024,
        "ids": {"trakt": trakt_id, "slug": f"{slug}-2024", "imdb": f"tt{trakt_id:07d}"},
        "overview": f"Overview for {title}",
        "runtime": 110,
        "rating": rating,
        "votes": votes,
        "genres": genres or ["thriller"],
        "images": {"poster": ["walter-r2.trakt.tv/not-for-hotlinking.webp"]},
    }


def test_normalize_movie_omits_uncached_trakt_images_and_adds_public_links():
    normalized = normalize_movie({"watchers": 42, "movie": _movie("Example Film", 7)}, source="trending")

    assert normalized is not None
    assert normalized["title"] == "Example Film"
    assert normalized["watchers"] == 42
    assert normalized["trakt_url"] == "https://trakt.tv/movies/example-film-2024"
    assert normalized["imdb_url"] == "https://www.imdb.com/title/tt0000007/"
    assert "images" not in normalized
    assert "thumbnail" not in normalized
    assert normalized["external_content_trust"] == "untrusted"


def test_reference_parser_handles_quoted_and_natural_favorite_lists():
    assert extract_reference_candidates(
        'I want something tense like "Inception" and "Interstellar" but under two hours'
    )[:2] == ["Inception", "Interstellar"]

    parsed = extract_reference_candidates(
        "My favorite movies are Arrival, Ex Machina; I want something thoughtful tonight"
    )
    assert parsed[:2] == ["Arrival", "Ex Machina"]


def test_reference_parser_separates_titles_from_movie_night_constraints():
    cases = {
        "thoughtful science fiction like Arrival and Blade Runner 2049, under two hours": [
            "Arrival",
            "Blade Runner 2049",
        ],
        "thoughtful science fiction like Arrival": ["Arrival"],
        "Looking for something to watch. I like these previous movies matrix, bird box, solace": [
            "matrix",
            "bird box",
            "solace",
        ],
        "I want a tense, intelligent science-fiction movie like Arrival and Ex Machina, "
        "under two hours, preferably on Netflix or Prime": ["Arrival", "Ex Machina"],
    }

    for request, expected in cases.items():
        assert extract_reference_candidates(request)[:3] == expected


def test_inference_handles_hyphenated_genre_and_written_hour_limit():
    request = "Tense, intelligent science-fiction under two hours"

    assert _infer_genres(request) == ["science-fiction", "thriller"]
    assert _infer_runtime_filter(request) == "1-120"


def test_inference_treats_no_anime_as_exclusion_not_positive_animation():
    request = "Thoughtful science fiction, no animated or anime movies"

    assert _infer_genres(request) == ["science-fiction"]
    assert _infer_excluded_genres(request) == ["animation"]


def test_discovery_action_excludes_requested_genres_locally():
    client = TraktClient("test-client-id")
    request_params = {}

    def fake_get(path, params=None):
        assert path == "/movies/anticipated"
        request_params.update(params or {})
        return [
            _movie("Animated Pick", 70, genres=["science-fiction", "animation"]),
            _movie("Live Action Pick", 71, genres=["science-fiction", "thriller"]),
        ]

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "anticipated",
                "genres": ["science-fiction"],
                "exclude_genres": ["animation"],
                "max_results": 2,
            },
        )

    assert request_params["genres"] == "science-fiction"
    assert "exclude_genres" not in request_params
    assert [movie["title"] for movie in data["results"]] == ["Live Action Pick"]


def test_related_match_outranks_candidate_repeated_across_current_lists():
    related = _movie("Reference Match", 30, rating=7.0, votes=500)
    related["source_signals"] = ["related:Arrival"]
    generic = _movie("Current Everywhere", 31, rating=8.5, votes=100000)
    generic["source_signals"] = ["streaming", "trending", "popular"]

    assert _candidate_score(related, []) > _candidate_score(generic, [])


def test_candidate_selection_preserves_one_result_per_reference_when_available():
    references = [_movie("Matrix", 40), _movie("Bird Box", 41), _movie("Solace", 42)]
    ranked = [
        {**_movie("Matrix Match 1", 43), "related_to": ["Matrix"]},
        {**_movie("Matrix Match 2", 44), "related_to": ["Matrix"]},
        {**_movie("Generic Pick", 45), "related_to": []},
        {**_movie("Bird Box Match", 46), "related_to": ["Bird Box"]},
        {**_movie("Solace Match", 47), "related_to": ["Solace"]},
    ]

    selected = _select_diverse_candidates(ranked, references, 3)
    coverage = {title for movie in selected for title in movie["related_to"]}

    assert coverage == {"Matrix", "Bird Box", "Solace"}


def test_recommend_blends_related_and_current_sources_and_attaches_trailer_metadata():
    client = TraktClient("test-client-id")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        client.request_count += 1
        if path == "/search/movie":
            return [
                {
                    "type": "movie",
                    "score": 100,
                    "movie": _movie(
                        "Inception", 1, genres=["science-fiction", "thriller"]
                    ),
                }
            ]
        if path.endswith("/related"):
            return [
                _movie("Source Match", 2, genres=["science-fiction", "thriller"], rating=8.2, votes=5000),
                _movie("Reference Duplicate", 1),
            ]
        if path == "/movies/trending":
            return [{"watchers": 50, "movie": _movie("Source Match", 2)}]
        if path == "/movies/streaming/weekly":
            return [{"rank": 1, "movie": _movie("Streaming Pick", 3, genres=["science-fiction"])}]
        if path == "/movies/popular":
            return [_movie("Popular Pick", 4, genres=["drama"])]
        if path.endswith("/videos"):
            return [
                {
                    "title": "Official Trailer",
                    "url": "https://youtube.com/watch?v=trailer123",
                    "site": "youtube",
                    "type": "trailer",
                    "official": True,
                    "published_at": "2024-01-01T00:00:00Z",
                    "country": "us",
                    "language": "en",
                }
            ]
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "recommend",
                "request": "I want mind-bending sci-fi like Inception",
                "reference_titles": ["Inception"],
                "max_results": 3,
                "include_videos": True,
                "video_limit": 1,
            },
        )

    assert data["results_count"] == 2
    assert data["top_results"][0]["title"] == "Source Match"
    assert data["top_results"][0]["related_to"] == ["Inception"]
    assert "trending" in data["top_results"][0]["source_signals"]
    assert data["top_results"][0]["trailer_url"] == "https://youtube.com/watch?v=trailer123"
    assert data["resolved_references"][0]["title"] == "Inception"
    assert data["streaming_provider_data"] == "not returned"
    assert any(path == "/movies/streaming/weekly" for path, _ in calls)


def test_recommend_applies_runtime_locally_without_sending_unstable_list_filter():
    client = TraktClient("test-client-id")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        client.request_count += 1
        if path in {"/movies/trending", "/movies/streaming/weekly", "/movies/popular"}:
            short = _movie("Short Pick", 10, genres=["science-fiction"])
            long = _movie("Long Pick", 11, genres=["science-fiction"])
            long["runtime"] = 145
            return [short, long]
        if path.endswith("/videos"):
            return []
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "recommend",
                "request": "Mind-bending science fiction, not too long",
                "max_results": 5,
                "include_videos": False,
            },
        )

    assert [movie["title"] for movie in data["results"]] == ["Short Pick"]
    assert data["filters_used"]["runtimes"] == "1-120"
    assert all("runtimes" not in params for _, params in calls)
    assert all(params.get("genres") == "science-fiction" for _, params in calls)


def test_streaming_action_overfetches_before_applying_local_runtime_filter():
    client = TraktClient("test-client-id")
    request_params = {}

    def fake_get(path, params=None):
        assert path == "/movies/streaming/weekly"
        request_params.update(params or {})
        rows = []
        for index, runtime in enumerate((145, 138, 130, 104), 1):
            movie = _movie(f"Pick {index}", 20 + index, genres=["thriller"])
            movie["runtime"] = runtime
            rows.append(movie)
        return rows

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "streaming",
                "runtimes": "1-120",
                "max_results": 4,
            },
        )

    assert request_params["limit"] == 12
    assert "runtimes" not in request_params
    assert [movie["title"] for movie in data["results"]] == ["Pick 4"]


def test_manifest_requires_only_public_client_id():
    manifest = json.loads((ROOT / "skills" / "trakt_movies.tool.json").read_text())

    assert manifest["availability"]["all_of_env"] == ["TRAKT_API_KEY"]
    assert manifest["proxy_policy"] == "prefer"
    assert "TRAKT_CLIENT_SECRET" not in json.dumps(manifest)
    assert "recommend" in manifest["parameters"]["properties"]["action"]["enum"]
    assert "exclude_genres" in manifest["parameters"]["properties"]


def test_client_requests_shared_proxy_chain_with_direct_fallback():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _json_response([])

    client = TraktClient("test-client-id", request_func=fake_request)

    assert client.get("/movies/trending", {"limit": 1}) == []
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.trakt.tv/movies/trending"
    assert kwargs["params"] == {"limit": 1}
    assert kwargs["timeout"] == 15
    assert kwargs["use_proxy"] is True
    assert kwargs["fallback_on_proxy_fail"] is True
    assert kwargs["headers"]["trakt-api-key"] == "test-client-id"
