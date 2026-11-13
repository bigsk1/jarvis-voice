#!/usr/bin/env python3
"""Jarvis Skill: SerpApi Search Index.

Find indexed public webpages and return compact source candidates whose URLs can
be passed to fetch/crawl tools in later turns or workflow steps.
"""
from __future__ import annotations

import json
import math
import os
import re
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
MAX_NORMAL_RESULT_BYTES = 48 * 1024
RESULT_BUCKETS = {
    "web": "organic_results",
    "place": "place_results",
    "product": "product_results",
    "video": "video_results",
    "publication": "publication_results",
}
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
    "type", "ll", "radius", "product_source", "as_ylo", "as_yhi", "gl", "hl",
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


def normalize_corpus_options(arguments: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Validate typed corpus options, including existing extra_params callers."""
    options: dict[str, Any] = {}
    for key, argument in (
        ("type", "type"), ("ll", "ll"), ("radius", "radius"),
        ("product_source", "product_source"), ("as_ylo", "as_ylo"),
        ("as_yhi", "as_yhi"), ("gl", "country"), ("hl", "language"),
    ):
        named = arguments.get(argument)
        forwarded = extra.get(key)
        if named not in (None, "") and forwarded not in (None, "") and named != forwarded:
            raise ValueError(f"Conflicting '{argument}' and extra_params.{key}.")
        value = named if named not in (None, "") else forwarded
        if value not in (None, ""):
            options[key] = value
    corpus = str(options.get("type") or "web").strip().lower()
    if corpus not in RESULT_BUCKETS:
        raise ValueError("'type' must be web, place, product, video, or publication.")
    if "type" in options:
        options["type"] = corpus
    for key, required in (("ll", "place"), ("radius", "place"),
                          ("product_source", "product"), ("as_ylo", "publication"),
                          ("as_yhi", "publication")):
        if key in options and corpus != required:
            raise ValueError(f"'{key}' requires type={required}.")
    if "ll" in options:
        ll = str(options["ll"]).strip()
        match = re.fullmatch(r"@?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?)[zm])?", ll)
        if not match or not (-90 <= float(match[1]) <= 90 and -180 <= float(match[2]) <= 180):
            raise ValueError("'ll' must contain valid latitude,longitude coordinates.")
        if match[3] is not None and float(match[3]) <= 0:
            raise ValueError("'ll' zoom or distance must be positive.")
        options["ll"] = ll
    if "radius" in options:
        if "ll" not in options:
            raise ValueError("'radius' requires 'll'.")
        try:
            radius = float(options["radius"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("'radius' must be greater than 0 and at most 20000 kilometers.") from exc
        if isinstance(options["radius"], bool) or not math.isfinite(radius) or not 0 < radius <= 20000:
            raise ValueError("'radius' must be greater than 0 and at most 20000 kilometers.")
        options["radius"] = radius
    for key in ("as_ylo", "as_yhi"):
        if key in options:
            year = str(options[key]).strip()
            if not re.fullmatch(r"[1-9]\d{3}", year):
                raise ValueError(f"'{key}' must be a four-digit publication year.")
            options[key] = int(year)
    if options.get("as_ylo", 1000) > options.get("as_yhi", 9999):
        raise ValueError("'as_ylo' must not be later than 'as_yhi'.")
    if "product_source" in options:
        source = str(options["product_source"]).strip()
        if not source or len(source) > 100:
            raise ValueError("'product_source' must be 1 to 100 characters.")
        options["product_source"] = source
    for key, pattern in (("gl", r"[a-zA-Z]{2}"), ("hl", r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2})?")):
        if key in options:
            value = str(options[key]).strip()
            if not re.fullmatch(pattern, value):
                raise ValueError(f"Invalid Search Index '{key}' localization code.")
            options[key] = value.lower() if key == "gl" else value
    return options


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


def _bounded_detail(
    value: Any, *, budget: list[int], omitted: list[bool], depth: int = 0,
) -> Any:
    """Keep typed evidence compact without passing the entire provider payload."""
    if depth > 3 or budget[0] < 4:
        budget[0] = 0
        omitted[0] = True
        return None
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            if len(value) > min(4096, budget[0]):
                budget[0] = 0
                omitted[0] = True
                return None
            text = value
        else:
            if len(" ".join(value.split())) > min(1200, budget[0]):
                omitted[0] = True
            text = _compact_text(value, min(1200, budget[0]))
        budget[0] -= len(text or "")
        return text
    if isinstance(value, dict):
        omitted[0] = omitted[0] or len(value) > 20
        return {str(key): _bounded_detail(item, depth=depth + 1, budget=budget, omitted=omitted)
                for key, item in list(value.items())[:20]}
    if isinstance(value, list):
        omitted[0] = omitted[0] or len(value) > 12
        return [_bounded_detail(item, depth=depth + 1, budget=budget, omitted=omitted) for item in value[:12]]
    budget[0] -= 20
    return value if value is None or isinstance(value, (bool, int, float)) else None


def extract_search_index_results(
    payload: dict[str, Any], limit: int = 10, result_type: str = "web"
) -> list[dict[str, Any]]:
    """Normalize web and typed corpora, including typed rows mixed into web results."""
    results: list[dict[str, Any]] = []
    for item in _dict_list(payload.get(RESULT_BUCKETS[result_type])):
        row_type = result_type
        if result_type == "web":
            hint = item.get("result_type") or item.get("type")
            if isinstance(hint, str) and hint in RESULT_BUCKETS:
                row_type = hint
            else:
                for key, corpus in (("data_cid", "place"), ("product_id", "product"),
                                    ("video_id", "video"), ("publication_info", "publication")):
                    if key in item:
                        row_type = corpus
                        break
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
                "snippet": _compact_text(item.get("snippet") or item.get("description")),
                "date": item.get("date"),
                "language": item.get("language"),
                "image_url": item.get("image_url") or (
                    item.get("thumbnail", {}).get("static") if isinstance(item.get("thumbnail"), dict)
                    else item.get("thumbnail")
                ),
                "source": item.get("source"),
            }.items()
            if value not in (None, "", [], {})
        }
        if row_type != "web":
            row["result_type"] = row_type
            detail_budget = [6000]
            detail_omitted = [False]
            for key in (
                "data_cid", "place_id", "data_id", "address", "gps_coordinates", "rating",
                "reviews", "price", "type", "types", "website", "phone", "last_updated",
                "product_id", "currency", "min_price", "max_price", "stores", "gl",
                "video_id", "channel", "views", "length", "published_date", "result_id",
                "publication_info", "resources", "inline_links",
            ):
                if item.get(key) not in (None, "", [], {}):
                    row[key] = _bounded_detail(item[key], budget=detail_budget, omitted=detail_omitted)
            if detail_omitted[0]:
                row["details_truncated"] = True
        sitelinks = _normalize_sitelinks(item.get("sitelinks"))
        if sitelinks:
            row["sitelinks"] = sitelinks
        results.append(row)
        if len(results) >= limit:
            break
    return results


def _bound_normal_result(data: dict[str, Any], speech: str) -> None:
    """Fit the complete serialized envelope, retaining every candidate identity."""
    def output_size() -> int:
        # Match return_success, including ASCII escapes and duplicated top_results.
        return len(json.dumps({"ok": True, "speech": speech, "data": data}).encode("utf-8"))

    if output_size() <= MAX_NORMAL_RESULT_BYTES:
        return
    data["result_details_truncated"] = True
    rows = data["results"]
    protected = {
        "position", "title", "url", "result_type", "data_cid", "place_id", "data_id",
        "product_id", "video_id", "result_id", "details_truncated",
    }
    while output_size() > MAX_NORMAL_RESULT_BYTES:
        largest: tuple[int, dict[str, Any], str] | None = None
        for index, row in enumerate(rows):
            for key, value in row.items():
                if key in protected or not isinstance(value, (str, list, dict)):
                    continue
                size = len(json.dumps(value)) * (2 if index < 5 else 1)
                if largest is None or size > largest[0]:
                    largest = (size, row, key)
        if largest is None:
            # Very long titles can consume the budget even after details are gone.
            titles = [
                (len(json.dumps(row["title"])) * (2 if index < 5 else 1), index)
                for index, row in enumerate(rows)
                if isinstance(row.get("title"), str) and len(row["title"]) > 40
            ]
            if not titles:
                raise ValueError("Search Index result identities exceed the output size limit; request fewer results.")
            row = rows[max(titles)[1]]
            row["title"] = _compact_text(row["title"], max(40, len(row["title"]) // 2))
            row["details_truncated"] = True
            continue
        _, row, key = largest
        value = row[key]
        if isinstance(value, list) and len(value) > 1:
            row[key] = value[:max(1, len(value) // 2)]
        elif isinstance(value, str) and not value.startswith(("http://", "https://")) and len(value) > 240:
            row[key] = _compact_text(value, 240)
        else:
            # Drop complete optional URLs/objects rather than returning broken URLs.
            del row[key]
        row["details_truncated"] = True


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


def build_speech(query: str, results: list[dict[str, Any]], mode: str, result_type: str = "web") -> str:
    noun = "webpage" if result_type == "web" else result_type
    if not results:
        return f"No indexed {noun}s found for '{query}'."
    label = "deep-recall " if mode == "deep" else ""
    top_title = results[0].get("title") or "result"
    return (
        f"Found {len(results)} {label}indexed {noun} result(s) for '{query}'. "
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
        corpus_options = normalize_corpus_options(input_data, extra_params)
        result_type = corpus_options.get("type", "web")

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
        params.update(corpus_options)

        payload = _search_index_request(params)
        results = extract_search_index_results(payload, limit=num_results, result_type=result_type)
        related_searches = extract_related_searches(payload)
        metadata = _search_metadata(payload)
        search_information = payload.get("search_information") or {}
        next_start = _next_start(payload)
        total_results = search_information.get("total_results")

        data: dict[str, Any] = {
            "engine": "search_index",
            "query": query,
            "mode": mode,
            "result_type": result_type,
            "filters": {key: value for key, value in corpus_options.items() if key != "type"},
            "safe": safe,
            "start": start,
            "num_results": num_results,
            "results_count": len(results),
            "provider_results_count": len(_dict_list(payload.get(RESULT_BUCKETS[result_type]))),
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
        speech = build_speech(query, results, mode, result_type)
        if include_raw:
            data["raw"] = payload
        else:
            _bound_normal_result(data, speech)

        return_success(speech, data)
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
