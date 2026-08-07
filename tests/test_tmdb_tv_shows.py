"""Regression tests for the standalone TMDB TV-show tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))

from tmdb_tv_shows import (  # noqa: E402
    ATTRIBUTION_NOTICE,
    TMDBClient,
    build_speech,
    execute_action,
    normalize_images,
    normalize_show,
)


CONFIGURATION = {
    "secure_base_url": "https://image.tmdb.org/t/p/",
    "poster_sizes": ["w92", "w185", "w342", "w500", "original"],
    "backdrop_sizes": ["w300", "w780", "w1280", "original"],
    "logo_sizes": ["w92", "w185", "w300", "w500", "original"],
    "profile_sizes": ["w45", "w185", "h632", "original"],
}
GENRES = {18: "Drama", 9648: "Mystery", 10765: "Sci-Fi & Fantasy"}


def _json_response(payload, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def _show(title="Severance", show_id=95396):
    return {
        "id": show_id,
        "name": title,
        "original_name": title,
        "first_air_date": "2022-02-17",
        "overview": "Office workers have their memories divided.",
        "episode_run_time": [50],
        "number_of_seasons": 2,
        "number_of_episodes": 19,
        "vote_average": 8.4,
        "vote_count": 7200,
        "genre_ids": [18, 9648],
        "poster_path": "/poster123.jpg",
        "backdrop_path": "/backdrop123.jpg",
        "origin_country": ["US"],
    }


def test_client_uses_proxy_chain_and_tv_user_agent():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _json_response({"results": []})

    client = TMDBClient(access_token="token", request_func=fake_request)
    client.get("/tv/popular", {"page": 1})

    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.themoviedb.org/3/tv/popular"
    assert kwargs["use_proxy"] is True
    assert kwargs["fallback_on_proxy_fail"] is True
    assert kwargs["headers"]["User-Agent"] == "JarvisVoice/TMDBTVShows-1.0"


def test_show_normalization_constructs_tv_links_and_episode_metadata():
    show = normalize_show(
        _show(),
        configuration=CONFIGURATION,
        genre_map=GENRES,
        source="search",
    )

    assert show is not None
    assert show["tmdb_id"] == 95396
    assert show["genres"] == ["Drama", "Mystery"]
    assert show["episode_runtime_minutes"] == 50
    assert show["number_of_seasons"] == 2
    assert show["runtime_scope"] == "episode"
    assert show["poster_url"] == "https://image.tmdb.org/t/p/w500/poster123.jpg"
    assert show["tmdb_url"] == "https://www.themoviedb.org/tv/95396"


def test_tv_images_reuse_strict_tmdb_paths_and_balanced_artwork():
    show = {"title": "Severance", "tmdb_url": "https://www.themoviedb.org/tv/95396"}
    images = normalize_images(
        {
            "posters": [{"file_path": "/poster.jpg", "vote_count": 10}],
            "backdrops": [{"file_path": "/backdrop.jpg", "vote_count": 9}],
            "logos": [{"file_path": "/logo.png", "vote_count": 8}],
        },
        configuration=CONFIGURATION,
        show=show,
        image_type="all",
        max_results=3,
    )

    assert [item["image_type"] for item in images] == ["poster", "backdrop", "logo"]
    assert all(item["source_url"] == show["tmdb_url"] for item in images)
    assert all(item["image_url"].startswith("https://image.tmdb.org/t/p/") for item in images)


def test_discover_uses_tv_genres_and_episode_runtime_filters():
    client = TMDBClient(api_key="test-key")
    seen_params = {}

    def fake_get(path, params=None):
        client.request_count += 1
        if path == "/configuration":
            return {"images": CONFIGURATION}
        if path == "/genre/tv/list":
            return {"genres": [{"id": key, "name": value} for key, value in GENRES.items()]}
        if path == "/discover/tv":
            seen_params.update(params or {})
            return {"page": 1, "total_pages": 1, "total_results": 1, "results": [_show()]}
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "discover",
                "genres": ["Mystery"],
                "runtime_max": 60,
                "min_rating": 8,
                "min_votes": 500,
                "origin_country": "US",
            },
        )

    assert seen_params["with_genres"] == "9648"
    assert seen_params["with_runtime.lte"] == 60
    assert seen_params["vote_average.gte"] == 8.0
    assert seen_params["vote_count.gte"] == 500
    assert seen_params["with_origin_country"] == "US"
    assert data["selection_criteria"]["episode_runtime_max_minutes"] == 60
    assert "provider-applied discover filters" in build_speech(data)


def test_details_bundles_aggregate_credits_seasons_rating_and_artwork():
    client = TMDBClient(access_token="test-token")

    def fake_get(path, params=None):
        client.request_count += 1
        if path == "/configuration":
            return {"images": CONFIGURATION}
        if path == "/genre/tv/list":
            return {"genres": [{"id": key, "name": value} for key, value in GENRES.items()]}
        if path == "/tv/95396":
            assert "aggregate_credits" in params["append_to_response"]
            return {
                **_show(),
                "created_by": [{"name": "Dan Erickson"}],
                "networks": [{"name": "Apple TV+"}],
                "production_companies": [{"name": "Fifth Season"}],
                "seasons": [
                    {
                        "id": 1,
                        "name": "Season 1",
                        "season_number": 1,
                        "episode_count": 9,
                        "poster_path": "/season1.jpg",
                    }
                ],
                "images": {
                    "posters": [{"file_path": "/poster.jpg", "vote_count": 10}],
                    "backdrops": [{"file_path": "/backdrop.jpg", "vote_count": 9}],
                    "logos": [],
                },
                "aggregate_credits": {
                    "cast": [
                        {
                            "id": 1,
                            "name": "Adam Scott",
                            "roles": [{"character": "Mark Scout", "episode_count": 19}],
                            "total_episode_count": 19,
                        }
                    ],
                    "crew": [
                        {
                            "id": 2,
                            "name": "Ben Stiller",
                            "department": "Directing",
                            "jobs": [{"job": "Director", "episode_count": 11}],
                            "total_episode_count": 11,
                        }
                    ],
                },
                "videos": {"results": []},
                "external_ids": {"imdb_id": "tt11280740", "tvdb_id": 371980},
                "content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-MA"}]},
                "keywords": {"results": [{"name": "workplace"}]},
                "recommendations": {"results": [_show("Silo", 125988)]},
                "similar": {"results": [_show("Dark", 70523)]},
            }
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {"action": "details", "show_id": 95396, "max_results": 4},
        )

    assert data["show"]["content_rating"] == "TV-MA"
    assert data["show"]["created_by"] == ["Dan Erickson"]
    assert data["show"]["networks"] == ["Apple TV+"]
    assert data["show"]["imdb_url"] == "https://www.imdb.com/title/tt11280740/"
    assert data["cast"][0]["character"] == "Mark Scout"
    assert data["cast"][0]["episode_count"] == 19
    assert data["crew"][0]["job"] == "Director"
    assert data["seasons"][0]["episode_count"] == 9
    assert data["artwork_counts"] == {"poster": 1, "backdrop": 1, "logo": 0}
    assert {"aggregate_cast", "aggregate_crew", "seasons", "content_rating"}.issubset(
        data["details_included"]
    )
    assert data["attribution_notice"] == ATTRIBUTION_NOTICE


def test_manifest_is_standalone_and_accepts_either_tmdb_credential():
    manifest = json.loads((ROOT / "skills" / "tmdb_tv_shows.tool.json").read_text())

    assert manifest["proxy_policy"] == "prefer"
    assert manifest["availability"]["any_of_env"] == ["TMDB_ACCESS_TOKEN", "TMDB_API_KEY"]
    assert "TRAKT_API_KEY" not in json.dumps(manifest["availability"])
    actions = manifest["parameters"]["properties"]["action"]["enum"]
    assert {"images", "discover", "airing_today", "on_the_air", "top_rated"}.issubset(actions)
    assert "do not search first" in manifest["parameters"]["properties"]["action"]["description"]
