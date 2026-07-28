"""Spotify playback routing regressions for podcasts and Connect devices."""

from __future__ import annotations

from skills import spotify


class LatestShowSpotify:
    def __init__(self):
        self.search_calls = []
        self.playback_calls = []

    def search(self, q, type, limit):
        self.search_calls.append({"q": q, "type": type, "limit": limit})
        assert type == "show"
        return {
            "shows": {
                "items": [{
                    "id": "jre",
                    "name": "The Joe Rogan Experience",
                    "uri": "spotify:show:jre",
                    "publisher": "Joe Rogan",
                }]
            }
        }

    def show_episodes(self, show_id, limit):
        assert show_id == "jre"
        return {
            "items": [{
                "name": "#2531 - Forrest Galante",
                "uri": "spotify:episode:2531",
            }]
        }

    def start_playback(self, **kwargs):
        self.playback_calls.append(kwargs)


class TransientDeviceSpotify:
    def __init__(self):
        self.device_calls = 0
        self.playback_calls = []

    def devices(self):
        self.device_calls += 1
        if self.device_calls == 1:
            return {"devices": []}
        return {
            "devices": [{
                "id": "office-tv-id",
                "name": "Office fire TV",
            }]
        }

    def start_playback(self, **kwargs):
        self.playback_calls.append(kwargs)


def test_play_trailing_latest_resolves_confident_show_instead_of_track(monkeypatch):
    client = LatestShowSpotify()
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: client)

    result = spotify.action_play({
        "action": "play",
        "query": "Joe Rogan Experience latest",
        "device_id": "office-tv-id",
    })

    assert result == {
        "ok": True,
        "speech": "Playing latest episode of The Joe Rogan Experience: #2531 - Forrest Galante",
        "data": {
            "uri": "spotify:episode:2531",
            "name": "#2531 - Forrest Galante",
            "show": "The Joe Rogan Experience",
            "publisher": "Joe Rogan",
            "type": "episode",
        },
    }
    assert client.search_calls == [{
        "q": "Joe Rogan Experience",
        "type": "show",
        "limit": 5,
    }]
    assert client.playback_calls == [{
        "uris": ["spotify:episode:2531"],
        "device_id": "office-tv-id",
    }]


def test_named_device_retry_stays_inside_one_playback_action(monkeypatch):
    client = TransientDeviceSpotify()
    sleeps = []
    monkeypatch.setattr(spotify, "get_spotify_client", lambda: client)
    monkeypatch.setattr(spotify.time, "sleep", sleeps.append)

    result = spotify.action_play({
        "action": "play",
        "query": "spotify:episode:2531",
        "device": "Office Fire TV",
    })

    assert result["ok"] is True
    assert client.device_calls == 2
    assert sleeps == [spotify.SPOTIFY_DEVICE_RETRY_SECONDS]
    assert client.playback_calls == [{
        "uris": ["spotify:episode:2531"],
        "device_id": "office-tv-id",
    }]
