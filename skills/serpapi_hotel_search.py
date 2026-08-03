#!/usr/bin/env python3
"""Jarvis Skill: SerpApi Google Hotels search.

Searches future stays once, normalizes the complete returned property page, and
then applies the requested ordering locally. Prices are reference prices; the
tool never books a room or submits payment.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    extract_hotel_results,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)
from time_utils import now_local


SERPAPI_TIMEOUT = 45
SORTS = {
    "price": 3,
    "rating": 8,
    "reviews": 13,
    "relevance": None,
}
SORT_ALIASES = {
    "3": "price",
    "lowest_price": "price",
    "cheapest": "price",
    "8": "rating",
    "highest_rating": "rating",
    "13": "reviews",
    "most_reviewed": "reviews",
    "top": "relevance",
}
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "json_restrictor",
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
    "special_offers",
    "eco_certified",
    "vacation_rentals",
    "bedrooms",
    "bathrooms",
    "next_page_token",
    "property_token",
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


def parse_stay_date(value: Any, label: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"'{label}' must be a calendar date formatted YYYY-MM-DD, got '{text}'."
        )
    if parsed.isoformat() != text:
        raise ValueError(
            f"'{label}' must be zero-padded YYYY-MM-DD, got '{text}'."
        )
    if parsed < now_local().date():
        raise ValueError(
            f"'{label}' ({text}) is in the past. Ask for the intended year if it is ambiguous."
        )
    return parsed


def parse_count(value: Any, label: str, *, default: int, minimum: int) -> int:
    if value is None:
        return default
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' must be an integer.")
    if count < minimum:
        raise ValueError(f"'{label}' must be at least {minimum}, got {count}.")
    return count


def parse_optional_int(value: Any, label: str, *, minimum: int = 0) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' must be an integer.")
    if number < minimum:
        raise ValueError(f"'{label}' must be at least {minimum}, got {number}.")
    return number


def parse_int_csv(value: Any, label: str, *, minimum: int = 0) -> list[int]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    parsed: list[int] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"'{label}' must contain integer IDs, got '{text}'.")
        if number < minimum:
            raise ValueError(
                f"'{label}' values must be at least {minimum}, got {number}."
            )
        parsed.append(number)
    return parsed


def serialize_int_csv(value: Any, label: str) -> str | None:
    values = parse_int_csv(value, label)
    return ",".join(str(item) for item in values) if values else None


def normalize_sort(value: Any) -> str:
    if value in (None, ""):
        return "price"
    normalized = str(value).strip().lower().replace(" ", "_")
    normalized = SORT_ALIASES.get(normalized, normalized)
    if normalized not in SORTS:
        raise ValueError(
            "'sort_by' must be one of: price, rating, reviews, relevance."
        )
    return normalized


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def sort_results(
    results: list[dict[str, Any]], sort_by: str, *, nights: int
) -> list[dict[str, Any]]:
    """Apply deterministic ordering to every property returned by SerpApi."""
    if sort_by == "relevance":
        return results

    if sort_by == "price":
        def price_key(item: dict[str, Any]) -> tuple[int, float, float]:
            total = _numeric(item.get("extracted_price_total"))
            nightly = _numeric(item.get("extracted_price_per_night"))
            comparable = total if total is not None else (
                nightly * nights if nightly is not None else None
            )
            return (
                1 if comparable is None else 0,
                comparable or 0.0,
                nightly or 0.0,
            )

        return sorted(results, key=price_key)

    field = "rating" if sort_by == "rating" else "reviews"

    def descending_key(item: dict[str, Any]) -> tuple[int, float]:
        value = _numeric(item.get(field))
        return (1 if value is None else 0, -(value or 0.0))

    return sorted(results, key=descending_key)


def build_speech(
    destination: str,
    check_in_date: str,
    check_out_date: str,
    nights: int,
    sort_by: str,
    results: list[dict[str, Any]],
) -> str:
    if not results:
        return (
            f"No hotel results found for {destination} from {check_in_date} "
            f"to {check_out_date}."
        )

    top = results[0]
    title = str(top.get("title") or "the top property").strip()
    total = top.get("price_total")
    nightly = top.get("price_per_night")
    rating = top.get("rating")
    stay_label = f"{nights} night" if nights == 1 else f"{nights} nights"

    if sort_by == "price" and (total or nightly):
        price_parts = []
        if total:
            price_parts.append(f"{total} total")
        if nightly:
            price_parts.append(f"{nightly} per night")
        detail = f"Lowest returned price is {'; '.join(price_parts)} at {title}"
    else:
        labels = {
            "rating": "Highest-rated returned option",
            "reviews": "Most-reviewed returned option",
            "relevance": "Top returned option",
        }
        detail = f"{labels.get(sort_by, 'Top returned option')} is {title}"
        if total:
            detail += f" at {total} total"
        elif nightly:
            detail += f" at {nightly} per night"

    if rating is not None:
        detail += f", rated {rating}"
    return (
        f"Found {len(results)} hotel option(s) in {destination} for {stay_label}, "
        f"{check_in_date} to {check_out_date}. {detail}."
    )


def search_hotels(options: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": options["query"],
        "check_in_date": options["check_in_date"],
        "check_out_date": options["check_out_date"],
        "adults": options["adults"],
        "children": options["children"],
        "currency": options["currency"],
        "device": options["device"],
        "no_cache": "true" if options["no_cache"] else "false",
        "hl": options["hl"],
        "gl": options["gl"],
    }
    if options["children_ages"]:
        params["children_ages"] = ",".join(
            str(age) for age in options["children_ages"]
        )
    provider_sort = SORTS[options["sort_by"]]
    if provider_sort is not None:
        params["sort_by"] = provider_sort
    for key in ("min_price", "max_price", "rating"):
        if options[key] is not None:
            params[key] = options[key]
    for key in ("hotel_class", "property_types", "amenities", "brands"):
        if options[key]:
            params[key] = options[key]
    for key in ("free_cancellation", "special_offers", "eco_certified"):
        if options[key]:
            params[key] = "true"

    merge_extra_params(params, options["extra_params"], reserved_keys=RESERVED_KEYS)
    payload = request_serpapi(params, timeout=SERPAPI_TIMEOUT)
    return extract_hotel_results(payload, limit=0), payload


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
        if not query:
            return_error(
                "Provide 'destination' (or a full 'query') for the hotel search."
            )
            return 1
        destination = destination or query

        try:
            check_in = parse_stay_date(
                input_data.get("check_in_date"), "check_in_date"
            )
            check_out = parse_stay_date(
                input_data.get("check_out_date"), "check_out_date"
            )
            if check_in is None or check_out is None:
                raise ValueError(
                    "Both 'check_in_date' and 'check_out_date' are required, formatted YYYY-MM-DD."
                )
            if check_out <= check_in:
                raise ValueError(
                    f"'check_out_date' ({check_out.isoformat()}) must be after "
                    f"'check_in_date' ({check_in.isoformat()})."
                )

            adults = parse_count(
                input_data.get("adults"), "adults", default=2, minimum=1
            )
            children = parse_count(
                input_data.get("children"), "children", default=0, minimum=0
            )
            children_ages = parse_int_csv(
                input_data.get("children_ages"), "children_ages"
            )
            if children_ages and len(children_ages) != children:
                raise ValueError(
                    "The number of 'children_ages' values must match 'children'."
                )
            invalid_ages = [age for age in children_ages if not 1 <= age <= 17]
            if invalid_ages:
                raise ValueError(
                    "Each child age must be from 1 through 17; "
                    f"got {invalid_ages}."
                )

            min_price = parse_optional_int(input_data.get("min_price"), "min_price")
            max_price = parse_optional_int(input_data.get("max_price"), "max_price")
            if min_price is not None and max_price is not None and min_price > max_price:
                raise ValueError("'min_price' cannot be greater than 'max_price'.")

            rating = parse_optional_int(input_data.get("rating"), "rating")
            if rating is not None and rating not in {7, 8, 9}:
                raise ValueError("'rating' must be 7 (3.5+), 8 (4.0+), or 9 (4.5+).")

            hotel_classes = parse_int_csv(input_data.get("hotel_class"), "hotel_class")
            invalid_classes = [value for value in hotel_classes if value not in {2, 3, 4, 5}]
            if invalid_classes:
                raise ValueError(
                    "'hotel_class' values must be 2, 3, 4, or 5; "
                    f"got {invalid_classes}."
                )
            property_types = parse_int_csv(
                input_data.get("property_types"), "property_types", minimum=1
            )
            amenities = parse_int_csv(
                input_data.get("amenities"), "amenities", minimum=1
            )
            brands = parse_int_csv(input_data.get("brands"), "brands", minimum=1)
            sort_by = normalize_sort(input_data.get("sort_by"))
        except ValueError as validation_error:
            return_error(str(validation_error))
            return 1

        currency = str(input_data.get("currency", "USD")).strip().upper() or "USD"
        if len(currency) != 3 or not currency.isalpha():
            return_error("'currency' must be a 3-letter code such as USD or EUR.")
            return 1
        device = str(input_data.get("device", "desktop")).strip().lower()
        if device not in {"desktop", "mobile", "tablet"}:
            return_error("'device' must be desktop, mobile, or tablet.")
            return 1

        nights = (check_out - check_in).days
        options: dict[str, Any] = {
            "query": query,
            "check_in_date": check_in.isoformat(),
            "check_out_date": check_out.isoformat(),
            "adults": adults,
            "children": children,
            "children_ages": children_ages,
            "currency": currency,
            "hl": str(input_data.get("hl", "en")).strip() or "en",
            "gl": str(input_data.get("gl", "us")).strip().lower() or "us",
            "device": device,
            "sort_by": sort_by,
            "min_price": min_price,
            "max_price": max_price,
            "rating": rating,
            "hotel_class": ",".join(str(value) for value in hotel_classes) or None,
            "property_types": serialize_int_csv(property_types, "property_types"),
            "amenities": serialize_int_csv(amenities, "amenities"),
            "brands": serialize_int_csv(brands, "brands"),
            "free_cancellation": parse_bool(input_data.get("free_cancellation", False)),
            "special_offers": parse_bool(input_data.get("special_offers", False)),
            "eco_certified": parse_bool(input_data.get("eco_certified", False)),
            "no_cache": parse_bool(input_data.get("no_cache", False)),
            "extra_params": input_data.get("extra_params", {}) or {},
        }
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        include_raw = parse_bool(input_data.get("include_raw", False))

        all_results, payload = search_hotels(options)
        provider_results_count = len(all_results)
        results = sort_results(all_results, sort_by, nights=nights)[:num_results]
        speech = build_speech(
            destination,
            options["check_in_date"],
            options["check_out_date"],
            nights,
            sort_by,
            results,
        )

        totals = [
            item.get("extracted_price_total")
            for item in results
            if _numeric(item.get("extracted_price_total")) is not None
        ]
        nightly_prices = [
            item.get("extracted_price_per_night")
            for item in results
            if _numeric(item.get("extracted_price_per_night")) is not None
        ]
        applied_filters = {
            key: value
            for key, value in {
                "min_price": min_price,
                "max_price": max_price,
                "rating": rating,
                "hotel_class": hotel_classes,
                "property_types": property_types,
                "amenities": amenities,
                "brands": brands,
                "free_cancellation": options["free_cancellation"] or None,
                "special_offers": options["special_offers"] or None,
                "eco_certified": options["eco_certified"] or None,
            }.items()
            if value not in (None, "", [], {})
        }
        metadata = payload.get("search_metadata") or {}
        data: dict[str, Any] = {
            "engine": "google_hotels",
            "provider": "serpapi",
            "query": query,
            "destination": destination,
            "check_in_date": options["check_in_date"],
            "check_out_date": options["check_out_date"],
            "nights": nights,
            "adults": adults,
            "children": children,
            "guests": {
                "adults": adults,
                "children": children,
                "children_ages": children_ages,
            },
            "currency": currency,
            "sort_by": sort_by,
            "applied_filters": applied_filters,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "cheapest_price_total": min(totals, key=float) if totals else None,
            "cheapest_price_per_night": min(nightly_prices, key=float) if nightly_prices else None,
            "price_basis": "lowest_listed_total_for_entire_stay",
            "booking_note": (
                "Prices can change and may have cancellation or room restrictions. "
                "Review the property or booking-provider page and book manually."
            ),
            "serpapi_searches_used": 1,
            "search_metadata": {
                "id": metadata.get("id"),
                "status": metadata.get("status"),
                "total_time_taken": metadata.get("total_time_taken"),
            },
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Hotels",
        }
        if include_raw:
            data["raw"] = payload

        return_success(speech=speech, data=data)
        return 0

    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi hotel search timed out. Try again or narrow the filters.")
            return 1
        return_error(f"SerpApi hotel search error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
