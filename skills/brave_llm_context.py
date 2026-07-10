#!/usr/bin/env python3
"""
Jarvis Skill: Brave LLM Context

Calls Brave's LLM Context API and returns compact extracted source snippets for
LLM grounding. This is retrieval/context, not a final-answer generator.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import get_config_value, load_config
from http_client import http_request


ENDPOINT = "https://api.search.brave.com/res/v1/llm/context"


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data is not None:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data is not None:
        result["data"] = data
    print(json.dumps(result))


def parse_input() -> dict[str, Any]:
    try:
        return json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return {}


def as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def as_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def add_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    target[key] = value


def normalize_goggles(value: Any) -> str:
    """Return a Brave Goggles URL/inline definition, or empty string for plain keywords."""
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("https://", "http://")):
        return text
    # Inline Goggles definitions are structured rule text. Plain search phrases
    # cause Brave's LLM Context API to reject the request with HTTP 422, so drop
    # those and let the normal query/body do the ranking work.
    if "\n" in text or text.startswith(("!", "$", "/")):
        return text
    return ""


def trim_text(value: Any, limit: int = 900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


SOURCE_METADATA_FIELDS = ("title", "hostname", "age", "site_name", "favicon")


def compact_source_metadata(sources: Any) -> dict[str, Any]:
    """Keep citation-friendly source metadata; drop bulky thumbnail objects."""
    if not isinstance(sources, dict):
        return {}

    compact: dict[str, Any] = {}
    for url, meta in sources.items():
        if not isinstance(meta, dict):
            continue
        entry = {
            key: meta[key]
            for key in SOURCE_METADATA_FIELDS
            if meta.get(key) not in (None, "", [])
        }
        if entry:
            compact[str(url)] = entry
    return compact


def enrich_items_with_sources(
    items: list[dict[str, Any]],
    sources: dict[str, Any],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        copy = dict(item)
        url = str(copy.get("url") or "").strip()
        meta = sources.get(url) if url else None
        if isinstance(meta, dict):
            if meta.get("site_name"):
                copy["site_name"] = meta["site_name"]
            if meta.get("hostname"):
                copy["hostname"] = meta["hostname"]
            age = meta.get("age")
            if isinstance(age, list) and age:
                copy["age"] = str(age[0])
            elif isinstance(age, str) and age.strip():
                copy["age"] = age.strip()
        enriched.append(copy)
    return enriched


def normalize_url_items(items: Any, *, max_sources: int = 8, max_snippets_per_source: int = 3) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in items[:max_sources]:
        if not isinstance(item, dict):
            continue
        snippets = item.get("snippets") or []
        if not isinstance(snippets, list):
            snippets = [snippets]

        normalized.append({
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "snippets": [
                trim_text(snippet)
                for snippet in snippets[:max_snippets_per_source]
                if str(snippet or "").strip()
            ],
        })
    return normalized


def build_speech(query: str, generic: list[dict[str, Any]], poi: Any, map_items: list[dict[str, Any]]) -> str:
    source_count = len(generic) + len(map_items) + (1 if isinstance(poi, dict) else 0)
    if source_count == 0:
        return f"Brave LLM Context found no relevant extracted content for: {query}"

    lines = [f"Brave LLM Context found {source_count} source(s) for: {query}"]

    combined = list(generic)
    if isinstance(poi, dict):
        combined.append({
            "title": poi.get("title") or poi.get("name") or "",
            "url": poi.get("url") or "",
            "snippets": poi.get("snippets") or [],
        })
    combined.extend(map_items)

    for index, item in enumerate(combined[:6], start=1):
        title = trim_text(item.get("title") or item.get("url") or f"Source {index}", 160)
        site_name = trim_text(item.get("site_name") or "", 80)
        url = item.get("url") or ""
        label = f"{title} ({site_name})" if site_name and site_name.lower() not in title.lower() else title
        lines.append(f"\n{index}. {label}")
        if url:
            lines.append(f"   {url}")
        age = item.get("age")
        if age:
            lines.append(f"   Age: {trim_text(age, 120)}")
        for snippet in (item.get("snippets") or [])[:2]:
            lines.append(f"   - {trim_text(snippet, 500)}")

    return "\n".join(lines)


def main() -> int:
    load_config()
    input_data = parse_input()

    query = str(input_data.get("query", "")).strip()
    if not query:
        return_error("Parameter 'query' is required.")
        return 1

    api_key = (get_config_value("BRAVE_API_KEY", "") or "").strip()
    fallback_key = (get_config_value("BRAVE_SEARCH_API_KEY", "") or "").strip()
    if not api_key and fallback_key:
        api_key = fallback_key

    if not api_key:
        return_error("BRAVE_API_KEY is not configured.")
        return 1

    freshness = str(input_data.get("freshness_range") or input_data.get("freshness") or "").strip()

    body: dict[str, Any] = {
        "q": query,
        "country": str(input_data.get("country") or "US").strip(),
        "search_lang": str(input_data.get("search_lang") or "en").strip(),
        "count": as_int(input_data.get("count"), 20, 1, 50),
        "maximum_number_of_urls": as_int(input_data.get("maximum_number_of_urls"), 8, 1, 50),
        "maximum_number_of_tokens": as_int(input_data.get("maximum_number_of_tokens"), 8192, 1024, 32768),
        "maximum_number_of_snippets": as_int(input_data.get("maximum_number_of_snippets"), 30, 1, 100),
        "maximum_number_of_tokens_per_url": as_int(input_data.get("maximum_number_of_tokens_per_url"), 4096, 512, 8192),
        "maximum_number_of_snippets_per_url": as_int(input_data.get("maximum_number_of_snippets_per_url"), 10, 1, 100),
        "context_threshold_mode": str(input_data.get("context_threshold_mode") or "balanced").strip(),
    }

    enable_source_metadata = as_bool_or_none(input_data.get("enable_source_metadata"))
    body["enable_source_metadata"] = False if enable_source_metadata is None else enable_source_metadata

    add_if_present(body, "freshness", freshness)
    add_if_present(body, "goggles", normalize_goggles(input_data.get("goggles")))
    enable_local = as_bool_or_none(input_data.get("enable_local"))
    if enable_local is not None:
        body["enable_local"] = enable_local

    headers = {
        "accept": "application/json",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
        "X-Subscription-Token": api_key,
    }

    location_header_map = {
        "loc_lat": "X-Loc-Lat",
        "loc_long": "X-Loc-Long",
        "loc_city": "X-Loc-City",
        "loc_state": "X-Loc-State",
        "loc_state_name": "X-Loc-State-Name",
        "loc_country": "X-Loc-Country",
        "loc_postal_code": "X-Loc-Postal-Code",
    }
    for input_key, header_name in location_header_map.items():
        value = input_data.get(input_key)
        if value is not None and str(value).strip():
            headers[header_name] = str(value).strip()

    try:
        response = http_request(
            "POST",
            ENDPOINT,
            headers=headers,
            json=body,
            timeout=30,
        )
    except requests.Timeout:
        return_error("Brave LLM Context request timed out.")
        return 1
    except requests.RequestException as exc:
        return_error(f"Brave LLM Context request failed: {exc}")
        return 1

    if response.status_code >= 400:
        detail = trim_text(response.text, 700)
        return_error(
            f"Brave LLM Context API returned HTTP {response.status_code}.",
            data={"status_code": response.status_code, "details": detail},
        )
        return 1

    try:
        payload = response.json()
    except ValueError:
        return_error("Brave LLM Context API returned non-JSON response.")
        return 1

    grounding = payload.get("grounding") if isinstance(payload, dict) else {}
    if not isinstance(grounding, dict):
        grounding = {}

    source_metadata = compact_source_metadata(payload.get("sources") if isinstance(payload, dict) else {})

    generic = enrich_items_with_sources(
        normalize_url_items(grounding.get("generic"), max_sources=8),
        source_metadata,
    )
    map_items = enrich_items_with_sources(
        normalize_url_items(grounding.get("map"), max_sources=5, max_snippets_per_source=2),
        source_metadata,
    )
    poi = grounding.get("poi")
    compact_poi = None
    if isinstance(poi, dict):
        compact_poi = {
            "name": poi.get("name") or "",
            "title": poi.get("title") or "",
            "url": poi.get("url") or "",
            "snippets": [
                trim_text(snippet)
                for snippet in (poi.get("snippets") or [])[:3]
                if str(snippet or "").strip()
            ],
        }
        enriched_poi = enrich_items_with_sources([compact_poi], source_metadata)
        if enriched_poi:
            compact_poi = enriched_poi[0]

    data: dict[str, Any] = {
        "query": query,
        "request": {key: value for key, value in body.items() if key != "q"},
        "grounding": {
            "generic": generic,
            "poi": compact_poi,
            "map": map_items,
        },
        "sources": source_metadata,
    }
    if input_data.get("include_raw"):
        data["raw"] = payload

    return_success(build_speech(query, generic, compact_poi, map_items), data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
