#!/usr/bin/env python3
"""Jarvis Skill: Tripadvisor discovery, place details, and reviews via SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


SERPAPI_TIMEOUT = 45
TRIPADVISOR_DOMAIN_RE = re.compile(r"^(?:www\.)?tripadvisor\.[a-z.]{2,24}$", re.IGNORECASE)

ACTION_ALIASES = {
    "search": "search",
    "find": "search",
    "discover": "search",
    "details": "details",
    "detail": "details",
    "place": "details",
    "reviews": "reviews",
    "review": "reviews",
}

CATEGORY_CODES = {
    "all": "a",
    "restaurants": "r",
    "restaurant": "r",
    "things_to_do": "A",
    "things_to_do_and_attractions": "A",
    "attractions": "A",
    "attraction": "A",
    "hotels": "h",
    "hotel": "h",
    "destinations": "g",
    "destination": "g",
    "forums": "f",
    "forum": "f",
}

VISIT_TYPES = {
    "business": "Business",
    "couples": "Couples",
    "family": "Family",
    "friends": "Friends",
    "solo": "Solo",
}

RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "json_restrictor",
    "q",
    "place_id",
    "tripadvisor_domain",
    "ssrc",
    "lat",
    "lon",
    "offset",
    "limit",
    "language",
    "sort_by",
    "translate",
    "rating",
    "month",
    "type_of_visit",
    "original_language",
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


def normalize_action(value: Any) -> str:
    normalized = str(value or "search").strip().lower().replace("-", "_").replace(" ", "_")
    action = ACTION_ALIASES.get(normalized)
    if not action:
        raise ValueError("'action' must be search, details, or reviews.")
    return action


def normalize_category(value: Any) -> tuple[str, str]:
    normalized = str(value or "all").strip().lower().replace("-", "_").replace(" ", "_")
    code = CATEGORY_CODES.get(normalized)
    if not code:
        raise ValueError(
            "'category' must be all, restaurants, things_to_do, hotels, destinations, or forums."
        )
    canonical = next(name for name, candidate in CATEGORY_CODES.items() if candidate == code)
    return canonical, code


def normalize_domain(value: Any) -> str:
    domain = str(value or "www.tripadvisor.com").strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    if not TRIPADVISOR_DOMAIN_RE.fullmatch(domain):
        raise ValueError("'tripadvisor_domain' must be a Tripadvisor hostname such as www.tripadvisor.com.")
    return domain


def parse_nonnegative_int(value: Any, label: str, *, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' must be a non-negative integer.")
    if number < 0:
        raise ValueError(f"'{label}' must be a non-negative integer.")
    return number


def parse_coordinate(value: Any, label: str, minimum: float, maximum: float) -> float | None:
    if value in (None, ""):
        return None
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' must be a number between {minimum} and {maximum}.")
    if not minimum <= coordinate <= maximum:
        raise ValueError(f"'{label}' must be between {minimum} and {maximum}.")
    return coordinate


def _csv_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else str(value or "").split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def serialize_int_filter(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> str | None:
    if value in (None, "", []):
        return None
    parsed: list[str] = []
    for item in _csv_values(value):
        try:
            number = int(item)
        except ValueError:
            raise ValueError(f"'{label}' must contain integers from {minimum} to {maximum}.")
        if not minimum <= number <= maximum:
            raise ValueError(f"'{label}' values must be from {minimum} to {maximum}.")
        text = str(number)
        if text not in parsed:
            parsed.append(text)
    return ",".join(parsed) if parsed else None


def normalize_visit_types(value: Any) -> str | None:
    if value in (None, "", []):
        return None
    normalized: list[str] = []
    for item in _csv_values(value):
        canonical = VISIT_TYPES.get(item.lower())
        if not canonical:
            raise ValueError("'type_of_visit' accepts Business, Couples, Family, Friends, or Solo.")
        if canonical not in normalized:
            normalized.append(canonical)
    return ",".join(normalized) if normalized else None


def normalize_languages(value: Any) -> str | None:
    if value in (None, "", []):
        return None
    normalized: list[str] = []
    for item in _csv_values(value):
        code = item.lower()
        if not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{2,8})?", code):
            raise ValueError("'original_language' must contain language codes such as en, fr, or es.")
        if code not in normalized:
            normalized.append(code)
    return ",".join(normalized) if normalized else None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any, maximum: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("name") or item.get("title") or item.get("text")
        text = str(item or "").strip()
        if text and text not in strings:
            strings.append(text)
        if len(strings) >= maximum:
            break
    return strings


def _image_urls(value: Any, maximum: int = 8) -> list[str]:
    images: list[str] = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, dict):
            item = item.get("original") or item.get("link") or item.get("url") or item.get("thumbnail")
        url = str(item or "").strip()
        if url.startswith(("https://", "http://")) and url not in images:
            images.append(url)
        if len(images) >= maximum:
            break
    return images


def extract_tripadvisor_search_results(
    payload: dict[str, Any], limit: int = 10
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in _dict_list(payload.get("places")):
        highlighted = item.get("highlighted_review")
        highlighted = highlighted if isinstance(highlighted, dict) else {}
        result = {
            "position": item.get("position"),
            "title": item.get("title") or item.get("name"),
            "place_id": str(item.get("place_id")) if item.get("place_id") not in (None, "") else None,
            "place_type": item.get("place_type") or item.get("type"),
            "url": item.get("link") or item.get("url"),
            "description": item.get("description") or item.get("snippet"),
            "rating": item.get("rating"),
            "reviews": item.get("reviews") or item.get("review_count"),
            "location": item.get("location") or item.get("address"),
            "thumbnail": item.get("thumbnail") or item.get("image"),
            "highlighted_review": {
                "text": highlighted.get("text"),
                "mention_count": highlighted.get("mention_count"),
            } if highlighted else None,
            "source": "places",
        }
        if not result["title"] and not result["place_id"] and not result["url"]:
            continue
        results.append(result)
        if limit and len(results) >= limit:
            break
    return results


def _normalize_related_place(item: dict[str, Any], group: str) -> dict[str, Any] | None:
    title = item.get("name") or item.get("title")
    place_id = item.get("place_id")
    url = item.get("link") or item.get("url")
    if not title and place_id in (None, "") and not url:
        return None
    return {
        "title": title,
        "place_id": str(place_id) if place_id not in (None, "") else None,
        "place_type": item.get("type") or group.rstrip("s"),
        "url": url,
        "serpapi_url": item.get("serpapi_link"),
        "thumbnail": item.get("thumbnail") or item.get("image"),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "address": item.get("address"),
        "distance": item.get("distance"),
        "categories": _string_list(item.get("categories") or item.get("cuisines"), 6),
        "additional_info": item.get("additional_info") or item.get("description"),
        "price": item.get("price") or item.get("price_level"),
        "group": group,
    }


def extract_interesting_places(place: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    for key, group in (
        ("attraction_suggestions", "attractions"),
        ("hotel_suggestions", "hotels"),
        ("restaurant_suggestions", "restaurants"),
    ):
        section = place.get(key)
        if isinstance(section, dict):
            candidates.append((group, section.get("items")))

    nearby = place.get("nearby")
    if isinstance(nearby, dict):
        for group in ("attractions", "restaurants", "hotels", "airports", "transit"):
            candidates.append((group, nearby.get(group)))

    related = place.get("related_places")
    if isinstance(related, list):
        candidates.append(("related", related))

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group, values in candidates:
        for item in _dict_list(values):
            normalized = _normalize_related_place(item, group)
            if not normalized:
                continue
            identity = str(normalized.get("place_id") or normalized.get("url") or normalized.get("title")).lower()
            if identity in seen:
                continue
            seen.add(identity)
            results.append(normalized)
            if len(results) >= limit:
                return results
    return results


def extract_tripadvisor_place(
    payload: dict[str, Any], place_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = payload.get("place_result")
    if not isinstance(raw, dict) or not raw:
        return {}, []

    images = _image_urls(raw.get("images"))
    prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
    offers = []
    for offer in _dict_list(prices.get("offers"))[:5]:
        compact = {
            "provider": offer.get("provider"),
            "price": offer.get("price"),
            "extracted_price": offer.get("extracted_price"),
            "additional_info": offer.get("additional_info"),
            "url": offer.get("link"),
        }
        if any(value not in (None, "", [], {}) for value in compact.values()):
            offers.append(compact)

    travel_advice = []
    for item in _dict_list(raw.get("travel_advice"))[:8]:
        if item.get("title") or item.get("link"):
            travel_advice.append({"title": item.get("title"), "url": item.get("link")})

    metadata = payload.get("search_metadata") or {}
    place = {
        "place_id": place_id,
        "place_type": raw.get("type"),
        "title": raw.get("name") or raw.get("title"),
        "url": raw.get("link") or raw.get("url") or metadata.get("tripadvisor_place_url"),
        "description": raw.get("description") or raw.get("about"),
        "rating": raw.get("rating"),
        "reviews": raw.get("reviews") or raw.get("review_count"),
        "ranking": raw.get("ranking"),
        "address": raw.get("address") or raw.get("location"),
        "phone": raw.get("phone"),
        "website": raw.get("website"),
        "price_level": raw.get("price_level"),
        "categories": _string_list(raw.get("categories"), 12),
        "amenities": _string_list(raw.get("amenities"), 24),
        "hours": raw.get("hours") if isinstance(raw.get("hours"), (dict, list)) else None,
        "gps_coordinates": raw.get("gps_coordinates"),
        "thumbnail": images[0] if images else raw.get("thumbnail"),
        "images": images,
        "travel_advice": travel_advice,
        "price_context": {
            key: prices.get(key)
            for key in ("check_in", "check_out", "rooms", "guests")
            if prices.get(key) not in (None, "")
        },
        "offers": offers,
        "source": "place_result",
    }
    interesting_places = extract_interesting_places(raw)
    return place, interesting_places


def extract_tripadvisor_reviews(
    payload: dict[str, Any], limit: int = 10
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for item in _dict_list(payload.get("reviews")):
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        trip_info = item.get("trip_info") if isinstance(item.get("trip_info"), dict) else {}
        review = {
            "position": item.get("position"),
            "title": item.get("title"),
            "text": item.get("snippet") or item.get("text"),
            "rating": item.get("rating"),
            "review_id": str(item.get("review_id")) if item.get("review_id") not in (None, "") else None,
            "url": item.get("link") or item.get("url"),
            "date": item.get("date"),
            "language": item.get("language"),
            "original_language": item.get("original_language"),
            "trip_date": trip_info.get("date"),
            "trip_type": trip_info.get("type"),
            "votes": item.get("votes"),
            "author_name": author.get("display_name") or author.get("username"),
            "author_username": author.get("username"),
            "author_url": author.get("link"),
            "author_avatar": author.get("avatar"),
            "author_contributions": author.get("contributions"),
            "author_hometown": author.get("hometown"),
            "source": "reviews",
        }
        if not review["title"] and not review["text"] and not review["review_id"]:
            continue
        reviews.append(review)
        if limit and len(reviews) >= limit:
            break
    return reviews


def _search_metadata(payload: dict[str, Any], url_key: str) -> dict[str, Any]:
    metadata = payload.get("search_metadata") or {}
    return {
        key: metadata.get(key)
        for key in ("id", "status", "total_time_taken", url_key)
        if metadata.get(key) not in (None, "")
    }


def _tripadvisor_request(params: dict[str, Any]) -> dict[str, Any]:
    # The shared helper remains proxy-capable. The manifest's proxy_policy=off
    # makes normal Jarvis execution direct; changing that policy later enables
    # the configured proxy chain without changing this tool.
    return request_serpapi(
        params,
        timeout=SERPAPI_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def fetch_place_details(
    place_id: str,
    *,
    domain: str,
    no_cache: bool,
    extra_params: Any,
    include_raw: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "tripadvisor_place",
        "place_id": place_id,
        "tripadvisor_domain": domain,
        "no_cache": "true" if no_cache else "false",
    }
    merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
    payload = _tripadvisor_request(params)
    place, interesting_places = extract_tripadvisor_place(payload, place_id)
    if not place:
        raise RuntimeError(f"Tripadvisor returned no place details for place_id {place_id}.")
    result: dict[str, Any] = {
        "place_id": place_id,
        "place": place,
        "interesting_places": interesting_places,
        "interesting_places_count": len(interesting_places),
        "search_metadata": _search_metadata(payload, "tripadvisor_place_url"),
    }
    if include_raw:
        result["raw"] = payload
    return result


def fetch_reviews(
    place_id: str,
    *,
    domain: str,
    language: str | None,
    sort_by: str,
    translate: bool,
    rating: str | None,
    month: str | None,
    type_of_visit: str | None,
    original_language: str | None,
    offset: int,
    limit: int,
    no_cache: bool,
    extra_params: Any,
    include_raw: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "tripadvisor_reviews",
        "place_id": place_id,
        "tripadvisor_domain": domain,
        "sort_by": sort_by,
        "translate": "true" if translate else "false",
        "offset": offset,
        "limit": limit,
        "no_cache": "true" if no_cache else "false",
    }
    for key, value in (
        ("language", language),
        ("rating", rating),
        ("month", month),
        ("type_of_visit", type_of_visit),
        ("original_language", original_language),
    ):
        if value not in (None, ""):
            params[key] = value
    merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
    payload = _tripadvisor_request(params)
    reviews = extract_tripadvisor_reviews(payload, limit=limit)
    search_information = payload.get("search_information") or {}
    result: dict[str, Any] = {
        "place_id": place_id,
        "total_reviews": search_information.get("total_reviews"),
        "results_count": len(reviews),
        "reviews": reviews,
        "search_metadata": _search_metadata(payload, "tripadvisor_reviews_url"),
    }
    if include_raw:
        result["raw"] = payload
    return result


def build_search_speech(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No Tripadvisor results found for '{query}'."
    top = results[0]
    detail = []
    if top.get("rating") is not None:
        detail.append(f"rated {top['rating']}")
    if top.get("location"):
        detail.append(str(top["location"]))
    suffix = f", {', '.join(detail)}" if detail else ""
    return f"Found {len(results)} Tripadvisor result(s) for '{query}'. Top result: {top.get('title') or 'result'}{suffix}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        action = normalize_action(input_data.get("action"))
        place_id = str(input_data.get("place_id") or "").strip()
        domain = normalize_domain(input_data.get("tripadvisor_domain"))
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params") or {}

        if action == "details":
            if not place_id:
                raise ValueError("'place_id' is required when action is details.")
            detail_data = fetch_place_details(
                place_id,
                domain=domain,
                no_cache=no_cache,
                extra_params=extra_params,
                include_raw=include_raw,
            )
            place = detail_data["place"]
            data = {
                "action": action,
                "engine": "tripadvisor_place",
                "tripadvisor_domain": domain,
                "place_id": place_id,
                "place": place,
                "interesting_places": detail_data["interesting_places"],
                "interesting_places_count": detail_data["interesting_places_count"],
                "results_count": 1,
                "results": [place],
                "top_results": [place],
                "top_url": place.get("url"),
                "serpapi_searches_used": 1,
                "search_metadata": detail_data["search_metadata"],
                "proxy_enabled": get_proxy_enabled(),
                "source": "SerpApi Tripadvisor Place",
            }
            if include_raw:
                data["raw"] = detail_data.get("raw")
            return_success(
                f"Found Tripadvisor details for {place.get('title') or place_id}, including {len(detail_data['interesting_places'])} nearby suggestion(s).",
                data,
            )
            return 0

        review_limit = clamp_results_count(
            input_data.get("review_limit", 10), default=10, maximum=20
        )
        review_offset = parse_nonnegative_int(input_data.get("review_offset"), "review_offset")
        sort_by = str(input_data.get("review_sort_by") or "most_recent").strip().lower()
        if sort_by not in {"most_recent", "detailed_review"}:
            raise ValueError("'review_sort_by' must be most_recent or detailed_review.")
        language = str(input_data.get("language") or "").strip() or None
        translate = parse_bool(input_data.get("translate", False))
        rating = serialize_int_filter(input_data.get("rating"), "rating", minimum=1, maximum=5)
        month = serialize_int_filter(input_data.get("month"), "month", minimum=1, maximum=12)
        type_of_visit = normalize_visit_types(input_data.get("type_of_visit"))
        original_language = normalize_languages(input_data.get("original_language"))

        if action == "reviews":
            if not place_id:
                raise ValueError("'place_id' is required when action is reviews.")
            review_data = fetch_reviews(
                place_id,
                domain=domain,
                language=language,
                sort_by=sort_by,
                translate=translate,
                rating=rating,
                month=month,
                type_of_visit=type_of_visit,
                original_language=original_language,
                offset=review_offset,
                limit=review_limit,
                no_cache=no_cache,
                extra_params=extra_params,
                include_raw=include_raw,
            )
            reviews = review_data["reviews"]
            data = {
                "action": action,
                "engine": "tripadvisor_reviews",
                "tripadvisor_domain": domain,
                "place_id": place_id,
                "review_sort_by": sort_by,
                "review_filters": {
                    "rating": rating,
                    "month": month,
                    "type_of_visit": type_of_visit,
                    "original_language": original_language,
                    "language": language,
                    "translate": translate,
                },
                "review_offset": review_offset,
                "total_reviews": review_data.get("total_reviews"),
                "results_count": len(reviews),
                "reviews": reviews,
                "results": reviews,
                "top_results": reviews[:5],
                "top_url": reviews[0].get("url") if reviews else None,
                "serpapi_searches_used": 1,
                "search_metadata": review_data["search_metadata"],
                "proxy_enabled": get_proxy_enabled(),
                "source": "SerpApi Tripadvisor Reviews",
            }
            if include_raw:
                data["raw"] = review_data.get("raw")
            return_success(
                f"Found {len(reviews)} Tripadvisor review(s) for place {place_id}.",
                data,
            )
            return 0

        query = str(input_data.get("query") or "").strip()
        if not query:
            raise ValueError("'query' is required when action is search.")
        category, category_code = normalize_category(input_data.get("category"))
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        offset = parse_nonnegative_int(input_data.get("offset"), "offset")
        latitude = parse_coordinate(input_data.get("lat"), "lat", -90, 90)
        longitude = parse_coordinate(input_data.get("lon"), "lon", -180, 180)
        if (latitude is None) != (longitude is None):
            raise ValueError("Provide both 'lat' and 'lon', or omit both.")

        params: dict[str, Any] = {
            "engine": "tripadvisor",
            "q": query,
            "ssrc": category_code,
            "tripadvisor_domain": domain,
            "offset": offset,
            "limit": num_results,
            "no_cache": "true" if no_cache else "false",
        }
        if latitude is not None and longitude is not None:
            params["lat"] = latitude
            params["lon"] = longitude
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = _tripadvisor_request(params)
        results = extract_tripadvisor_search_results(payload, limit=num_results)
        selected_place_id = place_id or (results[0].get("place_id") if results else None)
        include_details = parse_bool(input_data.get("include_details", False))
        include_reviews = parse_bool(input_data.get("include_reviews", False))
        searches_used = 1
        enrichment_errors: dict[str, str] = {}

        data: dict[str, Any] = {
            "action": action,
            "engine": "tripadvisor",
            "query": query,
            "category": category,
            "category_code": category_code,
            "tripadvisor_domain": domain,
            "lat": latitude,
            "lon": longitude,
            "offset": offset,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "place_id": selected_place_id,
            "serpapi_error": payload.get("error"),
            "search_metadata": _search_metadata(payload, "tripadvisor_url"),
            "search_information": payload.get("search_information") or {},
            "source": "SerpApi Tripadvisor",
        }

        if include_details and selected_place_id:
            try:
                data["detail_data"] = fetch_place_details(
                    selected_place_id,
                    domain=domain,
                    no_cache=no_cache,
                    # extra_params belongs to the selected search action. Do not
                    # leak search-engine-only options into enrichment engines.
                    extra_params={},
                    include_raw=include_raw,
                )
                searches_used += 1
            except Exception as exc:
                enrichment_errors["details"] = str(exc)

        if include_reviews and selected_place_id:
            try:
                data["review_data"] = fetch_reviews(
                    selected_place_id,
                    domain=domain,
                    language=language,
                    sort_by=sort_by,
                    translate=translate,
                    rating=rating,
                    month=month,
                    type_of_visit=type_of_visit,
                    original_language=original_language,
                    offset=review_offset,
                    limit=review_limit,
                    no_cache=no_cache,
                    extra_params={},
                    include_raw=include_raw,
                )
                searches_used += 1
            except Exception as exc:
                enrichment_errors["reviews"] = str(exc)

        if (include_details or include_reviews) and not selected_place_id:
            enrichment_errors["place_id"] = "No place_id was available for enrichment."
        if enrichment_errors:
            data["enrichment_errors"] = enrichment_errors
        data["serpapi_searches_used"] = searches_used
        data["proxy_enabled"] = get_proxy_enabled()
        if include_raw:
            data["raw"] = payload

        return_success(build_search_speech(query, results), data)
        return 0

    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Tripadvisor request timed out.")
            return 1
        return_error(f"SerpApi Tripadvisor error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
