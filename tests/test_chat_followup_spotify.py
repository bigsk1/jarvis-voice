"""Web conversation follow-up extraction for Spotify's varied payload shapes."""

from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server_package_utils import load_server_package


load_server_package("jarvis_web_spotify_test_server", ROOT / "jarvis-web" / "server")

from jarvis_web_spotify_test_server.services.followup_extractor import extract_followup_data


def _trace(action: str, **arguments) -> list[dict]:
    return [{
        "tool": "spotify",
        "ok": True,
        "arguments": {"action": action, **arguments},
    }]


def test_followed_payload_keeps_query_and_artist_candidates_for_later_turns():
    data = {
        "spotify": {
            "ok": True,
            "data": {
                "artists": [{
                    "id": "primus",
                    "name": "Primus",
                    "uri": "spotify:artist:primus",
                    "spotify_url": "https://open.spotify.com/artist/primus",
                    "genres": ["funk metal", "alternative metal"],
                    "followers": 1234,
                    "popularity": 73,
                }],
                "count": 1,
                "total_followed": 42,
                "query": "prim",
                "has_more": False,
            },
        },
        "_tool_trace": _trace("followed", query="prim", limit=5),
    }

    result = extract_followup_data(data)["spotify"]

    assert result["action"] == "followed"
    assert result["query"] == "prim"
    assert result["limit"] == 5
    assert result["count"] == 1
    assert result["total_followed"] == 42
    assert result["candidate_source"] == "artists"
    assert result["candidates"] == [{
        "id": "primus",
        "name": "Primus",
        "uri": "spotify:artist:primus",
        "spotify_url": "https://open.spotify.com/artist/primus",
        "genres": ["funk metal", "alternative metal"],
        "followers": 1234,
        "popularity": 73,
    }]


def test_spotify_followup_adapter_preserves_varied_list_payloads():
    cases = [
        (
            "top",
            {"items": [{"name": "Jerry Was a Race Car Driver", "artist": "Primus",
                        "uri": "spotify:track:jerry"}], "type": "tracks"},
            "items",
            {"name": "Jerry Was a Race Car Driver", "artist": "Primus",
             "uri": "spotify:track:jerry"},
        ),
        (
            "devices",
            {"devices": [{"id": "office", "name": "Office Echo", "type": "Speaker",
                          "active": True, "volume": 60}], "count": 1},
            "devices",
            {"id": "office", "name": "Office Echo", "type": "Speaker",
             "active": True, "volume": 60},
        ),
        (
            "episodes",
            {"show": "Heavyweight", "show_uri": "spotify:show:heavy",
             "episodes": [{"number": 1, "name": "The Follow-Up", "date": "2026-07-01",
                           "duration_min": 52, "uri": "spotify:episode:one"}]},
            "episodes",
            {"number": 1, "name": "The Follow-Up", "date": "2026-07-01",
             "duration_min": 52, "uri": "spotify:episode:one"},
        ),
        (
            "suggest",
            {"suggestions": [{"number": 1, "name": "Primus Radio", "type": "playlist",
                              "uri": "spotify:playlist:radio", "why": "Based on Primus"}]},
            "suggestions",
            {"number": 1, "name": "Primus Radio", "type": "playlist",
             "uri": "spotify:playlist:radio", "why": "Based on Primus"},
        ),
    ]

    for action, payload, source, candidate in cases:
        result = extract_followup_data({
            "spotify": {"ok": True, "data": payload},
            "_tool_trace": _trace(action),
        })["spotify"]

        assert result["action"] == action
        assert result["candidate_source"] == source
        assert result["candidates"][0] == candidate


def test_spotify_scalar_playback_payload_stays_available_to_followups():
    result = extract_followup_data({
        "spotify": {
            "ok": True,
            "data": {
                "playing": True,
                "name": "Unsung",
                "artist": "Helmet",
                "album": "Meantime",
                "progress": "1:04",
                "duration": "3:57",
                "device": "Office Echo",
            },
        },
        "_tool_trace": _trace("current"),
    })["spotify"]

    assert result == {
        "action": "current",
        "playing": True,
        "name": "Unsung",
        "artist": "Helmet",
        "album": "Meantime",
        "progress": "1:04",
        "duration": "3:57",
        "device": "Office Echo",
    }
