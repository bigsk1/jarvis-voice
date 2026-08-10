#!/usr/bin/env python3
"""Jarvis Skill: discover destinations with SerpApi Google Travel Explore.

This is the flexible planning stage before exact flight, hotel, or destination
research. It returns a bounded, normalized shortlist and never books travel.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import sys
from datetime import date, datetime
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from security_utils import redact_sensitive_text
from serpapi_client import (
    clamp_results_count,
    extract_travel_explore_destinations,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)
from time_utils import now_local

SERPAPI_TIMEOUT = 90
TRIP_TYPES = {"round_trip": 1, "one_way": 2}
TRAVEL_DURATIONS = {"weekend": 1, "one_week": 2, "two_weeks": 3}
TRAVEL_CLASSES = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
}
STOPS = {
    "any": 0,
    "nonstop": 1,
    "one_stop_or_fewer": 2,
    "two_stops_or_fewer": 3,
}
TRAVEL_MODES = {"all": 0, "flight_only": 1}
INTERESTS = {
    "popular": "0",
    "outdoors": "/g/11bc58l13w",
    "beaches": "/m/0b3yr",
    "museums": "/m/09cmq",
    "history": "/m/03g3w",
    "skiing": "/m/071k0",
}
SORTS = {"recommended", "flight_price", "hotel_price", "flight_duration"}
SORT_ALIASES = {
    "provider_order": "recommended",
    "relevance": "recommended",
    "popular": "recommended",
    "price": "flight_price",
    "airfare": "flight_price",
    "hotel": "hotel_price",
    "duration": "flight_duration",
    "fastest": "flight_duration",
}
ALLIANCES = {"STAR_ALLIANCE", "SKYTEAM", "ONEWORLD"}
KGMID_RE = re.compile(r"^/[mg]/[A-Za-z0-9_-]+$")
AIRPORT_RE = re.compile(r"^[A-Z]{3}$")
AIRLINE_RE = re.compile(r"^[A-Z0-9]{2}$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "json_restrictor",
    "departure_id",
    "arrival_area_id",
    "arrival_id",
    "type",
    "outbound_date",
    "return_date",
    "month",
    "travel_duration",
    "travel_class",
    "adults",
    "children",
    "infants_in_seat",
    "infants_on_lap",
    "stops",
    "travel_mode",
    "interest",
    "include_airlines",
    "exclude_airlines",
    "bags",
    "max_price",
    "max_duration",
    "currency",
    "hl",
    "gl",
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


def normalize_enum(
    value: Any, label: str, choices: dict[str, Any], *, default: str
) -> str:
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in choices:
        raise ValueError(f"'{label}' must be one of: {', '.join(choices)}.")
    return normalized


def normalize_sort(value: Any) -> str:
    if value in (None, ""):
        return "recommended"
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    normalized = SORT_ALIASES.get(normalized, normalized)
    if normalized not in SORTS:
        raise ValueError(
            "'sort_by' must be one of: recommended, flight_price, hotel_price, flight_duration."
        )
    return normalized


def normalize_departure_ids(value: Any) -> str:
    values = value if isinstance(value, list) else str(value or "").split(",")
    normalized: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        candidate = text if text.startswith("/") else text.upper()
        if not (AIRPORT_RE.fullmatch(candidate) or KGMID_RE.fullmatch(candidate)):
            raise ValueError(
                "'departure_id' values must be 3-letter IATA airport codes or "
                "Google location KGMIDs beginning /m/ or /g/."
            )
        if candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        raise ValueError("Provide 'departure_id' to explore destinations.")
    return ",".join(normalized)


def normalize_arrival_area_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not KGMID_RE.fullmatch(text):
        raise ValueError(
            "'arrival_area_id' must be a Google location KGMID beginning /m/ or /g/."
        )
    return text


def parse_future_date(value: Any, label: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"'{label}' must be a calendar date formatted YYYY-MM-DD.")
    if parsed.isoformat() != text:
        raise ValueError(f"'{label}' must be zero-padded YYYY-MM-DD, got '{text}'.")
    if parsed < now_local().date():
        raise ValueError(
            f"'{label}' ({text}) is in the past. Ask for the intended year if it is ambiguous."
        )
    return parsed


def parse_int(
    value: Any,
    label: str,
    *,
    default: int | None = None,
    minimum: int = 0,
    maximum: int | None = None,
) -> int | None:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' must be an integer.")
    if parsed < minimum or maximum is not None and parsed > maximum:
        bound = f"from {minimum} through {maximum}" if maximum is not None else f"at least {minimum}"
        raise ValueError(f"'{label}' must be {bound}, got {parsed}.")
    return parsed


def parse_month(value: Any) -> int:
    month = parse_int(value, "month", default=0, minimum=0, maximum=12)
    assert month is not None
    if month == 0:
        return 0
    current = now_local().date().month
    allowed = [((current - 1 + offset) % 12) + 1 for offset in range(6)]
    if month not in allowed:
        names = ", ".join(calendar.month_name[item] for item in allowed)
        raise ValueError(
            f"'month' must be within Google Explore's six selectable calendar months: {names}."
        )
    return month


def normalize_airlines(value: Any, label: str) -> str | None:
    if value in (None, "", []):
        return None
    values = value if isinstance(value, list) else str(value).split(",")
    normalized: list[str] = []
    for raw in values:
        candidate = str(raw).strip().upper().replace(" ", "_")
        if not candidate:
            continue
        if candidate not in ALLIANCES and not AIRLINE_RE.fullmatch(candidate):
            raise ValueError(
                f"'{label}' must contain 2-character airline codes or "
                "STAR_ALLIANCE, SKYTEAM, or ONEWORLD."
            )
        if candidate not in normalized:
            normalized.append(candidate)
    return ",".join(normalized) if normalized else None


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sort_results(
    results: list[dict[str, Any]], sort_by: str
) -> list[dict[str, Any]]:
    if sort_by == "recommended":
        return results
    field = {
        "flight_price": "flight_price",
        "hotel_price": "hotel_price",
        "flight_duration": "flight_duration_minutes",
    }[sort_by]

    def key(item: dict[str, Any]) -> tuple[int, float, int]:
        value = _numeric(item.get(field))
        return (1 if value is None else 0, value or 0.0, int(item.get("position") or 0))

    return sorted(results, key=key)


def search_travel_explore(
    options: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {
        "engine": "google_travel_explore",
        "departure_id": options["departure_id"],
        "type": TRIP_TYPES[options["trip_type"]],
        "travel_class": TRAVEL_CLASSES[options["travel_class"]],
        "adults": options["adults"],
        "children": options["children"],
        "infants_in_seat": options["infants_in_seat"],
        "infants_on_lap": options["infants_on_lap"],
        "stops": STOPS[options["stops"]],
        "bags": options["bags"],
        "currency": options["currency"],
        "hl": options["hl"],
        "gl": options["gl"],
        "no_cache": "true" if options["no_cache"] else "false",
    }
    if options["arrival_area_id"]:
        params["arrival_area_id"] = options["arrival_area_id"]
    if options["outbound_date"]:
        params["outbound_date"] = options["outbound_date"]
    if options["return_date"]:
        params["return_date"] = options["return_date"]
    if options["month"]:
        params["month"] = options["month"]
    if options["travel_duration"]:
        params["travel_duration"] = TRAVEL_DURATIONS[options["travel_duration"]]
    if options["travel_mode"]:
        params["travel_mode"] = TRAVEL_MODES[options["travel_mode"]]
    if options["interest"]:
        params["interest"] = INTERESTS[options["interest"]]
    for key in ("include_airlines", "exclude_airlines", "max_price", "max_duration"):
        if options[key] not in (None, ""):
            params[key] = options[key]

    merge_extra_params(params, options["extra_params"], reserved_keys=RESERVED_KEYS)
    payload = request_serpapi(params, timeout=SERPAPI_TIMEOUT)
    return extract_travel_explore_destinations(payload, limit=0), payload


def build_speech(
    departure_id: str,
    sort_by: str,
    currency: str,
    results: list[dict[str, Any]],
) -> str:
    if not results:
        return f"Google Travel Explore returned no destination ideas from {departure_id}."

    top = results[0]
    name = str(top.get("name") or "the top destination")
    dates = ""
    if top.get("start_date") and top.get("end_date"):
        dates = f" for {top['start_date']} through {top['end_date']}"
    elif top.get("start_date"):
        dates = f" starting {top['start_date']}"
    details = []
    if top.get("flight_price") not in (None, ""):
        details.append(f"headline flight fare {currency} {top['flight_price']}")
    if top.get("hotel_price") not in (None, ""):
        details.append(f"headline hotel price {currency} {top['hotel_price']}")
    detail_text = f" with {', '.join(details)}" if details else ""
    order_note = {
        "recommended": "Google's top suggestion",
        "flight_price": "Lowest returned headline airfare",
        "hotel_price": "Lowest returned headline hotel price",
        "flight_duration": "Shortest returned flight",
    }[sort_by]
    return (
        f"Found {len(results)} destination idea(s) from {departure_id}. "
        f"{order_note} is {name}{dates}{detail_text}. "
        "Use exact flight and hotel searches to confirm availability and final prices."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        try:
            departure_id = normalize_departure_ids(input_data.get("departure_id"))
            arrival_area_id = normalize_arrival_area_id(input_data.get("arrival_area_id"))
            trip_type = normalize_enum(
                input_data.get("trip_type"), "trip_type", TRIP_TYPES, default="round_trip"
            )
            travel_class = normalize_enum(
                input_data.get("travel_class"),
                "travel_class",
                TRAVEL_CLASSES,
                default="economy",
            )
            stops = normalize_enum(input_data.get("stops"), "stops", STOPS, default="any")
            sort_by = normalize_sort(input_data.get("sort_by"))

            outbound = parse_future_date(input_data.get("outbound_date"), "outbound_date")
            returning = parse_future_date(input_data.get("return_date"), "return_date")
            month = parse_month(input_data.get("month"))
            travel_duration_explicit = input_data.get("travel_duration") not in (None, "")
            travel_duration = normalize_enum(
                input_data.get("travel_duration"),
                "travel_duration",
                TRAVEL_DURATIONS,
                default="one_week",
            )

            if returning and not outbound:
                raise ValueError("'return_date' requires 'outbound_date'.")
            if outbound and month:
                raise ValueError("Use either exact dates or 'month', not both.")
            if outbound and travel_duration_explicit:
                raise ValueError("Use either exact dates or 'travel_duration', not both.")
            if trip_type == "round_trip" and outbound and not returning:
                raise ValueError("Round trips with an exact outbound date require 'return_date'.")
            if trip_type == "one_way" and returning:
                raise ValueError("One-way exploration cannot include 'return_date'.")
            if trip_type == "one_way" and travel_duration_explicit:
                raise ValueError("'travel_duration' applies only to round-trip exploration.")
            if outbound and returning and returning <= outbound:
                raise ValueError("'return_date' must be after 'outbound_date'.")

            adults = parse_int(input_data.get("adults"), "adults", default=1, minimum=1)
            children = parse_int(input_data.get("children"), "children", default=0, minimum=0)
            infants_in_seat = parse_int(
                input_data.get("infants_in_seat"), "infants_in_seat", default=0, minimum=0
            )
            infants_on_lap = parse_int(
                input_data.get("infants_on_lap"), "infants_on_lap", default=0, minimum=0
            )
            assert adults is not None and children is not None
            assert infants_in_seat is not None and infants_on_lap is not None
            total_travelers = adults + children + infants_in_seat + infants_on_lap
            if total_travelers > 9:
                raise ValueError("Google Travel Explore supports at most 9 travelers per search.")
            if infants_on_lap > adults:
                raise ValueError("'infants_on_lap' cannot exceed 'adults'.")
            bags = parse_int(input_data.get("bags"), "bags", default=0, minimum=0)
            assert bags is not None
            bag_eligible_travelers = adults + children + infants_in_seat
            if bags > bag_eligible_travelers:
                raise ValueError(
                    "'bags' cannot exceed adults, children, and seated infants combined."
                )

            max_price = parse_int(input_data.get("max_price"), "max_price", minimum=1)
            max_duration = parse_int(
                input_data.get("max_duration"), "max_duration", minimum=1
            )
            include_airlines = normalize_airlines(
                input_data.get("include_airlines"), "include_airlines"
            )
            exclude_airlines = normalize_airlines(
                input_data.get("exclude_airlines"), "exclude_airlines"
            )
            if include_airlines and exclude_airlines:
                raise ValueError("Use either 'include_airlines' or 'exclude_airlines', not both.")

            travel_mode_explicit = input_data.get("travel_mode") not in (None, "")
            interest_explicit = input_data.get("interest") not in (None, "")
            travel_mode = normalize_enum(
                input_data.get("travel_mode"),
                "travel_mode",
                TRAVEL_MODES,
                default="all",
            )
            interest = normalize_enum(
                input_data.get("interest"), "interest", INTERESTS, default="popular"
            )
            if travel_mode_explicit and interest_explicit:
                raise ValueError("'travel_mode' and 'interest' cannot be used together.")
        except ValueError as validation_error:
            return_error(str(validation_error))
            return 1

        currency = str(input_data.get("currency", "USD")).strip().upper() or "USD"
        if not re.fullmatch(r"[A-Z]{3}", currency):
            return_error("'currency' must be a 3-letter code such as USD or EUR.")
            return 1
        hl = str(input_data.get("hl", "en")).strip().lower() or "en"
        gl = str(input_data.get("gl", "us")).strip().lower() or "us"
        if not re.fullmatch(r"[a-z]{2}", hl):
            return_error("'hl' must be a 2-letter Google language code such as en.")
            return 1
        if not re.fullmatch(r"[a-z]{2}", gl):
            return_error("'gl' must be a 2-letter Google country code such as us.")
            return 1

        options: dict[str, Any] = {
            "departure_id": departure_id,
            "arrival_area_id": arrival_area_id,
            "trip_type": trip_type,
            "outbound_date": outbound.isoformat() if outbound else None,
            "return_date": returning.isoformat() if returning else None,
            "month": month,
            "travel_duration": (
                travel_duration if trip_type == "round_trip" and not outbound else None
            ),
            "travel_class": travel_class,
            "adults": adults,
            "children": children,
            "infants_in_seat": infants_in_seat,
            "infants_on_lap": infants_on_lap,
            "stops": stops,
            "travel_mode": travel_mode if travel_mode_explicit else None,
            "interest": interest if interest_explicit else None,
            "include_airlines": include_airlines,
            "exclude_airlines": exclude_airlines,
            "bags": bags,
            "max_price": max_price,
            "max_duration": max_duration,
            "currency": currency,
            "hl": hl,
            "gl": gl,
            "no_cache": parse_bool(input_data.get("no_cache", False)),
            "extra_params": input_data.get("extra_params", {}) or {},
        }
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        include_raw = parse_bool(input_data.get("include_raw", False))

        all_results, payload = search_travel_explore(options)
        provider_results_count = len(all_results)
        results = sort_results(all_results, sort_by)[:num_results]
        speech = build_speech(departure_id, sort_by, currency, results)

        applied_filters = {
            key: value
            for key, value in {
                "arrival_area_id": arrival_area_id,
                "outbound_date": options["outbound_date"],
                "return_date": options["return_date"],
                "month": month or None,
                "travel_duration": options["travel_duration"],
                "travel_class": travel_class if travel_class != "economy" else None,
                "stops": stops if stops != "any" else None,
                "travel_mode": travel_mode if travel_mode_explicit else None,
                "interest": interest if interest_explicit else None,
                "include_airlines": include_airlines,
                "exclude_airlines": exclude_airlines,
                "bags": bags or None,
                "max_price": max_price,
                "max_duration": max_duration,
            }.items()
            if value not in (None, "", [], {})
        }
        metadata = payload.get("search_metadata") or {}
        flexible = not options["outbound_date"]
        data: dict[str, Any] = {
            "engine": "google_travel_explore",
            "provider": "serpapi",
            "planning_stage": "destination_discovery",
            "departure_id": departure_id,
            "arrival_area_id": arrival_area_id,
            "trip_type": trip_type,
            "date_mode": "flexible" if flexible else "exact",
            "outbound_date": options["outbound_date"],
            "return_date": options["return_date"],
            "month": month,
            "month_label": "next_six_months" if month == 0 else calendar.month_name[month],
            "travel_duration": options["travel_duration"],
            "travel_class": travel_class,
            "travel_mode": travel_mode if travel_mode_explicit else "all",
            "interest": interest if interest_explicit else "popular",
            "travelers": {
                "adults": adults,
                "children": children,
                "infants_in_seat": infants_in_seat,
                "infants_on_lap": infants_on_lap,
            },
            "currency": currency,
            "sort_by": sort_by,
            "sort_basis": (
                "provider_order" if sort_by == "recommended" else "local_sort_of_returned_page"
            ),
            "applied_filters": applied_filters,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("google_travel_url") if results else None,
            "flight_price_basis": f"provider_headline_{trip_type}_fare",
            "hotel_price_basis": "provider_headline_lodging_price_unspecified",
            "price_confirmation_required": True,
            "booking_note": (
                "Explore prices are planning signals, not booking quotes. Confirm the chosen "
                "route with flight_search and the stay with serpapi_hotel_search before booking."
            ),
            "serpapi_searches_used": 1,
            "search_metadata": {
                "id": metadata.get("id"),
                "status": metadata.get("status"),
                "total_time_taken": metadata.get("total_time_taken"),
                "cached": metadata.get("cached"),
            },
            "google_travel_url": metadata.get("google_travel_explore_url"),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Travel Explore",
        }
        if include_raw:
            data["raw"] = payload

        return_success(speech=speech, data=data)
        return 0
    except Exception as exc:
        message = redact_sensitive_text(str(exc))[:1000]
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error(
                "SerpApi Travel Explore timed out. Try again or narrow the filters."
            )
            return 1
        return_error(f"SerpApi Travel Explore error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
