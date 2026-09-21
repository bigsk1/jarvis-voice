#!/usr/bin/env python3
"""Search Tavily and return bounded, cited source candidates."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from tavily_client import TavilyError, compact_text, request_tavily, tool_result


def search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("'query' is required.")
    if len(query) > 400:
        raise ValueError("'query' must be at most 400 characters.")
    depth = str(arguments.get("search_depth") or "basic").strip().lower()
    if depth not in {"basic", "advanced", "fast", "ultra-fast"}:
        raise ValueError("'search_depth' must be basic, advanced, fast, or ultra-fast.")
    topic = str(arguments.get("topic") or "general").strip().lower()
    if topic not in {"general", "news", "finance"}:
        raise ValueError("'topic' must be general, news, or finance.")
    time_range = arguments.get("time_range")
    if time_range is not None and time_range not in {"day", "week", "month", "year"}:
        raise ValueError("'time_range' must be day, week, month, or year.")
    max_results = arguments.get("max_results", 5)
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 20:
        raise ValueError("'max_results' must be an integer from 1 to 20.")
    domains = arguments.get("include_domains") or []
    if not isinstance(domains, list) or len(domains) > 20 or any(
        not isinstance(domain, str) or not domain.strip() for domain in domains
    ):
        raise ValueError("'include_domains' must be a list of at most 20 domains.")

    body: dict[str, Any] = {
        "query": query,
        "search_depth": depth,
        "topic": topic,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_published_date": True,
        "include_usage": True,
    }
    if time_range:
        body["time_range"] = time_range
        body["filter_by_published_date"] = True
    if domains:
        body["include_domains"] = [domain.strip() for domain in domains]

    payload = request_tavily("search", body)
    rows: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        row: dict[str, Any] = {
            "title": compact_text(item.get("title") or item["url"], 240),
            "url": str(item["url"]),
            "snippet": compact_text(item.get("content"), 1500),
        }
        for field in ("score", "published_date"):
            if item.get(field) is not None:
                row[field] = item[field]
        rows.append(row)
        if len(rows) >= max_results:
            break
    speech = f"Tavily found {len(rows)} source(s) for: {query}"
    for index, row in enumerate(rows[:5], 1):
        speech += f"\n{index}. {row['title']}\n{row['url']}"
        if row["snippet"]:
            speech += f"\n{compact_text(row['snippet'], 350)}"
    data = {
        "provider": "tavily",
        "query": query,
        "search_depth": depth,
        "topic": topic,
        "time_range": time_range,
        "results_count": len(rows),
        "results": rows,
        "request_id": payload.get("request_id"),
        "usage": payload.get("usage"),
        "external_content_trust": "untrusted",
    }
    return tool_result(True, speech, data)


def main() -> int:
    load_config()
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool input must be a JSON object.")
        result = search(arguments)
    except (ValueError, TavilyError) as exc:
        result = tool_result(False, str(exc))
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
