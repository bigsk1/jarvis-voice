"""Airbnb search parameters and listing evidence without inferred destinations or dates."""
from __future__ import annotations

import json
import math
import re
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

AIRBNB_TIMEOUT = 60
AIRBNB_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
AIRBNB_RESULT_BYTES = 56 * 1024
PROPERTY_TYPES = ("house", "apartment", "guesthouse", "hotel")
AMENITIES = (
    "wifi", "kitchen", "washer", "dryer", "air_conditioning", "heating", "dedicated_workspace",
    "tv", "hair_dryer", "iron", "pool", "hot_tub", "free_parking", "ev_charger", "crib", "king_bed",
    "gym", "bbq_grill", "breakfast", "indoor_fireplace", "smoking_allowed", "waterfront", "smoke_alarm",
    "carbon_monoxide_alarm", "private_attached_bathroom",
)
BOOKING_OPTIONS = ("instant_book", "self_check_in", "guest_favorite", "luxe")
NIGHTLY_AVERAGE_NOTE = "Average stay total per night, including fees; not the base nightly rate."
BOOKING_CAVEAT = (
    "Prices and availability may change before booking; review the listing's fees, cancellation and house rules. "
    "Entire-home and house filters approximate whole houses, not guaranteed detached single-family homes. "
    "No smoke-free or pet-free restriction is established by this search. Pets above zero request pet-friendly stays."
)


def read_input(argv: list[str]) -> dict[str, Any]:
    value = json.loads(argv[1]) if len(argv) > 1 else {}
    if not isinstance(value, dict):
        raise ValueError("Tool input must be a JSON object.")
    return value


def _date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Dates must use YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Dates must be valid calendar dates in YYYY-MM-DD format.") from None


def _number(value: Any, *, minimum: float | None = 0, maximum: float | None = None) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return None
    if not finite or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return value


def validate_options(options: dict[str, Any]) -> None:
    strings = {"query", "check_in_date", "check_out_date", "room_type", "currency"}
    integers = {"adults", "children", "infants", "pets", "bedrooms", "beds", "num_results", "page"}
    numbers = {"bathrooms", "min_price_per_night", "max_price_per_night"}
    booleans = {"use_price_filter", "no_cache", *BOOKING_OPTIONS}
    arrays = {"property_types", "amenities"}
    if options.keys() - strings - integers - numbers - booleans - arrays:
        raise ValueError("Unknown Airbnb argument; use the declared tool parameters.")
    for key, value in options.items():
        if key in strings and not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if key in integers and type(value) is not int:
            raise ValueError(f"{key} must be an integer.")
        if key in numbers and _number(value, maximum=1000000) is None:
            raise ValueError(f"{key} must be a finite nonnegative number no greater than 1000000.")
        if key in booleans and type(value) is not bool:
            raise ValueError(f"{key} must be a boolean.")
        if key in arrays:
            supported = PROPERTY_TYPES if key == "property_types" else AMENITIES
            if (not isinstance(value, list) or len(value) > len(supported)
                    or any(not isinstance(item, str) or item not in supported for item in value)):
                raise ValueError(f"{key} must contain only documented Airbnb identifiers.")
    if not options.get("query", "").strip() or len(options["query"]) > 400:
        raise ValueError("Provide an explicit destination in query (1 to 400 characters).")
    if options.get("room_type", "entire_home") not in {"entire_home", "private_room"}:
        raise ValueError("room_type must be entire_home or private_room.")
    if not re.fullmatch(r"[A-Z]{3}", options.get("currency", "USD")):
        raise ValueError("currency must be a three-letter uppercase currency code.")
    if not 1 <= options.get("page", 1) <= 15:
        raise ValueError("page must be between 1 and 15.")
    for key in ("adults", "children", "infants", "pets", "bedrooms", "beds"):
        if key in options and not (1 if key == "adults" else 0) <= options[key] <= 50:
            raise ValueError(f"{key} is outside the supported range (up to 50).")
    if "bathrooms" in options and options["bathrooms"] > 50:
        raise ValueError("bathrooms must be between 0 and 50.")
    if ("check_in_date" in options) != ("check_out_date" in options):
        raise ValueError("Provide check_in_date and check_out_date together, or omit both.")
    if "check_in_date" in options and _date(options["check_out_date"]) <= _date(options["check_in_date"]):
        raise ValueError("check_out_date must be later than check_in_date.")
    if ("min_price_per_night" in options and "max_price_per_night" in options
            and options["min_price_per_night"] > options["max_price_per_night"]):
        raise ValueError("min_price_per_night cannot exceed max_price_per_night.")


def build_search_parameters(options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Translate nightly preferences to the provider's fee-inclusive stay-total filter."""
    validate_options(options)
    explicit = "check_in_date" in options
    nights = (_date(options["check_out_date"]) - _date(options["check_in_date"])).days if explicit else None
    mode = "explicit" if explicit else "suggested"
    room_type = options.get("room_type", "entire_home")
    properties = list(dict.fromkeys(options.get("property_types", ["house"] if room_type == "entire_home" else [])))
    amenities = list(dict.fromkeys(options.get("amenities", [])))
    context: dict[str, Any] = {
        "query": options["query"].strip(), "check_in_date": options.get("check_in_date"),
        "check_out_date": options.get("check_out_date"), "nights": nights, "dates_mode": mode,
        "adults": options.get("adults", 2), "children": options.get("children", 0),
        "infants": options.get("infants", 0), "pets": options.get("pets", 0),
        "room_type": room_type, "property_types": properties, "amenities": amenities,
        "currency": options.get("currency", "USD"),
    }
    params: dict[str, Any] = {
        "engine": "airbnb", "q": context["query"], "currency": context["currency"],
        "room_type": room_type, "adults": context["adults"], "page": options.get("page", 1),
        "no_cache": "true" if options.get("no_cache", False) else "false",
    }
    if explicit:
        params.update(check_in_date=options["check_in_date"], check_out_date=options["check_out_date"])
    for key in ("property_types", "amenities"):
        if context[key]:
            params[key] = ",".join(context[key])
    for key in ("children", "infants", "pets"):
        if context[key] > 0:
            params[key] = context[key]
    requested_filters = {key: context[key] for key in ("room_type", "property_types", "amenities", "adults", "children", "infants", "pets")}
    for key in ("bedrooms", "beds", "bathrooms"):
        if key in options:
            params[key] = requested_filters[key] = options[key]
    for key in BOOKING_OPTIONS:
        if key in options:
            params[key] = "true" if options[key] else "false"
            requested_filters[key] = options[key]
    enabled = options.get("use_price_filter", True)
    custom = "min_price_per_night" in options or "max_price_per_night" in options
    minimum = options.get("min_price_per_night") if custom else 125
    maximum = options.get("max_price_per_night") if custom else 250
    filter_nights = nights if nights is not None else 5
    budget: dict[str, Any] = {
        "enabled": enabled, "currency": context["currency"], "filter_nights": filter_nights,
        "min_price_per_night": minimum if enabled else None, "max_price_per_night": maximum if enabled else None,
        "provider_min_price": None, "provider_max_price": None,
    }
    if enabled:
        for value, field, provider_key in ((minimum, "provider_min_price", "min_price"), (maximum, "provider_max_price", "max_price")):
            if value is not None:
                amount = Decimal(str(value)) * filter_nights
                params[provider_key] = budget[field] = int(amount) if amount == amount.to_integral_value() else float(amount)
        budget["note"] = (
            f"Nightly budget bounds are multiplied by {filter_nights} nights for Airbnb's fee-inclusive total-trip filter. "
            + ("These are the explicitly requested dates." if explicit else
               "No dates were requested: the filter assumes 5 nights, while Airbnb suggests dates separately for each listing; actual stay lengths can differ.")
        )
    else:
        budget["note"] = "No price filter applied; nightly budget bounds were not sent."
    return params, context, budget, requested_filters


def _text(value: Any, maximum: int = 400) -> str | None:
    return value[:maximum] if isinstance(value, str) else None


def _strings(value: Any, maximum: int = 10) -> list[str]:
    return [item[:400] for item in value if isinstance(item, str)][:maximum] if isinstance(value, list) else []


def _url(value: Any, *, image: bool = False) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048 or "\\" in value:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        allowed = hostname == "airbnb.com" or hostname.endswith(".airbnb.com")
        if image:
            allowed = allowed or hostname == "muscache.com" or hostname.endswith(".muscache.com")
        if (not allowed or parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 80, 443}):
            return None
    except ValueError:
        return None
    return value


def normalize_listing(item: dict[str, Any], *, currency: str, dates_mode: str, position: int) -> dict[str, Any] | None:
    """Keep each stay total, source URL and actual suggested dates together."""
    url = _url(item.get("link"))
    match = re.fullmatch(r"/rooms/([0-9]{1,32})/?", urlsplit(url).path) if url else None
    identifier = item.get("listing_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{1,32}", identifier):
        identifier = match.group(1) if match else None
    if identifier is None or (match and match.group(1) != identifier):
        return None
    if not match:
        url = None
    check_in = check_out = None
    nights = None
    try:
        start, end = _date(item.get("check_in_date")), _date(item.get("check_out_date"))
        if end > start:
            check_in, check_out, nights = start.isoformat(), end.isoformat(), (end - start).days
    except ValueError:
        pass
    qualifier = _text(item.get("price_qualifier"))
    price_nights = re.fullmatch(r"(?:for\s+)?([0-9]+)\s+nights?", qualifier.strip(), re.IGNORECASE) if qualifier else None
    stated_nights = int(price_nights.group(1)) if price_nights else None
    conflict = nights is not None and stated_nights is not None and stated_nights != nights
    if nights is None and stated_nights and stated_nights <= 3660:
        nights = stated_nights
    total = _number(item.get("extracted_price"))
    average = round(total / nights, 2) if total is not None and nights and not conflict else None
    thumbnail = _url(item.get("thumbnail"), image=True)
    images = [_url(value, image=True) for value in item.get("images", [])] if isinstance(item.get("images"), list) else []
    images = list(dict.fromkeys(value for value in [thumbnail, *images] if value))[:5]
    breakdown = []
    for line in item.get("price_breakdown", []) if isinstance(item.get("price_breakdown"), list) else []:
        if isinstance(line, dict):
            breakdown.append({"description": _text(line.get("description")), "price": _text(line.get("price")),
                              "extracted_price": _number(line.get("extracted_price"), minimum=None),
                              "old_price": _text(line.get("old_price")),
                              "extracted_old_price": _number(line.get("extracted_old_price"))})
        if len(breakdown) >= 12:
            break
    coordinates = item.get("gps_coordinates")
    gps = {}
    if isinstance(coordinates, dict):
        for key, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
            value = _number(coordinates.get(key), minimum=minimum, maximum=maximum)
            if value is not None:
                gps[key] = value
    reviews = _number(item.get("reviews"))
    result = {
        "position": position, "listing_id": identifier, "name": _text(item.get("name")),
        "title": _text(item.get("title")), "description": _text(item.get("description"), 1600), "url": url,
        "currency": currency, "total_price": total, "price_formatted": _text(item.get("price")),
        "price_qualifier": qualifier, "old_total_price": _number(item.get("extracted_old_price")),
        "old_price_formatted": _text(item.get("old_price")), "price_breakdown": breakdown,
        "price_disclaimers": _strings(item.get("price_disclaimers")),
        "check_in_date": check_in, "check_out_date": check_out, "nights": nights, "dates_mode": dates_mode,
        "nightly_average": average,
        "nightly_average_note": "Provider dates and price qualifier disagree; no nightly average calculated." if conflict else NIGHTLY_AVERAGE_NOTE,
        "rating": _number(item.get("rating"), maximum=5),
        "reviews": int(reviews) if reviews is not None and reviews == int(reviews) else None,
        "bedrooms": _number(item.get("bedrooms")), "beds": _number(item.get("beds")),
        "bathrooms": _number(item.get("bathrooms")), "details": _strings(item.get("details")),
        "badges": _strings(item.get("badges")), "highlights": _strings(item.get("highlights")),
        "free_cancellation": item.get("free_cancellation") if type(item.get("free_cancellation")) is bool else None,
        "is_new_listing": item.get("is_new_listing") if type(item.get("is_new_listing")) is bool else None,
        "host_type": _text(item.get("host_type")), "gps_coordinates": gps,
        "thumbnail": images[0] if images else None, "image_url": images[0] if images else None, "images": images,
    }
    result["result_truncated"] = (
        any(isinstance(item.get(key), str) and len(item[key]) > maximum
            for key, maximum in (("name", 400), ("title", 400), ("description", 1600), ("price_qualifier", 400),
                                 ("price", 400), ("old_price", 400), ("host_type", 400)))
        or any(isinstance(item.get(key), list) and (len(item[key]) > 10
               or any(isinstance(value, str) and len(value) > 400 for value in item[key]))
               for key in ("details", "badges", "highlights", "price_disclaimers"))
        or (isinstance(item.get("images"), list) and len(item["images"]) > 5)
        or (isinstance(item.get("price_breakdown"), list) and (len(item["price_breakdown"]) > 12
            or any(isinstance(line, dict) and any(isinstance(line.get(key), str) and len(line[key]) > 400
                   for key in ("description", "price", "old_price")) for line in item["price_breakdown"])))
    )
    return result


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Airbnb returned an invalid response.")
    metadata, parameters = payload.get("search_metadata", {}), payload.get("search_parameters", {})
    if not isinstance(metadata, dict) or metadata.get("status", "Success") != "Success" or payload.get("error"):
        raise ValueError("Airbnb did not return a completed result.")
    if not isinstance(parameters, dict) or parameters.get("engine", "airbnb") != "airbnb":
        raise ValueError("Airbnb returned a response for a different engine.")
    return payload


def bound_result_data(data: dict[str, Any]) -> None:
    """Bound returned JSON while retaining listing identities before optional detail."""
    def oversized() -> bool:
        return len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > AIRBNB_RESULT_BYTES

    if not oversized():
        return
    data["result_truncated"] = True
    data["top_results"] = []
    for row in data["results"]:
        row["description"] = _text(row.get("description"), 300)
        row["images"] = row["images"][:1]
        for key in ("price_breakdown", "price_disclaimers", "details", "badges", "highlights"):
            row[key] = row[key][:3]
    if not oversized():
        return
    for row in data["results"]:
        row.pop("thumbnail", None)
        row["images"] = []
        row["description"] = None
        for key in ("price_breakdown", "price_disclaimers", "details", "badges", "highlights"):
            row[key] = []
    while oversized() and data["results"]:
        data["results"].pop()
        data["results_truncated"] = True
    data["results_count"] = len(data["results"])
