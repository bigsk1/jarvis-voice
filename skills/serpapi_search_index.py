#!/usr/bin/env python3
"""Jarvis Skill: SerpApi Search Index.

Find indexed public webpages and return compact source candidates whose URLs can
be passed to fetch/crawl tools in later turns or workflow steps.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


SEARCH_INDEX_TIMEOUT = 90
MAX_SITELINKS = 8
MAX_RELATED_SEARCHES = 12
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "q",
    "num",
    "start",
    "safe",
    "mode",
    "no_cache",
    "json_restrictor",
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def normalize_mode(value: Any) -> str:
    mode = str(value or "standard").strip().lower().replace("-", "_")
    aliases = {
        "": "standard",
        "normal": "standard",
        "default": "standard",
        "standard": "standard",
        "deep": "deep",
        "expanded": "deep",
        "expanded_recall": "deep",
    }
    if mode not in aliases:
        raise ValueError("'mode' must be standard or deep.")
    return aliases[mode]


def normalize_safe(value: Any) -> str:
    safe = str(value or "active").strip().lower()
    if safe not in {"active", "off"}:
        raise ValueError("'safe' must be active or off.")
    return safe


def parse_start(value: Any) -> int:
    try:
        start = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("'start' must be a non-negative integer.") from exc
    if start < 0:
        raise ValueError("'start' must be a non-negative integer.")
    return start


def _compact_text(value: Any, maximum: int = 1200) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_sitelinks(value: Any, maximum: int = MAX_SITELINKS) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        candidates.extend(_dict_list(value))
    elif isinstance(value, dict):
        if value.get("link") or value.get("url"):
            candidates.append(value)
        for key in ("list", "inline", "expanded", "items"):
            candidates.extend(_dict_list(value.get(key)))

    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in candidates:
        url = str(item.get("link") or item.get("url") or "").strip()
        title = _compact_text(item.get("title"), 240)
        if not (url or title) or (url and url in seen_urls):
            continue
        if url:
            seen_urls.add(url)
        row = {
            key: value
            for key, value in {
                "title": title,
                "url": url or None,
                "date": item.get("date"),
            }.items()
            if value not in (None, "")
        }
        normalized.append(row)
        if len(normalized) >= maximum:
            break
    return normalized


def extract_search_index_results(
    payload: dict[str, Any], limit: int = 10
) -> list[dict[str, Any]]:
    """Normalize Search Index organic results into compact source candidates."""
    results: list[dict[str, Any]] = []
    for item in _dict_list(payload.get("organic_results")):
        url = str(item.get("link") or item.get("url") or "").strip()
        title = _compact_text(item.get("title"), 500)
        if not (title or url):
            continue
        row = {
            key: value
            for key, value in {
                "position": item.get("position"),
                "title": title,
                "url": url or None,
                "displayed_link": _compact_text(item.get("displayed_link"), 500),
                "snippet": _compact_text(item.get("snippet")),
                "date": item.get("date"),
                "language": item.get("language"),
                "image_url": item.get("image_url") or item.get("thumbnail"),
                "source": item.get("source"),
            }.items()
            if value not in (None, "", [], {})
        }
        sitelinks = _normalize_sitelinks(item.get("sitelinks"))
        if sitelinks:
            row["sitelinks"] = sitelinks
        results.append(row)
        if len(results) >= limit:
            break
    return results


def extract_related_searches(
    payload: dict[str, Any], maximum: int = MAX_RELATED_SEARCHES
) -> list[str]:
    related: list[str] = []
    seen: set[str] = set()
    values = payload.get("related_searches")
    if not isinstance(values, list):
        return related
    for item in values:
        query = item.get("query") if isinstance(item, dict) else item
        text = _compact_text(query, 300)
        identity = str(text or "").casefold()
        if not text or identity in seen:
            continue
        seen.add(identity)
        related.append(text)
        if len(related) >= maximum:
            break
    return related


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata") or {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
        )
        if key in metadata and metadata[key] not in (None, "")
    }


def _next_start(payload: dict[str, Any]) -> int | None:
    pagination = payload.get("serpapi_pagination") or {}
    next_url = pagination.get("next") if isinstance(pagination, dict) else None
    if not next_url:
        return None
    try:
        raw_start = parse_qs(urlparse(str(next_url)).query).get("start", [None])[0]
        return int(raw_start) if raw_start is not None else None
    except (TypeError, ValueError):
        return None


def _search_index_request(params: dict[str, Any]) -> dict[str, Any]:
    # The shared client remains proxy-capable. The manifest's proxy_policy=off
    # keeps normal Search Index execution direct while allowing a later policy
    # change without rewriting the tool.
    return request_serpapi(
        params,
        timeout=SEARCH_INDEX_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def build_speech(query: str, results: list[dict[str, Any]], mode: str) -> str:
    if not results:
        return f"No indexed webpages found for '{query}'."
    label = "deep-recall " if mode == "deep" else ""
    top_title = results[0].get("title") or "result"
    return (
        f"Found {len(results)} {label}indexed webpage result(s) for '{query}'. "
        f"Top result: {top_title}."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = str(input_data.get("query") or "").strip()
        if not query:
            raise ValueError("'query' is required.")

        mode = normalize_mode(input_data.get("mode"))
        safe = normalize_safe(input_data.get("safe"))
        num_results = clamp_results_count(
            input_data.get("num_results", 10),
            default=10,
            maximum=20,
        )
        start = parse_start(input_data.get("start"))
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        json_restrictor = str(input_data.get("json_restrictor") or "").strip()
        if len(json_restrictor) > 500:
            raise ValueError("'json_restrictor' must be 500 characters or fewer.")
        extra_params = input_data.get("extra_params") or {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "search_index",
            "q": query,
            "num": num_results,
            "start": start,
            "safe": safe,
            "no_cache": "true" if no_cache else "false",
        }
        if mode == "deep":
            params["mode"] = "deep"
        if json_restrictor:
            params["json_restrictor"] = json_restrictor
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _search_index_request(params)
        results = extract_search_index_results(payload, limit=num_results)
        related_searches = extract_related_searches(payload)
        metadata = _search_metadata(payload)
        search_information = payload.get("search_information") or {}
        next_start = _next_start(payload)
        total_results = search_information.get("total_results")

        data: dict[str, Any] = {
            "engine": "search_index",
            "query": query,
            "mode": mode,
            "safe": safe,
            "start": start,
            "num_results": num_results,
            "results_count": len(results),
            "provider_results_count": len(_dict_list(payload.get("organic_results"))),
            "total_results": total_results,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "related_searches": related_searches,
            "pagination": {
                "start": start,
                "num_results": num_results,
                "has_more": next_start is not None,
                "next_start": next_start,
            },
            "has_more": next_start is not None,
            "next_start": next_start,
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "search_information": {
                key: search_information[key]
                for key in ("query_displayed", "total_results")
                if search_information.get(key) not in (None, "")
            },
            "serpapi_searches_used": 1,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Search Index",
        }
        if json_restrictor:
            data["json_restrictor"] = json_restrictor
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(query, results, mode), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Search Index request timed out.")
            return 1
        return_error(f"SerpApi Search Index error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
