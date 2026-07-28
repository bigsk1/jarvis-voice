"""Spotify followed-artist action regressions."""

from __future__ import annotations

import json
from pathlib import Path

from skills import spotify


ROOT = Path(__file__).resolve().parents[1]


class FakeSpotify:
    def __init__(self, pages):
        self.pages = pages
        self.followed_calls = []
        self.search_calls = []

    def current_user_followed_artists(self, limit=20, after=None):
        self.followed_calls.append({"limit": limit, "after": after})
        return self.pages[after]

    def current_user_top_artists(self, limit=3, time_range="short_term"):
        return {"items": []}

    def search(self, q, type, limit):
        self.search_calls.append({"q": q, "type": type, "limit": limit})
        return {
            "playlists": {
                "items": [
                    {
                        "name": f"{q} Radio",
                        "uri": "spotify:playlist:radio",
                        "owner": {"display_name": "Spotify"},
                    }
                ]
            }
        }


def _artist(name: str, artist_id: str) -> dict:
    return {
        "id": artist_id,
        "name": name,
        "uri": f"spotify:artist:{artist_id}",
        "external_urls": {"spotify": f"https://open.spotify.com/artist/{artist_id}"},
        "genres": ["alternative metal", "rock"],
        "followers": {"total": 1234},
        "popularity": 72,
    }


def test_followed_lists_artists_with_compact_playable_references(monkeypatch):
    client = FakeSpotify({
        None: {
            "artists": {
                "items": [_artist("Helmet", "helmet"), _artist("Primus", "primus")],
                "total": 2,
                "next": None,
                "cursors": {"after": None},
            }
        }
    })
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: client)

    result = spotify.action_followed({"action": "followed", "limit": 2})

    assert result["ok"] is True
    assert result["data"]["count"] == 2
    assert result["data"]["total_followed"] == 2
    assert result["data"]["has_more"] is False
    assert result["data"]["artists"][0] == {
        "id": "helmet",
        "name": "Helmet",
        "uri": "spotify:artist:helmet",
        "spotify_url": "https://open.spotify.com/artist/helmet",
        "genres": ["alternative metal", "rock"],
        "followers": 1234,
        "popularity": 72,
    }
    assert client.followed_calls == [{"limit": 2, "after": None}]


def test_followed_query_searches_across_cursor_pages(monkeypatch):
    client = FakeSpotify({
        None: {
            "artists": {
                "items": [_artist("Helmet", "helmet")],
                "total": 2,
                "next": "next-page",
                "cursors": {"after": "helmet"},
            }
        },
        "helmet": {
            "artists": {
                "items": [_artist("Primus", "primus")],
                "total": 2,
                "next": None,
                "cursors": {"after": None},
            }
        },
    })
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: client)

    result = spotify.action_followed({
        "action": "followed",
        "query": "prim",
        "limit": 5,
    })

    assert result["ok"] is True
    assert result["data"]["query"] == "prim"
    assert [item["name"] for item in result["data"]["artists"]] == ["Primus"]
    assert client.followed_calls == [
        {"limit": 50, "after": None},
        {"limit": 50, "after": "helmet"},
    ]


def test_suggest_falls_back_to_followed_artists_when_top_history_is_empty(monkeypatch):
    client = FakeSpotify({
        None: {
            "artists": {
                "items": [_artist("Helmet", "helmet")],
                "total": 1,
                "next": None,
                "cursors": {"after": None},
            }
        }
    })
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: client)

    result = spotify.action_suggest({"action": "suggest"})

    assert result["ok"] is True
    assert result["data"]["suggestions"][0]["why"] == "Based on followed artist Helmet"
    assert client.search_calls[0]["q"] == "Helmet radio"


def test_spotify_manifest_exposes_followed_and_bounded_list_limit():
    manifest = json.loads((ROOT / "skills" / "spotify.tool.json").read_text())
    action = manifest["parameters"]["properties"]["action"]
    limit = manifest["parameters"]["properties"]["limit"]

    assert "followed" in action["enum"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == 50
