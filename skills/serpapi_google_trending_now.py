#!/usr/bin/env python3
"""Jarvis Skill: current Google trends and associated news through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


TRENDING_NOW_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 20
DEFAULT_MAX_BREAKDOWN_QUERIES = 10
SUPPORTED_HOURS = {4, 24, 48, 168}
SUPPORTED_CATEGORY_IDS = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20
}
ACTION_ALIASES = {
    "trending_now": "trending_now",
    "trending": "trending_now",
    "trends": "trending_now",
    "current": "trending_now",
    "now": "trending_now",
    "news": "news",
    "articles": "news",
}
GEO_RE = re.compile(r"^[A-Z]{2}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2}$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "geo",
    "hours",
    "category_id",
    "only_active",
    "hl",
    "page_token",
    "no_cache",
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").removeprefix("+").removesuffix("%")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if number.is_integer() else number


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def normalize_action(value: Any) -> str:
    normalized = str(value or "trending_now").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    action = ACTION_ALIASES.get(normalized)
    if not action:
        raise ValueError("'action' must be trending_now or news.")
    return action


def normalize_geo(value: Any) -> str:
    geo = str(value or "US").strip().upper()
    if not GEO_RE.fullmatch(geo):
        raise ValueError("'geo' must be a two-letter Trending Now country code such as US or GB.")
    return geo


def normalize_language(value: Any) -> str | None:
    language = str(value or "").strip().lower()
    if not language:
        return None
    if not LANGUAGE_RE.fullmatch(language):
        raise ValueError("'language' must be a two-letter language code such as en.")
    return language


def normalize_hours(value: Any) -> int:
    hours = _bounded_int(value, "hours", default=24, minimum=4, maximum=168)
    if hours not in SUPPORTED_HOURS:
        raise ValueError("'hours' must be 4, 24, 48, or 168.")
    return hours


def normalize_category_id(value: Any) -> int | None:
    if value in (None, ""):
        return None
    category_id = _bounded_int(
        value,
        "category_id",
        default=11,
        minimum=1,
        maximum=20,
    )
    if category_id not in SUPPORTED_CATEGORY_IDS:
        raise ValueError("'category_id' is not a supported Trending Now category ID.")
    return category_id


def _timestamp_iso(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _public_trend_url(query: str, geo: str) -> str:
    return f"https://trends.google.com/trends/explore?{urlencode({'q': query, 'geo': geo})}"


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
            "google_trends_trending_now_url",
            "google_trends_news_url",
        )
        if metadata.get(key) not in (None, "")
    }


def extract_trending_searches(
    payload: dict[str, Any],
    *,
    geo: str,
    max_results: int,
    max_breakdown_queries: int,
) -> tuple[list[dict[str, Any]], int, int]:
    raw_results = _dict_list(payload.get("trending_searches"))
    active_count = sum(item.get("active") is True for item in raw_results)
    results = []
    for position, item in enumerate(raw_results[:max_results], 1):
        query = " ".join(str(item.get("query") or "").split())
        if not query:
            continue
        categories = []
        for category in _dict_list(item.get("categories")):
            compact = {
                key: category[key]
                for key in ("id", "name")
                if category.get(key) not in (None, "")
            }
            if compact:
                categories.append(compact)
        breakdown = [
            " ".join(str(value).split())
            for value in (item.get("trend_breakdown") or [])[:max_breakdown_queries]
            if str(value).strip()
        ] if isinstance(item.get("trend_breakdown"), list) else []
        result = {
            key: field_value
            for key, field_value in {
                "position": position,
                "title": query,
                "query": query,
                "start_timestamp": _number(item.get("start_timestamp")),
                "start_time": _timestamp_iso(item.get("start_timestamp")),
                "end_timestamp": _number(item.get("end_timestamp")),
                "end_time": _timestamp_iso(item.get("end_timestamp")),
                "active": item.get("active") if isinstance(item.get("active"), bool) else None,
                "search_volume": _number(item.get("search_volume")),
                "increase_percentage": _number(item.get("increase_percentage")),
                "categories": categories,
                "category_names": [category["name"] for category in categories if category.get("name")],
                "trend_breakdown": breakdown,
                "google_trends_url": _public_trend_url(query, geo),
                "trends_api_url": item.get("serpapi_google_trends_link"),
                "news_page_token": item.get("news_page_token"),
                "news_api_url": item.get("serpapi_news_link"),
            }.items()
            if field_value not in (None, "", [], {})
        }
        results.append(result)
    return results, len(raw_results), active_count


def extract_news(
    payload: dict[str, Any],
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], int]:
    raw_results = _dict_list(payload.get("news"))
    results = []
    for position, item in enumerate(raw_results[:max_results], 1):
        title = " ".join(str(item.get("title") or "").split())
        url = item.get("link")
        if not title and not url:
            continue
        results.append({
            key: field_value
            for key, field_value in {
                "position": position,
                "title": title or None,
                "url": url,
                "source": item.get("source"),
                "date": item.get("date"),
                "thumbnail": item.get("thumbnail"),
            }.items()
            if field_value not in (None, "")
        })
    return results, len(raw_results)


def _trending_now_request(params: dict[str, Any]) -> dict[str, Any]:
    # proxy_policy=off keeps Jarvis calls direct. This path remains proxy-capable
    # so the manifest can opt in later without a code change.
    return request_serpapi(
        params,
        timeout=TRENDING_NOW_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def build_speech(action: str, data: dict[str, Any]) -> str:
    results = data.get("results") or []
    if action == "news":
        label = data.get("trend_query") or "the selected trend"
        if not results:
            return f"Google Trends returned no associated news for {label}."
        return f"Found {len(results)} news article(s) associated with {label}."

    scope_notice = str(data.get("scope_notice") or "").strip()
    scope_prefix = f"{scope_notice} " if scope_notice else ""
    if not results:
        return (
            f"{scope_prefix}Google Trends returned no current trends for "
            f"{data.get('geo', 'US')}."
        )
    top = max(results, key=lambda item: item.get("search_volume", -1))
    volume = top.get("search_volume")
    volume_text = f" with {volume:,} searches" if isinstance(volume, int) else ""
    return (
        f"{scope_prefix}Found {len(results)} current Google trend(s) for {data.get('geo', 'US')} "
        f"over the past {data.get('hours', 24)} hours. "
        f"Highest-volume returned trend: {top['query']}{volume_text}."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        action = normalize_action(input_data.get("action"))
        max_results = _bounded_int(
            input_data.get("max_results"),
            "max_results",
            default=DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=50,
        )
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params") or {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        if action == "news":
            page_token = str(input_data.get("page_token") or "").strip()
            if not page_token:
                raise ValueError("'page_token' is required for the news action.")
            trend_query = " ".join(str(input_data.get("trend_query") or "").split())
            if len(trend_query) > 100:
                raise ValueError("'trend_query' must be 100 characters or fewer.")
            params: dict[str, Any] = {
                "engine": "google_trends_news",
                "page_token": page_token,
                "no_cache": "true" if no_cache else "false",
            }
            merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
            payload = _trending_now_request(params)
            results, provider_results_count = extract_news(
                payload,
                max_results=max_results,
            )
            metadata = _search_metadata(payload)
            data: dict[str, Any] = {
                "action": "news",
                "engine": "google_trends_news",
                "trend_query": trend_query or None,
                "page_token": page_token,
                "results_count": len(results),
                "provider_results_count": provider_results_count,
                "results": results,
                "top_results": results[:10],
                "top_url": results[0].get("url") if results else None,
                "search_id": metadata.get("id"),
                "search_metadata": metadata,
                "trends_news_url": metadata.get("google_trends_news_url"),
                "serpapi_searches_used": 1,
                "proxy_enabled": get_proxy_enabled(),
                "source": "SerpApi Google Trends News",
            }
        else:
            if input_data.get("page_token") not in (None, ""):
                raise ValueError("'page_token' is supported only for the news action.")
            requested_topic = " ".join(str(input_data.get("query") or "").split())
            if len(requested_topic) > 200:
                raise ValueError("'query' must be 200 characters or fewer.")
            scope_notice = (
                f"Trending Now is a seedless feed, so the requested topic "
                f"'{requested_topic}' was not used as a filter."
                if requested_topic
                else None
            )
            geo = normalize_geo(input_data.get("geo"))
            language = normalize_language(input_data.get("language"))
            hours = normalize_hours(input_data.get("hours"))
            category_id = normalize_category_id(input_data.get("category_id"))
            only_active = parse_bool(input_data.get("only_active", False))
            max_breakdown_queries = _bounded_int(
                input_data.get("max_breakdown_queries"),
                "max_breakdown_queries",
                default=DEFAULT_MAX_BREAKDOWN_QUERIES,
                minimum=0,
                maximum=25,
            )
            params = {
                "engine": "google_trends_trending_now",
                "geo": geo,
                "hours": hours,
                "only_active": "true" if only_active else "false",
                "no_cache": "true" if no_cache else "false",
            }
            if category_id is not None:
                params["category_id"] = category_id
            if language:
                params["hl"] = language
            merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
            payload = _trending_now_request(params)
            results, provider_results_count, active_count = extract_trending_searches(
                payload,
                geo=geo,
                max_results=max_results,
                max_breakdown_queries=max_breakdown_queries,
            )
            metadata = _search_metadata(payload)
            top = max(results, key=lambda item: item.get("search_volume", -1)) if results else {}
            data = {
                "action": "trending_now",
                "engine": "google_trends_trending_now",
                "requested_topic": requested_topic or None,
                "scope_notice": scope_notice,
                "geo": geo,
                "language": language,
                "hours": hours,
                "category_id": category_id,
                "only_active": only_active,
                "results_count": len(results),
                "provider_results_count": provider_results_count,
                "active_results_count": active_count,
                "results": results,
                "top_results": results[:10],
                "top_query": top.get("query"),
                "top_news_page_token": top.get("news_page_token"),
                "search_id": metadata.get("id"),
                "search_metadata": metadata,
                "trending_now_url": f"https://trends.google.com/trending?{urlencode({'geo': geo})}",
                "serpapi_searches_used": 1,
                "proxy_enabled": get_proxy_enabled(),
                "source": "SerpApi Google Trends Trending Now",
            }

        if include_raw:
            data["raw"] = payload
        return_success(build_speech(action, data), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Trends request timed out.")
            return 1
        return_error(f"SerpApi Google Trends error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
