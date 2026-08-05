#!/usr/bin/env python3
"""Tests for LLM tool-result preview truncation (orchestrator_v2)."""

import sys
import unittest
import json
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class ToolContextPreviewTests(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_url_field_allows_long_querystrings(self):
        """Regression: generic strings used to cap at 240 chars, truncating URLs."""
        long = "https://example.com/path?" + "q=" + "a" * 400
        out = self.orch._build_preview_value({"url": long, "title": "x"}, parent_key="data")
        self.assertEqual(out["url"], long)
        self.assertNotIn("[truncated]", out["url"])

    def test_non_url_string_still_short(self):
        out = self.orch._build_preview_value({"note": "x" * 500}, parent_key="data")
        self.assertIn("[truncated]", out["note"])

    def test_bookmark_search_gets_larger_preview_budget(self):
        self.assertEqual(self.orch._tool_context_max_chars("bookmark_search"), 5000)
        self.assertEqual(self.orch._tool_context_max_chars("serpapi_web_search"), 6000)
        self.assertEqual(self.orch._tool_context_max_chars("workflow"), 8000)

    def test_workflow_preview_keeps_late_step_handles_and_omits_variables_graph(self):
        steps = []
        for index in range(1, 14):
            data = {
                "content": f"step {index} " + ("large payload " * 700),
                "status": "complete",
            }
            if index == 1:
                data["stash_ref"] = "stash://research/source-1"
            if index == 13:
                data["page_id"] = "page_final_13"
                data["url"] = "https://jarvis.example/canvas/page_final_13"
            steps.append(
                {
                    "step": index,
                    "tool": "canvas" if index == 13 else "stash",
                    "ok": True,
                    "data": data,
                    "duration_ms": index * 10,
                }
            )

        result = {
            "ok": True,
            "speech": "Workflow complete.",
            "data": {
                "action": "run",
                "workflow_id": "deep_research",
                "workflow_name": "Deep Research",
                "execution": "foreground",
                "workflow_started": True,
                "workflow_completed": True,
                "steps_completed": 13,
                "component_tools_used": ["stash", "canvas"],
                "results": steps,
                "variables": {"huge": "do not expose " * 5000},
            },
        }

        preview, total, shown, truncated = self.orch._build_llm_result_context_preview(
            "workflow",
            result,
        )

        parsed = json.loads(preview)
        step_results = parsed["llm_context_preview"]["step_results"]
        self.assertTrue(truncated)
        self.assertGreater(total, shown)
        self.assertLessEqual(shown, 8000)
        self.assertEqual(len(step_results), 13)
        self.assertIn("stash://research/source-1", preview)
        self.assertIn("page_final_13", preview)
        self.assertNotIn("do not expose", preview)

    def test_search_preview_lifts_exact_source_candidates(self):
        long_blob = "x" * 9000
        result = {
            "ok": True,
            "speech": "Found 2 YouTube results.",
            "data": {
                "engine": "youtube",
                "search_query": "cheddar cheese video",
                "top_url": "https://www.youtube.com/watch?v=abc123",
                "next_page_token": long_blob,
                "results": [
                    {
                        "title": "Cheddar explained",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "video_id": "abc123",
                        "channel": "Cheese Channel",
                        "duration": "2:00",
                    },
                    {
                        "title": "Cheddar factory tour",
                        "url": "https://www.youtube.com/watch?v=def456",
                        "video_id": "def456",
                        "channel": "Food Channel",
                        "duration": "5:00",
                    },
                ],
            },
        }

        preview, _total, _shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_youtube_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertEqual(candidates[0]["url"], "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(candidates[1]["video_id"], "def456")
        self.assertIn("Cheddar factory tour", preview)

    def test_search_index_preview_keeps_fetchable_sources_and_grounding_fields(self):
        result = {
            "ok": True,
            "speech": "Found indexed sources.",
            "data": {
                "engine": "search_index",
                "query": "PostgreSQL queue patterns",
                "mode": "deep",
                "results_count": 6,
                "total_results": 314,
                "search_id": "search-index-123",
                "related_searches": ["SKIP LOCKED queue", "durable job queue"],
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "position": index,
                        "title": f"PostgreSQL source {index}",
                        "url": f"https://example.test/postgres/{index}",
                        "displayed_link": f"example.test/postgres/{index}",
                        "snippet": "Grounded source summary. " * 30,
                        "date": "Aug 1, 2026",
                        "language": "en",
                        "image_url": f"https://images.example/{index}.jpg",
                        "sitelinks": [
                            {
                                "title": "Schema",
                                "url": f"https://example.test/postgres/{index}/schema",
                            }
                        ],
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_search_index", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["url"], "https://example.test/postgres/1")
        self.assertEqual(candidates[0]["language"], "en")
        self.assertIn("Grounded source summary", candidates[0]["snippet"])
        self.assertEqual(candidates[0]["sitelinks"][0]["title"], "Schema")
        self.assertEqual(data_preview["search_id"], "search-index-123")
        self.assertNotIn("large_provider_payload", preview)

    def test_google_news_light_preview_keeps_articles_and_grouped_top_stories(self):
        result = {
            "ok": True,
            "speech": "Found recent Google News results.",
            "data": {
                "engine": "google_news_light",
                "query": "agentic AI",
                "query_displayed": "agentic AI news",
                "country": "us",
                "results_count": 6,
                "provider_results_count": 42,
                "top_stories_count": 1,
                "top_story_articles_count": 4,
                "search_id": "news-light-123",
                "has_more": True,
                "next_start": 10,
                "pagination": {
                    "current": 1,
                    "start": 0,
                    "has_more": True,
                    "next_start": 10,
                },
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "position": index,
                        "title": f"Agentic AI article {index}",
                        "url": f"https://news.example/agentic-ai/{index}",
                        "source": f"News Source {index}",
                        "thumbnail": f"https://images.example/{index}.jpg",
                        "snippet": "Grounded recent-news summary. " * 30,
                        "date": f"{index} hours ago",
                    }
                    for index in range(1, 7)
                ],
                "top_stories": [
                    {
                        "position": 1,
                        "title": "AI funding",
                        "stories_count": 4,
                        "provider_stories_count": 4,
                        "stories": [
                            {
                                "position": index,
                                "title": f"Top funding story {index}",
                                "url": f"https://finance.example/story/{index}",
                                "source": "Finance Example",
                                "date": f"{index} hours ago",
                            }
                            for index in range(1, 5)
                        ],
                    }
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_news_light", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["url"], "https://news.example/agentic-ai/1")
        self.assertIn("Grounded recent-news summary", candidates[0]["snippet"])
        self.assertEqual(data_preview["search_id"], "news-light-123")
        self.assertEqual(data_preview["pagination"]["next_start"], 10)
        self.assertEqual(data_preview["top_stories"][0]["title"], "AI funding")
        self.assertEqual(
            data_preview["top_stories"][0]["stories"][0]["url"],
            "https://finance.example/story/1",
        )
        self.assertNotIn("large_provider_payload", preview)

    def test_google_local_preview_keeps_places_provenance_ads_and_related_searches(self):
        result = {
            "ok": True,
            "speech": "Found local coffee shops.",
            "data": {
                "engine": "google_local",
                "query": "coffee",
                "location": "Portland, Oregon",
                "location_source": "jarvis_default_location",
                "provider_location_used": "Portland,Oregon,United States",
                "results_count": 6,
                "provider_results_count": 20,
                "ads_count": 1,
                "discover_more_count": 1,
                "search_id": "google-local-123",
                "has_more": True,
                "next_start": 20,
                "pagination": {
                    "current": 1,
                    "start": 0,
                    "has_more": True,
                    "next_start": 20,
                },
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "position": index,
                        "title": f"Coffee Shop {index}",
                        "url": f"https://coffee.example/{index}",
                        "website": f"https://coffee.example/{index}",
                        "place_id": str(1000 + index),
                        "rating": 4.8,
                        "reviews": 100 + index,
                        "type": "Coffee shop",
                        "address": f"{index} Market St",
                        "hours": "Open until 8 PM",
                        "description": "Independent neighborhood coffee shop. " * 20,
                        "gps_coordinates": {"latitude": 45.5, "longitude": -122.6},
                        "service_options": {"dine_in": True, "takeout": True},
                    }
                    for index in range(1, 7)
                ],
                "ads": [
                    {
                        "title": "Sponsored Coffee",
                        "url": "https://sponsor.example/",
                        "sponsored": True,
                    }
                ],
                "discover_more_places": [
                    {
                        "title": "Best coffee",
                        "url": "https://www.google.com/search?q=best+coffee&tbm=lcl",
                    }
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_local", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["url"], "https://coffee.example/1")
        self.assertEqual(candidates[0]["place_id"], "1001")
        self.assertEqual(candidates[0]["service_options"]["dine_in"], True)
        self.assertEqual(data_preview["location_source"], "jarvis_default_location")
        self.assertEqual(data_preview["pagination"]["next_start"], 20)
        self.assertIn("Sponsored Coffee", json.dumps(data_preview["ads"]))
        self.assertIn("Best coffee", json.dumps(data_preview["discover_more_places"]))
        self.assertNotIn("large_provider_payload", preview)

    def test_google_local_services_preview_keeps_provider_ids_and_resolution_cost(self):
        result = {
            "ok": True,
            "speech": "Found Local Services providers.",
            "data": {
                "engine": "google_local_services",
                "mode": "search",
                "query": "car repair shop",
                "provider_query": "auto_repair_shop",
                "location": "Phoenix, Arizona",
                "resolved_location": "Phoenix",
                "data_cid": "112233445566",
                "data_cid_source": "google_maps_resolver",
                "results_count": 6,
                "provider_results_count": 20,
                "serpapi_searches_used": 2,
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "position": index,
                        "title": f"Electrician {index}",
                        "url": f"https://services.example/{index}",
                        "rating": 4.9,
                        "reviews": 100 + index,
                        "phone": f"+16025550{index:03d}",
                        "badge": "GOOGLE GUARANTEED",
                        "service_area": "Phoenix",
                        "hours_current": "Open 24 hours",
                        "services": ["Restore power", "Repair panel"],
                        "cid": str(1000 + index),
                        "bid": str(2000 + index),
                        "pid": str(3000 + index),
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_local_services", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["cid"], "1001")
        self.assertEqual(candidates[0]["bid"], "2001")
        self.assertEqual(candidates[0]["pid"], "3001")
        self.assertEqual(candidates[0]["services"], ["Restore power", "Repair panel"])
        self.assertEqual(data_preview["data_cid_source"], "google_maps_resolver")
        self.assertEqual(data_preview["provider_query"], "auto_repair_shop")
        self.assertEqual(data_preview["serpapi_searches_used"], 2)
        self.assertNotIn("large_provider_payload", preview)

    def test_google_trends_preview_keeps_trend_summaries_and_recent_timeline(self):
        result = {
            "ok": True,
            "speech": "Analyzed Google Trends interest for two topics.",
            "data": {
                "engine": "google_trends",
                "query": "AI agents, AI assistants",
                "queries": ["AI agents", "AI assistants"],
                "data_type": "interest_over_time",
                "provider_data_type": "TIMESERIES",
                "date": "now 7-d",
                "geo": "US",
                "results_count": 2,
                "latest_period": "Aug 5, 2026",
                "timeline_points_returned": 5,
                "timeline_points_original": 5,
                "search_id": "trends-123",
                "averages": [
                    {"query": "AI agents", "value": 61},
                    {"query": "AI assistants", "value": 48},
                ],
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "title": "AI agents",
                        "query": "AI agents",
                        "latest_date": "Aug 5, 2026",
                        "latest_value": 83,
                        "previous_value": 74,
                        "change_from_previous": 9,
                        "change_over_period": 28,
                        "direction": "rising",
                        "average_value": 61,
                        "peak_value": 83,
                        "peak_date": "Aug 5, 2026",
                    },
                    {
                        "title": "AI assistants",
                        "query": "AI assistants",
                        "latest_value": 47,
                        "direction": "falling",
                    },
                ],
                "timeline_data": [
                    {
                        "date": f"Aug {day}, 2026",
                        "values": [
                            {"query": "AI agents", "extracted_value": value}
                        ],
                    }
                    for day, value in ((1, 55), (2, 60), (3, 68), (4, 74), (5, 83))
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_trends", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(candidates[0]["direction"], "rising")
        self.assertEqual(candidates[0]["change_over_period"], 28)
        self.assertEqual(data_preview["averages"][0]["value"], 61)
        self.assertEqual(
            [point["date"] for point in data_preview["timeline_sample"]],
            ["Aug 1, 2026", "Aug 3, 2026", "Aug 4, 2026", "Aug 5, 2026"],
        )
        self.assertNotIn("large_provider_payload", preview)

    def test_google_trending_now_preview_keeps_current_rows_under_real_token_sizes(self):
        result = {
            "ok": True,
            "speech": "Found current trends.",
            "data": {
                "action": "trending_now",
                "engine": "google_trends_trending_now",
                "requested_topic": "agentic ai",
                "scope_notice": (
                    "Trending Now is a seedless feed, so the requested topic "
                    "'agentic ai' was not used as a filter."
                ),
                "geo": "US",
                "hours": 24,
                "only_active": False,
                "results_count": 6,
                "provider_results_count": 50,
                "active_results_count": 42,
                "top_query": "trend 1",
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "position": index,
                        "title": f"trend {index}",
                        "query": f"trend {index}",
                        "active": index % 2 == 1,
                        "search_volume": index * 100000,
                        "increase_percentage": index * 100,
                        "category_names": ["Technology"],
                        "trend_breakdown": [f"related {index}"],
                        "google_trends_url": f"https://trends.google.com/trends/explore?q=trend+{index}",
                        "trends_api_url": "https://serpapi.com/search.json?" + "t" * 500,
                        "news_page_token": f"exact-news-token-{index}-" + "n" * 1200,
                        "news_api_url": "https://serpapi.com/search.json?" + "a" * 1700,
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_trending_now", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        data_preview = parsed["llm_context_preview"]["data_preview"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertNotIn("data_preview_text", parsed["llm_context_preview"])
        self.assertEqual(candidates[0]["query"], "trend 1")
        self.assertEqual(candidates[0]["search_volume"], 100000)
        self.assertNotIn("news_page_token", candidates[0])
        self.assertNotIn("news_api_url", candidates[0])
        self.assertNotIn("trends_api_url", candidates[0])
        self.assertFalse(candidates[1]["active"])
        self.assertEqual(data_preview["hours"], 24)
        self.assertEqual(data_preview["active_results_count"], 42)
        self.assertEqual(data_preview["requested_topic"], "agentic ai")
        self.assertIn("seedless feed", data_preview["scope_notice"])
        self.assertNotIn("large_provider_payload", preview)

    def test_google_trending_now_news_preview_keeps_article_urls(self):
        result = {
            "ok": True,
            "speech": "Found associated news.",
            "data": {
                "action": "news",
                "engine": "google_trends_news",
                "trend_query": "agentic ai",
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "title": f"Agentic article {index}",
                        "url": f"https://news.example/article-{index}",
                        "source": "Example News",
                        "date": f"{index} hours ago",
                        "thumbnail": f"https://images.example/article-{index}.jpg",
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, _shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_google_trending_now", result
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertEqual(candidates[0]["url"], "https://news.example/article-1")
        self.assertEqual(candidates[0]["source"], "Example News")
        self.assertEqual(candidates[0]["date"], "1 hours ago")

    def test_hotel_preview_keeps_compact_prices_pet_status_and_urls(self):
        result = {
            "ok": True,
            "speech": "Found 6 hotel options. Lowest returned price is $113 total.",
            "data": {
                "engine": "google_hotels",
                "destination": "Mesa, Arizona",
                "raw": {"large_provider_payload": "x" * 12000},
                "top_results": [
                    {
                        "title": f"Mesa Hotel {index}",
                        "url": f"https://hotels.example/{index}",
                        "rating": 4.0 + (index / 10),
                        "price_total": f"${110 + index}",
                        "price_per_night": f"${55 + index}",
                        "amenities": (
                            ["Free Wi-Fi", "Pet-friendly"]
                            if index % 2
                            else ["Free Wi-Fi", "Pool"]
                        ),
                        "description": "details " * 200,
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_hotel_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["price_total"], "$111")
        self.assertEqual(candidates[0]["price_per_night"], "$56")
        self.assertEqual(candidates[0]["rating"], 4.1)
        self.assertTrue(candidates[0]["pet_friendly"])
        self.assertFalse(candidates[1]["pet_friendly"])
        self.assertEqual(candidates[4]["url"], "https://hotels.example/5")
        self.assertNotIn("amenities", candidates[0])

    def test_yelp_preview_keeps_compact_business_identity_and_details(self):
        result = {
            "ok": True,
            "speech": "Found 6 Yelp options.",
            "data": {
                "engine": "yelp",
                "find_desc": "coffee shops",
                "find_loc": "Hillsboro, OR",
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "title": f"Hillsboro Cafe {index}",
                        "url": f"https://www.yelp.com/biz/hillsboro-cafe-{index}",
                        "place_id": f"place-{index}",
                        "rating": 4.0 + (index / 10),
                        "reviews": index * 100,
                        "price": "$$",
                        "categories": ["Coffee & Tea", "Cafes"],
                        "neighborhoods": "Hillsboro",
                        "open_state": "Open until 8:00 PM",
                        "snippet": "A locally grounded Yelp snippet. " * 20,
                        "service_options": {"takeout": True},
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_yelp_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["place_id"], "place-1")
        self.assertEqual(candidates[0]["reviews"], 100)
        self.assertEqual(candidates[0]["categories"], ["Coffee & Tea", "Cafes"])
        self.assertEqual(candidates[0]["neighborhoods"], "Hillsboro")
        self.assertEqual(candidates[0]["open_state"], "Open until 8:00 PM")
        self.assertIn("locally grounded", candidates[0]["snippet"])
        self.assertEqual(
            candidates[4]["url"],
            "https://www.yelp.com/biz/hillsboro-cafe-5",
        )
        self.assertNotIn("service_options", candidates[0])

    def test_tripadvisor_preview_keeps_place_ids_and_followup_evidence(self):
        result = {
            "ok": True,
            "speech": "Found 6 Tripadvisor options.",
            "data": {
                "action": "search",
                "engine": "tripadvisor",
                "query": "Rome",
                "category": "things_to_do",
                "raw": {"large_provider_payload": "x" * 12000},
                "results": [
                    {
                        "title": f"Rome attraction {index}",
                        "url": f"https://www.tripadvisor.com/Attraction-d{index}.html",
                        "place_id": str(190000 + index),
                        "place_type": "ATTRACTION",
                        "rating": 4.0 + (index / 10),
                        "reviews": index * 1000,
                        "location": "Rome, Italy",
                        "description": "Historically grounded attraction details. " * 20,
                        "provider_only": {"large": "omit me"},
                    }
                    for index in range(1, 7)
                ],
            },
        }

        preview, _total, shown, truncated = self.orch._build_llm_result_context_preview(
            "serpapi_tripadvisor",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertLessEqual(shown, 6000)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(candidates[0]["place_id"], "190001")
        self.assertEqual(candidates[0]["place_type"], "ATTRACTION")
        self.assertEqual(candidates[0]["location"], "Rome, Italy")
        self.assertEqual(candidates[0]["reviews"], 1000)
        self.assertIn("Historically grounded", candidates[0]["description"])
        self.assertNotIn("provider_only", candidates[0])

    def test_flight_preview_keeps_compact_option_identity_including_flight_numbers(self):
        result = {
            "ok": True,
            "speech": "Found 2 round-trip flight options from PDX to PHX.",
            "data": {
                "provider": "serpapi",
                "trip_type": "round_trip",
                "departure_id": "PDX",
                "arrival_id": "PHX",
                "outbound_date": "2099-09-15",
                "return_date": "2099-09-20",
                "currency": "USD",
                "results_count": 2,
                "cheapest_price": 257,
                "price_basis": "round_trip_total",
                "booking_url": "https://www.google.com/travel/flights",
                "results": [
                    {
                        "price": 257 + index,
                        "airlines": ["Alaska"],
                        "flight_numbers": [f"AS {1349 + index}"],
                        "departure_airport": "PDX",
                        "departure_time": f"2099-09-15 0{7 + index}:03",
                        "arrival_airport": "PHX",
                        "arrival_time": f"2099-09-15 {9 + index:02d}:51",
                        "duration_display": "2h 48m",
                        "stops_label": "Nonstop",
                        "segments": [{"flight_number": f"AS {1349 + index}"}],
                    }
                    for index in range(2)
                ],
            },
        }

        preview, total, shown, truncated = self.orch._build_llm_result_context_preview(
            "flight_search",
            result,
        )

        parsed = json.loads(preview)
        candidates = parsed["llm_context_preview"]["source_candidates"]
        self.assertTrue(truncated)
        self.assertGreater(total, shown)
        self.assertEqual(candidates[0]["airlines"], ["Alaska"])
        self.assertEqual(candidates[0]["departure_time"], "2099-09-15 07:03")
        self.assertEqual(candidates[0]["arrival_time"], "2099-09-15 09:51")
        self.assertEqual(candidates[0]["price"], 257)
        self.assertEqual(candidates[0]["flight_numbers"], ["AS 1349"])
        self.assertIn("AS 1349", preview)
        self.assertNotIn("segments", candidates[0])

    def test_turn_context_marks_truncated_arguments_as_display_only(self):
        self.orch.timezone = ZoneInfo("America/Los_Angeles")
        context = self.orch._build_turn_context(
            "update bugs intel",
            [
                {
                    "tool": "manage_intel",
                    "arguments": {
                        "action": "append",
                        "path": "2026-garden-bugs.md",
                        "content": "Widow Skimmer\n" + ("details " * 200) + "Hoverfly",
                    },
                    "result": {"ok": True, "speech": "Append complete", "data": {}},
                    "meta": {},
                }
            ],
        )

        self.assertIn("Arguments Meta: arguments_truncated=true", context)
        self.assertIn("complete arguments were sent to the tool", context)
        self.assertIn("does not indicate partial execution", context)

    def test_provider_result_marks_truncated_arguments(self):
        assembler = self.orch._get_context_assembler()
        message, metadata = assembler.build_provider_tool_result_message(
            tool_name="manage_intel",
            arguments={"action": "append", "path": "bugs.md", "content": "x" * 2000},
            result={"ok": True, "speech": "Append complete", "data": {"appended": True}},
            max_chars=1800,
        )

        self.assertTrue(metadata["arguments_truncated"])
        self.assertIn("arguments_truncated=true", message)
        self.assertIn("preview does not indicate partial execution", message)

    def test_provider_result_marks_complete_arguments_untruncated(self):
        assembler = self.orch._get_context_assembler()
        message, metadata = assembler.build_provider_tool_result_message(
            tool_name="manage_intel",
            arguments={"action": "read", "path": "bugs.md"},
            result={"ok": True, "speech": "Read complete", "data": {"size_bytes": 42}},
            max_chars=1800,
        )

        self.assertFalse(metadata["arguments_truncated"])
        self.assertIn("arguments_truncated=false", message)


if __name__ == "__main__":
    unittest.main()
