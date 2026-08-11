from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))

from trakt_account import (  # noqa: E402
    MAX_WATCHED_PAGES,
    TraktAccountClient,
    TraktAccountError,
    execute_action,
)


class FakeClient:
    def __init__(self, payload, pagination=None):
        self.payload = payload
        self.pagination = pagination or {"page": 1, "page_count": 2, "item_count": 30}
        self.calls = []
        self.request_count = 0

    def get(self, path, params=None):
        self.calls.append((path, params))
        self.request_count += 1
        return self.payload, self.pagination


class RoutedFakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.request_count = 0

    def get(self, path, params=None):
        self.calls.append((path, params))
        self.request_count += 1
        expected_path, payload, pagination = self.responses.pop(0)
        assert path == expected_path
        return payload, pagination


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_manifest_is_availability_gated_and_strictly_read_only():
    manifest = json.loads((ROOT / "skills" / "trakt_account.tool.json").read_text())
    assert manifest["availability"]["all_of_env"] == [
        "TRAKT_API_KEY",
        "TRAKT_CLIENT_SECRET",
        "TRAKT_REDIRECT_URI",
    ]
    assert manifest["availability"]["config_files"] == ["data/.trakt_oauth.json"]
    assert manifest["permissions"] == {
        "dangerous": False,
        "bash": False,
        "network": True,
        "filesystem": False,
        "auto_approve": True,
    }
    action_names = set(manifest["parameters"]["properties"]["action"]["enum"])
    assert not action_names & {"add", "remove", "rate", "create", "update", "delete"}
    public_candidates = manifest["parameters"]["properties"]["public_candidates"]
    assert public_candidates["maxItems"] == 20
    assert public_candidates["items"]["required"] == ["title"]


def test_movie_night_context_infers_filters_and_marks_account_data():
    client = FakeClient(
        [
            {
                "title": "Arrival",
                "year": 2016,
                "runtime": 116,
                "rating": 8.0,
                "ids": {"slug": "arrival-2016", "trakt": 1},
            }
        ]
    )
    payload = execute_action(
        client,
        {
            "action": "movie_night_context",
            "request": "thoughtful science fiction under two hours",
            "max_results": 8,
            "ignore_watched": False,
        },
    )
    assert client.calls[0][0] == "/recommendations/movies/"
    assert client.calls[0][1]["genres"] == "science-fiction"
    assert client.calls[0][1]["runtimes"] == "1-120"
    assert payload["candidates"][0]["title"] == "Arrival"
    assert payload["candidates"][0]["media_type"] == "movie"
    assert payload["oauth_used"] is True
    assert payload["account_data"] is True
    assert payload["read_only"] is True
    assert payload["watched_filter_applied"] is False


def test_movie_night_context_filters_public_and_account_candidates_across_watched_pages():
    client = RoutedFakeClient(
        [
            (
                "/recommendations/movies/",
                [
                    {"title": "Alita: Battle Angel", "year": 2019, "ids": {"trakt": 2}},
                    {"title": "Moon", "year": 2009, "ids": {"trakt": 3}},
                ],
                {"page": 1, "page_count": 1, "item_count": 2},
            ),
            (
                "/sync/watched/movies",
                [
                    {
                        "last_watched_at": "private",
                        "movie": {
                            "title": "Alita: Battle Angel",
                            "year": 2019,
                            "ids": {"trakt": 2},
                        },
                    }
                ],
                {"page": 1, "page_count": 2, "item_count": 2, "limit": 100},
            ),
            (
                "/sync/watched/movies",
                [
                    {
                        "last_watched_at": "private",
                        "movie": {"title": "Arrival", "year": 2016, "ids": {"trakt": 1}},
                    }
                ],
                {"page": 2, "page_count": 2, "item_count": 2, "limit": 100},
            ),
        ]
    )
    payload = execute_action(
        client,
        {
            "action": "movie_night_context",
            "request": "thoughtful science fiction",
            "max_results": 8,
            "ignore_watched": True,
            "public_candidates": [
                {
                    "title": "Alita: Battle Angel",
                    "year": 2019,
                    "ids": {"trakt": 2},
                    "related_to": ["The Matrix"],
                },
                {
                    "title": "Ghost in the Shell",
                    "year": 1995,
                    "ids": {"trakt": 4},
                    "related_to": ["The Matrix"],
                    "match_score": 10.5,
                },
            ],
        },
    )

    assert [item["title"] for item in payload["eligible_public_candidates"]] == [
        "Ghost in the Shell"
    ]
    assert payload["eligible_public_candidates"][0]["related_to"] == ["The Matrix"]
    assert payload["eligible_public_candidates"][0]["match_score"] == 10.5
    assert [item["title"] for item in payload["candidates"]] == ["Moon"]
    assert [item["title"] for item in payload["eligible_candidates"]] == [
        "Ghost in the Shell",
        "Moon",
    ]
    assert payload["enrichment_title"] == "Ghost in the Shell"
    assert payload["enrichment_year"] == 1995
    assert payload["second_eligible_title"] == "Moon"
    assert payload["watched_filter_applied"] is True
    assert payload["watched_items_checked"] == 2
    assert payload["watched_pages_checked"] == 2
    assert payload["watched_public_excluded_count"] == 1
    assert payload["watched_account_excluded_count"] == 1
    assert payload["watched_excluded_count"] == 2
    assert payload["api_requests"] == 3
    assert [params["page"] for path, params in client.calls if path == "/sync/watched/movies"] == [
        1,
        2,
    ]
    serialized = json.dumps(payload)
    assert "Alita: Battle Angel" not in serialized
    assert "last_watched_at" not in serialized


def test_tv_night_context_filters_watched_shows_and_preserves_show_semantics():
    client = RoutedFakeClient(
        [
            (
                "/recommendations/shows/",
                [
                    {"title": "Dark", "year": 2017, "runtime": 60, "ids": {"trakt": 11}},
                    {"title": "Severance", "year": 2022, "runtime": 50, "ids": {"trakt": 12}},
                ],
                {"page": 1, "page_count": 1, "item_count": 2},
            ),
            (
                "/sync/watched/shows",
                [{"show": {"title": "Dark", "year": 2017, "ids": {"trakt": 11}}}],
                {"page": 1, "page_count": 1, "item_count": 1, "limit": 100},
            ),
        ]
    )
    payload = execute_action(
        client,
        {
            "action": "tv_night_context",
            "request": "a thoughtful mystery",
            "public_candidates": [
                {"title": "Dark", "year": 2017, "ids": {"trakt": 11}},
                {"title": "The Expanse", "year": 2015, "ids": {"trakt": 13}},
            ],
        },
    )

    assert [item["title"] for item in payload["eligible_public_candidates"]] == ["The Expanse"]
    assert [item["title"] for item in payload["candidates"]] == ["Severance"]
    assert all(item["media_type"] == "show" for item in payload["eligible_candidates"])
    assert payload["candidates"][0]["episode_runtime_minutes"] == 50
    assert payload["watched_excluded_count"] == 2
    assert payload["runtime_scope"] == "typical episode runtime"


def test_night_context_skips_watched_sync_when_filter_disabled():
    client = RoutedFakeClient(
        [
            (
                "/recommendations/movies/",
                [],
                {"page": 1, "page_count": 1, "item_count": 0},
            ),
        ]
    )
    payload = execute_action(
        client,
        {
            "action": "movie_night_context",
            "ignore_watched": False,
            "public_candidates": [{"title": "Arrival", "year": 2016, "ids": {"trakt": 1}}],
        },
    )
    assert payload["watched_filter_applied"] is False
    assert payload["watched_items_checked"] == 0
    assert payload["watched_pages_checked"] == 0
    assert payload["eligible_public_candidates"][0]["title"] == "Arrival"
    assert len(client.calls) == 1


def test_night_context_fails_closed_when_watched_sync_exceeds_page_bound():
    client = RoutedFakeClient(
        [
            (
                "/recommendations/movies/",
                [],
                {"page": 1, "page_count": 1, "item_count": 0},
            ),
            (
                "/sync/watched/movies",
                [],
                {"page": 1, "page_count": MAX_WATCHED_PAGES + 1, "item_count": 2500},
            ),
        ]
    )
    with pytest.raises(TraktAccountError, match="bounded page limit") as raised:
        execute_action(client, {"action": "movie_night_context", "ignore_watched": True})
    assert raised.value.endpoint == "/sync/watched/movies"


def test_night_context_clears_enrichment_lead_when_every_candidate_is_watched():
    client = RoutedFakeClient(
        [
            (
                "/recommendations/movies/",
                [],
                {"page": 1, "page_count": 1, "item_count": 0},
            ),
            (
                "/sync/watched/movies",
                [{"movie": {"title": "Arrival", "year": 2016, "ids": {"trakt": 1}}}],
                {"page": 1, "page_count": 1, "item_count": 1},
            ),
        ]
    )
    payload = execute_action(
        client,
        {
            "action": "movie_night_context",
            "public_candidates": [{"title": "Arrival", "year": 2016, "ids": {"trakt": 1}}],
        },
    )
    assert payload["eligible_candidates"] == []
    assert payload["enrichment_title"] == "not returned"
    assert payload["enrichment_year"] == "not returned"


def test_watch_history_preserves_safe_account_metadata_and_pagination():
    client = FakeClient(
        [
            {
                "watched_at": "2026-01-01T00:00:00Z",
                "id": 44,
                "movie": {"title": "Arrival", "year": 2016, "ids": {"slug": "arrival-2016"}},
            }
        ]
    )
    payload = execute_action(client, {"action": "history", "media_type": "movies"})
    assert client.calls[0][0] == "/users/me/history/movies"
    assert payload["results"][0]["watched_at"] == "2026-01-01T00:00:00Z"
    assert payload["results"][0]["history_id"] == 44
    assert payload["pagination"]["item_count"] == 30


def test_personal_lists_are_normalized_without_raw_payload():
    client = FakeClient(
        [
            {
                "name": "Mind benders",
                "description": "Favorites",
                "privacy": "private",
                "share_link": "https://trakt.tv/users/me/lists/mind-benders",
                "ids": {"trakt": 9, "slug": "mind-benders"},
                "item_count": 12,
            }
        ]
    )
    payload = execute_action(client, {"action": "personal_lists"})
    assert payload["results"][0]["name"] == "Mind benders"
    assert payload["results"][0]["privacy"] == "private"
    assert payload["results"][0]["item_count"] == 12


def test_favorites_rejects_unsupported_media_type():
    with pytest.raises(TraktAccountError, match="movies or shows"):
        execute_action(FakeClient([]), {"action": "favorites", "media_type": "episodes"})


def test_client_refreshes_once_after_401_without_exposing_token():
    responses = [FakeResponse(401, {}), FakeResponse(200, [])]
    credential_calls = []
    request_headers = []

    def credentials(**kwargs):
        credential_calls.append(kwargs["force_refresh"])
        token = "stale-token" if not kwargs["force_refresh"] else "fresh-token"
        return SimpleNamespace(access_token=token)

    def request(*_args, **kwargs):
        request_headers.append(kwargs["headers"])
        return responses.pop(0)

    payload, pagination = TraktAccountClient(
        "client", "secret", "oob", request_func=request, credential_func=credentials
    ).get("/users/settings")
    assert payload == []
    assert pagination == {}
    assert credential_calls == [False, True]
    assert request_headers[0]["Authorization"] == "Bearer stale-token"
    assert request_headers[1]["Authorization"] == "Bearer fresh-token"


@pytest.mark.parametrize(
    ("status", "field"),
    [(426, "vip_required"), (420, "vip_enhanced_limit")],
)
def test_vip_errors_use_safe_structured_headers(status, field):
    def credentials(**_kwargs):
        return SimpleNamespace(access_token="secret-token")

    def request(*_args, **_kwargs):
        return FakeResponse(
            status,
            {"access_token": "secret-token"},
            {
                "X-Upgrade-URL": "https://trakt.tv/vip",
                "X-VIP-User": "yes",
                "X-Account-Limit": "1000",
            },
        )

    client = TraktAccountClient(
        "client", "secret", "oob", request_func=request, credential_func=credentials
    )
    with pytest.raises(TraktAccountError) as raised:
        client.get("/users/me/lists")
    assert getattr(raised.value, field) is True
    assert raised.value.upgrade_url == "https://trakt.tv/vip"
    assert "secret-token" not in str(raised.value)
