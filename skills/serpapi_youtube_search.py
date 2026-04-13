#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi YouTube Search
Search YouTube videos through SerpApi with normalized video-first results.
"""
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "search_query",
    "sp",
    "gl",
    "hl",
    "no_cache",
}


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def _parse_view_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip().lower().replace(",", "")
    if not text:
        return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])?\s*(?:views?|watching)?", text)
    if not match:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None

    number = float(match.group(1))
    suffix = match.group(2)
    multiplier = 1
    if suffix == "k":
        multiplier = 1_000
    elif suffix == "m":
        multiplier = 1_000_000
    elif suffix == "b":
        multiplier = 1_000_000_000
    return int(number * multiplier)


def _is_popularity_query(query: str) -> bool:
    lowered = (query or "").lower()
    popularity_terms = (
        "popular",
        "most popular",
        "best",
        "top",
        "highest viewed",
        "most viewed",
        "viral",
    )
    return any(term in lowered for term in popularity_terms)


def normalize_video_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for item in payload.get("video_results") or []:
        if not isinstance(item, dict):
            continue

        channel = item.get("channel") if isinstance(item.get("channel"), dict) else {}
        thumbnail = item.get("thumbnail")
        if isinstance(thumbnail, dict):
            thumbnail = thumbnail.get("static") or thumbnail.get("rich")

        entry = {
            "video_id": item.get("video_id"),
            "title": item.get("title"),
            "url": item.get("link"),
            "serpapi_link": item.get("serpapi_link"),
            "thumbnail": thumbnail,
            "channel": channel.get("name"),
            "channel_url": channel.get("link"),
            "channel_verified": channel.get("verified"),
            "published_date": item.get("published_date"),
            "views": item.get("views"),
            "extracted_views": item.get("extracted_views"),
            "duration": item.get("length"),
            "live": item.get("live"),
            "extensions": item.get("extensions"),
            "description": item.get("description"),
            "source": "video_results",
        }
        entry["extracted_views"] = _parse_view_count(entry.get("extracted_views") or entry.get("views"))

        if not entry["title"] and not entry["url"]:
            continue
        results.append(entry)
        if len(results) >= limit:
            break

    return results


def rank_video_results(query: str, results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not results:
        return results, "default"
    if not _is_popularity_query(query):
        return results, "default"

    ranked = sorted(
        results,
        key=lambda item: (
            item.get("extracted_views") is not None,
            item.get("extracted_views") or 0,
        ),
        reverse=True,
    )
    return ranked, "views_desc"


def build_speech(query: str, results: list[dict[str, Any]], ranking_mode: str = "default") -> str:
    if not results:
        return f"No YouTube videos found for '{query}'."

    top = results[0]
    title = (top.get("title") or "top video").strip()
    channel = top.get("channel")
    published = top.get("published_date")
    views = top.get("views")

    details = []
    if channel:
        details.append(f"by {channel}")
    if published:
        details.append(published)
    if ranking_mode == "views_desc" and views:
        details.append(str(views))

    if details:
        label = "Top by views" if ranking_mode == "views_desc" else "Top result"
        return f"Found {len(results)} YouTube video result(s) for '{query}'. {label}: {title}, {', '.join(details)}."
    return f"Found {len(results)} YouTube video result(s) for '{query}'. Top result: {title}."


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        search_query = str(input_data.get("search_query", "")).strip()
        sp = str(input_data.get("sp", "")).strip()
        gl = str(input_data.get("gl", "")).strip()
        hl = str(input_data.get("hl", "en")).strip()
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not search_query:
            return_error("Parameter 'search_query' is required.")
            return 1

        params: dict[str, Any] = {
            "engine": "youtube",
            "search_query": search_query,
            "no_cache": "true" if no_cache else "false",
        }
        if sp:
            params["sp"] = sp
        if gl:
            params["gl"] = gl
        if hl:
            params["hl"] = hl

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        results = normalize_video_results(payload, limit=num_results)
        results, ranking_mode = rank_video_results(search_query, results)

        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        serpapi_pagination = payload.get("serpapi_pagination") if isinstance(payload.get("serpapi_pagination"), dict) else {}

        data: dict[str, Any] = {
            "engine": "youtube",
            "search_query": search_query,
            "sp": sp or None,
            "gl": gl or None,
            "hl": hl or None,
            "ranking_mode": ranking_mode,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "next_page_token": pagination.get("next_page_token") or serpapi_pagination.get("next_page_token"),
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(search_query, results, ranking_mode=ranking_mode), data=data)
        return 0

    except Exception as exc:
        msg = str(exc)
        if "timeout" in msg.lower():
            return_error("SerpApi YouTube search timed out.")
            return 1
        if "HTTP " in msg:
            return_error(msg)
            return 1
        return_error(f"SerpApi YouTube search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
