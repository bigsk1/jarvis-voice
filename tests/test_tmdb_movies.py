"""Regression tests for the standalone TMDB movie tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))

from tmdb_movies import (  # noqa: E402
    ATTRIBUTION_NOTICE,
    TMDBAPIError,
    TMDBClient,
    build_speech,
    execute_action,
    normalize_images,
    normalize_movie,
)


CONFIGURATION = {
    "secure_base_url": "https://image.tmdb.org/t/p/",
    "poster_sizes": ["w92", "w185", "w342", "w500", "original"],
    "backdrop_sizes": ["w300", "w780", "w1280", "original"],
    "logo_sizes": ["w92", "w185", "w300", "w500", "original"],
    "profile_sizes": ["w45", "w185", "h632", "original"],
}
GENRES = {12: "Adventure", 878: "Science Fiction", 53: "Thriller"}


def _json_response(payload, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def _movie(title="Arrival", movie_id=329865):
    return {
        "id": movie_id,
        "title": title,
        "original_title": title,
        "release_date": "2016-11-11",
        "overview": "A linguist works to understand visitors from another world.",
        "runtime": 116,
        "vote_average": 7.6,
        "vote_count": 19000,
        "genre_ids": [878, 12],
        "poster_path": "/poster123.jpg",
        "backdrop_path": "/backdrop123.jpg",
    }


def test_client_prefers_bearer_and_requests_shared_proxy_chain():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _json_response({"results": []})

    client = TMDBClient(
        access_token="test-access-token",
        api_key="test-api-key",
        request_func=fake_request,
    )
    client.get("/movie/popular", {"page": 1})

    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.themoviedb.org/3/movie/popular"
    assert kwargs["headers"]["Authorization"] == "Bearer test-access-token"
    assert "api_key" not in kwargs["params"]
    assert kwargs["use_proxy"] is True
    assert kwargs["fallback_on_proxy_fail"] is True
    assert client.auth_method == "bearer"


def test_client_uses_v3_api_key_when_bearer_is_absent():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(kwargs)
        return _json_response({"results": []})

    client = TMDBClient(api_key="test-api-key", request_func=fake_request)
    client.get("/movie/popular")

    assert calls[0]["params"]["api_key"] == "test-api-key"
    assert "Authorization" not in calls[0]["headers"]
    assert client.auth_method == "api_key"


def test_configuration_rejects_non_tmdb_image_origin():
    client = TMDBClient(access_token="test-token")
    with patch.object(
        client,
        "get",
        return_value={"images": {"secure_base_url": "https://evil.example/t/p/"}},
    ):
        with pytest.raises(TMDBAPIError, match="invalid image configuration"):
            client.configuration()


def test_movie_normalization_constructs_bounded_tmdb_cdn_variants():
    movie = normalize_movie(
        _movie(),
        configuration=CONFIGURATION,
        genre_map=GENRES,
        source="search",
    )

    assert movie is not None
    assert movie["tmdb_id"] == 329865
    assert movie["genres"] == ["Science Fiction", "Adventure"]
    assert movie["poster_thumbnail"] == "https://image.tmdb.org/t/p/w342/poster123.jpg"
    assert movie["poster_url"] == "https://image.tmdb.org/t/p/w500/poster123.jpg"
    assert movie["poster_original_url"] == "https://image.tmdb.org/t/p/original/poster123.jpg"
    assert movie["tmdb_url"] == "https://www.themoviedb.org/movie/329865"


def test_image_normalization_drops_malicious_paths_and_returns_size_variants():
    movie = {"title": "Arrival", "tmdb_url": "https://www.themoviedb.org/movie/329865"}
    images = normalize_images(
        {
            "posters": [
                {
                    "file_path": "/poster123.jpg",
                    "width": 1000,
                    "height": 1500,
                    "vote_average": 5.5,
                    "vote_count": 20,
                    "iso_639_1": "en",
                },
                {
                    "file_path": "https://evil.example/not-an-image",
                    "width": 1000,
                    "height": 1500,
                    "vote_count": 999,
                },
            ]
        },
        configuration=CONFIGURATION,
        movie=movie,
        image_type="poster",
        max_results=10,
    )

    assert len(images) == 1
    assert images[0]["thumbnail"].startswith("https://image.tmdb.org/t/p/w342/")
    assert images[0]["original_url"].startswith("https://image.tmdb.org/t/p/original/")
    assert images[0]["source_url"] == movie["tmdb_url"]


def test_all_images_preserves_poster_backdrop_and_logo_variety():
    movie = {"title": "Arrival", "tmdb_url": "https://www.themoviedb.org/movie/329865"}
    images = normalize_images(
        {
            "posters": [
                {"file_path": "/poster1.jpg", "vote_count": 100},
                {"file_path": "/poster2.jpg", "vote_count": 90},
            ],
            "backdrops": [{"file_path": "/backdrop1.jpg", "vote_count": 80}],
            "logos": [{"file_path": "/logo1.png", "vote_count": 1}],
        },
        configuration=CONFIGURATION,
        movie=movie,
        image_type="all",
        max_results=3,
    )

    assert [item["image_type"] for item in images] == ["poster", "backdrop", "logo"]
    assert [item["position"] for item in images] == [1, 2, 3]


def test_all_images_round_robins_types_instead_of_filling_with_posters():
    movie = {"title": "Arrival", "tmdb_url": "https://www.themoviedb.org/movie/329865"}
    images = normalize_images(
        {
            "posters": [
                {"file_path": f"/poster{index}.jpg", "vote_count": 100 - index}
                for index in range(1, 6)
            ],
            "backdrops": [
                {"file_path": f"/backdrop{index}.jpg", "vote_count": 50 - index}
                for index in range(1, 3)
            ],
            "logos": [{"file_path": "/logo1.png", "vote_count": 1}],
        },
        configuration=CONFIGURATION,
        movie=movie,
        image_type="all",
        max_results=6,
    )

    assert [item["image_type"] for item in images] == [
        "poster",
        "backdrop",
        "logo",
        "poster",
        "backdrop",
        "poster",
    ]


def test_images_action_resolves_title_and_returns_ranked_artwork():
    client = TMDBClient(access_token="test-token")

    def fake_get(path, params=None):
        client.request_count += 1
        if path == "/configuration":
            return {"images": CONFIGURATION}
        if path == "/genre/movie/list":
            return {"genres": [{"id": key, "name": value} for key, value in GENRES.items()]}
        if path == "/search/movie":
            return {"results": [_movie()]}
        if path == "/movie/329865":
            assert params["append_to_response"] == "images"
            assert params["include_image_language"] == "en,null"
            return {
                **_movie(),
                "images": {
                    "posters": [
                        {
                            "file_path": "/poster123.jpg",
                            "width": 1000,
                            "height": 1500,
                            "vote_average": 5.4,
                            "vote_count": 50,
                            "iso_639_1": "en",
                        }
                    ],
                    "backdrops": [],
                    "logos": [],
                },
            }
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {"action": "images", "query": "Arrival", "image_type": "poster"},
        )

    assert data["movie"]["title"] == "Arrival"
    assert data["results_count"] == 1
    assert data["results"][0]["image_type"] == "poster"
    assert data["artwork_counts"] == {"poster": 1, "backdrop": 0, "logo": 0}
    assert data["artwork_types_returned"] == ["poster"]
    assert build_speech(data).endswith("1 poster.")
    assert data["attribution_notice"] == ATTRIBUTION_NOTICE
    assert data["auth_method"] == "bearer"


def test_discover_resolves_genre_names_and_preserves_filters():
    client = TMDBClient(api_key="test-api-key")
    seen_params = {}

    def fake_get(path, params=None):
        client.request_count += 1
        if path == "/configuration":
            return {"images": CONFIGURATION}
        if path == "/genre/movie/list":
            return {"genres": [{"id": key, "name": value} for key, value in GENRES.items()]}
        if path == "/discover/movie":
            seen_params.update(params or {})
            return {"page": 1, "total_pages": 1, "total_results": 1, "results": [_movie()]}
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {
                "action": "discover",
                "genres": ["Science Fiction"],
                "runtime_max": 120,
                "min_rating": 7,
                "min_votes": 500,
                "max_results": 5,
            },
        )

    assert seen_params["with_genres"] == "878"
    assert seen_params["with_runtime.lte"] == 120
    assert seen_params["vote_average.gte"] == 7.0
    assert seen_params["vote_count.gte"] == 500
    assert data["results"][0]["title"] == "Arrival"
    assert data["selection_criteria"] == {
        "genres": ["Science Fiction"],
        "runtime_max_minutes": 120,
        "minimum_rating": 7.0,
        "minimum_votes": 500,
        "sort_by": "popularity.desc",
        "provider_filters_applied": True,
        "all_returned_results_match": True,
    }
    assert "provider-applied discover filters" in build_speech(data)
    assert data["auth_method"] == "api_key"


def test_details_bundles_metadata_and_honors_result_limit():
    client = TMDBClient(access_token="test-token")

    def fake_get(path, params=None):
        client.request_count += 1
        if path == "/configuration":
            return {"images": CONFIGURATION}
        if path == "/genre/movie/list":
            return {"genres": [{"id": key, "name": value} for key, value in GENRES.items()]}
        if path == "/movie/329865":
            assert "images" in params["append_to_response"]
            return {
                **_movie(),
                "imdb_id": "tt2543164",
                "production_companies": [{"name": "FilmNation Entertainment"}],
                "images": {
                    "posters": [
                        {"file_path": f"/poster{index}.jpg", "vote_count": 10 - index}
                        for index in range(3)
                    ],
                    "backdrops": [],
                    "logos": [],
                },
                "credits": {
                    "cast": [
                        {"id": index, "name": f"Actor {index}", "character": f"Role {index}"}
                        for index in range(1, 4)
                    ],
                    "crew": [
                        {"id": index, "name": f"Crew {index}", "job": "Director", "department": "Directing"}
                        for index in range(1, 4)
                    ],
                },
                "videos": {
                    "results": [
                        {
                            "name": f"Trailer {index}",
                            "site": "YouTube",
                            "key": f"trailer{index}",
                            "type": "Trailer",
                            "official": True,
                        }
                        for index in range(1, 4)
                    ]
                },
                "external_ids": {"imdb_id": "tt2543164"},
                "release_dates": {
                    "results": [
                        {
                            "iso_3166_1": "US",
                            "release_dates": [{"type": 3, "certification": "PG-13"}],
                        }
                    ]
                },
                "keywords": {"keywords": [{"name": "language"}, {"name": "alien"}]},
                "recommendations": {"results": [_movie("Recommendation 1", 1), _movie("Recommendation 2", 2), _movie("Recommendation 3", 3)]},
                "similar": {"results": [_movie("Similar 1", 11), _movie("Similar 2", 12), _movie("Similar 3", 13)]},
            }
        raise AssertionError(f"Unexpected path: {path}")

    with patch.object(client, "get", side_effect=fake_get):
        data = execute_action(
            client,
            {"action": "details", "movie_id": 329865, "max_results": 2},
        )

    assert data["movie"]["certification"] == "PG-13"
    assert data["external_ids"]["imdb_id"] == "tt2543164"
    assert data["keywords"] == ["language", "alien"]
    assert len(data["images"]) == 2
    assert len(data["cast"]) == 2
    assert len(data["crew"]) == 2
    assert len(data["videos"]) == 2
    assert len(data["recommendations"]) == 2
    assert len(data["similar"]) == 2
    assert data["artwork_counts"] == {"poster": 2, "backdrop": 0, "logo": 0}
    assert {
        "production_details",
        "certification",
        "cast",
        "director_and_crew",
        "artwork",
    }.issubset(data["details_included"])
    assert "including cast, crew, production metadata" in build_speech(data)


def test_manifest_is_standalone_and_accepts_either_tmdb_credential():
    manifest = json.loads((ROOT / "skills" / "tmdb_movies.tool.json").read_text())

    assert manifest["proxy_policy"] == "prefer"
    assert manifest["availability"]["any_of_env"] == [
        "TMDB_ACCESS_TOKEN",
        "TMDB_API_KEY",
    ]
    assert "TRAKT_API_KEY" not in json.dumps(manifest["availability"])
    assert "images" in manifest["parameters"]["properties"]["action"]["enum"]
    assert "discover" in manifest["parameters"]["properties"]["action"]["enum"]
    assert "make one images call" in manifest["parameters"]["properties"]["action"]["description"]
    assert "do not search first" in manifest["parameters"]["properties"]["action"]["description"]
    assert "one successful discover call" in manifest["parameters"]["properties"]["action"]["description"]


def test_invalid_action_fails_before_any_network_helper_call():
    client = TMDBClient(access_token="test-token")
    with patch.object(client, "get") as get:
        with pytest.raises(TMDBAPIError, match="Unsupported action"):
            execute_action(client, {"action": "tv_search"})
    get.assert_not_called()
