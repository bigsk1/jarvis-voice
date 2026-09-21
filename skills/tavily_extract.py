#!/usr/bin/env python3
"""Extract bounded content from one public webpage with Tavily."""

from __future__ import annotations

import json
import ipaddress
import os
import sys
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from tavily_client import TavilyError, request_tavily, tool_result


def extract(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("'url' must be an HTTP(S) webpage URL without embedded credentials.")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("'url' must be a public webpage URL.")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("'url' must be a public webpage URL.")
    depth = str(arguments.get("extract_depth") or "basic").strip().lower()
    if depth not in {"basic", "advanced"}:
        raise ValueError("'extract_depth' must be basic or advanced.")
    query = str(arguments.get("query") or "").strip()
    if len(query) > 400:
        raise ValueError("'query' must be at most 400 characters.")
    max_chars = arguments.get("max_chars", 12000)
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1000 <= max_chars <= 20000:
        raise ValueError("'max_chars' must be an integer from 1000 to 20000.")

    body: dict[str, Any] = {
        "urls": url,
        "extract_depth": depth,
        "format": "markdown",
        "include_usage": True,
    }
    if query:
        body["query"] = query
        body["chunks_per_source"] = 5
    payload = request_tavily("extract", body, timeout=65 if depth == "advanced" else 35)
    rows = payload.get("results") or []
    if not isinstance(rows, list):
        rows = []
    page = next((item for item in rows if isinstance(item, dict) and item.get("raw_content")), None)
    if page is None:
        failed = payload.get("failed_results") or []
        reason = "The page could not be extracted." if failed else "No page content was returned."
        return tool_result(False, f"Tavily extract: {reason}")
    content = str(page["raw_content"])
    truncated = len(content) > max_chars
    excerpt = content[:max_chars].rstrip()
    data = {
        "provider": "tavily",
        "url": str(page.get("url") or url),
        "query": query or None,
        "extract_depth": depth,
        "content": excerpt,
        "content_chars": len(content),
        "content_truncated": truncated,
        "request_id": payload.get("request_id"),
        "usage": payload.get("usage"),
        "external_content_trust": "untrusted",
    }
    speech = f"Tavily extracted {len(excerpt)} characters from {data['url']}.\n{excerpt}"
    if truncated:
        speech += "\n[Content truncated. Use a focused query or read the source for more.]"
    return tool_result(True, speech, data)


def main() -> int:
    load_config()
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool input must be a JSON object.")
        result = extract(arguments)
    except (ValueError, TavilyError) as exc:
        result = tool_result(False, str(exc))
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
