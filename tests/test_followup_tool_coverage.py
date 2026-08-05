#!/usr/bin/env python3
"""Contract coverage for every enabled Jarvis follow-up payload."""

import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR_PATH = (
    PROJECT_ROOT / "jarvis-web" / "server" / "services" / "followup_extractor.py"
)
SPEC = importlib.util.spec_from_file_location("followup_extractor_coverage", EXTRACTOR_PATH)
followup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(followup)


def _case(payload, arguments=None):
    return payload, arguments


# One representative successful data payload per enabled local tool. Complex,
# multi-action adapters have additional focused tests below.
LOCAL_TOOL_SAMPLES = {
    "acknowledge_alerts": _case({"alert_id": 7, "acknowledged": True}),
    "acknowledge_reminders": _case(
        {"acknowledged_count": 2, "acknowledged_ids": [11, 12]}
    ),
    "analyze_image": _case(
        {
            "analysis": "The image contains a red bicycle beside a blue door.",
            "source_count": 1,
            "sources": ["stash://images/bicycle"],
            "stash_ref": "stash://images/bicycle",
        }
    ),
    "api_call": _case(
        {
            "url": "https://api.example.test/items/7",
            "method": "GET",
            "status_code": 200,
            "response": {
                "id": 7,
                "status": "ready",
                "access_token": "SECRET_SENTINEL",
                "headers": {"Set-Cookie": "SECRET_SENTINEL"},
            },
        }
    ),
    "bookmark_search": _case(
        {
            "query": "postgres",
            "matched_count": 1,
            "results": [
                {
                    "title": "Postgres queues",
                    "url": "https://example.test/postgres",
                    "date": "2026-07-01",
                }
            ],
        }
    ),
    "brave_llm_context": _case(
        {
            "query": "Jarvis",
            "grounding": {
                "generic": [
                    {
                        "title": "Jarvis reference",
                        "url": "https://example.test/jarvis",
                        "snippets": ["A useful grounded result."],
                    }
                ]
            },
        }
    ),
    "calculator": _case({"expression": "2+2", "result": 4.0, "type": "expression"}),
    "canvas": _case(
        {
            "page_id": "page_7",
            "title": "Research notes",
            "content": "# Research notes\nUseful details",
            "content_length": 31,
        },
        {"action": "read", "page_id": "page_7"},
    ),
    "check_opencode_sessions": _case(
        {
            "count": 1,
            "sessions": [
                {
                    "session_id": "ses_7",
                    "title": "Fix tests",
                    "status": "completed",
                }
            ],
        }
    ),
    "check_tool_logs": _case(
        {
            "logs": [
                {
                    "timestamp": "2026-07-29T10:00:00Z",
                    "tool": "get_time",
                    "status": "ok",
                    "duration_ms": 250,
                }
            ]
        }
    ),
    "convert_file": _case(
        {
            "stash_ref": "stash://converted/audio",
            "filename": "audio.mp3",
            "source_format": "wav",
            "target_format": "mp3",
        }
    ),
    "crawl_url": _case(
        {
            "results": [
                {
                    "results": [
                        {
                            "url": "https://example.test/article",
                            "title": "Article",
                            "success": True,
                            "markdown": "large body omitted",
                        }
                    ]
                }
            ]
        }
    ),
    "create_alert": _case(
        {
            "alert_id": 9,
            "title": "Freezer warning",
            "status": "pending",
            "severity": "critical",
        }
    ),
    "create_reminder": _case(
        {"reminder_id": 19, "formatted_time": "tomorrow at 9:00 AM"}
    ),
    "create_social_clip": _case(
        {
            "task_id": "clip_7",
            "title": "Launch clip",
            "video_url": "https://cdn.example.test/clip.mp4",
            "stash_ref": "stash://clips/clip_7",
            "filename": "clip.mp4",
        }
    ),
    "crypto_chart": _case(
        {
            "coin": "Bitcoin",
            "coin_id": "bitcoin",
            "current_price": 100000,
            "change_percent": 1.2,
            "series": {
                "prices": [
                    {"iso": "2026-07-28T00:00:00Z", "value": 98000},
                    {"iso": "2026-07-29T00:00:00Z", "value": 100000},
                ]
            },
        }
    ),
    "crypto_price": _case(
        {
            "coin": "Bitcoin",
            "coin_id": "bitcoin",
            "price_usd": 100000,
            "change_24h_percent": 1.2,
            "market_cap_usd": 2000000000000,
        }
    ),
    "deep_memory_search": _case(
        {
            "query": "family visit",
            "mode": "keyword",
            "flat_results": [
                {
                    "id": "page_7",
                    "title": "Family visit",
                    "_source": "canvas",
                    "snippet": "Arrival details",
                    "content": "full content omitted",
                }
            ],
        }
    ),
    "docker_control": _case(
        {
            "count": 1,
            "containers": [
                {
                    "id": "abc123",
                    "name": "jarvis-web",
                    "status": "running",
                    "image": "jarvis-web:latest",
                }
            ],
        },
        {"action": "list"},
    ),
    "execute_bash": _case(
        {
            "command": "printf smoke",
            "exit_code": 0,
            "stdout": "smoke ok",
            "stderr": "",
        },
        {"command": "printf smoke"},
    ),
    "flight_search": _case(
        {
            "provider": "serpapi",
            "trip_type": "round_trip",
            "departure_id": "PDX",
            "arrival_id": "PHX",
            "outbound_date": "2099-09-15",
            "return_date": "2099-09-20",
            "results_count": 1,
            "cheapest_price": 257,
            "price_basis": "round_trip_total",
            "booking_url": "https://www.google.com/travel/flights",
            "results": [
                {
                    "price": 257,
                    "airlines": ["Alaska"],
                    "flight_numbers": ["AS 1349"],
                    "departure_airport": "PDX",
                    "departure_time": "2099-09-15 07:03",
                    "arrival_airport": "PHX",
                    "arrival_time": "2099-09-15 09:51",
                    "duration_display": "2h 48m",
                    "stops_label": "Nonstop",
                    "segments": [{"large": "nested detail not needed in follow-up"}],
                }
            ],
        }
    ),
    "forget": _case(
        {"deleted_ids": [31, 32], "deleted_keys": ["old_a", "old_b"]}
    ),
    "generate_image": _case(
        {
            "provider": "openai",
            "model": "gpt-image",
            "aspect_ratio": "1:1",
            "mime_type": "image/png",
            "saved": {
                "stash_ref": "stash://images/generated",
                "filename": "generated.png",
            },
        }
    ),
    "generate_music": _case(
        {
            "provider": "Google Gemini",
            "model": "lyria",
            "title": "Midnight Drive",
            "duration_seconds": 90,
            "song_id": "song_7",
            "instrumental": False,
            "synthid_watermarked": True,
            "stash_ref": "stash://music/song_7",
        }
    ),
    "generate_video": _case(
        {
            "provider": "xai",
            "model": "grok-video",
            "duration": 8,
            "video_url": "https://cdn.example.test/video.mp4",
            "saved": {
                "stash_ref": "stash://videos/video_7",
                "filename": "video.mp4",
            },
        }
    ),
    "get_recent_conversations": _case(
        {
            "count": 1,
            "conversations": [
                {
                    "conversation_id": "conv_7",
                    "title": "Payload audit",
                    "updated_at": "2026-07-29T10:00:00Z",
                }
            ],
        }
    ),
    "get_time": _case(
        {
            "date": "2026-07-29",
            "date_formatted": "July 29, 2026",
            "day_of_week": "Wednesday",
            "time": "10:00",
            "time_12h": "10:00 AM",
            "timezone": "America/Los_Angeles",
        }
    ),
    "git_release_notes": _case(
        {
            "release_tag": "v1.2.3",
            "release_url": "https://github.com/example/repo/releases/tag/v1.2.3",
            "stash_ref": "stash://releases/v1.2.3",
            "canvas_page_id": "page_release",
            "repo": "repo",
            "owner": "example",
        }
    ),
    "ingest_intel": _case(
        {"ingested": True, "new_files": 2, "total_facts": 17, "partial": False}
    ),
    "list_alerts": _case(
        {
            "count": 1,
            "alerts": [
                {
                    "alert_id": 7,
                    "title": "Freezer warning",
                    "status": "pending",
                    "severity": "critical",
                }
            ],
        }
    ),
    "list_reminders": _case(
        {
            "count": 1,
            "reminders": [
                {
                    "reminder_id": 8,
                    "title": "Water garden",
                    "status": "pending",
                    "due_at": "2026-07-30T09:00:00Z",
                }
            ],
        }
    ),
    "manage_intel": _case(
        {
            "action": "read",
            "file": "project.md",
            "content": "A" * 12000,
            "size_bytes": 12000,
            "file_sha256": "a" * 64,
        },
        {"action": "read", "path": "project.md"},
    ),
    "memory_deduper": _case(
        {
            "action": "analyze",
            "stash_ref": "stash://dedupe/report",
            "canvas_page_id": "page_dedupe",
        }
    ),
    "network_tools": _case(
        {
            "reachable": True,
            "packets_sent": 1,
            "packets_received": 1,
            "packet_loss_percent": 0.0,
            "avg_ms": 0.1,
            "raw_output": "large raw output omitted",
        }
    ),
    "opencode": _case(
        {
            "session_id": "ses_7",
            "task_type": "code",
            "opencode_result": {"info": {"status": "completed"}, "parts": ["Fixed tests"]},
        }
    ),
    "pdf_create": _case(
        {
            "space_id": "pdfs",
            "file_id": "document",
            "name": "document.pdf",
            "ref": "stash://pdfs/document",
            "size_bytes": 4096,
        }
    ),
    "pdf_read": _case(
        {
            "text": "Extracted PDF text",
            "page_count": 2,
            "char_count": 18,
            "stash_ref": "stash://pdfs/document",
        },
        {"action": "extract_text", "stash_ref": "stash://pdfs/document"},
    ),
    "phone_call": _case(
        {
            "call_id": "call_7",
            "duration": 92,
            "saved_to_canvas": True,
            "canvas_location": "page_calls",
            "summary": "The recipient confirmed the appointment.",
            "transcript": "Jarvis: Is Tuesday at ten okay?\nRecipient: Yes.",
            "follow_up_hints": ["Send the confirmation details."],
        }
    ),
    "price_alert": _case(
        {
            "count": 1,
            "alerts": [
                {
                    "id": "BTC-above",
                    "name": "Bitcoin above 100k",
                    "status": "active",
                    "symbol": "BTC",
                    "condition": "above",
                    "value": 100000,
                }
            ],
        }
    ),
    "printer": _case({"job_id": 44, "message": "Queued", "ok": True}),
    "qr_code_generator": _case(
        {
            "stash_ref": "stash://qr/code_7",
            "filename": "code.png",
            "size_bytes": 1200,
        }
    ),
    "query_service_logs": _case(
        {
            "stats": {
                "reminder_scheduler": {
                    "total_actions": 4,
                    "total_errors": 0,
                }
            },
            "logs": {
                "reminder_scheduler": [
                    {
                        "timestamp": "2026-07-29T10:00:00Z",
                        "event_type": "action",
                        "message": "Processed reminder 7",
                    }
                ]
            },
        }
    ),
    "recall": _case(
        {"memories": []},
        {"query": "payload audit sentinel", "limit": 1},
    ),
    "release_watch": _case(
        {
            "watch_id": "yt-dlp",
            "source": "pypi",
            "project": "yt-dlp",
            "initialized": False,
            "changed": False,
            "regression_detected": False,
            "current_version": "2026.7.4",
        }
    ),
    "remember": _case(
        {"memory_id": 77, "key": "payload_audit", "category": "technical"}
    ),
    "samantha": _case(
        {},
        {
            "message": "Review the payload audit.",
            "session": "jarvis",
            "priority": "normal",
        },
    ),
    "schedule_task": _case(
        {
            "count": 1,
            "tasks": [
                {
                    "task_id": 17,
                    "name": "Daily check",
                    "status": "enabled",
                    "next_run": "2026-07-30T11:00:00-07:00",
                }
            ],
        }
    ),
    "screenshot_url": _case(
        {
            "url": "https://example.test",
            "screenshot_path": "/tmp/example.png",
            "stash_ref": "stash://screenshots/example",
        }
    ),
    "search_conversations": _case(
        {
            "count": 1,
            "match_mode": "all_terms",
            "conversations": [
                {
                    "conversation_id": "conv_8",
                    "title": "Tool follow-up",
                    "updated_at": "2026-07-29T11:00:00Z",
                }
            ],
        },
        {"query": "tool follow-up", "match_mode": "all_terms"},
    ),
    "search_docs": _case(
        {
            "query": "follow-up",
            "result_count": 1,
            "documentation": "Use compact payload adapters.",
            "results": [
                {
                    "title": "Tool documentation",
                    "path": "skills/README.md",
                }
            ],
        }
    ),
    "search_memory": _case(
        {
            "count": 1,
            "memories": [
                {
                    "id": 77,
                    "key": "payload_audit",
                    "value": "Cover every tool",
                    "category": "technical",
                }
            ],
        }
    ),
    "semantic_recall": _case(
        {
            "count": 1,
            "memories": [
                {
                    "id": 78,
                    "key": "followup_context",
                    "value": "Keep it concise",
                    "category": "preference",
                    "similarity": 0.95,
                }
            ],
        }
    ),
    "send_email": _case(
        {"to": "user@example.test", "subject": "Report", "status": "sent"}
    ),
    "send_webhook": _case(
        {
            "webhooks": [
                {
                    "name": "notify",
                    "status": "available",
                    "description": "Notification endpoint",
                }
            ]
        },
        {"webhook": "list"},
    ),
    "serpapi_ebay_product": _case(
        {
            "engine": "ebay_product",
            "product_id": "123",
            "results": [
                {
                    "title": "Camera",
                    "url": "https://example.test/camera",
                    "product_id": "123",
                    "thumbnail": "https://example.test/camera.jpg",
                }
            ],
        }
    ),
    "serpapi_ebay_search": _case(
        {
            "engine": "ebay",
            "query": "camera",
            "results": [
                {
                    "title": "Camera",
                    "url": "https://example.test/camera",
                    "product_id": "123",
                    "price": {"raw": "$100"},
                }
            ],
        }
    ),
    "serpapi_home_depot": _case(
        {
            "engine": "home_depot",
            "query": "drill",
            "results": [
                {
                    "title": "Cordless drill",
                    "url": "https://example.test/drill",
                    "product_id": "HD7",
                    "price_formatted": "$99",
                }
            ],
        }
    ),
    "serpapi_hotel_search": _case(
        {
            "engine": "google_hotels",
            "query": "Seattle",
            "destination": "Seattle",
            "check_in_date": "2026-08-11",
            "check_out_date": "2026-08-13",
            "nights": 2,
            "sort_by": "price",
            "applied_filters": {"rating": 8, "free_cancellation": True},
            "currency": "USD",
            "cheapest_price_total": 400,
            "price_basis": "lowest_listed_total_for_entire_stay",
            "results": [
                {
                    "title": "Harbor Hotel",
                    "property_id": "hotel-harbor-1",
                    "url": "https://example.test/hotel",
                    "price_total": "$400",
                }
            ],
        }
    ),
    "serpapi_maps_search": _case(
        {
            "engine": "google_maps",
            "query": "coffee",
            "results": [
                {
                    "title": "Coffee shop",
                    "url": "https://example.test/coffee",
                    "place_id": "place_7",
                    "rating": 4.8,
                }
            ],
        }
    ),
    "serpapi_search_index": _case(
        {
            "engine": "search_index",
            "query": "payload adapters",
            "mode": "standard",
            "results_count": 1,
            "total_results": 9,
            "search_id": "search-index-coverage",
            "source": "SerpApi Search Index",
            "results": [
                {
                    "position": 1,
                    "title": "Payload adapters",
                    "url": "https://example.test/search-index-result",
                    "displayed_link": "example.test/search-index-result",
                    "snippet": "A source candidate with a fetchable URL.",
                    "language": "en",
                }
            ],
        }
    ),
    "serpapi_tripadvisor": _case(
        {
            "action": "search",
            "engine": "tripadvisor",
            "query": "Rome",
            "category": "all",
            "tripadvisor_domain": "www.tripadvisor.com",
            "place_id": "187791",
            "results_count": 1,
            "serpapi_searches_used": 1,
            "source": "SerpApi Tripadvisor",
            "results": [
                {
                    "title": "Rome",
                    "place_id": "187791",
                    "place_type": "GEO",
                    "url": "https://www.tripadvisor.com/Tourism-g187791-Rome.html",
                    "location": "Lazio, Italy",
                    "description": "Historic city with museums, food, and monuments.",
                }
            ],
        }
    ),
    "serpapi_yelp_search": _case(
        {
            "engine": "yelp",
            "find_desc": "coffee shops",
            "find_loc": "Hillsboro, OR",
            "sort_by": "rating",
            "sort_basis": "local_sort_of_returned_page",
            "results_count": 1,
            "provider_results_count": 10,
            "serpapi_searches_used": 1,
            "source": "SerpApi Yelp",
            "results": [
                {
                    "title": "Cabana do Cafe",
                    "url": "https://www.yelp.com/biz/cabana-do-cafe-hillsboro",
                    "place_id": "provider-place-id",
                    "rating": 4.8,
                    "reviews": 24,
                    "price": "$$",
                    "categories": ["Cafes", "Coffee & Tea"],
                    "neighborhoods": "Hillsboro",
                    "open_state": "Open until 8:00 PM",
                    "snippet": "Brazilian coffee and pastries.",
                }
            ],
        }
    ),
    "serpapi_amazon_search": _case(
        {
            "engine": "amazon",
            "query": "headphones",
            "results": [
                {
                    "title": "Headphones",
                    "asin": "B000000007",
                    "url": "https://example.test/headphones",
                    "price": "$50",
                }
            ],
        }
    ),
    "serpapi_youtube": _case(
        {
            "video_id": "abc123",
            "url": "https://youtube.test/watch?v=abc123",
            "title": "Payload adapters",
            "channel": "Jarvis",
            "duration": "10:00",
            "transcript_api_url": "https://api.example.test/transcript/abc123",
        }
    ),
    "serpapi_youtube_search": _case(
        {
            "search_query": "payload adapters",
            "results": [
                {
                    "video_id": "abc123",
                    "url": "https://youtube.test/watch?v=abc123",
                    "title": "Payload adapters",
                    "channel": "Jarvis",
                    "duration": "10:00",
                }
            ],
        }
    ),
    "speaker_volume": _case({"volume": 35, "muted": False, "card": "Volume 35%"}),
    "spotify": _case(
        {"playing": True, "name": "Unsung", "artist": "Helmet", "uri": "track:7"}
    ),
    "ssh_remote": _case(
        {
            "count": 1,
            "hosts": [
                {
                    "alias": "vps",
                    "hostname": "vps.example.test",
                    "status": "configured",
                }
            ],
        },
        {"action": "list_hosts"},
    ),
    "stash": _case(
        {
            "spaces": [
                {
                    "space_id": "space_7",
                    "name": "Payload audit",
                    "status": "active",
                    "files_count": 2,
                }
            ]
        },
        {"action": "list"},
    ),
    "status_recap": _case(
        {
            "stash_ref": "stash://status/report",
            "canvas_id": "page_status",
            "image_ref": "stash://status/image",
            "failures": [],
        }
    ),
    "stock_price": _case(
        {
            "symbol": "AAPL",
            "company": "Apple",
            "price_usd": 210.5,
            "change_today_percent": 1.1,
            "market_cap_usd": 3000000000000,
            "source": "Yahoo Finance",
        }
    ),
    "supa_crawl_knowledge": _case(
        {
            "action": "search",
            "query": "payload",
            "count": 1,
            "results": [
                {
                    "page_id": 7,
                    "site_id": 2,
                    "title": "Payload guide",
                    "url": "https://example.test/payload",
                    "similarity": 0.91,
                }
            ],
        }
    ),
    "system_monitor": _case(
        {
            "status": "healthy",
            "issue_count": 0,
            "highest_severity": "none",
            "summary_markdown": "System health is normal.",
            "cpu": {"total_percent": 12.5, "logical_cores": 8},
            "memory": {
                "ram": {"percent": 42.0, "used_gb": 6.7, "total_gb": 16.0},
                "swap": {"percent": 0.0},
            },
            "uptime": {"uptime_string": "2 days"},
        }
    ),
    "text_summarizer": _case(
        {
            "keywords": [
                {"keyword": "payload", "frequency": 7},
                {"keyword": "followup", "frequency": 5},
            ],
            "source": {
                "stash_ref": "stash://docs/payload",
                "space_id": "docs",
                "file_id": "payload",
            },
        },
        {"operation": "keywords", "stash_ref": "stash://docs/payload"},
    ),
    "tool_search": _case(
        {
            "query": "make a PDF",
            "count": 1,
            "matches": [
                {
                    "name": "pdf_create",
                    "score": 0.97,
                    "status": "available",
                }
            ],
        }
    ),
    "update_memory": _case(
        {
            "memory_id": 77,
            "old_value": "partial coverage",
            "new_value": "full coverage",
        }
    ),
    "upload_cloudflare": _case(
        {
            "url": "https://imagedelivery.example.test/image_7/public",
            "image_id": "image_7",
            "filename": "image.png",
        }
    ),
    "weather": _case(
        {
            "location": "Seattle",
            "temperature": 72,
            "feels_like": 71,
            "condition": "Clear",
            "humidity": 48,
            "wind_speed": 5,
            "wind_unit": "mph",
            "provider": "Open-Meteo",
            "daily_forecast": [
                {
                    "date": "2026-07-30",
                    "condition": "Sunny",
                    "high": 75,
                    "low": 58,
                }
            ],
        }
    ),
    "workflow": _case(
        {
            "action": "search",
            "query": "research",
            "count": 1,
            "matches": [
                {
                    "id": "research",
                    "name": "Research workflow",
                    "status": "available",
                }
            ],
        },
        {"action": "search", "query": "research"},
    ),
    "youtube_transcript": _case(
        {
            "video_title": "Payload adapters",
            "srt_stash_ref": "stash://youtube/transcript.srt",
            "md_stash_ref": "stash://youtube/transcript.md",
            "space_id": "youtube",
        }
    ),
    "youtube_video": _case(
        {
            "video_title": "Payload adapters",
            "stash_ref": "stash://youtube/video",
            "filename": "video.mp4",
            "duration_seconds": 600,
            "channel": "Jarvis",
        }
    ),
}


MCP_TOOL_SAMPLES = {
    "mcp_brave_search_brave_image_search": _case(
        {
            "raw": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "type": "object",
                            "items": [
                                {
                                    "title": "Codex logo",
                                    "url": "https://example.test/logo-page",
                                    "confidence": "high",
                                    "properties": {
                                        "url": "https://example.test/logo.png",
                                        "width": 640,
                                        "height": 640,
                                    },
                                }
                            ],
                        }
                    ),
                }
            ]
        },
        {"query": "Codex logo", "count": 1},
    ),
    "mcp_brave_search_brave_local_search": _case(
        {
            "full_text": json.dumps(
                {
                    "title": "Coffee shop",
                    "url": "https://example.test/coffee",
                    "description": "Coffee near downtown.",
                }
            )
        },
        {"query": "coffee", "count": 1},
    ),
    "mcp_brave_search_brave_place_search": _case(
        {
            "full_text": json.dumps(
                {
                    "type": "locations",
                    "results": [
                        {
                            "title": "Space Needle",
                            "url": "https://example.test/space-needle",
                            "description": "Observation tower",
                            "coordinates": [47.6205, -122.3493],
                        }
                    ],
                }
            )
        },
        {"query": "Space Needle", "location": "Seattle", "count": 1},
    ),
    "mcp_brave_search_brave_video_search": _case(
        {
            "full_text": json.dumps(
                {
                    "url": "https://video.example.test/7",
                    "title": "Payload adapters",
                    "description": "A concise walkthrough.",
                    "duration": "06:52",
                    "thumbnail_url": "https://video.example.test/7.jpg",
                }
            )
        },
        {"query": "payload adapters", "count": 1},
    ),
    "mcp_brave_search_brave_web_search": _case(
        {
            "full_text": json.dumps(
                {
                    "url": "https://example.test/followup",
                    "title": "Follow-up adapters",
                    "description": "Compact result context.",
                }
            )
        },
        {"query": "follow-up adapters", "count": 1},
    ),
    "mcp_fetch_fetch": _case(
        {"full_text": "Fetched article content"},
        {"url": "https://example.test/followup"},
    ),
}


def _enabled_local_tool_names():
    names = set()
    manifests = list((PROJECT_ROOT / "skills").glob("*.tool.json"))
    manifests.extend((PROJECT_ROOT / "skills" / "auto-tools").glob("*.tool.json"))
    for manifest in manifests:
        config = json.loads(manifest.read_text(encoding="utf-8"))
        if config.get("enabled", True):
            names.add(config["name"])
    return names


def test_every_enabled_local_tool_has_an_audited_payload_sample():
    assert set(LOCAL_TOOL_SAMPLES) == _enabled_local_tool_names()


@pytest.mark.parametrize(
    ("tool_name", "case"),
    sorted({**LOCAL_TOOL_SAMPLES, **MCP_TOOL_SAMPLES}.items()),
)
def test_every_current_tool_payload_produces_bounded_followup_context(tool_name, case):
    payload, arguments = case
    payload = dict(payload)
    payload["api_token"] = "SECRET_SENTINEL"
    data = {tool_name: payload}
    if arguments is not None:
        data["_tool_trace"] = [
            {"tool": tool_name, "ok": True, "arguments": arguments}
        ]

    result = followup.extract_followup_data(data)

    assert result is not None
    assert tool_name in result
    compact = result[tool_name]
    assert compact
    if tool_name not in {"recall", "samantha"}:
        assert set(compact) - {"request"}
    encoded = json.dumps(
        compact,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    assert json.loads(encoded) == compact
    assert "SECRET_SENTINEL" not in encoded
    assert len(encoded) <= 8000


def test_flight_search_followup_keeps_option_identity_without_nested_segments():
    payload, _ = LOCAL_TOOL_SAMPLES["flight_search"]

    result = followup.extract_followup_data({"flight_search": payload})["flight_search"]

    assert result["provider"] == "serpapi"
    assert result["price_basis"] == "round_trip_total"
    assert result["booking_url"] == "https://www.google.com/travel/flights"
    assert result["candidates"] == [
        {
            "price": 257,
            "departure_time": "2099-09-15 07:03",
            "arrival_time": "2099-09-15 09:51",
            "duration_display": "2h 48m",
            "stops_label": "Nonstop",
            "departure_airport": "PDX",
            "arrival_airport": "PHX",
            "airlines": "Alaska",
            "flight_numbers": "AS 1349",
        }
    ]
    assert "segments" not in result["candidates"][0]

    wrapped = followup.extract_followup_data(
        {"flight_search": {"ok": True, "data": payload}}
    )["flight_search"]
    assert wrapped["candidates"] == result["candidates"]


def test_hotel_search_followup_keeps_stay_context_and_property_identity():
    payload, _ = LOCAL_TOOL_SAMPLES["serpapi_hotel_search"]

    result = followup.extract_followup_data(
        {"serpapi_hotel_search": payload}
    )["serpapi_hotel_search"]

    assert result["destination"] == "Seattle"
    assert result["check_in_date"] == "2026-08-11"
    assert result["check_out_date"] == "2026-08-13"
    assert result["nights"] == 2
    assert result["sort_by"] == "price"
    assert result["applied_filters"] == {"rating": 8, "free_cancellation": True}
    assert result["cheapest_price_total"] == 400
    assert result["price_basis"] == "lowest_listed_total_for_entire_stay"
    assert result["candidates"][0]["property_id"] == "hotel-harbor-1"
    assert result["candidates"][0]["price_total"] == "$400"


def test_yelp_search_followup_keeps_business_identity_and_comparison_fields():
    payload, _ = LOCAL_TOOL_SAMPLES["serpapi_yelp_search"]

    result = followup.extract_followup_data(
        {"serpapi_yelp_search": payload}
    )["serpapi_yelp_search"]

    assert result["find_loc"] == "Hillsboro, OR"
    assert result["sort_by"] == "rating"
    assert result["sort_basis"] == "local_sort_of_returned_page"
    assert result["provider_results_count"] == 10
    assert result["serpapi_searches_used"] == 1
    assert result["candidates"][0]["place_id"] == "provider-place-id"
    assert result["candidates"][0]["reviews"] == 24
    assert result["candidates"][0]["categories"] == ["Cafes", "Coffee & Tea"]
    assert result["candidates"][0]["neighborhoods"] == "Hillsboro"


def test_bounded_default_preserves_live_scalar_payloads_and_false_values():
    result = followup.extract_followup_data(
        {
            "calculator": {"expression": "2+2", "result": 4.0, "type": "expression"},
            "get_time": {
                "date": "2026-07-29",
                "time": "10:00",
                "timezone": "America/Los_Angeles",
            },
            "network_tools": {
                "reachable": True,
                "packet_loss_percent": 0.0,
                "packets_sent": 1,
                "packets_received": 1,
            },
            "speaker_volume": {"volume": 0, "muted": False},
        }
    )

    assert result["calculator"]["result"] == 4.0
    assert result["get_time"]["timezone"] == "America/Los_Angeles"
    assert result["network_tools"]["packet_loss_percent"] == 0.0
    assert result["speaker_volume"]["volume"] == 0
    assert result["speaker_volume"]["muted"] is False


def test_search_conversations_preserves_match_mode_with_candidates():
    payload, arguments = LOCAL_TOOL_SAMPLES["search_conversations"]
    result = followup.extract_followup_data(
        {
            "search_conversations": payload,
            "_tool_trace": [
                {
                    "tool": "search_conversations",
                    "ok": True,
                    "arguments": arguments,
                }
            ],
        }
    )["search_conversations"]

    assert result["match_mode"] == "all_terms"
    assert result["count"] == 1
    assert result["candidates"][0]["conversation_id"] == "conv_8"


def test_content_adapters_keep_handles_and_bound_large_bodies():
    huge = "start\n" + ("X" * 10000) + "\nend"
    result = followup.extract_followup_data(
        {
            "canvas": {"page_id": "page_7", "title": "Page", "content": huge},
            "stash": {
                "ref": "stash://space/file",
                "name": "notes.txt",
                "content": huge,
            },
            "pdf_read": {
                "stash_ref": "stash://space/document",
                "page_count": 3,
                "text": huge,
            },
            "execute_bash": {
                "exit_code": 0,
                "stdout": huge,
                "stderr": "",
            },
            "phone_call": {
                "call_id": "call_7",
                "canvas_location": "page_calls",
                "summary": huge,
                "transcript": huge,
            },
        }
    )

    assert result["canvas"]["page_id"] == "page_7"
    assert len(result["canvas"]["content_excerpt"]) <= 2000
    assert (
        "content truncated for follow-up context"
        in result["canvas"]["content_excerpt"]
    )
    assert result["stash"]["ref"] == "stash://space/file"
    assert len(result["stash"]["content_excerpt"]) <= 2000
    assert (
        "content truncated for follow-up context"
        in result["stash"]["content_excerpt"]
    )
    assert len(result["pdf_read"]["text_excerpt"]) <= 2000
    assert (
        "content truncated for follow-up context"
        in result["pdf_read"]["text_excerpt"]
    )
    assert len(result["execute_bash"]["stdout_excerpt"]) <= 2000
    assert (
        "content truncated for follow-up context"
        in result["execute_bash"]["stdout_excerpt"]
    )
    assert result["phone_call"]["canvas_location"] == "page_calls"
    assert len(result["phone_call"]["transcript_excerpt"]) <= 2000
    assert (
        "content truncated for follow-up context"
        in result["phone_call"]["transcript_excerpt"]
    )


def test_repeated_summaries_and_manage_intel_share_a_total_context_budget():
    summaries = [
        {
            "summary": letter * 10000,
            "source": {"stash_ref": f"stash://summaries/{letter}"},
        }
        for letter in "ABCDE"
    ]
    result = followup.extract_followup_data(
        {
            "text_summarizer": summaries,
            "manage_intel": [
                {
                    "action": "read",
                    "file": f"doc_{index}.md",
                    "content": str(index) * 12000,
                    "size_bytes": 12000,
                }
                for index in range(8)
            ],
        }
    )

    assert len(json.dumps(result["text_summarizer"])) <= 8000
    assert result["text_summarizer"]["results_count"] == 5
    assert "truncated for follow-up context" in json.dumps(
        result["text_summarizer"]
    )
    assert len(json.dumps(result["manage_intel"])) <= 8000
    assert result["manage_intel"]["operation_count"] == 5
    assert result["manage_intel"]["operations_total"] == 8
    assert result["manage_intel"]["operations_truncated"] is True
    assert "truncated for follow-up context" in json.dumps(
        result["manage_intel"]
    )


def test_nested_api_previews_remain_structured_and_mark_every_compaction():
    response = {
        "body": "A" * 5000,
        "items": [
            {"index": index, "description": "B" * 700}
            for index in range(20)
        ],
        **{f"field_{index}": "C" * 500 for index in range(12)},
        "access_token": "SECRET_SENTINEL",
        "headers": {"Authorization": "Bearer SECRET_SENTINEL"},
    }

    result = followup.extract_followup_data(
        {
            "api_call": {
                "url": "https://api.example.test/items",
                "status_code": 200,
                "response": response,
            }
        }
    )["api_call"]

    preview = result["response_preview"]
    assert isinstance(preview, dict)
    assert "response_excerpt" not in result
    encoded = json.dumps(
        preview,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    assert json.loads(encoded) == preview
    assert len(encoded) <= followup.FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS
    assert "truncated for follow-up context" in encoded
    assert followup._FOLLOWUP_STRUCTURAL_TRUNCATION_KEY in encoded
    assert "SECRET_SENTINEL" not in encoded
    assert "access_token" not in result["response_keys"]
    assert "headers" not in result["response_keys"]


def test_non_finite_numbers_are_normalized_to_strict_json():
    result = followup.extract_followup_data(
        {
            "network_tools": {
                "avg_ms": float("nan"),
                "min_ms": float("inf"),
                "max_ms": float("-inf"),
            }
        }
    )

    encoded = json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    assert json.loads(encoded) == result
    assert "non-finite number normalized for follow-up context" in encoded


def test_tiny_excerpt_budgets_still_return_an_explicit_marker():
    summary = followup.truncate_followup_summary("A" * 100, max_chars=5)
    excerpt = followup._bounded_content_excerpt("B" * 100, max_chars=5)

    assert "truncated for follow-up context" in summary
    assert "truncated for follow-up context" in excerpt


def test_workflow_discovery_and_text_non_summary_actions_reach_fallbacks():
    result = followup.extract_followup_data(
        {
            "workflow": {
                "action": "search",
                "query": "research",
                "matches": [
                    {
                        "id": "research",
                        "name": "Research workflow",
                        "status": "available",
                    }
                ],
            },
            "text_summarizer": {
                "statistics": {
                    "words": 20,
                    "characters_with_spaces": 120,
                    "sentences": 2,
                }
            },
        }
    )

    assert result["workflow"]["candidates"][0]["id"] == "research"
    assert result["text_summarizer"]["statistics"]["words"] == 20


def test_artifact_and_entity_tools_preserve_their_followup_handles():
    expected_handles = {
        "analyze_image": {"stash_ref"},
        "canvas": {"page_id"},
        "convert_file": {"stash_ref"},
        "create_alert": {"alert_id"},
        "create_reminder": {"reminder_id"},
        "create_social_clip": {"task_id", "stash_ref"},
        "generate_image": {"stash_ref"},
        "generate_music": {"stash_ref", "song_id"},
        "generate_video": {"stash_ref", "video_url"},
        "git_release_notes": {"stash_ref", "canvas_page_id"},
        "memory_deduper": {"stash_ref", "canvas_page_id"},
        "opencode": {"session_id"},
        "pdf_create": {"ref"},
        "pdf_read": {"stash_ref"},
        "phone_call": {"call_id", "canvas_location"},
        "printer": {"job_id"},
        "qr_code_generator": {"stash_ref"},
        "screenshot_url": {"stash_ref"},
        "status_recap": {"stash_ref", "canvas_id", "image_ref"},
        "upload_cloudflare": {"url", "image_id"},
        "youtube_transcript": {"srt_stash_ref", "md_stash_ref"},
        "youtube_video": {"stash_ref"},
    }

    for tool_name, fields in expected_handles.items():
        payload, arguments = LOCAL_TOOL_SAMPLES[tool_name]
        data = {tool_name: payload}
        if arguments is not None:
            data["_tool_trace"] = [
                {"tool": tool_name, "ok": True, "arguments": arguments}
            ]
        compact = followup.extract_followup_data(data)[tool_name]
        assert fields <= set(compact), (tool_name, compact)


def test_request_context_is_bounded_and_drops_secret_or_bulky_arguments():
    result = followup.extract_followup_data(
        {
            "samantha": {},
            "_tool_trace": [
                {
                    "tool": "samantha",
                    "ok": True,
                    "arguments": {
                        "message": "Review the adapter.",
                        "session": "jarvis",
                        "api_token": "SECRET_SENTINEL",
                        "headers": {"Authorization": "Bearer SECRET_SENTINEL"},
                        "image": "A" * 10000,
                    },
                }
            ],
        }
    )

    request = result["samantha"]["request"]
    assert request["message"] == "Review the adapter."
    assert request["session"] == "jarvis"
    assert "SECRET_SENTINEL" not in json.dumps(request)
    assert "headers" not in request
    assert "image" not in request
