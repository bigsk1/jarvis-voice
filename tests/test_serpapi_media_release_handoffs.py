"""Updated media/sports evidence remains usable in saved chats and existing cards."""

from __future__ import annotations

import importlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / "jarvis-web/client/js"
load_server_package("media_release_handoff_server", ROOT / "jarvis-web/server")
followup = importlib.import_module("media_release_handoff_server.services.followup_extractor")


@pytest.fixture
def media(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "skills"))
    return tuple(importlib.import_module(name) for name in (
        "serpapi_youtube", "serpapi_youtube_search", "serpapi_google_sports",
    ))


def search_payload(search):
    provider = {
        "video_results": [{
            "video_id": "fixture", "title": "Fixture video", "link": "https://www.youtube.com/watch?v=fixture",
            "channel": {"name": "Channel", "channel_id": "UCfixture"},
            "chapters": [{"title": "Opening", "time_start": 0, "auto_generated": True}],
        }],
        "posts_results": [{"position_on_page": 5, "posts": [{
            "position": 1,
            "post_id": "UgFixture", "link": "https://www.youtube.com/post/UgFixture",
            "text": "Useful update <script>inert()</script>", "extracted_votes": 0,
            "comments_count": "0", "extracted_comments_count": 0,
            "author": {"name": "Post author", "channel_id": "UCauthor", "verified": False},
            "attachment": {"type": "video", "video_id": "attached",
                           "title": "Attached video", "link": "https://www.youtube.com/watch?v=attached",
                           "thumbnail": "https://images.example/post-attachment.jpg"},
        }]}],
        "featured_panel": {"type": "channel", "channel_id": "UCfeatured", "verified": False, "title": "Featured author",
                           "thumbnail": "https://images.example/panel.jpg", "videos": [{
                               "video_id": "featured", "title": "Featured video",
                               "link": "https://www.youtube.com/watch?v=featured",
                               "channel": {"name": "Featured author", "channel_id": "UCfeatured"},
                           }]},
    }
    return {"search_query": "fixture", "results_count": 1,
            "results": search.normalize_video_results(provider, 5),
            **search.normalize_supplemental_results(provider)}


def extract(name, value):
    result = followup.extract_followup_data({name: json.loads(json.dumps(value, allow_nan=False))})
    assert isinstance(result, dict)
    return result[name]


def render(data, tools_used=None):
    paths = [str(JS_ROOT / name) for name in (
        "structured-results-shopping.js", "structured-results-search.js",
        "structured-results-local-travel.js", "structured-results.js",
    )]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, console, window: {}, Utils: {
  escapeHtml,
  safeHttpUrlForAttr: value => {
    try { const url = new URL(String(value)); return ['http:', 'https:'].includes(url.protocol) ? escapeHtml(url.href) : ''; }
    catch (_) { return ''; }
  },
}};
vm.createContext(sandbox);
vm.runInContext(PATHS.map(path => fs.readFileSync(path, 'utf8')).join('\n'), sandbox);
const renderer = sandbox.window.structuredResultsRenderer;
process.stdout.write(JSON.stringify({
  html: renderer.render(DATA, {}, TOOL_NAMES),
  youtube: DATA.serpapi_youtube_search ? renderer._adaptYouTubeSearch(DATA.serpapi_youtube_search) : null,
}));
""".replace("PATHS", json.dumps(paths)).replace("DATA", json.dumps(data)).replace("TOOL_NAMES", json.dumps(tools_used or []))
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("wrapped", [False, True])
def test_search_followups_keep_video_post_panel_identity_and_survive_saved_reprojection(media, wrapped):
    _, search, _ = media
    source = search_payload(search)
    untouched = deepcopy(source)
    result = extract("serpapi_youtube_search", {"ok": True, "data": source} if wrapped else source)
    assert result["candidates"][0]["channel_id"] == "UCfixture"
    assert result["candidates"][0]["chapters"][0] == source["results"][0]["chapters"][0]
    post = result["posts_results"][0]
    assert post["post_id"] == "UgFixture" and post["extracted_votes"] == 0
    assert post["position"] == 1 and post["position_on_page"] == 5
    assert post["comments_count"] == "0" and post["extracted_comments_count"] == 0
    assert post["author"]["channel_id"] == "UCauthor" and post["author"]["verified"] is False
    assert post["url"].endswith("/post/UgFixture")
    assert post["attachment"]["url"].endswith("v=attached")
    assert result["featured_panel"]["videos"][0]["channel_id"] == "UCfeatured"
    assert result["featured_panel"]["channel_id"] == "UCfeatured" and result["featured_panel"]["verified"] is False
    assert result["supplemental_note"] == source["supplemental_note"]
    restored = extract("serpapi_youtube_search", result)
    for key in ("candidates", "posts_results", "featured_panel", "supplemental_note"):
        assert restored[key] == result[key]
    assert source == untouched


@pytest.mark.parametrize("section", ["posts_results", "featured_panel"])
def test_supplement_only_saved_followups_and_cards_are_not_empty(media, section):
    _, search, _ = media
    source = search_payload(search)
    source = {"search_query": "fixture", "results": [], "results_count": 0, section: source[section]}
    saved = extract("serpapi_youtube_search", source)
    assert saved[section]
    result = render({"serpapi_youtube_search": json.loads(json.dumps(source))})
    assert len(result["youtube"]["items"]) == 1
    assert "Community post" in result["html"] if section == "posts_results" else "Featured channel" in result["html"]


def test_search_followup_omissions_are_explicit_and_do_not_cut_identity_links(media):
    _, search, _ = media
    source = search_payload(search)
    source["posts_results"] *= 5
    source["posts_results"][0]["text"] = "x" * 1200
    source["featured_panel"]["videos"] *= 5
    source["results"][0]["chapters"] *= 12
    result = extract("serpapi_youtube_search", source)
    assert len(result["posts_results"]) == 3
    assert len(result["posts_results"][0]["text"]) == 400
    assert len(result["featured_panel"]["videos"]) == 3
    assert len(result["candidates"][0]["chapters"]) == 8
    assert result["posts_results_truncated"] is result["featured_panel_truncated"] is True
    assert result["candidates"][0]["chapters_truncated"] is True
    assert result["posts_results"][0]["url"] == source["posts_results"][0]["url"]


@pytest.mark.parametrize("panel_type,identity,value", [
    ("playlist", "playlist_id", "OLAK5uy_m2pWyg-txDMGdNNiHtjorZVRbrVg_Ihxo"),
    ("show", "show_id", "SCxoxXLn_0TfdvIVbVWIMdfw"),
])
def test_documented_album_and_show_panels_keep_ids_through_saved_followups_and_cards(media, panel_type, identity, value):
    _, search, _ = media
    provider = {"featured_panel": {
        "type": panel_type, identity: value, "title": "Fixture panel", "subtitle": "Album or show",
        "link": "https://www.youtube.com/playlist?list=fixture", "videos": [{
            "video_id": "fixture", "title": "Fixture track or episode", "length": "4:19",
            "link": "https://www.youtube.com/watch?v=fixture",
        }],
    }}
    source = {"results": [], "results_count": 0, **search.normalize_supplemental_results(provider)}
    saved = extract("serpapi_youtube_search", source)
    assert saved["featured_panel"][identity] == value
    assert saved["featured_panel"]["videos"][0]["video_id"] == "fixture"
    assert extract("serpapi_youtube_search", saved)["featured_panel"][identity] == value
    result = render({"serpapi_youtube_search": json.loads(json.dumps(source))})
    assert len(result["youtube"]["items"]) == 1
    assert result["youtube"]["items"][0]["url"] == provider["featured_panel"]["link"]
    assert f"Featured {panel_type}" in result["html"]
    assert "Fixture track or episode" in result["html"]


def test_youtube_cards_distinguish_sources_escape_text_and_use_each_sources_own_image(media):
    _, search, _ = media
    source = search_payload(search)
    result = render({"serpapi_youtube_search": source})
    items = result["youtube"]["items"]
    assert len(items) == 3
    assert items[0]["details"] == ["Automatic chapter: Opening"]
    assert items[1]["url"].endswith("/post/UgFixture")
    assert items[1]["image"] == "https://images.example/post-attachment.jpg"
    assert items[1]["chips"] == ["0 votes"]
    assert items[2]["image"] == "https://images.example/panel.jpg"
    assert "&lt;script&gt;inert()&lt;/script&gt;" in result["html"]
    assert "<script>" not in result["html"]
    assert 'href="https://www.youtube.com/post/UgFixture"' in result["html"]
    assert render({"serpapi_youtube_search": json.loads(json.dumps(source))})["youtube"] == result["youtube"]
    source["featured_panel"].pop("thumbnail")
    assert "image" not in render({"serpapi_youtube_search": source})["youtube"]["items"][2]


def surfaced_search(payload, surface):
    name = "serpapi_youtube_search"
    if surface == "trace":
        return {name: {"ok": True, "data": payload}, "_tool_trace": [{"tool": name, "ok": True}]}, []
    if surface == "tools_used":
        return {name: payload}, [name]
    workflow = {"action": "run", "workflow_id": "media_fixture", "results": []}
    if surface == "workflow_fallback":
        return {"workflow": workflow, name: payload}, []
    step = {"step": 1, "tool": name, "ok": True}
    if surface == "workflow_outputs":
        step["outputs"] = [{"ok": True, "data": payload}]
    else:
        step["data"] = payload
    workflow["results"] = [step]
    return {"workflow": workflow}, []


@pytest.mark.parametrize("surface", ["trace", "tools_used", "workflow_step", "workflow_outputs", "workflow_fallback"])
@pytest.mark.parametrize("section", ["posts_results", "featured_panel"])
@pytest.mark.parametrize("include_videos", [False, True])
def test_real_chat_and_workflow_surfaces_render_supplements_without_duplicating_playable_videos(media, surface, section, include_videos):
    _, search, _ = media
    source = search_payload(search)
    source.pop("featured_panel" if section == "posts_results" else "posts_results")
    if not include_videos:
        source["results"] = []
        source["results_count"] = 0
    data, tools_used = surfaced_search(source, surface)
    html = render(json.loads(json.dumps(data)), tools_used)["html"]
    assert "Community post" in html if section == "posts_results" else "Featured channel" in html
    assert "Fixture video" not in html
    if surface.startswith("workflow"):
        assert 'data-workflow-tool="serpapi_youtube_search"' in html
    if section == "posts_results":
        assert "Useful update &lt;script&gt;inert()&lt;/script&gt;" in html
        assert 'href="https://www.youtube.com/post/UgFixture"' in html


@pytest.mark.parametrize("surface", ["trace", "tools_used", "workflow_step", "workflow_outputs", "workflow_fallback"])
def test_video_only_chat_and_workflow_keep_the_existing_dedicated_surface(media, surface):
    _, search, _ = media
    source = search_payload(search)
    source.pop("posts_results")
    source.pop("featured_panel")
    data, tools_used = surfaced_search(source, surface)
    assert render(data, tools_used)["html"] == ""


def test_repeated_traced_search_calls_match_supplements_to_successful_occurrences(media):
    _, search, _ = media
    first = search_payload(search)
    first.pop("featured_panel")
    second = search_payload(search)
    second.pop("posts_results")
    html = render({
        "_tool_trace": [{"tool": "serpapi_youtube_search", "ok": True},
                        {"tool": "serpapi_youtube_search", "ok": False},
                        {"tool": "serpapi_youtube_search", "ok": True}],
        "serpapi_youtube_search": [first, second],
    })["html"]
    assert "2 visual sections from 3 tool calls" in html
    assert "1 failed" in html
    assert html.index("Community post") < html.index("Featured channel")
    assert "Fixture video" not in html


@pytest.mark.parametrize("entity", ["game", "team", "league"])
def test_sports_saved_followups_and_cards_keep_down_distance_zero_timeouts_and_possession(media, entity):
    _, _, sports = media
    game = {"title": "Fixture matchup", "down_and_distance": "1st & 10 at MIA 33",
            "teams": [{"name": "Patriots", "short_code": "NE", "timeouts_remaining": 0, "possession": False},
                      {"name": "Dolphins", "short_code": "MIA", "timeouts_remaining": 1, "possession": True}]}
    provider = {f"{entity}_results": {"info": game} if entity == "game" else {"game_groups": [{"games": [game]}]}}
    rows, kind, _extras = sports.extract_results(provider, entity_type=entity, tab=None)
    source = {"query": "fixture", "results_kind": kind, "results": rows, "results_count": len(rows)}
    untouched = deepcopy(source)
    saved = extract("serpapi_google_sports", {"ok": True, "data": source})
    candidate = saved["candidates"][0]
    assert candidate["down_and_distance"] == game["down_and_distance"]
    assert candidate["teams"][0]["timeouts_remaining"] == 0
    assert candidate["teams"][0]["possession"] is False
    assert candidate["teams"][1]["possession"] is True
    assert extract("serpapi_google_sports", saved)["candidates"][0] == candidate
    html = render({"serpapi_google_sports": source})["html"]
    for text in ("1st &amp; 10 at MIA 33", "NE: 0 timeouts remaining", "No possession", "MIA: 1 timeouts remaining", "Possession"):
        assert text in html
    assert source == untouched
