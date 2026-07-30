#!/usr/bin/env python3
"""Regression tests for SerpApi follow-up context extraction."""

import types
import json
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.sockets.chat import ChatHandler
from jarvis_web_test_server.services import followup_extractor as followup_module
from jarvis_web_test_server.services.followup_extractor import (
    FOLLOWUP_FETCH_EXCERPT_MAX_CHARS,
    FOLLOWUP_SUMMARY_MAX_CHARS,
    workflow_result_payload,
    workflow_step_tool_results,
)


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
                    "prime": True,
                    "prime_eligible": True,
                    "delivery": ["FREE Prime delivery Tomorrow"],
                    "stock": "In Stock",
                    "badges": ["Amazon's Choice"],
                    "bought_last_month": "10K+ bought in past month",
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
    assert serp["prime_eligible"] is True
    assert serp["delivery"] == ["FREE Prime delivery Tomorrow"]
    assert serp["stock"] == "In Stock"
    assert serp["badges"] == ["Amazon's Choice"]
    assert serp["bought_last_month"] == "10K+ bought in past month"


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
                    "prime": False,
                    "prime_eligible": False,
                    "shipping": "Ships from Example Seller",
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
    assert candidates[0]["prime"] is False
    assert candidates[0]["prime_eligible"] is False
    assert candidates[0]["shipping"] == "Ships from Example Seller"


def test_extract_followup_data_merges_amazon_workflow_search_and_detail_runs():
    workflow = {
        "action": "run",
        "workflow_id": "amazon_value_search",
        "workflow_name": "Amazon Value Search",
        "workflow_completed": True,
        "results": [
            {
                "step": 1,
                "tool": "serpapi_search",
                "data": {
                    "engine": "amazon",
                    "query": "usb c charger 65w under 40",
                    "query_effective": "usb c charger 65w 40",
                    "delivery_localized": True,
                    "delivery_location_source": "jarvis_default",
                    "results_count": 2,
                    "results": [
                        {
                            "title": "Anker 65W Charger",
                            "asin": "B09C5RG6KV",
                            "url": "https://www.amazon.com/dp/B09C5RG6KV/",
                            "price": "$24.99",
                            "rating": 4.7,
                            "reviews": 21600,
                        },
                        {
                            "title": "INIU 65W Charger",
                            "asin": "B0DN6VXM61",
                            "url": "https://www.amazon.com/dp/B0DN6VXM61/",
                            "price": "$19.77",
                            "rating": 4.7,
                            "reviews": 1200,
                        },
                    ],
                },
            },
            {
                "step": 2,
                "tool": "serpapi_search",
                "outputs": [
                    {
                        "ok": True,
                        "data": {
                            "engine": "amazon_product",
                            "asin": "B09C5RG6KV",
                            "delivery_localized": True,
                            "results": [
                                {
                                    "title": "Anker 65W Charger",
                                    "asin": "B09C5RG6KV",
                                    "url": "https://www.amazon.com/dp/B09C5RG6KV/",
                                    "prime_eligible": True,
                                    "delivery": ["Prime members get FREE delivery Today"],
                                    "stock": "In Stock",
                                    "badges": ["Overall Pick"],
                                }
                            ],
                        },
                    },
                    {
                        "ok": True,
                        "data": {
                            "engine": "amazon_product",
                            "asin": "B0DN6VXM61",
                            "delivery_localized": True,
                            "results": [
                                {
                                    "title": "INIU 65W Charger",
                                    "asin": "B0DN6VXM61",
                                    "url": "https://www.amazon.com/dp/B0DN6VXM61/",
                                    "prime": False,
                                    "prime_eligible": False,
                                    "delivery": ["FREE delivery Sunday"],
                                    "stock": "Only 4 left in stock",
                                    "save_with_coupon": "Save 10% with coupon",
                                }
                            ],
                        },
                    },
                ],
            },
        ],
    }

    followup = _handler()._extract_followup_data({"workflow": workflow})
    serp = followup["serpapi_search"]

    assert serp["engine"] == "amazon"
    assert serp["query"] == "usb c charger 65w under 40"
    assert serp["query_effective"] == "usb c charger 65w 40"
    assert serp["delivery_localized"] is True
    assert serp["delivery_location_source"] == "jarvis_default"
    assert serp["runs_count"] == 3
    assert len(serp["candidates"]) == 2
    assert serp["candidates"][0]["asin"] == "B09C5RG6KV"
    assert serp["candidates"][0]["prime_eligible"] is True
    assert serp["candidates"][0]["stock"] == "In Stock"
    assert serp["candidates"][0]["badges"] == ["Overall Pick"]
    assert serp["candidates"][1]["asin"] == "B0DN6VXM61"
    assert serp["candidates"][1]["prime"] is False
    assert serp["candidates"][1]["prime_eligible"] is False
    assert serp["candidates"][1]["delivery"] == ["FREE delivery Sunday"]
    assert serp["candidates"][1]["save_with_coupon"] == "Save 10% with coupon"


def test_extract_followup_data_merges_flattened_amazon_workflow_runs():
    data = {
        "serpapi_search": [
            {
                "engine": "amazon",
                "query": "portable monitor",
                "results_count": 1,
                "results": [
                    {
                        "title": "Example Portable Monitor",
                        "asin": "B0EXAMPLE1",
                        "url": "https://www.amazon.com/dp/B0EXAMPLE1/",
                        "price": "$99.99",
                    }
                ],
            },
            {
                "engine": "amazon_product",
                "asin": "B0EXAMPLE1",
                "results_count": 1,
                "results": [
                    {
                        "title": "Example Portable Monitor",
                        "asin": "B0EXAMPLE1",
                        "url": "https://www.amazon.com/dp/B0EXAMPLE1/",
                        "prime_eligible": True,
                        "delivery": ["Prime members get FREE delivery Tomorrow"],
                        "stock": "In Stock",
                    }
                ],
            },
        ]
    }

    serp = _handler()._extract_followup_data(data)["serpapi_search"]

    assert serp["runs_count"] == 2
    assert serp["results_count"] == 1
    assert serp["candidates"] == [
        {
            "title": "Example Portable Monitor",
            "asin": "B0EXAMPLE1",
            "url": "https://www.amazon.com/dp/B0EXAMPLE1/",
            "price": "$99.99",
            "prime_eligible": True,
            "delivery": ["Prime members get FREE delivery Tomorrow"],
            "stock": "In Stock",
        }
    ]


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


def test_extract_followup_data_preserves_serpapi_home_depot_candidates():
    handler = _handler()
    data = {
        "serpapi_home_depot": {
            "engine": "home_depot",
            "query": "cordless drill",
            "country": "us",
            "results": [
                {
                    "title": "20V MAX Cordless Drill/Driver Kit",
                    "url": "https://www.homedepot.com/p/drill/123456789",
                    "product_id": "123456789",
                    "brand": "DEWALT",
                    "model_number": "DCD771C2",
                    "price_formatted": "$99.00",
                    "rating": 4.7,
                    "reviews": 2400,
                    "thumbnail": "https://images.example.com/drill.jpg",
                },
                {
                    "title": "M18 18V Lithium-Ion Drill Driver",
                    "url": "https://www.homedepot.com/p/m18/987654321",
                    "product_id": "987654321",
                    "brand": "Milwaukee",
                    "model_number": "2606-20",
                    "price_formatted": "$89.00",
                },
            ],
        }
    }

    result = handler._extract_followup_data(data)
    home_depot = result["serpapi_home_depot"]

    assert home_depot["query"] == "cordless drill"
    assert home_depot["country"] == "us"
    assert home_depot["title"] == "20V MAX Cordless Drill/Driver Kit"
    assert home_depot["top_url"] == "https://www.homedepot.com/p/drill/123456789"
    assert home_depot["product_id"] == "123456789"
    assert home_depot["brand"] == "DEWALT"
    assert home_depot["model_number"] == "DCD771C2"
    assert home_depot["price"] == "$99.00"
    assert len(home_depot["candidates"]) == 2
    assert home_depot["candidates"][1]["product_id"] == "987654321"


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
                "path": "~/should/not/be/prompted.md",
            },
            "summary_meta": {
                "summary_method": "llm",
                "llm_used": True,
                "llm_provider": "xai",
                "llm_model": "grok-4.3",
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
    long_summary = "A" * 10000
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
    assert len(summary) <= FOLLOWUP_SUMMARY_MAX_CHARS
    assert summary.endswith("...[summary truncated for follow-up context]")
    assert result["text_summarizer"]["stash_ref"] == "stash://space/file"


def test_autonomous_workflow_followup_preserves_component_handles_and_summary():
    workflow = {
        "action": "run",
        "workflow_id": "research",
        "workflow_name": "Research",
        "execution": "foreground",
        "workflow_started": True,
        "workflow_completed": True,
        "steps_completed": 2,
        "results": [
            {
                "step": 1,
                "tool": "text_summarizer",
                "ok": True,
                "data": {
                    "summary": "The report needs one correction before publishing.",
                    "source": {
                        "stash_ref": "stash://research/source",
                        "space_id": "research",
                        "file_id": "source",
                    },
                    "summary_meta": {
                        "summary_method": "llm",
                        "llm_used": True,
                        "llm_provider": "ollama",
                        "llm_model": "summary-model:cloud",
                    },
                },
            },
            {
                "step": 2,
                "tool": "canvas",
                "ok": True,
                "data": {
                    "page_id": "page_research",
                    "title": "Research Report",
                },
            },
        ],
    }
    data = {"workflow": workflow}

    assert workflow_result_payload(data) is workflow
    flattened = workflow_step_tool_results(workflow)
    assert flattened["canvas"]["page_id"] == "page_research"

    result = _handler()._extract_followup_data(data)

    assert result["workflow"]["workflow_id"] == "research"
    assert result["workflow"]["workflow_completed"] is True
    assert result["canvas"]["page_id"] == "page_research"
    assert result["canvas"]["title"] == "Research Report"
    assert result["text_summarizer"]["summary"].startswith("The report needs")
    assert result["text_summarizer"]["stash_ref"] == "stash://research/source"
    assert result["text_summarizer"]["llm_model"] == "summary-model:cloud"

    searched_then_ran = {
        "workflow": [
            {
                "action": "search",
                "matches": [{"workflow_id": "research"}],
            },
            workflow,
        ]
    }
    assert workflow_result_payload(searched_then_ran) is workflow
    repeated_result = _handler()._extract_followup_data(searched_then_ran)
    assert repeated_result["canvas"]["page_id"] == "page_research"


def test_workflow_step_flattening_preserves_repeated_tool_results():
    workflow = {
        "results": [
            {
                "step": 1,
                "tool": "crypto_price",
                "data": {"coin": "bitcoin", "price_usd": 100000},
            },
            {
                "step": 2,
                "tool": "crypto_price",
                "data": {"coin": "solana", "price_usd": 200},
            },
        ]
    }

    flattened = workflow_step_tool_results(workflow)

    assert flattened["crypto_price"] == [
        {"coin": "bitcoin", "price_usd": 100000},
        {"coin": "solana", "price_usd": 200},
    ]

    followup = _handler()._extract_followup_data({"workflow": {
        "action": "run",
        "workflow_id": "crypto_report",
        **workflow,
    }})
    assert followup["crypto_price"]["coin"] == "solana"
    assert followup["crypto_price"]["runs_count"] == 2
    assert followup["crypto_price"]["candidates"][0]["coin"] == "bitcoin"
    assert followup["crypto_price"]["candidates"][1]["price_usd"] == 200


def test_extract_followup_data_preserves_manage_intel_document_content():
    handler = _handler()
    markdown = "# Family Visit\n- Danny arrives Monday\n- Joey leaves Sunday\n"
    data = {
        "manage_intel": [
            {"files": [{"path": "existing.md", "size_bytes": 10}], "count": 1},
            {
                "action": "create",
                "file": "2026-07-family-visit-timeline.md",
                "content": markdown,
                "size_bytes": len(markdown),
                "created": True,
                "ingest": {
                    "ingested": True,
                    "new_files": 2,
                    "total_facts": 12,
                    "modes": ["cloud", "local"],
                },
            },
        ],
        "_tool_trace": [
            {"tool": "manage_intel", "ok": True, "arguments": {"action": "list", "pattern": "*"}},
            {
                "tool": "manage_intel",
                "ok": True,
                "arguments": {
                    "action": "create",
                    "path": "2026-07-family-visit-timeline.md",
                    "content": markdown[:20] + "... [truncated]",
                },
            },
        ],
    }

    result = handler._extract_followup_data(data)
    intel = result["manage_intel"]

    assert intel["operation_count"] == 2
    assert intel["latest_action"] == "create"
    assert intel["latest_file"] == "2026-07-family-visit-timeline.md"
    assert intel["latest_content"] == markdown
    assert intel["latest_content_source"] == "tool_result"
    assert intel["latest_document"]["file"] == "2026-07-family-visit-timeline.md"
    assert "content" not in intel["latest_document"]
    assert intel["operations"][1]["ingest"]["modes"] == ["cloud", "local"]


def test_extract_followup_data_rehydrates_manage_intel_create_from_flat_file(tmp_path, monkeypatch):
    handler = _handler()
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    markdown = "# Family Visit\n- Full content from existing intel file\n"
    (intel_dir / "2026-07-family-visit-timeline.md").write_text(markdown, encoding="utf-8")
    monkeypatch.setattr(followup_module, "MANAGE_INTEL_DIR", intel_dir)

    data = {
        "manage_intel": {
            "file": "2026-07-family-visit-timeline.md",
            "size_bytes": len(markdown),
            "created": True,
        },
        "_tool_trace": [
            {
                "tool": "manage_intel",
                "ok": True,
                "arguments": {
                    "action": "create",
                    "path": "2026-07-family-visit-timeline.md",
                    "content": "# Family Visit\n- Full content... [truncated]",
                },
            }
        ],
    }

    result = handler._extract_followup_data(data)
    intel = result["manage_intel"]

    assert intel["latest_action"] == "create"
    assert intel["latest_file"] == "2026-07-family-visit-timeline.md"
    assert intel["latest_content"] == markdown
    assert intel["latest_content_source"] == "jarvis-intel/current_file"


def test_extract_followup_data_preserves_semantic_intel_version_identity():
    handler = _handler()
    data = {
        "manage_intel": {
            "action": "create",
            "file": "pdf-ingest-docker-commands-cheat-sheet-2.md",
            "size_bytes": 900,
            "created": True,
            "versioned": True,
            "content": "# Docker Commands Cheat Sheet\n",
        },
        "_tool_trace": [
            {
                "tool": "manage_intel",
                "ok": True,
                "arguments": {
                    "action": "create",
                    "filename_from_title": True,
                    "filename_prefix": "pdf-ingest",
                    "on_conflict": "version",
                },
            }
        ],
    }

    result = handler._extract_followup_data(data)
    intel = result["manage_intel"]

    assert intel["latest_file"] == "pdf-ingest-docker-commands-cheat-sheet-2.md"
    assert intel["latest_created"] is True
    assert intel["latest_versioned"] is True
    assert intel["operations"][0]["versioned"] is True


def test_extract_followup_data_generic_fallback_preserves_scalar_handles():
    handler = _handler()
    data = {
        "create_alert": {
            "alert_id": "alert_123",
            "title": "Frost warning",
            "status": "pending",
            "severity": "high",
            "description": "Long prose should not be carried by generic fallback",
            "api_token": "secret-token",
        }
    }

    result = handler._extract_followup_data(data)
    alert = result["create_alert"]

    assert alert["alert_id"] == "alert_123"
    assert alert["title"] == "Frost warning"
    assert alert["status"] == "pending"
    assert alert["severity"] == "high"
    assert "description" not in alert
    assert "api_token" not in alert


def test_extract_followup_data_preserves_release_watch_state_for_direct_tool_followups():
    handler = _handler()
    data = {
        "release_watch": {
            "watch_id": "yt-dlp-stable",
            "source": "pypi",
            "project": "yt-dlp",
            "initialized": False,
            "changed": False,
            "regression_detected": False,
            "previous_version": "2026.7.4",
            "current_version": "2026.7.4",
            "normalized_version": "2026.7.4",
            "release_url": "https://pypi.org/project/yt-dlp/2026.7.4/",
            "published_at": "2026-07-04T22:42:14Z",
            "checked_at": "2026-07-22T07:38:29Z",
            "alert_title": "New yt-dlp release: 2026.7.4",
            "alert_severity": "medium",
            "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.7.4",
            "summary": "Bulky prose is intentionally not follow-up state.",
            "state_path": "/private/internal/state.json",
        }
    }

    result = handler._extract_followup_data(data)
    release = result["release_watch"]

    assert release == {
        "watch_id": "yt-dlp-stable",
        "source": "pypi",
        "project": "yt-dlp",
        "initialized": False,
        "changed": False,
        "regression_detected": False,
        "previous_version": "2026.7.4",
        "current_version": "2026.7.4",
        "normalized_version": "2026.7.4",
        "release_url": "https://pypi.org/project/yt-dlp/2026.7.4/",
        "published_at": "2026-07-04T22:42:14Z",
        "checked_at": "2026-07-22T07:38:29Z",
        "alert_title": "New yt-dlp release: 2026.7.4",
        "alert_severity": "medium",
        "alert_dedupe_key": "release-watch:yt-dlp-stable:2026.7.4",
    }


def test_extract_followup_data_generic_fallback_preserves_common_candidate_lists():
    handler = _handler()
    data = {
        "list_reminders": {
            "count": 3,
            "results_count": 99,
            "reminders": [
                {
                    "reminder_id": "rem_1",
                    "title": "Water garden",
                    "status": "pending",
                    "due_at": "2026-07-10T18:00:00",
                    "content": "Do not carry full reminder body",
                    "authorization": "Bearer nope",
                },
                {
                    "reminder_id": "rem_2",
                    "title": "Check smoker",
                    "status": "pending",
                    "due_at": "2026-07-10T19:00:00",
                },
                {
                    "reminder_id": "rem_3",
                    "title": "Third item",
                    "status": "pending",
                },
            ],
        }
    }

    result = handler._extract_followup_data(data, max_candidates=2)
    reminders = result["list_reminders"]

    assert reminders["reminders_count"] == 3
    assert reminders["candidate_source"] == "reminders"
    assert len(reminders["candidates"]) == 2
    assert reminders["candidates"][0]["reminder_id"] == "rem_1"
    assert reminders["candidates"][0]["title"] == "Water garden"
    assert "content" not in reminders["candidates"][0]
    assert "authorization" not in reminders["candidates"][0]
    json.dumps(result)


def test_extract_followup_data_generic_fallback_unwraps_nested_data_envelope():
    handler = _handler()
    data = {
        "list_alerts": {
            "ok": True,
            "data": {
                "count": 2,
                "alerts": [
                    {
                        "alert_id": "alert_1",
                        "title": "Freezer warning",
                        "status": "pending",
                        "severity": "critical",
                    },
                    {
                        "alert_id": "alert_2",
                        "title": "Door open",
                        "status": "pending",
                    },
                ],
            },
        }
    }

    result = handler._extract_followup_data(data)
    alerts = result["list_alerts"]

    assert alerts["alerts_count"] == 2
    assert alerts["title"] == "Freezer warning"
    assert alerts["candidates"][0]["alert_id"] == "alert_1"
    assert alerts["candidates"][0]["severity"] == "critical"


def test_extract_followup_data_generic_fallback_handles_conversation_lists():
    handler = _handler()
    data = {
        "search_conversations": {
            "conversations": [
                {
                    "conversation_id": "aae4ab72",
                    "title": "Family timeline",
                    "updated_at": "2026-07-10T02:02:07",
                    "summary": "Do not carry prose summary by default",
                }
            ]
        }
    }

    result = handler._extract_followup_data(data)
    conversations = result["search_conversations"]

    assert conversations["candidate_source"] == "conversations"
    assert conversations["conversations_count"] == 1
    assert conversations["title"] == "Family timeline"
    assert conversations["candidates"][0] == {
        "title": "Family timeline",
        "conversation_id": "aae4ab72",
        "updated_at": "2026-07-10T02:02:07",
    }


def test_extract_followup_data_generic_fallback_keeps_maps_and_hotel_candidate_richness():
    handler = _handler()
    data = {
        "serpapi_maps_search": {
            "engine": "google_maps",
            "query": "coffee",
            "results": [
                {
                    "title": "Pup Cup Coffee",
                    "url": "https://maps.example/pup",
                    "place_id": "place_123",
                    "rating": 4.8,
                    "reviews": 321,
                    "address": "123 Market St",
                    "thumbnail": "https://images.example/pup.jpg",
                }
            ],
        },
        "serpapi_hotel_search": {
            "destination": "Newport",
            "items": [
                {
                    "name": "Harbor Inn",
                    "url": "https://hotels.example/harbor",
                    "rating": 4.4,
                    "reviews": 88,
                    "price_total": "$420",
                    "price_per_night": "$210",
                    "thumbnail": "https://images.example/harbor.jpg",
                    "address": "1 Bay Rd",
                }
            ],
        },
    }

    result = handler._extract_followup_data(data)
    maps = result["serpapi_maps_search"]
    hotels = result["serpapi_hotel_search"]

    assert maps["title"] == "Pup Cup Coffee"
    assert maps["top_url"] == "https://maps.example/pup"
    assert maps["candidates"][0]["rating"] == 4.8
    assert maps["candidates"][0]["address"] == "123 Market St"
    assert maps["candidates"][0]["thumbnail"] == "https://images.example/pup.jpg"
    assert maps["candidates"][0]["reviews"] == 321
    assert hotels["name"] == "Harbor Inn"
    assert hotels["top_url"] == "https://hotels.example/harbor"
    assert hotels["candidates"][0]["price_total"] == "$420"
    assert hotels["candidates"][0]["price_per_night"] == "$210"
    assert hotels["candidates"][0]["rating"] == 4.4


def test_extract_followup_data_flattens_repeated_maps_runs_before_generic_candidates():
    handler = _handler()
    data = {
        "serpapi_maps_search": [
            {
                "engine": "google_maps",
                "query": "coffee shops downtown Newport Beach",
                "results_count": 2,
                "results": [
                    {
                        "title": "Jasper Coffee",
                        "url": "https://www.jasper.coffee/",
                        "place_id": "place_1",
                        "rating": 4.7,
                        "reviews": 25,
                        "address": "327 Marine Ave, Newport Beach, CA 92662",
                        "thumbnail": "https://lh3.googleusercontent.com/example=w1000-h1000-c-n",
                    }
                ],
            },
            {
                "engine": "google_maps",
                "query": "coffee shops downtown Newport Beach",
                "results_count": 2,
                "results": [
                    {
                        "title": "Jasper Coffee",
                        "url": "https://www.jasper.coffee/",
                        "place_id": "place_1",
                        "rating": 4.7,
                        "address": "327 Marine Ave, Newport Beach, CA 92662",
                    },
                    {
                        "title": "Sundays Coffee & Co.",
                        "url": "https://serpapi.com/search.json?place_id=place_2",
                        "place_id": "place_2",
                        "rating": 4.7,
                        "reviews": 27,
                        "address": "408 31st St, Newport Beach, CA 92663",
                    },
                ],
            },
        ]
    }

    result = handler._extract_followup_data(data)
    maps = result["serpapi_maps_search"]

    assert maps["runs_count"] == 2
    assert maps["results_count"] == 2
    assert maps["candidates"][0]["title"] == "Jasper Coffee"
    assert maps["candidates"][0]["rating"] == 4.7
    assert maps["candidates"][0]["address"] == "327 Marine Ave, Newport Beach, CA 92662"
    assert maps["candidates"][0]["thumbnail"] == "https://lh3.googleusercontent.com/example=w1000-h1000-c-n"
    assert maps["candidates"][1]["title"] == "Sundays Coffee & Co."
    assert maps["candidates"][1]["address"] == "408 31st St, Newport Beach, CA 92663"
    assert "source" not in maps["candidates"][0]


def test_extract_followup_data_flattens_repeated_hotel_runs_before_generic_candidates():
    handler = _handler()
    data = {
        "serpapi_hotel_search": [
            {
                "engine": "google_hotels",
                "destination": "Newport Beach",
                "check_in_date": "2026-07-17",
                "check_out_date": "2026-07-19",
                "results_count": 2,
                "results": [
                    {
                        "title": "Newport Beach Marriott Bayview",
                        "url": "https://www.marriott.com/newport-bayview",
                        "rating": 4.3,
                        "reviews": 1520,
                        "price_per_night": "$306",
                        "price_total": "$612",
                        "extracted_price_per_night": 306,
                        "extracted_price_total": 612,
                    },
                    {
                        "title": "Newport Channel Inn - Family Triple Room",
                        "url": "https://www.freecancellations.com/channel-inn",
                        "rating": 5,
                        "reviews": 8,
                        "price_per_night": "$330",
                        "price_total": "$659",
                        "extracted_price_per_night": 330,
                        "extracted_price_total": 659,
                    },
                ],
            },
            {
                "engine": "google_hotels",
                "destination": "Newport Beach",
                "check_in_date": "2026-07-17",
                "check_out_date": "2026-07-19",
                "results_count": 1,
                "results": [
                    {
                        "title": "Newport Beach Marriott Bayview",
                        "url": "https://www.marriott.com/newport-bayview",
                        "rating": 4.3,
                        "price_per_night": "$306",
                        "price_total": "$612",
                    }
                ],
            },
        ]
    }

    result = handler._extract_followup_data(data)
    hotels = result["serpapi_hotel_search"]

    assert hotels["runs_count"] == 2
    assert hotels["results_count"] == 2
    assert hotels["destination"] == "Newport Beach"
    assert hotels["check_in_date"] == "2026-07-17"
    assert hotels["candidates"][0]["title"] == "Newport Beach Marriott Bayview"
    assert hotels["candidates"][0]["price_per_night"] == "$306"
    assert hotels["candidates"][0]["price_total"] == "$612"
    assert hotels["candidates"][1]["title"] == "Newport Channel Inn - Family Triple Room"
    assert hotels["candidates"][1]["price_per_night"] == "$330"
    assert hotels["candidates"][1]["price_total"] == "$659"


def test_extract_followup_data_flattens_repeated_serpapi_product_runs_for_dedicated_branch():
    handler = _handler()
    data = {
        "serpapi_search": [
            {
                "engine": "amazon",
                "query": "coffee",
                "results_count": 1,
                "results": [
                    {
                        "title": "Amazon Fresh Colombia Ground Coffee",
                        "url": "https://www.amazon.com/dp/B072MQ5BRX/",
                        "asin": "B072MQ5BRX",
                        "price": "$17.79",
                        "rating": 4.4,
                        "thumbnail": "https://m.media-amazon.com/images/I/example.jpg",
                    }
                ],
            },
            {
                "engine": "amazon",
                "query": "coffee",
                "results_count": 1,
                "results": [
                    {
                        "title": "Amazon Fresh Colombia Ground Coffee",
                        "url": "https://www.amazon.com/dp/B072MQ5BRX/",
                        "asin": "B072MQ5BRX",
                        "price": "$17.79",
                        "rating": 4.4,
                    }
                ],
            },
        ]
    }

    result = handler._extract_followup_data(data)
    serp = result["serpapi_search"]

    assert serp["runs_count"] == 2
    assert serp["results_count"] == 1
    assert serp["title"] == "Amazon Fresh Colombia Ground Coffee"
    assert serp["candidates"] == [
        {
            "title": "Amazon Fresh Colombia Ground Coffee",
            "asin": "B072MQ5BRX",
            "url": "https://www.amazon.com/dp/B072MQ5BRX/",
            "price": "$17.79",
            "rating": 4.4,
            "thumbnail": "https://m.media-amazon.com/images/I/example.jpg",
        }
    ]


def test_extract_followup_data_generic_fallback_keeps_candidate_only_shopping_handles():
    handler = _handler()
    data = {
        "shopping_probe": {
            "results": [
                {
                    "asin": "B000TEST",
                    "price": "$19.99",
                    "rating": 4.2,
                    "thumbnail": "https://images.example/item.jpg",
                }
            ]
        }
    }

    result = handler._extract_followup_data(data)
    shopping = result["shopping_probe"]

    assert shopping["results_count"] == 1
    assert shopping["candidates"] == [
        {
            "asin": "B000TEST",
            "rating": 4.2,
            "price": "$19.99",
            "thumbnail": "https://images.example/item.jpg",
        }
    ]


def test_extract_followup_data_generic_fallback_keeps_urlish_candidate_values_intact():
    handler = _handler()
    long_thumbnail = "https://imagedelivery.net/account/hash/public?" + ("w=1200&" * 80)
    long_link = "https://cdn.example.com/assets/photo.jpg?" + ("sig=abc123&" * 80)
    long_href = "https://media.example.com/render/item?" + ("variant=full&" * 80)
    long_image_uri = "cloudflare://images/" + ("nested-path/" * 80)
    long_title = "Family trip image " + ("preview " * 80)
    data = {
        "image_probe": {
            "results": [
                {
                    "title": long_title,
                    "thumbnail": long_thumbnail,
                    "link": long_link,
                    "href": long_href,
                    "image_uri": long_image_uri,
                }
            ]
        }
    }

    result = handler._extract_followup_data(data)
    candidate = result["image_probe"]["candidates"][0]

    assert candidate["thumbnail"] == long_thumbnail
    assert candidate["link"] == long_link
    assert candidate["href"] == long_href
    assert candidate["image_uri"] == long_image_uri
    assert len(candidate["title"]) <= 300
    assert candidate["title"].endswith("... [truncated for follow-up context]")


def test_extract_followup_data_dedicated_branch_skips_generic_candidate_source():
    handler = _handler()
    data = {
        "serpapi_yelp_search": {
            "find_desc": "Coffee",
            "results": [
                {
                    "title": "Pup Cup Coffee",
                    "url": "https://www.yelp.com/biz/pup-cup-coffee",
                    "place_id": "pup-cup-coffee-nyc",
                }
            ],
        }
    }

    result = handler._extract_followup_data(data)
    yelp = result["serpapi_yelp_search"]

    assert yelp["candidates"][0]["place_id"] == "pup-cup-coffee-nyc"
    assert "candidate_source" not in yelp


def test_extract_followup_data_preserves_crawl_url_deduped_urls():
    handler = _handler()
    data = {
        "crawl_url": {
            "results": [
                {
                    "results": [
                        {
                            "url": "https://example.com/post",
                            "title": "Example Post",
                            "success": True,
                            "markdown": "large content should not be retained",
                        }
                    ]
                },
                {
                    "results": [
                        {
                            "url": "https://example.com/post",
                            "title": "Example Post Duplicate",
                            "success": True,
                        },
                        {
                            "url": "https://example.com/other",
                            "title": "Other Page",
                            "success": False,
                        },
                    ]
                },
            ]
        }
    }

    result = handler._extract_followup_data(data)
    crawl = result["crawl_url"]

    assert crawl["runs_count"] == 2
    assert crawl["crawled_urls"] == [
        {"url": "https://example.com/post", "title": "Example Post", "success": True},
        {"url": "https://example.com/other", "title": "Other Page", "success": False},
    ]
    assert "markdown" not in crawl["crawled_urls"][0]


def test_extract_followup_data_preserves_top_level_crawl_url_run_list():
    handler = _handler()
    data = {
        "crawl_url": [
            {
                "results": [
                    {
                        "url": "https://example.com/post",
                        "title": "Example Post",
                        "success": True,
                        "markdown": "large content should not be retained",
                    }
                ]
            },
            {
                "results": [
                    {
                        "url": "https://example.com/other",
                        "title": "Other Page",
                        "success": False,
                    }
                ]
            },
        ]
    }

    result = handler._extract_followup_data(data)
    crawl = result["crawl_url"]

    assert crawl["runs_count"] == 2
    assert crawl["crawled_urls"] == [
        {"url": "https://example.com/post", "title": "Example Post", "success": True},
        {"url": "https://example.com/other", "title": "Other Page", "success": False},
    ]


def test_extract_followup_data_preserves_brave_urls_from_full_text():
    handler = _handler()
    data = {
        "mcp_brave_search_brave_web_search": {
            "results": [
                {
                    "full_text": (
                        "Alpha https://alpha.example/a. "
                        "Beta https://beta.example/b) "
                        "Again https://alpha.example/a"
                    )
                },
                {
                    "full_text": "Gamma https://gamma.example/c, trailing punctuation included."
                },
            ]
        }
    }

    result = handler._extract_followup_data(data, max_candidates=1)
    brave = result["mcp_brave_search_brave_web_search"]

    assert brave["runs_count"] == 2
    assert brave["urls_seen"] == [
        "https://alpha.example/a",
        "https://beta.example/b",
    ]


def test_extract_followup_data_preserves_brave_urls_from_raw_text():
    handler = _handler()
    data = {
        "mcp_brave_search_brave_news_search": {
            "results": [
                {
                    "raw": [
                        {
                            "type": "text",
                            "text": '{"url":"https://news.example/story","title":"Story"}',
                        }
                    ]
                }
            ]
        }
    }

    result = handler._extract_followup_data(data)
    brave = result["mcp_brave_search_brave_news_search"]

    assert brave["runs_count"] == 1
    assert brave["urls_seen"] == ["https://news.example/story"]


def test_extract_followup_data_compacts_duckduckgo_search_results():
    handler = _handler()
    full_text = """Found 2 search results:

1. Alpha Result
   URL: https://alpha.example/page
   Summary: Alpha has a useful result.

2. Beta Result
   URL: https://beta.example/page
   Summary: Beta has another useful result.
"""
    data = {
        "mcp_duckduckgo_search": {
            "raw": [{"type": "text", "text": full_text}],
            "full_text": full_text,
        },
        "_tool_trace": [
            {
                "tool": "mcp_duckduckgo_search",
                "ok": True,
                "arguments": {
                    "query": "alpha beta",
                    "region": "us-en",
                    "max_results": 2,
                },
            }
        ],
    }

    result = handler._extract_followup_data(data, max_candidates=1)
    search = result["mcp_duckduckgo_search"]

    assert search["query"] == "alpha beta"
    assert search["region"] == "us-en"
    assert search["max_results"] == 2
    assert search["runs_count"] == 1
    assert search["results_count"] == 2
    assert search["top_url"] == "https://alpha.example/page"
    assert search["urls_seen"] == [
        "https://alpha.example/page",
        "https://beta.example/page",
    ]
    assert search["candidates"] == [
        {
            "title": "Alpha Result",
            "url": "https://alpha.example/page",
            "snippet": "Alpha has a useful result.",
        }
    ]
    assert "raw" not in search
    assert "full_text" not in search


def test_extract_followup_data_compacts_mcp_fetch_content():
    handler = _handler()
    body = "A" * 2500
    tail = (
        "\n\n[Content info: Showing characters 1000-3500 of 9000 total. "
        "Specify start_index=3500 to continue.]"
    )
    full_text = body + tail
    data = {
        "mcp_duckduckgo_fetch_content": {
            "raw": [{"type": "text", "text": full_text}],
            "full_text": full_text,
        },
        "mcp_fetch_fetch": {
            "full_text": "Fetched article content",
        },
        "_tool_trace": [
            {
                "tool": "mcp_duckduckgo_fetch_content",
                "ok": True,
                "arguments": {
                    "url": "https://example.com/article",
                    "start_index": 1000,
                    "max_length": 2500,
                    "backend": "auto",
                },
            },
            {
                "tool": "mcp_fetch_fetch",
                "ok": True,
                "arguments": {
                    "url": "https://example.com/other",
                    "raw": True,
                },
            },
        ],
    }

    result = handler._extract_followup_data(data)
    duck_fetch = result["mcp_duckduckgo_fetch_content"]
    generic_fetch = result["mcp_fetch_fetch"]

    assert duck_fetch["backend"] == "auto"
    assert duck_fetch["url"] == "https://example.com/article"
    assert duck_fetch["fetched_urls"] == ["https://example.com/article"]
    assert duck_fetch["start_index"] == 1000
    assert duck_fetch["max_length"] == 2500
    assert duck_fetch["runs_count"] == 1
    assert duck_fetch["content_characters"] == len(full_text)
    assert len(duck_fetch["content_excerpt"]) <= FOLLOWUP_FETCH_EXCERPT_MAX_CHARS
    assert "content truncated for follow-up context" in duck_fetch["content_excerpt"]
    assert "Specify start_index=3500 to continue." in duck_fetch["content_excerpt"]
    assert duck_fetch["content_start"] == 1000
    assert duck_fetch["content_end"] == 3500
    assert duck_fetch["content_total"] == 9000
    assert duck_fetch["has_more"] is True

    assert generic_fetch["url"] == "https://example.com/other"
    assert generic_fetch["raw"] is True
    assert generic_fetch["content_excerpt"] == "Fetched article content"


def test_extract_followup_data_preserves_brave_llm_context_sources():
    handler = _handler()
    data = {
        "brave_llm_context": {
            "query": "Regal Portland showtimes",
            "grounding": {
                "generic": [
                    {
                        "title": "Regal Movies On TV Showtimes",
                        "url": "https://www.cinemaclock.com/movie-theaters/regal-movies-on-tv",
                        "snippets": ["Current showtimes for Regal Movies On TV."],
                        "site_name": "Cinema Clock",
                        "age": "2 days ago",
                    }
                ],
                "poi": {
                    "name": "Regal Movies On TV",
                    "url": "https://regmovies.com/theatres/regal-movies-on-tv-0855",
                    "snippets": ["1234 Example Blvd, Portland OR."],
                },
            },
            "sources": {
                "https://regmovies.com/theatres/regal-movies-on-tv-0855": {
                    "site_name": "Regal",
                    "age": ["2 days ago", "2026-06-28"],
                }
            },
        }
    }

    result = handler._extract_followup_data(data)
    brave = result["brave_llm_context"]

    assert brave["query"] == "Regal Portland showtimes"
    assert brave["sources_count"] == 2
    assert brave["sources"][0]["title"] == "Regal Movies On TV Showtimes"
    assert brave["sources"][0]["site_name"] == "Cinema Clock"
    assert brave["sources"][0]["age"] == "2 days ago"
    assert brave["sources"][1]["url"] == "https://regmovies.com/theatres/regal-movies-on-tv-0855"
    assert brave["sources"][1]["site_name"] == "Regal"
    assert brave["sources"][1]["age"] == "2 days ago"


def test_compute_effective_evidence_tool_turn():
    handler = _handler()
    save_data = {
        "serpapi_yelp_search": {
            "find_desc": "pizza",
            "find_loc": "Portland, OR",
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


def test_compute_effective_evidence_includes_duckduckgo_candidates():
    handler = _handler()
    full_text = """Found 1 search result:

1. Jarvis
   URL: https://example.com/jarvis
   Summary: A relevant source.
"""
    save_data = {
        "mcp_duckduckgo_search": {"full_text": full_text},
        "_tool_trace": [
            {
                "tool": "mcp_duckduckgo_search",
                "ok": True,
                "arguments": {"query": "Jarvis"},
            }
        ],
    }

    evidence = handler._compute_effective_evidence(
        "conv1",
        save_data,
        ["mcp_duckduckgo_search"],
        {},
        "msg-web-ddg",
        "search for Jarvis",
    )

    supporting = evidence["supporting_tool_results"]["mcp_duckduckgo_search"]
    assert supporting["query"] == "Jarvis"
    assert supporting["candidates"][0]["url"] == "https://example.com/jarvis"


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
