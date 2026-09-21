#!/usr/bin/env python3
"""Search a configured SearXNG instance and return bounded source candidates."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config
from http_client import http_request


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class SearxngError(Exception):
    """An error safe to show in a tool result."""


def _text(value: Any, limit: int) -> str:
    plain = re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))
    compact = " ".join(plain.split())
    return compact if len(compact) <= limit else compact[: limit - 3].rstrip() + "..."


def _http_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url or len(url) > 2048:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return url


def _search_endpoint() -> str:
    configured = str(get_config_value("SEARXNG_BASE_URL", "") or "").strip()
    if not configured:
        raise SearxngError("SEARXNG_BASE_URL is not configured in the active mode.")
    try:
        parsed = urlsplit(configured)
    except ValueError as exc:
        raise SearxngError("SEARXNG_BASE_URL is not a valid HTTP(S) instance URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SearxngError(
            "SEARXNG_BASE_URL must be an HTTP(S) instance URL without credentials or query parameters."
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/search"):
        path += "/search"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _request_auth() -> tuple[dict[str, str], tuple[str, str] | None]:
    """Read optional reverse-proxy credentials without exposing them in results."""
    username = str(get_config_value("SEARXNG_USERNAME", "") or "")
    password = str(get_config_value("SEARXNG_PASSWORD", "") or "")
    authorization = str(get_config_value("SEARXNG_AUTHORIZATION", "") or "").strip()
    header_name = str(get_config_value("SEARXNG_HEADER_NAME", "") or "").strip()
    header_value = str(get_config_value("SEARXNG_HEADER_VALUE", "") or "")

    if bool(username) != bool(password):
        raise SearxngError("Set both SEARXNG_USERNAME and SEARXNG_PASSWORD for Basic auth.")
    if authorization and username:
        raise SearxngError("Choose Basic auth or SEARXNG_AUTHORIZATION, not both.")
    if bool(header_name) != bool(header_value):
        raise SearxngError("Set both SEARXNG_HEADER_NAME and SEARXNG_HEADER_VALUE.")
    if header_name and (
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", header_name)
        or header_name.lower() in {
            "accept", "content-length", "host", "proxy-authorization",
            "user-agent", "authorization",
        }
    ):
        raise SearxngError("SEARXNG_HEADER_NAME must be a valid custom header name.")
    if any(char in value for value in (authorization, header_value) for char in "\r\n"):
        raise SearxngError("SearXNG header values cannot contain line breaks.")

    headers = {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT}
    if authorization:
        headers["Authorization"] = authorization
    if header_name:
        headers[header_name] = header_value
    return headers, (username, password) if username else None


def _request_json(params: dict[str, Any]) -> dict[str, Any]:
    headers, auth = _request_auth()
    options: dict[str, Any] = {
        "headers": headers,
        "params": params,
    }
    if auth:
        options["auth"] = auth
    try:
        response = http_request(
            "GET", _search_endpoint(), use_proxy=False, timeout=30, **options,
        )
    except requests.RequestException as exc:
        raise SearxngError(f"SearXNG request failed ({type(exc).__name__}).") from exc
    if response.status_code != 200:
        challenge = getattr(response, "headers", {}).get("WWW-Authenticate")
        if response.status_code in {401, 403} and challenge:
            detail = "Reverse-proxy authentication is required or was rejected."
        elif response.status_code == 401:
            detail = "Instance authentication is required or was rejected."
        elif response.status_code == 403:
            detail = "JSON output may be disabled, or instance access was denied."
        elif response.status_code == 429:
            detail = "The instance limiter or rate limit rejected the request."
        else:
            detail = "Check the instance and request parameters."
        raise SearxngError(f"SearXNG returned HTTP {response.status_code}. {detail}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SearxngError("SearXNG did not return JSON; check that JSON output is enabled.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearxngError("SearXNG returned an unexpected JSON response.")
    return payload


def _bounded_strings(values: Any, *, count: int, length: int) -> list[str]:
    if not isinstance(values, list):
        return []
    strings = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("answer") or value.get("content") or value.get("title")
        if not isinstance(value, str):
            continue
        item = _text(value, length)
        if item:
            strings.append(item)
        if len(strings) >= count:
            break
    return strings


def search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query or len(query) > 400:
        raise ValueError("'query' must be 1 to 400 characters.")
    page = arguments.get("page", 1)
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 10:
        raise ValueError("'page' must be an integer from 1 to 10.")
    max_results = arguments.get("max_results", 10)
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 20:
        raise ValueError("'max_results' must be an integer from 1 to 20.")
    safesearch = arguments.get("safesearch")
    if safesearch is not None and (
        isinstance(safesearch, bool) or not isinstance(safesearch, int) or safesearch not in {0, 1, 2}
    ):
        raise ValueError("'safesearch' must be 0, 1, or 2.")
    time_range = arguments.get("time_range")
    if time_range is not None and time_range not in {"day", "week", "month", "year"}:
        raise ValueError("'time_range' must be day, week, month, or year.")
    categories = arguments.get("categories")
    if categories is not None and (
        not isinstance(categories, str)
        or len(categories) > 80
        or not re.fullmatch(r"\s*[a-z0-9_-]+(?:\s*,\s*[a-z0-9_-]+)*\s*", categories.lower())
    ):
        raise ValueError("'categories' must be comma-separated category names.")
    language = arguments.get("language")
    if language is not None and (
        not isinstance(language, str)
        or len(language) > 32
        or not re.fullmatch(r"[A-Za-z0-9_-]+", language.strip())
    ):
        raise ValueError("'language' must be a language code such as en-US.")

    params: dict[str, Any] = {"q": query, "format": "json", "pageno": page}
    if categories:
        params["categories"] = ",".join(part.strip().lower() for part in categories.split(","))
    if language:
        params["language"] = language.strip()
    if time_range:
        params["time_range"] = time_range
    if safesearch is not None:
        params["safesearch"] = safesearch

    payload = _request_json(params)

    results = payload["results"]
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = _http_url(item.get("url"))
        if not url:
            continue
        row: dict[str, Any] = {
            "title": _text(item.get("title") or url, 240),
            "url": url,
            "snippet": _text(item.get("content"), 1200),
        }
        for source, target, limit in (
            ("engine", "engine", 80),
            ("category", "category", 40),
            ("publishedDate", "published_date", 80),
        ):
            if item.get(source):
                row[target] = _text(item[source], limit)
        thumbnail = _http_url(item.get("thumbnail") or item.get("img_src"))
        if thumbnail:
            row["thumbnail"] = thumbnail
        rows.append(row)
        if len(rows) >= max_results:
            break

    answers = _bounded_strings(payload.get("answers"), count=3, length=300)
    suggestions = _bounded_strings(payload.get("suggestions"), count=5, length=100)
    infoboxes = []
    if isinstance(payload.get("infoboxes"), list):
        for item in payload["infoboxes"][:2]:
            if isinstance(item, dict):
                infoboxes.append({
                    "title": _text(item.get("infobox") or item.get("title"), 120),
                    "content": _text(item.get("content"), 300),
                    "url": _http_url(item.get("urls", [{}])[0].get("url"))
                    if isinstance(item.get("urls"), list) and item["urls"]
                    and isinstance(item["urls"][0], dict) else "",
                })
    unresponsive = payload.get("unresponsive_engines")
    data = {
        "provider": "searxng",
        "query": query,
        "page": page,
        "categories": params.get("categories"),
        "language": params.get("language"),
        "time_range": time_range,
        "safesearch": safesearch,
        "results_count": len(rows),
        "provider_results_count": len(results),
        "results_truncated": len(results) > len(rows),
        "results": rows,
        "answers": answers,
        "suggestions": suggestions,
        "infoboxes": infoboxes,
        "unresponsive_engine_count": len(unresponsive) if isinstance(unresponsive, list) else 0,
        "external_content_trust": "untrusted",
    }
    speech = f"SearXNG found {len(rows)} source(s) for: {query}"
    if answers:
        speech += f"\nAnswer: {answers[0]}"
    for index, row in enumerate(rows[:5], 1):
        speech += f"\n{index}. {row['title']}\n{row['url']}"
        if row["snippet"]:
            speech += f"\n{_text(row['snippet'], 300)}"
    return {"ok": True, "speech": speech, "data": data}


def probe() -> dict[str, Any]:
    """Check JSON search availability without returning source content."""
    payload = _request_json({"q": "searxng probe", "format": "json", "pageno": 1})
    return {
        "ok": True,
        "speech": "SearXNG JSON search is available.",
        "data": {"results_count": len(payload["results"])},
    }


def main() -> int:
    load_config()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--probe":
            result = probe()
        else:
            arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
            if not isinstance(arguments, dict):
                raise ValueError("Tool input must be a JSON object.")
            result = search(arguments)
    except (ValueError, SearxngError) as exc:
        result = {"ok": False, "speech": str(exc), "error": str(exc)}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
