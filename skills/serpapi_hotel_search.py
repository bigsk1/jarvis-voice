#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Hotel Search
Thin wrapper around SerpApi's Google Hotels engine with hotel-focused output.
"""
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    extract_hotel_results,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    parse_int_list,
    request_serpapi,
)


RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "device",
    "no_cache",
    "q",
    "hl",
    "gl",
    "currency",
    "check_in_date",
    "check_out_date",
    "adults",
    "children",
    "children_ages",
    "sort_by",
    "min_price",
    "max_price",
    "property_types",
    "amenities",
    "rating",
    "brands",
    "hotel_class",
    "free_cancellation",
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


def _serialize_csv(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        clean = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(clean) if clean else None

    text = str(value).strip()
    return text or None


def build_speech(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No hotel results found for '{query}'."

    top = results[0]
    title = (top.get("title") or "top hotel").strip()
    price = top.get("price_total") or top.get("price_per_night")
    rating = top.get("rating")

    details = []
    if rating is not None:
        details.append(f"rated {rating}")
    if price:
        details.append(f"starting at {price}")

    if details:
        return f"Found {len(results)} hotel result(s) for '{query}'. Top result: {title}, {', '.join(details)}."
    return f"Found {len(results)} hotel result(s) for '{query}'. Top result: {title}."


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        destination = str(input_data.get("destination", "")).strip()
        query = str(input_data.get("query", "")).strip() or destination
        check_in_date = str(input_data.get("check_in_date", "")).strip()
        check_out_date = str(input_data.get("check_out_date", "")).strip()
        adults = int(input_data.get("adults", 2))
        children = int(input_data.get("children", 0))
        children_ages = parse_int_list(input_data.get("children_ages"))
        min_price = input_data.get("min_price")
        max_price = input_data.get("max_price")
        rating = input_data.get("rating")
        hotel_class = _serialize_csv(input_data.get("hotel_class"))
        sort_by = input_data.get("sort_by")
        property_types = _serialize_csv(input_data.get("property_types"))
        amenities = _serialize_csv(input_data.get("amenities"))
        brands = _serialize_csv(input_data.get("brands"))
        free_cancellation = parse_bool(input_data.get("free_cancellation", False))
        hl = str(input_data.get("hl", "en")).strip()
        gl = str(input_data.get("gl", "us")).strip()
        currency = str(input_data.get("currency", "USD")).strip()
        device = str(input_data.get("device", "desktop")).strip()
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not query:
            return_error("Provide 'query' or 'destination'.")
            return 1
        if not check_in_date or not check_out_date:
            return_error("Parameters 'check_in_date' and 'check_out_date' are required.")
            return 1
        if adults < 1:
            adults = 1
        if children < 0:
            children = 0

        params: dict[str, Any] = {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": adults,
            "children": children,
            "currency": currency,
            "device": device,
            "no_cache": "true" if no_cache else "false",
        }
        if hl:
            params["hl"] = hl
        if gl:
            params["gl"] = gl
        if children_ages:
            params["children_ages"] = ",".join(str(age) for age in children_ages)
        if sort_by is not None:
            params["sort_by"] = sort_by
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price
        if rating is not None:
            params["rating"] = rating
        if hotel_class:
            params["hotel_class"] = hotel_class
        if property_types:
            params["property_types"] = property_types
        if amenities:
            params["amenities"] = amenities
        if brands:
            params["brands"] = brands
        if free_cancellation:
            params["free_cancellation"] = "true"

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        results = extract_hotel_results(payload, limit=num_results)

        speech = build_speech(query, results)
        top_url = results[0].get("url") if results else None
        data: dict[str, Any] = {
            "engine": "google_hotels",
            "query": query,
            "destination": destination or None,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": adults,
            "children": children,
            "currency": currency or None,
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
            return_error("SerpApi hotel search timed out.")
            return 1
        return_error(f"SerpApi hotel search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
