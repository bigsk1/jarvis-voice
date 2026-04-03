#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Maps Search
Thin wrapper around SerpApi's Google Maps engine with place-focused output.
"""
import json
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
        extra_params = input_data.get("extra_params", {}) or {}

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

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        results = extract_maps_results(payload, limit=num_results)

        speech = build_speech(query, results)
        top_url = results[0].get("url") if results else None
        data: dict[str, Any] = {
            "engine": "google_maps",
            "query": query,
            "ll": ll or None,
            "hl": hl or None,
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
