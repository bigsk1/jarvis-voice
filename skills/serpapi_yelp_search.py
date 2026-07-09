#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Yelp Search
Search Yelp places through SerpApi with optional review lookup.
"""
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config, get_config_value
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "find_desc",
    "find_loc",
    "attrs",
    "sortby",
    "sort_by",
    "place_id",
    "no_cache",
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


def get_default_location() -> str:
    return get_config_value("JARVIS_DEFAULT_LOCATION", "").strip()


def _serialize_csv(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        clean = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(clean) if clean else None
    text = str(value).strip()
    return text or None


def normalize_attrs(attrs: Any, dogs_allowed: bool = False) -> str | None:
    attr_text = _serialize_csv(attrs)
    attr_list = [item.strip() for item in (attr_text or "").split(",") if item.strip()]
    if dogs_allowed and "DogsAllowed" not in attr_list:
        attr_list.append("DogsAllowed")
    return ",".join(attr_list) if attr_list else None


def normalize_sort_by(sort_by: Any) -> str | None:
    if sort_by is None:
        return None
    raw = str(sort_by).strip()
    if not raw:
        return None

    lowered = raw.lower().replace(" ", "_")
    mapping = {
        "best": "best_match",
        "best_match": "best_match",
        "rating": "rating",
        "review_count": "review_count",
        "reviews": "review_count",
        "distance": "distance",
    }
    return mapping.get(lowered, raw)


def _normalize_address(item: dict[str, Any]) -> str | None:
    address = item.get("address")
    if isinstance(address, list):
        address = ", ".join(str(part).strip() for part in address if str(part).strip())
    elif isinstance(address, dict):
        parts = [address.get("street"), address.get("city"), address.get("state"), address.get("zip")]
        address = ", ".join(str(part).strip() for part in parts if part)
    elif address is not None:
        address = str(address).strip()

    if address:
        return address

    location = item.get("location")
    if isinstance(location, dict):
        display = location.get("display_address")
        if isinstance(display, list):
            return ", ".join(str(part).strip() for part in display if str(part).strip())
    return None


def extract_yelp_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for bucket in ("organic_results", "ad_results", "ads"):
        values = payload.get(bucket)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue

            categories = item.get("categories")
            if isinstance(categories, list):
                categories = [str(cat).strip() for cat in categories if str(cat).strip()]

            result = {
                "title": item.get("title") or item.get("name"),
                "url": item.get("link") or item.get("url"),
                "place_id": item.get("place_id") or item.get("biz_id") or item.get("business_id"),
                "rating": item.get("rating"),
                "reviews": item.get("reviews") or item.get("review_count"),
                "price": item.get("price"),
                "phone": item.get("phone"),
                "address": _normalize_address(item),
                "categories": categories,
                "thumbnail": item.get("thumbnail") or item.get("image") or item.get("photo"),
                "snippet": item.get("snippet") or item.get("description"),
                "source": bucket,
            }
            if not result["title"] and not result["url"]:
                continue
            results.append(result)
            if len(results) >= limit:
                return results

    return results


def extract_yelp_reviews(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in payload.get("reviews") or []:
        if not isinstance(item, dict):
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        photos = item.get("photos") if isinstance(item.get("photos"), list) else None
        results.append(
            {
                "rating": item.get("rating"),
                "date": item.get("date"),
                "text": item.get("text") or item.get("snippet"),
                "user_name": user.get("name"),
                "user_url": user.get("link"),
                "photos": photos,
            }
        )
        if len(results) >= limit:
            break
    return results


def build_speech(find_desc: str, find_loc: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No Yelp results found for '{find_desc}' in {find_loc}."

    top = results[0]
    title = (top.get("title") or "top place").strip()
    details = []
    if top.get("rating") is not None:
        details.append(f"rated {top['rating']}")
    if top.get("price"):
        details.append(str(top["price"]))
    if top.get("address"):
        details.append(top["address"])

    if details:
        return f"Found {len(results)} Yelp result(s) for '{find_desc}' in {find_loc}. Top result: {title}, {', '.join(details)}."
    return f"Found {len(results)} Yelp result(s) for '{find_desc}' in {find_loc}. Top result: {title}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        find_desc = str(input_data.get("find_desc", "")).strip()
        find_loc = str(input_data.get("find_loc", "")).strip() or get_default_location()
        attrs = input_data.get("attrs")
        sort_by = normalize_sort_by(input_data.get("sort_by"))
        dogs_allowed = parse_bool(input_data.get("dogs_allowed", False))
        place_id = str(input_data.get("place_id", "")).strip()
        include_reviews = parse_bool(input_data.get("include_reviews", False))
        review_limit = clamp_results_count(input_data.get("review_limit", 3), default=3)
        no_cache = parse_bool(input_data.get("no_cache", False))
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not find_desc:
            return_error("Parameter 'find_desc' is required.")
            return 1
        if not find_loc:
            return_error("Provide 'find_loc' or set JARVIS_DEFAULT_LOCATION.")
            return 1

        normalized_attrs = normalize_attrs(attrs, dogs_allowed=dogs_allowed)
        params: dict[str, Any] = {
            "engine": "yelp",
            "find_desc": find_desc,
            "find_loc": find_loc,
            "no_cache": "true" if no_cache else "false",
        }
        if normalized_attrs:
            params["attrs"] = normalized_attrs
        if sort_by:
            params["sortby"] = sort_by

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(
            params,
            allowed_error_substrings=("Yelp hasn't returned any results",),
        )
        results = extract_yelp_results(payload, limit=num_results)

        selected_place_id = place_id or (results[0].get("place_id") if results else None)
        review_data: dict[str, Any] | None = None
        if include_reviews and selected_place_id:
            review_payload = request_serpapi(
                {
                    "engine": "yelp_reviews",
                    "place_id": selected_place_id,
                    "no_cache": "true" if no_cache else "false",
                }
            )
            review_results = extract_yelp_reviews(review_payload, limit=review_limit)
            review_data = {
                "place_id": selected_place_id,
                "results_count": len(review_results),
                "reviews": review_results,
                "search_metadata": review_payload.get("search_metadata", {}),
            }
            if include_raw:
                review_data["raw"] = review_payload

        data: dict[str, Any] = {
            "engine": "yelp",
            "find_desc": find_desc,
            "find_loc": find_loc,
            "attrs": normalized_attrs,
            "sort_by": sort_by,
            "dogs_allowed": dogs_allowed,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "place_id": selected_place_id,
            "serpapi_error": payload.get("error"),
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if review_data is not None:
            data["review_data"] = review_data
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(find_desc, find_loc, results), data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi Yelp search timed out.")
            return 1
        return_error(f"SerpApi Yelp search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
