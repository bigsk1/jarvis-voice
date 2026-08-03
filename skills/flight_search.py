#!/usr/bin/env python3
"""
Jarvis Skill: Flight Search

Returns real flight times and prices for a route so the booking itself can be
done manually on the airline or Google Flights site.

Providers, selected automatically with no extra configuration:
  1. SerpApi `google_flights` when SERP_API_KEY is set (richer: flight numbers,
     price insights, layover detail, filters).
  2. `fast-flights` otherwise — keyless Google Flights reader. Google rejects a
     minority of these queries outright, so it is a fallback, not the default.

Round trips are a single request. Google prices a round trip as one total and
shows the outbound options for it, which is what both providers return here.
"""
import json
import os
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    extract_flight_results,
    extract_price_insights,
    format_duration_minutes,
    get_api_key,
    get_proxy_enabled,
    parse_bool,
    request_serpapi,
)
from time_utils import now_local


SERPAPI_TIMEOUT = 45
SERPAPI_DEEP_SEARCH_TIMEOUT = 90

TRAVEL_CLASSES = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
}
TRAVEL_CLASS_SEATS = {
    "economy": "economy",
    "premium_economy": "premium-economy",
    "business": "business",
    "first": "first",
}
STOPS = {
    "any": 0,
    "nonstop": 1,
    "one_stop_or_fewer": 2,
    "two_stops_or_fewer": 3,
}
# fast-flights takes a literal maximum rather than SerpApi's enum.
STOPS_MAX = {
    "any": None,
    "nonstop": 0,
    "one_stop_or_fewer": 1,
    "two_stops_or_fewer": 2,
}
SORTS = {
    "price": 2,
    "top_flights": 1,
    "departure_time": 3,
    "arrival_time": 4,
    "duration": 5,
    "emissions": 6,
}

# fast-flights only encodes route, date, cabin, passengers, and max stops into
# its query. Anything else has to be applied locally or reported as unapplied.
FALLBACK_UNSUPPORTED = ("max_price", "exclude_airlines", "outbound_times", "return_times", "deep_search")


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


def serpapi_configured() -> bool:
    try:
        get_api_key()
        return True
    except ValueError:
        return False


def parse_airport(value: Any) -> str:
    """Accept 'PDX', 'pdx', or a comma-separated list of nearby airports."""
    codes = [part.strip().upper() for part in str(value or "").split(",")]
    return ",".join(code for code in codes if code)


def parse_date(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"'{label}' must be a calendar date formatted YYYY-MM-DD, got '{text}'.")
    if parsed < now_local().date():
        raise ValueError(f"'{label}' ({text}) is in the past. Ask for the intended year if it is ambiguous.")
    return text


def parse_count(value: Any, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def serialize_csv(value: Any) -> str | None:
    if isinstance(value, list):
        items = [str(item).strip().upper() for item in value if str(item).strip()]
        return ",".join(items) if items else None
    text = str(value or "").strip().upper()
    return text or None


def sort_results(results: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    """Order itineraries locally so every provider honors the requested sort."""
    def price_key(item: dict[str, Any]) -> tuple[int, float]:
        price = item.get("price")
        return (1, 0.0) if price is None else (0, float(price))

    def duration_key(item: dict[str, Any]) -> tuple[int, float]:
        duration = item.get("total_duration_minutes")
        return (1, 0.0) if duration is None else (0, float(duration))

    def departure_key(item: dict[str, Any]) -> tuple[int, str]:
        depart = item.get("departure_time")
        return (1, "") if not depart else (0, str(depart))

    if sort_by == "price":
        return sorted(results, key=price_key)
    if sort_by == "duration":
        return sorted(results, key=duration_key)
    if sort_by == "departure_time":
        return sorted(results, key=departure_key)
    return results


def format_clock(value: Any) -> str | None:
    """Turn '2026-09-15 07:03' into '7:03 AM on Tue Sep 15' for speech."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return text
    clock = parsed.strftime("%I:%M %p").lstrip("0")
    return f"{clock} on {parsed.strftime('%a %b %d')}"


def build_speech(
    results: list[dict[str, Any]],
    departure_id: str,
    arrival_id: str,
    trip_type: str,
    currency: str,
    price_insights: dict[str, Any],
) -> str:
    trip_label = "round trip" if trip_type == "round_trip" else "one way"
    if not results:
        return f"No {trip_label} flights found from {departure_id} to {arrival_id} on those dates."

    top = results[0]
    price = top.get("price")
    symbol = "$" if currency == "USD" else f"{currency} "
    price_text = f"{symbol}{price}" if price is not None else "an unlisted price"
    airline = ", ".join(top.get("airlines") or []) or "multiple airlines"

    parts = [
        f"Found {len(results)} {trip_label} option(s) from {departure_id} to {arrival_id}.",
        f"Best price is {price_text} on {airline}, {top.get('stops_label', 'unknown stops')}",
    ]
    duration = top.get("duration_display")
    if duration:
        parts[-1] += f", {duration}"
    departs = format_clock(top.get("departure_time"))
    if departs:
        parts[-1] += f", departing {departs}"
    parts[-1] += "."

    level = price_insights.get("price_level")
    if level:
        parts.append(f"Google rates that as a {level} price for this route.")
    return " ".join(parts)


def search_serpapi(options: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": options["departure_id"],
        "arrival_id": options["arrival_id"],
        "outbound_date": options["outbound_date"],
        "type": 1 if options["trip_type"] == "round_trip" else 2,
        "travel_class": TRAVEL_CLASSES[options["travel_class"]],
        "adults": options["adults"],
        "sort_by": SORTS[options["sort_by"]],
        "currency": options["currency"],
        "hl": "en",
        "gl": "us",
    }
    if options["trip_type"] == "round_trip":
        params["return_date"] = options["return_date"]
    for key in ("children", "infants_in_seat", "infants_on_lap"):
        if options[key]:
            params[key] = options[key]
    if options["stops"] != "any":
        params["stops"] = STOPS[options["stops"]]
    if options["max_price"] is not None:
        params["max_price"] = options["max_price"]
    if options["include_airlines"]:
        params["include_airlines"] = options["include_airlines"]
    elif options["exclude_airlines"]:
        params["exclude_airlines"] = options["exclude_airlines"]
    if options["outbound_times"]:
        params["outbound_times"] = options["outbound_times"]
    if options["return_times"] and options["trip_type"] == "round_trip":
        params["return_times"] = options["return_times"]
    if options["deep_search"]:
        params["deep_search"] = "true"

    timeout = SERPAPI_DEEP_SEARCH_TIMEOUT if options["deep_search"] else SERPAPI_TIMEOUT
    payload = request_serpapi(params, timeout=timeout)

    # Both buckets are normalized before the cap so a price sort can see every
    # itinerary, not just the first page of Google's own picks.
    results = extract_flight_results(payload, limit=0)
    meta = {
        "price_insights": extract_price_insights(payload),
        "booking_url": (payload.get("search_metadata") or {}).get("google_flights_url"),
        "serpapi_searches_used": 1,
    }
    return results, meta


def convert_fallback_datetime(value: Any) -> str | None:
    """Render fast-flights' SimpleDatetime as 'YYYY-MM-DD HH:MM'."""
    date_parts = list(getattr(value, "date", None) or [])
    time_parts = list(getattr(value, "time", None) or [])
    if len(date_parts) < 3:
        return None
    hour = time_parts[0] if len(time_parts) >= 1 else 0
    minute = time_parts[1] if len(time_parts) >= 2 else 0
    try:
        return f"{int(date_parts[0]):04d}-{int(date_parts[1]):02d}-{int(date_parts[2]):02d} {int(hour):02d}:{int(minute):02d}"
    except (TypeError, ValueError):
        return None


def convert_fallback_itinerary(entry: Any, travel_class: str) -> dict[str, Any]:
    """Map a fast-flights result onto the same shape as the SerpApi extractor.

    Flight numbers, legroom, and delay history are absent from this source, so
    those fields stay null rather than being guessed at.
    """
    segments: list[dict[str, Any]] = []
    for leg in getattr(entry, "flights", None) or []:
        from_airport = getattr(leg, "from_airport", None)
        to_airport = getattr(leg, "to_airport", None)
        segments.append(
            {
                "flight_number": None,
                "airline": None,
                "from": getattr(from_airport, "code", None),
                "to": getattr(to_airport, "code", None),
                "depart": convert_fallback_datetime(getattr(leg, "departure", None)),
                "arrive": convert_fallback_datetime(getattr(leg, "arrival", None)),
                "duration_minutes": getattr(leg, "duration", None),
                "duration_display": format_duration_minutes(getattr(leg, "duration", None)),
                "aircraft": getattr(leg, "plane_type", None),
                "travel_class": travel_class.replace("_", " ").title(),
                "legroom": None,
                "overnight": None,
                "often_delayed": None,
            }
        )

    layovers: list[dict[str, Any]] = []
    for previous, following in zip(segments, segments[1:]):
        minutes = None
        try:
            arrive = datetime.strptime(str(previous.get("arrive")), "%Y-%m-%d %H:%M")
            depart = datetime.strptime(str(following.get("depart")), "%Y-%m-%d %H:%M")
            minutes = max(0, int((depart - arrive).total_seconds() // 60))
        except (TypeError, ValueError):
            minutes = None
        layovers.append(
            {
                "airport": previous.get("to"),
                "duration_minutes": minutes,
                "duration_display": format_duration_minutes(minutes),
                "overnight": None,
            }
        )

    first = segments[0] if segments else {}
    last = segments[-1] if segments else {}
    total_duration = sum(
        segment.get("duration_minutes") or 0 for segment in segments
    ) + sum(layover.get("duration_minutes") or 0 for layover in layovers)
    emission = getattr(getattr(entry, "carbon", None), "emission", None)
    price = getattr(entry, "price", None)

    return {
        "price": price if isinstance(price, int) and price > 0 else None,
        "airlines": list(getattr(entry, "airlines", None) or []),
        "flight_numbers": [],
        "departure_airport": first.get("from"),
        "departure_time": first.get("depart"),
        "arrival_airport": last.get("to"),
        "arrival_time": last.get("arrive"),
        "total_duration_minutes": total_duration or None,
        "duration_display": format_duration_minutes(total_duration),
        "stops": max(0, len(segments) - 1),
        "stops_label": "Nonstop" if len(segments) <= 1 else (f"{len(segments) - 1} stop" if len(segments) == 2 else f"{len(segments) - 1} stops"),
        "travel_class": first.get("travel_class"),
        "layovers": layovers,
        "segments": segments,
        "carbon_kg": round(emission / 1000) if isinstance(emission, (int, float)) else None,
        "often_delayed": None,
        "overnight": None,
        "source": "fast_flights",
    }


def search_fallback(options: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from fast_flights import FlightQuery, Passengers, create_query, get_flights
    except ImportError:
        raise RuntimeError(
            "No flight provider available. Set SERP_API_KEY for SerpApi Google Flights, "
            "or install the keyless fallback with 'pip install fast-flights'."
        )

    legs = [
        FlightQuery(
            date=options["outbound_date"],
            from_airport=options["departure_id"],
            to_airport=options["arrival_id"],
        )
    ]
    if options["trip_type"] == "round_trip":
        legs.append(
            FlightQuery(
                date=options["return_date"],
                from_airport=options["arrival_id"],
                to_airport=options["departure_id"],
            )
        )

    query = create_query(
        flights=legs,
        seat=TRAVEL_CLASS_SEATS[options["travel_class"]],
        trip="round-trip" if options["trip_type"] == "round_trip" else "one-way",
        passengers=Passengers(
            adults=options["adults"],
            children=options["children"],
            infants_in_seat=options["infants_in_seat"],
            infants_on_lap=options["infants_on_lap"],
        ),
        currency=options["currency"],
        language="en-US",
        max_stops=STOPS_MAX[options["stops"]],
    )

    entries = get_flights(query)
    results = [convert_fallback_itinerary(entry, options["travel_class"]) for entry in entries]

    # Filters Google never saw are applied here so the numbers stay truthful.
    if options["max_price"] is not None:
        results = [
            item for item in results
            if item.get("price") is None or item["price"] <= options["max_price"]
        ]
    if options["include_airlines"]:
        wanted = {code.strip() for code in options["include_airlines"].split(",") if code.strip()}
        results = [
            item for item in results
            if any(code in wanted for code in item.get("airlines") or [])
        ]

    unapplied = [name for name in FALLBACK_UNSUPPORTED if options.get(name)]
    meta = {
        "price_insights": {},
        "booking_url": query.url(),
        "serpapi_searches_used": 0,
    }
    if unapplied:
        meta["unapplied_filters"] = unapplied
    return results, meta


def main() -> int:
    departure_id = arrival_id = outbound_date = ""
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        departure_id = parse_airport(input_data.get("departure_id"))
        arrival_id = parse_airport(input_data.get("arrival_id"))
        if not departure_id or not arrival_id:
            return_error(
                "Both 'departure_id' and 'arrival_id' are required as 3-letter airport codes, for example PDX and PHX."
            )
            return 1

        try:
            outbound_date = parse_date(input_data.get("outbound_date"), "outbound_date")
            return_date = parse_date(input_data.get("return_date"), "return_date")
        except ValueError as date_error:
            return_error(str(date_error))
            return 1

        if not outbound_date:
            return_error("'outbound_date' is required, formatted YYYY-MM-DD.")
            return 1
        if return_date and return_date < outbound_date:
            return_error(f"'return_date' ({return_date}) is before 'outbound_date' ({outbound_date}).")
            return 1

        trip_type = "round_trip" if return_date else "one_way"

        travel_class = str(input_data.get("travel_class", "economy")).strip().lower()
        if travel_class not in TRAVEL_CLASSES:
            travel_class = "economy"
        stops = str(input_data.get("stops", "any")).strip().lower()
        if stops not in STOPS:
            stops = "any"
        sort_by = str(input_data.get("sort_by", "price")).strip().lower()
        if sort_by not in SORTS:
            sort_by = "price"

        max_price = input_data.get("max_price")
        try:
            max_price = int(max_price) if max_price is not None else None
        except (TypeError, ValueError):
            max_price = None

        options: dict[str, Any] = {
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "return_date": return_date,
            "trip_type": trip_type,
            "travel_class": travel_class,
            "stops": stops,
            "sort_by": sort_by,
            "max_price": max_price,
            "adults": parse_count(input_data.get("adults", 1), default=1, minimum=1),
            "children": parse_count(input_data.get("children", 0), default=0, minimum=0),
            "infants_in_seat": parse_count(input_data.get("infants_in_seat", 0), default=0, minimum=0),
            "infants_on_lap": parse_count(input_data.get("infants_on_lap", 0), default=0, minimum=0),
            "include_airlines": serialize_csv(input_data.get("include_airlines")),
            "exclude_airlines": serialize_csv(input_data.get("exclude_airlines")),
            "outbound_times": str(input_data.get("outbound_times", "")).strip() or None,
            "return_times": str(input_data.get("return_times", "")).strip() or None,
            "currency": str(input_data.get("currency", "USD")).strip().upper() or "USD",
            "deep_search": parse_bool(input_data.get("deep_search", False)),
        }
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)

        # Google caps a single booking at 9 travelers and requires an adult per
        # lap infant; both providers reject the search otherwise.
        traveler_total = sum(
            options[key] for key in ("adults", "children", "infants_in_seat", "infants_on_lap")
        )
        if traveler_total > 9:
            return_error(f"Google Flights allows at most 9 travelers per search, got {traveler_total}.")
            return 1
        if options["infants_on_lap"] > options["adults"]:
            return_error("Each lap infant needs its own adult. Reduce 'infants_on_lap' or raise 'adults'.")
            return 1

        provider = "serpapi" if serpapi_configured() else "fast_flights"
        if provider == "serpapi":
            results, meta = search_serpapi(options)
        else:
            results, meta = search_fallback(options)

        results = sort_results(results, sort_by)[:num_results]
        price_insights = meta.get("price_insights") or {}
        speech = build_speech(
            results, departure_id, arrival_id, trip_type, options["currency"], price_insights
        )

        prices = [item["price"] for item in results if item.get("price") is not None]
        data: dict[str, Any] = {
            "provider": provider,
            "trip_type": trip_type,
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "return_date": return_date or None,
            "travel_class": travel_class,
            "stops_filter": stops,
            "sort_by": sort_by,
            "currency": options["currency"],
            "passengers": {
                "adults": options["adults"],
                "children": options["children"],
                "infants_in_seat": options["infants_in_seat"],
                "infants_on_lap": options["infants_on_lap"],
            },
            "results_count": len(results),
            "results": results,
            "cheapest_price": min(prices) if prices else None,
            # Round-trip totals cover both legs; only outbound times are listed,
            # matching what Google itself shows before a return leg is chosen.
            "price_basis": "round_trip_total" if trip_type == "round_trip" else "one_way_total",
            "booking_note": "Prices and times are for reference. Book on the airline site or the Google Flights link.",
            "booking_url": meta.get("booking_url"),
            "price_insights": price_insights,
            "serpapi_searches_used": meta.get("serpapi_searches_used", 0),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Flights" if provider == "serpapi" else "Google Flights (fast-flights, keyless)",
        }
        if meta.get("unapplied_filters"):
            data["unapplied_filters"] = meta["unapplied_filters"]

        return_success(speech=speech, data=data)
        return 0

    except Exception as e:
        msg = str(e)
        lowered = msg.lower()
        if "timeout" in lowered or "timed out" in lowered:
            return_error("Flight search timed out. Try again, or narrow the dates.")
            return 1
        if "no flights found" in lowered:
            return_error(
                f"Google returned no flight data for {departure_id} to {arrival_id} on {outbound_date}. "
                "This is a known intermittent limit of the keyless fallback; retry or set SERP_API_KEY."
            )
            return 1
        return_error(f"Flight search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
