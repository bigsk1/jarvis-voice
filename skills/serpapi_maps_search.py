#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Maps Search
Thin wrapper around SerpApi's Google Maps engine with place-focused output.
"""
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    extract_maps_results,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


FILTER_FIELDS = {"min_price", "max_price", "min_rating", "open_state", "open_on_day", "open_at_hour"}
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "device",
    "no_cache",
    "q",
    "type",
    "ll",
    "hl",
    "start",
} | FILTER_FIELDS


def _filter_value(name: str, value: Any) -> str | int | float:
    if name in {"open_state", "open_on_day"}:
        allowed = {"now", "24h"} if name == "open_state" else {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if not isinstance(value, str) or value.lower() not in allowed:
            raise ValueError(f"'{name}' must be one of: {', '.join(sorted(allowed))}.")
        return value.lower()
    if isinstance(value, bool):
        raise ValueError(f"'{name}' must be a finite nonnegative number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"'{name}' must be a finite nonnegative number.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"'{name}' must be a finite nonnegative number.")
    if name == "min_rating" and number not in {2, 2.5, 3, 3.5, 4, 4.5}:
        raise ValueError("'min_rating' must be 2, 2.5, 3, 3.5, 4 or 4.5; it is a ranking preference.")
    if name == "open_at_hour" and (not number.is_integer() or number > 23):
        raise ValueError("'open_at_hour' must be an integer from 0 to 23.")
    return int(number) if number.is_integer() else number


def normalize_filters(
    options: dict[str, Any], extra_params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Validate both public fields and their existing advanced-parameter equivalents."""
    requested: dict[str, Any] = {}
    effective: dict[str, Any] = {}
    for name in sorted(FILTER_FIELDS):
        supplied = [source[name] for source in (options, extra_params)
                    if name in source and source[name] is not None]
        if not supplied:
            continue
        values = [_filter_value(name, value) for value in supplied]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(f"Conflicting '{name}' values; use its first-class argument or matching extra_params.")
        requested[name] = supplied[0]
        effective[name] = values[0]
    if "min_price" in effective and "max_price" in effective and effective["min_price"] > effective["max_price"]:
        raise ValueError("'max_price' must not be below 'min_price'.")
    if "open_state" in effective and {"open_on_day", "open_at_hour"}.intersection(effective):
        raise ValueError("'open_state' cannot be combined with 'open_on_day' or 'open_at_hour'.")
    if "open_at_hour" in effective and "open_on_day" not in effective:
        raise ValueError("'open_at_hour' requires 'open_on_day'.")
    notes = []
    if "min_rating" in effective:
        notes.append("Minimum rating is a Google ranking preference; lower-rated or unrated places may still appear.")
    if {"min_price", "max_price"}.intersection(effective):
        notes.append("Price filters match overlapping place price ranges, not an exact bill or per-person quote.")
    return requested, effective, notes


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


def build_speech(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No map results found for '{query}'."

    top = results[0]
    title = (top.get("title") or "top place").strip()
    rating = top.get("rating")
    address = top.get("address")

    details = []
    if rating is not None:
        details.append(f"rated {rating}")
    if address:
        details.append(address)

    if details:
        return f"Found {len(results)} map result(s) for '{query}'. Top result: {title}, {', '.join(details)}."
    return f"Found {len(results)} map result(s) for '{query}'. Top result: {title}."


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = str(input_data.get("query", "")).strip()
        ll = str(input_data.get("ll", "")).strip()
        hl = str(input_data.get("hl", "en")).strip()
        device = str(input_data.get("device", "desktop")).strip()
        start = int(input_data.get("start", 0))
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params")
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")
        requested_filters, effective_filters, filter_notes = normalize_filters(input_data, extra_params)

        if not query:
            return_error("Parameter 'query' is required.")
            return 1

        if start < 0:
            start = 0

        params: dict[str, Any] = {
            "engine": "google_maps",
            "type": "search",
            "q": query,
            "device": device,
            "no_cache": "true" if no_cache else "false",
        }
        if hl:
            params["hl"] = hl
        if ll:
            params["ll"] = ll
        if start:
            params["start"] = start
        params.update(effective_filters)

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        results = extract_maps_results(payload, limit=num_results)

        speech = build_speech(query, results)
        if "min_rating" in effective_filters:
            speech += " Minimum rating is a ranking preference, not a strict cutoff."
        top_url = results[0].get("url") if results else None
        data: dict[str, Any] = {
            "engine": "google_maps",
            "query": query,
            "ll": ll or None,
            "hl": hl or None,
            "requested_filters": requested_filters,
            "effective_filters": effective_filters,
            "filter_notes": filter_notes,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": top_url,
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if include_raw:
            data["raw"] = payload

        return_success(speech=speech, data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi maps search timed out.")
            return 1
        return_error(f"SerpApi maps search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
