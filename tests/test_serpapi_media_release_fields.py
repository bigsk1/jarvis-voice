"""Recent provider metadata survives media and live-game normalization without paid calls."""

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from tool_child_environment import parse_child_environment_policy, restrict_child_environment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def media(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "skills"))
    return tuple(importlib.import_module(name) for name in (
        "serpapi_youtube", "serpapi_youtube_search", "serpapi_google_sports",
    ))


def video_payload():
    return {
        "video_id": "dQw4w9WgXcQ", "title": "Fixture video",
        "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "channel": {"name": "Fixture channel", "channel_id": "UCfixture",
                    "link": "https://www.youtube.com/@fixture"},
        "length": "1:00", "length_seconds": 60, "comment_count": "0", "category": "Music",
        "keywords": ["fixture"], "age_restricted": False, "made_with_ai": True,
        "chapters": [{"title": "Opening", "thumbnail": "https://i.ytimg.com/chapter.jpg",
                      "time_start": 0, "auto_generated": True}],
        "music": [{"title": "Song", "artist": "Artist", "album": "Album",
                   "thumbnail": "https://i.ytimg.com/music.jpg"}],
    }


def supplemental_payload():
    return {
        "posts_results": [{
            "post_id": "UgFixture", "link": "https://www.youtube.com/post/UgFixture",
            "text": "A useful community update.", "published_date": "1 day ago",
            "votes": "0", "extracted_votes": 0,
            "author": {"name": "Author", "channel_id": "UCauthor",
                       "link": "https://www.youtube.com/@author", "verified": False},
            "attachment": {"type": "video", "video_id": "dQw4w9WgXcQ",
                           "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        }],
        "featured_panel": {"type": "channel", "channel_id": "UCfixture", "title": "Fixture channel",
                           "handle": "@fixture", "videos": [video_payload()]},
    }


def test_video_metadata_keeps_labels_identity_chapters_music_and_existing_fields(media):
    video, _, _ = media
    payload = video_payload()
    payload["related_videos"] = [video_payload()]
    result = video.normalize_video_data(payload, "dQw4w9WgXcQ")
    for key in ("length_seconds", "comment_count", "category", "keywords", "age_restricted", "made_with_ai"):
        assert result[key] == payload[key]
    assert result["channel_id"] == "UCfixture"
    assert result["related_videos"][0]["channel_id"] == "UCfixture"
    assert result["duration"] == "1:00"
    assert result["chapters"] == payload["chapters"]
    assert result["music"] == payload["music"]
    assert result["chapters_truncated"] is result["music_truncated"] is False


def test_video_optional_flags_stay_unknown_and_invalid_duration_does_not_become_zero(media):
    video, _, _ = media
    result = video.normalize_video_data({"length_seconds": True, "age_restricted": "false"}, "fixture")
    assert result["length_seconds"] is None
    assert result["age_restricted"] is result["made_with_ai"] is None


def test_video_metadata_caps_preserve_complete_urls_and_mark_omissions(media):
    video, _, _ = media
    payload = video_payload()
    payload["chapters"] *= 50
    payload["music"] *= 20
    result = video.normalize_video_data(payload, "fixture")
    assert 0 < len(result["chapters"]) <= 24
    assert 0 < len(result["music"]) <= 8
    assert len(json.dumps(result["chapters"], ensure_ascii=False)) <= 6000
    assert len(json.dumps(result["music"], ensure_ascii=False)) <= 4000
    assert result["chapters"][0]["thumbnail"] == payload["chapters"][0]["thumbnail"]
    assert result["chapters_truncated"] is result["music_truncated"] is True


def test_video_chapters_reject_nonfinite_timestamps_and_keep_false_and_zero(media):
    video, _, _ = media
    result = video.normalize_video_data({"chapters": [
        {"title": "First", "time_start": 0, "auto_generated": False},
        {"title": "Unknown timestamp", "time_start": float("nan")},
    ]}, "fixture")
    assert result["chapters"][0] == {"title": "First", "time_start": 0, "auto_generated": False}
    assert "time_start" not in result["chapters"][1]
    json.dumps(result, allow_nan=False)


def test_search_video_rows_keep_stable_ids_and_automatic_chapters(media):
    _, search, _ = media
    result = search.normalize_video_results({"video_results": [video_payload()]}, 5)[0]
    assert result["channel_id"] == "UCfixture"
    assert result["chapters"][0]["time_start"] == 0
    assert result["chapters"][0]["auto_generated"] is True


def test_search_posts_and_featured_panel_keep_distinct_identities_links_and_zero(media):
    _, search, _ = media
    result = search.normalize_supplemental_results(supplemental_payload())
    post = result["posts_results"][0]
    assert post["post_id"] == "UgFixture"
    assert post["url"] == "https://www.youtube.com/post/UgFixture"
    assert post["author"]["channel_id"] == "UCauthor"
    assert post["author"]["url"] == "https://www.youtube.com/@author"
    assert post["author"]["verified"] is False
    assert post["extracted_votes"] == 0
    assert post["attachment"]["url"].endswith("dQw4w9WgXcQ")
    assert result["featured_panel"]["videos"][0]["channel_id"] == "UCfixture"
    assert result["posts_results_count"] == result["provider_posts_results_count"] == 1
    assert result["posts_results_truncated"] is result["featured_panel_truncated"] is False


def test_documented_search_post_shelves_flatten_posts_and_count_posts_before_the_cap(media):
    # https://serpapi.com/youtube-posts-results: positions belong to both shelf and post.
    _, search, _ = media
    post = supplemental_payload()["posts_results"][0]
    source = {"posts_results": [
        {"position_on_page": 5, "posts": [{**post, "position": 1, "comments_count": "0", "extracted_comments_count": 0}]},
        {"position_on_page": 8, "posts": [{**post, "position": position} for position in range(1, 7)]},
    ]}
    result = search.normalize_supplemental_results(source)
    assert result["provider_posts_results_count"] == 7
    assert result["posts_results_count"] == len(result["posts_results"]) == 5
    assert result["posts_results_truncated"] is True
    first, second = result["posts_results"][:2]
    assert first["post_id"] == post["post_id"] and first["url"] == post["link"]
    assert first["position"] == 1 and first["position_on_page"] == 5
    assert first["comments_count"] == "0" and first["extracted_comments_count"] == 0
    assert second["position"] == 1 and second["position_on_page"] == 8
    assert second["author"]["url"] == post["author"]["link"]


def test_empty_documented_post_shelf_does_not_create_a_fake_community_post(media):
    _, search, _ = media
    result = search.normalize_supplemental_results({"posts_results": [{"position_on_page": 5, "posts": []}]})
    assert result["posts_results"] == []
    assert result["posts_results_count"] == result["provider_posts_results_count"] == 0
    assert result["posts_results_truncated"] is False


@pytest.mark.parametrize("panel_type,identity,value", [
    ("channel", "channel_id", "UCBJycsmduvYEL83R_U4JriQ"),
    ("playlist", "playlist_id", "OLAK5uy_m2pWyg-txDMGdNNiHtjorZVRbrVg_Ihxo"),
    ("show", "show_id", "SCxoxXLn_0TfdvIVbVWIMdfw"),
])
def test_documented_featured_panel_identity_and_verified_false_are_preserved(media, panel_type, identity, value):
    # https://serpapi.com/youtube-featured-panel: album and show IDs have distinct keys.
    _, search, _ = media
    panel = {"type": panel_type, identity: value, "title": "Fixture panel", "verified": False,
             "link": "https://www.youtube.com/playlist?list=fixture", "videos": [video_payload()]}
    result = search.normalize_supplemental_results({"featured_panel": panel})["featured_panel"]
    assert result[identity] == value and result["verified"] is False
    assert result["url"] == panel["link"]
    assert result["videos"][0]["video_id"] == "dQw4w9WgXcQ"


def test_search_supplements_are_bounded_without_silently_cutting_links(media):
    _, search, _ = media
    payload = supplemental_payload()
    payload["posts_results"] *= 20
    payload["posts_results"][0]["text"] = "x" * 10000
    payload["featured_panel"]["videos"] *= 20
    result = search.normalize_supplemental_results(payload)
    assert 0 < len(result["posts_results"]) <= 5
    assert len(result["posts_results"][0]["text"]) <= 1200
    assert len(json.dumps(result["posts_results"], ensure_ascii=False)) <= 8000
    assert len(json.dumps(result["featured_panel"], ensure_ascii=False)) <= 6000
    assert result["posts_results_truncated"] is result["featured_panel_truncated"] is True
    assert result["posts_results"][0]["url"] == payload["posts_results"][0]["link"]


def test_search_supplement_budgets_count_json_escaping_without_an_unbounded_loop(media):
    _, search, _ = media
    payload = supplemental_payload()
    payload["posts_results"][0].update(text="\x00" * 1200, link="https://example.test/" + "a" * 1800)
    payload["featured_panel"].update(link="\x00" * 2000, thumbnail="\x00" * 2000)
    result = search.normalize_supplemental_results(payload)
    assert len(json.dumps(result["posts_results"], ensure_ascii=False)) <= 8000
    assert len(json.dumps(result["featured_panel"], ensure_ascii=False)) <= 6000
    assert result["posts_results_truncated"] is result["featured_panel_truncated"] is True


@pytest.mark.parametrize("section", ["posts_results", "featured_panel"])
def test_search_main_reports_supplements_when_no_videos_exist(media, monkeypatch, capsys, section):
    _, search, _ = media
    payload = {section: supplemental_payload()[section]}
    request = Mock(return_value=payload)
    monkeypatch.setattr(search, "request_serpapi", request)
    monkeypatch.setattr(search, "load_config", lambda: None)
    monkeypatch.setattr(search.sys, "argv", ["serpapi_youtube_search.py", '{"search_query":"fixture"}'])
    assert search.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True and result["data"]["results_count"] == 0
    assert "No YouTube videos found" not in result["speech"]
    assert "community post" in result["speech"] or "featured panel" in result["speech"]
    assert result["data"][section]
    request.assert_called_once()


@pytest.mark.parametrize("entity", ["game", "team", "league"])
def test_live_football_state_preserves_game_and_team_locations(media, entity):
    _, _, sports = media
    game = {"title": "Fixture matchup", "down_and_distance": "1st & 10 at MIA 33",
            "teams": [{"name": "Patriots", "timeouts_remaining": 0, "possession": False},
                      {"name": "Dolphins", "timeouts_remaining": 1, "possession": True}]}
    root = {"info": game} if entity == "game" else {"game_groups": [{"games": [game]}]}
    rows, _kind, _extras = sports.extract_results({f"{entity}_results": root}, entity_type=entity, tab=None)
    assert rows[0]["down_and_distance"] == game["down_and_distance"]
    assert rows[0]["teams"][0]["timeouts_remaining"] == 0
    assert rows[0]["teams"][0]["possession"] is False
    assert rows[0]["teams"][1]["possession"] is True


@pytest.mark.parametrize("name", ["serpapi_youtube", "serpapi_youtube_search", "serpapi_google_sports"])
def test_changed_media_tools_restrict_child_settings_and_keep_transcript_stash_settings(name, tmp_path):
    manifest = json.loads((ROOT / "skills" / f"{name}.tool.json").read_text())
    policy = parse_child_environment_policy(manifest["child_environment"], manifest["availability"])
    assert policy is not None
    expected = {"SERP_API_KEY"}
    if name == "serpapi_youtube":
        expected |= {"STASH_DIR", "STASH_SOURCE_ARTIFACT_TTL_DAYS"}
    assert policy == frozenset(expected)
    source = {"SERP_API_KEY": "test-only", "UNRELATED_SECRET": "not-for-this-tool",
              "STASH_DIR": str(tmp_path / "stash"), "STASH_SOURCE_ARTIFACT_TTL_DAYS": "60"}
    child = restrict_child_environment(source, policy, home=str(tmp_path), proxy_policy="off")
    assert "UNRELATED_SECRET" not in child
    assert child["SERP_API_KEY"] == "test-only"
    if name == "serpapi_youtube":
        assert child["STASH_DIR"] == source["STASH_DIR"]
        assert child["STASH_SOURCE_ARTIFACT_TTL_DAYS"] == "60"
