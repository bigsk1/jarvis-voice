#!/usr/bin/env python3
"""Regression tests for SerpApi follow-up context extraction."""

import types
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

CHAT_PATH = PROJECT_ROOT / "jarvis-web" / "server" / "sockets" / "chat.py"
SPEC = importlib.util.spec_from_file_location("jarvis_web_chat", CHAT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
ChatHandler = MODULE.ChatHandler


def _handler():
    return ChatHandler.__new__(ChatHandler)


def test_extract_followup_data_includes_focused_serpapi_product_fields():
    handler = _handler()
    data = {
        "serpapi_search": {
            "engine": "amazon_product",
            "query": None,
            "asin": "B072MQ5BRX",
            "results_count": 1,
            "results": [
                {
                    "title": "Amazon Fresh, Colombia Ground Coffee, Medium Roast, 32 Oz",
                    "url": "https://www.amazon.com/dp/B072MQ5BRX/",
                    "thumbnail": "https://m.media-amazon.com/images/I/example.jpg",
                    "price": "$17.79",
                    "rating": 4.4,
                    "reviews": 10873,
                }
            ],
        }
    }

    result = handler._extract_followup_data(data)
    serp = result["serpapi_search"]

    assert serp["engine"] == "amazon_product"
    assert serp["asin"] == "B072MQ5BRX"
    assert serp["title"].startswith("Amazon Fresh")
    assert serp["top_url"] == "https://www.amazon.com/dp/B072MQ5BRX/"
    assert serp["thumbnail"] == "https://m.media-amazon.com/images/I/example.jpg"
    assert serp["price"] == "$17.79"
    assert serp["rating"] == 4.4
    assert serp["reviews"] == 10873


def test_extract_followup_data_preserves_compact_candidate_list():
    handler = _handler()
    data = {
        "serpapi_search": {
            "engine": "amazon",
            "query": "interesting tech gift over 100 no logo",
            "results_count": 2,
            "results": [
                {
                    "title": "Amazon Echo Show 5 (newest model)",
                    "url": "https://www.amazon.com/dp/B09B2SBHQK/",
                    "asin": "B09B2SBHQK",
                    "price": "$89.99",
                    "rating": 4.2,
                    "reviews": 64800,
                    "thumbnail": "https://m.media-amazon.com/images/I/echo.jpg",
                },
                {
                    "title": "Aura Carver HD WiFi Digital Picture Frame, 10.1",
                    "url": "https://www.amazon.com/dp/B09X1XN3FZ/",
                    "asin": "B09X1XN3FZ",
                    "price": "$149.00",
                    "rating": 4.7,
                    "reviews": 19000,
                    "thumbnail": "https://m.media-amazon.com/images/I/aura.jpg",
                },
            ],
        }
    }

    result = handler._extract_followup_data(data)
    serp = result["serpapi_search"]
    candidates = serp["candidates"]

    assert len(candidates) == 2
    assert candidates[1]["title"].startswith("Aura Carver HD")
    assert candidates[1]["asin"] == "B09X1XN3FZ"
    assert candidates[1]["url"] == "https://www.amazon.com/dp/B09X1XN3FZ/"
    assert candidates[1]["thumbnail"] == "https://m.media-amazon.com/images/I/aura.jpg"


def test_extract_followup_data_includes_serpapi_youtube_fields():
    handler = _handler()
    data = {
        "serpapi_youtube": {
            "video_id": "dQw4w9WgXcQ",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Example Video",
            "channel": "Example Channel",
            "duration": "3:33",
            "published_date": "2 years ago",
            "transcript_api_url": "https://serpapi.com/search.json?engine=youtube_video_transcript&video_id=dQw4w9WgXcQ&language_code=en",
        }
    }

    result = handler._extract_followup_data(data)
    video = result["serpapi_youtube"]

    assert video["video_id"] == "dQw4w9WgXcQ"
    assert video["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert video["title"] == "Example Video"
    assert video["transcript_api_url"].startswith("https://serpapi.com/search.json")


def test_extract_followup_data_preserves_serpapi_youtube_search_candidates():
    handler = _handler()
    data = {
        "serpapi_youtube_search": {
            "search_query": "pepper fermenting hot sauce",
            "results": [
                {
                    "video_id": "abc123def45",
                    "title": "Ferment Peppers Hot Sauce",
                    "url": "https://www.youtube.com/watch?v=abc123def45",
                    "channel": "Pepper Geek",
                    "duration": "12:34",
                    "thumbnail": "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg",
                },
                {
                    "video_id": "zyx987wvu65",
                    "title": "Belizean Style Fermented Sauce",
                    "url": "https://www.youtube.com/watch?v=zyx987wvu65",
                    "channel": "Chili Lab",
                    "duration": "9:10",
                },
            ],
        }
    }

    result = handler._extract_followup_data(data)
    youtube = result["serpapi_youtube_search"]

    assert youtube["title"] == "Ferment Peppers Hot Sauce"
    assert youtube["top_url"] == "https://www.youtube.com/watch?v=abc123def45"
    assert len(youtube["candidates"]) == 2
    assert youtube["candidates"][1]["video_id"] == "zyx987wvu65"


def test_extract_followup_data_preserves_serpapi_yelp_candidates():
    handler = _handler()
    data = {
        "serpapi_yelp_search": {
            "find_desc": "Coffee",
            "find_loc": "New York, NY, USA",
            "results": [
                {
                    "title": "Pup Cup Coffee",
                    "url": "https://www.yelp.com/biz/pup-cup-coffee",
                    "place_id": "pup-cup-coffee-nyc",
                    "rating": 4.7,
                    "price": "$$",
                    "address": "123 Market St, New York, NY 10001",
                    "thumbnail": "https://s3-media.example.com/pup.jpg",
                },
                {
                    "title": "Dog Park Cafe",
                    "url": "https://www.yelp.com/biz/dog-park-cafe",
                    "place_id": "dog-park-cafe-nyc",
                    "rating": 4.5,
                    "price": "$",
                    "address": "9 Broadway, New York, NY 10012",
                },
            ],
        }
    }

    result = handler._extract_followup_data(data)
    yelp = result["serpapi_yelp_search"]

    assert yelp["title"] == "Pup Cup Coffee"
    assert yelp["top_url"] == "https://www.yelp.com/biz/pup-cup-coffee"
    assert yelp["place_id"] == "pup-cup-coffee-nyc"
    assert len(yelp["candidates"]) == 2
    assert yelp["candidates"][1]["place_id"] == "dog-park-cafe-nyc"


def test_extract_followup_data_accepts_list_shaped_yelp_payload():
    handler = _handler()
    data = {
        "serpapi_yelp_search": [
            {
                "title": "Pup Cup Coffee",
                "url": "https://www.yelp.com/biz/pup-cup-coffee",
                "place_id": "pup-cup-coffee-nyc",
                "rating": 4.7,
            },
            {
                "title": "Dog Park Cafe",
                "url": "https://www.yelp.com/biz/dog-park-cafe",
                "place_id": "dog-park-cafe-nyc",
                "rating": 4.5,
            },
        ]
    }
    result = handler._extract_followup_data(data)
    yelp = result["serpapi_yelp_search"]
    assert yelp["results_count"] == 2
    assert len(yelp["candidates"]) == 2
    assert yelp["candidates"][0]["place_id"] == "pup-cup-coffee-nyc"


def test_extract_followup_data_yelp_candidates_respect_evidence_max():
    handler = _handler()
    results = [
        {"title": f"Place {i}", "url": f"https://yelp.com/biz/p{i}", "place_id": f"p{i}"}
        for i in range(15)
    ]
    data = {"serpapi_yelp_search": {"find_desc": "Coffee", "find_loc": "NYC", "results": results}}
    compact = handler._extract_followup_data(data)
    assert len(compact["serpapi_yelp_search"]["candidates"]) == 5
    evidence = handler._extract_followup_data(data, max_candidates=12)
    assert len(evidence["serpapi_yelp_search"]["candidates"]) == 12
    assert evidence["serpapi_yelp_search"]["results_count"] == 15


def test_extract_followup_data_preserves_text_summarizer_summary_and_refs():
    handler = _handler()
    data = {
        "text_summarizer": {
            "summary": "Postgres can replace several services: queues, cache, search, analytics, and vector storage.",
            "source": {
                "stash_ref": "stash://space_20260417_000524_029bf796/f_72ddfcb6db47",
                "file_id": "f_72ddfcb6db47",
                "space_id": "space_20260417_000524_029bf796",
                "source": "stash",
                "characters_loaded": 13088,
                "path": "/home/boss/should/not/be/prompted.md",
            },
            "summary_meta": {
                "summary_method": "llm",
                "llm_used": True,
                "llm_provider": "xai",
                "llm_model": "grok-4-1-fast-non-reasoning-latest",
                "chunks_used": 2,
                "chunks_total": 2,
                "input_characters": 13088,
            },
        }
    }

    result = handler._extract_followup_data(data)
    summary = result["text_summarizer"]

    assert summary["summary"].startswith("Postgres can replace")
    assert summary["stash_ref"] == "stash://space_20260417_000524_029bf796/f_72ddfcb6db47"
    assert summary["file_id"] == "f_72ddfcb6db47"
    assert summary["space_id"] == "space_20260417_000524_029bf796"
    assert summary["summary_method"] == "llm"
    assert summary["llm_used"] is True
    assert summary["chunks_total"] == 2
    assert "path" not in summary


def test_extract_followup_data_truncates_text_summarizer_summary():
    handler = _handler()
    long_summary = "A" * 6000
    data = {
        "text_summarizer": {
            "summary": long_summary,
            "source": {"stash_ref": "stash://space/file"},
            "summary_meta": {"summary_method": "llm"},
        }
    }

    result = handler._extract_followup_data(data)
    summary = result["text_summarizer"]["summary"]

    assert len(summary) < len(long_summary)
    assert summary.endswith("...[summary truncated for follow-up context]")
    assert result["text_summarizer"]["stash_ref"] == "stash://space/file"


def test_compute_effective_evidence_tool_turn():
    handler = _handler()
    save_data = {
        "serpapi_yelp_search": {
            "find_desc": "pizza",
            "find_loc": "Hillsboro, OR",
            "results": [
                {"title": "A", "url": "https://yelp.com/a", "place_id": "a"},
            ],
        },
    }
    ev = handler._compute_effective_evidence(
        "conv1", save_data, ["serpapi_yelp_search"], {}, "msg-web-1", "find pizza"
    )
    assert ev["v"] == 1
    assert ev["derived_from_prior"] is False
    assert ev["source_message_ids"] == ["msg-web-1"]
    assert "serpapi_yelp_search" in ev["supporting_tool_results"]


def test_compute_effective_evidence_inherits_when_short_refinement():
    handler = _handler()
    prior = {
        "v": 1,
        "supporting_tools_used": ["serpapi_yelp_search"],
        "supporting_tool_results": {"serpapi_yelp_search": {"results_count": 3}},
        "source_message_ids": ["root-id"],
        "derived_from_prior": False,
    }
    with patch.object(handler, "_find_nearest_prior_effective_evidence", return_value=prior):
        ev = handler._compute_effective_evidence("c", {}, [], {}, "newmid", "sorry meant top 10")
    assert ev["derived_from_prior"] is True
    assert ev["source_message_ids"] == ["root-id"]


def test_compute_effective_evidence_skips_inherit_on_long_query():
    handler = _handler()
    prior = {
        "v": 1,
        "supporting_tools_used": ["serpapi_yelp_search"],
        "supporting_tool_results": {},
        "source_message_ids": ["root-id"],
        "derived_from_prior": False,
    }
    with patch.object(handler, "_find_nearest_prior_effective_evidence", return_value=prior):
        ev = handler._compute_effective_evidence("c", {}, [], {}, "newmid", "x" * 900)
    assert ev is None


def test_compute_effective_evidence_skips_inherit_on_unrelated_short_query():
    handler = _handler()
    prior = {
        "v": 1,
        "supporting_tools_used": ["serpapi_yelp_search"],
        "supporting_tool_results": {"serpapi_yelp_search": {"results_count": 3}},
        "source_message_ids": ["root-id"],
        "derived_from_prior": False,
    }
    with patch.object(handler, "_find_nearest_prior_effective_evidence", return_value=prior):
        ev = handler._compute_effective_evidence("c", {}, [], {}, "newmid", "what's the weather?")
    assert ev is None


def test_compute_effective_evidence_native_tools_only_creates_fresh_epoch():
    """Provider-native tools: tools_used empty but server_side_tools must rebuild, not inherit."""
    handler = _handler()
    save_data = {"raw_llm_response": "...", "server_side_tools": {"web_search": 1}}
    prior = {
        "v": 1,
        "supporting_tools_used": ["serpapi_yelp_search"],
        "supporting_tool_results": {"serpapi_yelp_search": {"results_count": 99}},
        "source_message_ids": ["stale"],
        "derived_from_prior": False,
    }
    with patch.object(handler, "_find_nearest_prior_effective_evidence", return_value=prior):
        ev = handler._compute_effective_evidence(
            "c", save_data, [], {"web_search": 1}, "native-msg-1", "search the web for foo"
        )
    assert ev is not None
    assert ev["derived_from_prior"] is False
    assert "native:web_search" in ev["supporting_tools_used"]
    assert ev["source_message_ids"] == ["native-msg-1"]
    assert "native_tools" in ev["supporting_tool_results"]
