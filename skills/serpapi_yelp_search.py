#!/usr/bin/env python3
"""Jarvis Skill: SerpApi Yelp place discovery with optional review lookup."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import unquote, urlparse

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
    "async",
    "json_restrictor",
}

SORT_ALIASES = {
    "best": "recommended",
    "best_match": "recommended",
    "recommended": "recommended",
    "rating": "rating",
    "highest_rated": "rating",
    "review_count": "review_count",
    "reviews": "review_count",
    "most_reviewed": "review_count",
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


def normalize_sort_by(sort_by: Any) -> str:
    normalized = str(sort_by or "recommended").strip().lower().replace(" ", "_")
    normalized = SORT_ALIASES.get(normalized, normalized)
    if normalized not in {"recommended", "rating", "review_count"}:
        raise ValueError(
            "'sort_by' must be recommended, rating, or review_count."
        )
    return normalized


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sort_yelp_results(
    results: list[dict[str, Any]], sort_by: str
) -> list[dict[str, Any]]:
    """Order the complete provider page without triggering skeletal sorted rows."""
    if sort_by == "recommended":
        return results

    primary = "rating" if sort_by == "rating" else "reviews"
    secondary = "reviews" if sort_by == "rating" else "rating"

    def descending(item: dict[str, Any]) -> tuple[int, float, int, float]:
        first = _numeric(item.get(primary))
        second = _numeric(item.get(secondary))
        return (
            1 if first is None else 0,
            -(first or 0.0),
            1 if second is None else 0,
            -(second or 0.0),
        )

    return sorted(results, key=descending)


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


def _normalize_string_list(value: Any, *, dict_key: str = "title") -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get(dict_key)
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_neighborhoods(value: Any) -> str | None:
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(values) if values else None
    text = str(value or "").strip()
    return text or None


def _extract_place_ids(item: dict[str, Any]) -> list[str]:
    raw = item.get("place_ids")
    values = raw if isinstance(raw, list) else []
    if not values:
        values = [
            item.get("place_id"),
            item.get("biz_id"),
            item.get("business_id"),
        ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _title_from_yelp_url(value: Any) -> str | None:
    try:
        slug = unquote(urlparse(str(value or "")).path).rstrip("/").split("/")[-1]
    except (TypeError, ValueError):
        return None
    if not slug:
        return None
    return " ".join(part for part in slug.replace("_", "-").split("-") if part).title()


def extract_yelp_results(payload: dict[str, Any], limit: int = 0) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    values = payload.get("organic_results")
    if not isinstance(values, list):
        return results
    for item in values:
        if not isinstance(item, dict):
            continue

        url = item.get("link") or item.get("url")
        title = item.get("title") or item.get("name")
        title_source = "provider"
        if not title and url:
            title = _title_from_yelp_url(url)
            title_source = "url_slug"
        place_ids = _extract_place_ids(item)
        result = {
            "position": item.get("position"),
            "title": title,
            "title_source": title_source,
            "url": url,
            "place_id": place_ids[0] if place_ids else None,
            "place_ids": place_ids,
            "rating": item.get("rating"),
            "reviews": item.get("reviews") if item.get("reviews") is not None else item.get("review_count"),
            "price": item.get("price"),
            "phone": item.get("phone"),
            "address": _normalize_address(item),
            "categories": _normalize_string_list(item.get("categories")),
            "neighborhoods": _normalize_neighborhoods(item.get("neighborhoods")),
            "open_state": item.get("open_state"),
            "service_options": item.get("service_options") if isinstance(item.get("service_options"), dict) else None,
            "highlights": _normalize_string_list(item.get("highlights"), dict_key="text"),
            "thumbnail": item.get("thumbnail") or item.get("image") or item.get("photo"),
            "snippet": item.get("snippet") or item.get("description"),
            "source": "organic_results",
        }
        if not result["title"] and not result["url"] and not result["place_id"]:
            continue
        results.append(result)
        if limit > 0 and len(results) >= limit:
            break

    return results


def extract_yelp_reviews(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in payload.get("reviews") or []:
        if not isinstance(item, dict):
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        comment = item.get("comment") if isinstance(item.get("comment"), dict) else {}
        photos = []
        for photo in item.get("photos") or []:
            if isinstance(photo, dict) and photo.get("link"):
                photos.append(
                    {
                        key: photo[key]
                        for key in ("link", "caption")
                        if photo.get(key) not in (None, "")
                    }
                )
        results.append(
            {
                "position": item.get("position"),
                "rating": item.get("rating"),
                "date": item.get("date"),
                "text": item.get("text") or item.get("snippet") or comment.get("text"),
                "language": comment.get("language"),
                "user_name": user.get("name"),
                "user_id": user.get("user_id"),
                "user_url": user.get("link"),
                "user_location": user.get("address"),
                "feedback": item.get("feedback") if isinstance(item.get("feedback"), dict) else None,
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
        try:
            sort_by = normalize_sort_by(input_data.get("sort_by"))
        except ValueError as validation_error:
            return_error(str(validation_error))
            return 1
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
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(
            params,
            allowed_error_substrings=("Yelp hasn't returned any results",),
        )
        all_results = extract_yelp_results(payload, limit=0)
        provider_results_count = len(all_results)
        results = sort_yelp_results(all_results, sort_by)[:num_results]

        selected_place_id = place_id or (results[0].get("place_id") if results else None)
        review_data: dict[str, Any] | None = None
        serpapi_searches_used = 1
        if include_reviews and selected_place_id:
            review_payload = request_serpapi(
                {
                    "engine": "yelp_reviews",
                    "place_id": selected_place_id,
                    "num": review_limit,
                    "no_cache": "true" if no_cache else "false",
                }
            )
            serpapi_searches_used += 1
            review_results = extract_yelp_reviews(review_payload, limit=review_limit)
            review_search_information = review_payload.get("search_information") or {}
            review_data = {
                "place_id": selected_place_id,
                "business": review_search_information.get("business"),
                "total_results": review_search_information.get("total_results"),
                "results_count": len(review_results),
                "reviews": review_results,
                "search_metadata": {
                    key: (review_payload.get("search_metadata") or {}).get(key)
                    for key in ("id", "status", "total_time_taken", "yelp_reviews_url")
                },
            }
            if include_raw:
                review_data["raw"] = review_payload

        data: dict[str, Any] = {
            "engine": "yelp",
            "find_desc": find_desc,
            "find_loc": find_loc,
            "attrs": normalized_attrs,
            "sort_by": sort_by,
            "sort_basis": (
                "provider_recommended_order"
                if sort_by == "recommended"
                else "local_sort_of_returned_page"
            ),
            "dogs_allowed": dogs_allowed,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "place_id": selected_place_id,
            "serpapi_error": payload.get("error"),
            "serpapi_searches_used": serpapi_searches_used,
            "search_metadata": {
                key: (payload.get("search_metadata") or {}).get(key)
                for key in ("id", "status", "total_time_taken", "yelp_url")
            },
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Yelp",
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
