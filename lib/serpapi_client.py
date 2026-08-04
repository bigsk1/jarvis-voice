#!/usr/bin/env python3
"""Shared SerpApi helpers used by Jarvis skills."""
from __future__ import annotations

import re
from typing import Any

from config_loader import get_config_value
from http_client import get_proxy_config, http_request


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_STATUS_PAGE_URL = "https://status.serpapi.com/"
SERPAPI_UNRESOLVED_INCIDENTS_ENDPOINT = (
    "https://status.serpapi.com/api/v2/incidents/unresolved.json"
)
SERPAPI_STATUS_TIMEOUT = 3

SERPAPI_TOOL_ENGINES = {
    "serpapi_ebay_product": ("ebay_product",),
    "serpapi_ebay_search": ("ebay",),
    "serpapi_hotel_search": ("google_hotels",),
    "serpapi_maps_search": ("google_maps",),
    "serpapi_youtube_search": ("youtube",),
}

SERPAPI_ENGINE_LABELS = {
    "amazon": "Amazon Search",
    "amazon_product": "Amazon Product",
    "ebay": "eBay Search",
    "ebay_product": "eBay Product",
    "bing": "Bing Search",
    "google": "Google Search",
    "google_flights": "Google Flights",
    "google_hotels": "Google Hotels",
    "google_light": "Google Light Search",
    "google_maps": "Google Maps",
    "google_news": "Google News",
    "google_shopping": "Google Shopping",
    "home_depot": "Home Depot Search",
    "home_depot_product": "Home Depot Product",
    "yelp": "Yelp Search",
    "yelp_reviews": "Yelp Reviews",
    "youtube": "YouTube Search",
    "youtube_video": "YouTube Video",
    "youtube_video_transcript": "YouTube Video Transcript",
    "news": "Google News",
}

SERPAPI_ENGINE_STATUS_ALIASES = {
    "amazon": ("amazon search api", "amazon search", "amazon api"),
    "amazon_product": ("amazon product api", "amazon product"),
    "ebay": ("ebay search api", "ebay search", "ebay api"),
    "ebay_product": ("ebay product api", "ebay product"),
    "bing": ("bing search api", "bing search", "bing api"),
    "google": ("google search api", "google search"),
    "google_flights": ("google flights api", "google flights"),
    "google_hotels": ("google hotels api", "google hotels"),
    "google_light": ("google light search api", "google light search"),
    "google_maps": ("google maps api", "google maps"),
    "google_news": ("google news api", "google news"),
    "google_shopping": ("google shopping api", "google shopping"),
    "home_depot": ("home depot search api", "home depot search", "home depot api"),
    "home_depot_product": ("home depot product api", "home depot product"),
    "yelp": ("yelp search api", "yelp search", "yelp api"),
    "yelp_reviews": ("yelp reviews api", "yelp reviews"),
    "youtube": ("youtube search api", "youtube search", "youtube api"),
    "youtube_video": ("youtube video api", "youtube video"),
    "youtube_video_transcript": (
        "youtube video transcript api",
        "youtube video transcript",
        "youtube transcript api",
        "youtube transcript",
    ),
    "news": ("google news api", "google news"),
}

_TRANSIENT_SERPAPI_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connection error",
    "connectionerror",
    "connection refused",
    "max retries exceeded",
    "proxy error",
    "proxyerror",
    "service unavailable",
    "temporarily unavailable",
    "couldn't get valid results",
    "please try again later",
)
GENERIC_RESERVED_KEYS = {
    "engine",
    "api_key",
    "q",
    "k",
    "asin",
    "output",
    "device",
    "page",
    "num",
    "no_cache",
    "amazon_domain",
    "language",
    "delivery_zip",
    "shipping_location",
}


def _normalize_status_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _serpapi_key_is_configured() -> bool:
    value = get_config_value("SERP_API_KEY", "").strip()
    return bool(value and "YOUR_" not in value and "REPLACE" not in value and len(value) >= 16)


def serpapi_engines_for_tool(tool_name: str, args: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Return the SerpApi engines a failed Jarvis tool may have been calling."""
    options = args if isinstance(args, dict) else {}

    if tool_name == "serpapi_search":
        engine = str(options.get("engine") or "").strip().lower()
        return (engine,) if engine else ()
    if tool_name == "flight_search":
        return ("google_flights",) if _serpapi_key_is_configured() else ()
    if tool_name == "serpapi_home_depot":
        query = str(options.get("query") or options.get("q") or "").strip()
        product_id = str(options.get("product_id") or "").strip()
        return ("home_depot_product",) if product_id and not query else ("home_depot",)
    if tool_name == "serpapi_yelp_search":
        engines = ["yelp"]
        if parse_bool(options.get("include_reviews")):
            engines.append("yelp_reviews")
        return tuple(engines)
    if tool_name == "serpapi_youtube":
        engines = ["youtube_video"]
        if parse_bool(options.get("include_transcript")):
            engines.append("youtube_video_transcript")
        return tuple(engines)

    return SERPAPI_TOOL_ENGINES.get(tool_name, ())


def is_transient_serpapi_failure(error_text: Any) -> bool:
    """Whether a final tool error is worth correlating with provider incidents."""
    lowered = str(error_text or "").lower()
    if any(marker in lowered for marker in _TRANSIENT_SERPAPI_ERROR_MARKERS):
        return True
    return re.search(r"\b(?:500|502|503|504)\b", lowered) is not None


def fetch_serpapi_unresolved_incidents(
    timeout: int = SERPAPI_STATUS_TIMEOUT,
) -> list[dict[str, Any]]:
    """Fetch active SerpApi incidents without extending a failed tool by long."""
    try:
        response = http_request(
            "GET",
            SERPAPI_UNRESOLVED_INCIDENTS_ENDPOINT,
            timeout=timeout,
            use_proxy=False,
            fallback_on_proxy_fail=False,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception:
        return []

    incidents = payload.get("incidents") if isinstance(payload, dict) else None
    if not isinstance(incidents, list):
        return []
    return [incident for incident in incidents if isinstance(incident, dict)]


def _status_aliases_for_engine(engine: str) -> tuple[str, ...]:
    aliases = SERPAPI_ENGINE_STATUS_ALIASES.get(engine)
    if aliases:
        return aliases
    normalized = _normalize_status_text(engine)
    if not normalized:
        return ()
    return (f"{normalized} api", f"{normalized} search api", f"{normalized} search")


def find_serpapi_incident(
    engines: tuple[str, ...],
    incidents: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    """Find an active incident whose title specifically names a requested engine."""
    for engine in engines:
        aliases = _status_aliases_for_engine(engine)
        for incident in incidents:
            incident_name = _normalize_status_text(incident.get("name"))
            padded_name = f" {incident_name} "
            if any(f" {_normalize_status_text(alias)} " in padded_name for alias in aliases):
                return engine, incident
    return None


def _compact_serpapi_incident(engine: str, incident: dict[str, Any]) -> dict[str, Any]:
    updates = incident.get("incident_updates")
    latest_update = updates[0] if isinstance(updates, list) and updates and isinstance(updates[0], dict) else {}
    body = " ".join(str(latest_update.get("body") or "").split())[:500]

    components: list[dict[str, Any]] = []
    raw_components = incident.get("components")
    if isinstance(raw_components, list):
        for component in raw_components[:8]:
            if not isinstance(component, dict):
                continue
            components.append(
                {
                    "name": component.get("name"),
                    "status": component.get("status"),
                }
            )

    return {
        "engine": engine,
        "engine_label": SERPAPI_ENGINE_LABELS.get(engine, engine.replace("_", " ").title()),
        "name": incident.get("name"),
        "status": incident.get("status"),
        "impact": incident.get("impact"),
        "started_at": incident.get("started_at"),
        "updated_at": incident.get("updated_at"),
        "latest_update": body or None,
        "latest_update_status": latest_update.get("status"),
        "components": components,
        "incident_url": incident.get("shortlink") or SERPAPI_STATUS_PAGE_URL,
        "status_page_url": SERPAPI_STATUS_PAGE_URL,
    }


def diagnose_serpapi_tool_failure(
    tool_name: str,
    args: dict[str, Any] | None,
    error_text: Any,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """Correlate a final transient SerpApi tool failure with an active incident."""
    engines = serpapi_engines_for_tool(tool_name, args)
    if not engines or (not force and not is_transient_serpapi_failure(error_text)):
        return None

    match = find_serpapi_incident(engines, fetch_serpapi_unresolved_incidents())
    if not match:
        return None

    engine, raw_incident = match
    incident = _compact_serpapi_incident(engine, raw_incident)
    label = incident["engine_label"]
    name = incident.get("name") or "a provider incident"
    state_parts = [str(incident["status"])] if incident.get("status") else []
    if incident.get("impact"):
        state_parts.append(f"{incident['impact']} impact")
    state = f" ({', '.join(state_parts)})" if state_parts else ""

    latest_update = str(incident.get("latest_update") or "")
    speech_update = re.sub(r"https?://\S+", "", latest_update).strip(" .")[:220]
    speech_update = re.sub(
        r"(?:github\s+issue|issue)\s*:\s*$",
        "",
        speech_update,
        flags=re.IGNORECASE,
    ).strip(" .")
    update_sentence = f" Latest update: {speech_update}." if speech_update else ""
    speech = (
        f"SerpApi could not complete the {label} request after the configured request path failed. "
        f"SerpApi is currently reporting {name}{state}, which likely explains the failure."
        f"{update_sentence} Try this tool again later or check {SERPAPI_STATUS_PAGE_URL}"
    )

    return {
        "speech": speech,
        "data": {
            "provider": "SerpApi",
            "failure_reason": "active_provider_incident",
            "retry_recommended": True,
            "status_page_url": SERPAPI_STATUS_PAGE_URL,
            "serpapi_incident": incident,
        },
    }

AMAZON_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "around", "best", "can", "for", "find", "from",
    "give", "help", "i", "ideas", "in", "into", "is", "it", "looking", "me",
    "my", "of", "on", "please", "recommend", "search", "show", "suggest",
    "that", "the", "to", "under", "want", "with", "you", "your",
    "amazon", "product", "products", "listing", "listings", "let", "know",
    "could", "would", "should", "for", "gift", "gifts", "idea", "ideas",
    "birthday", "present", "male", "female", "adult", "year", "years", "old",
    "he", "him", "his", "she", "her", "they", "them", "their",
    "so", "just", "really", "also", "items", "item", "get", "got",
}


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def clamp_results_count(value: Any, default: int = 5, *, maximum: int = 10) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default

    cap = max(1, int(maximum))
    if count < 1:
        return 1
    if count > cap:
        return cap
    return count


def get_api_key() -> str:
    api_key = get_config_value("SERP_API_KEY", "").strip()
    if not api_key:
        raise ValueError("SERP_API_KEY is not configured.")
    if "YOUR_" in api_key or "REPLACE" in api_key or len(api_key) < 16:
        raise ValueError("SERP_API_KEY appears to be a placeholder or invalid.")
    return api_key


def get_proxy_enabled() -> bool:
    return get_proxy_config() is not None


def merge_extra_params(
    params: dict[str, Any],
    extra_params: Any,
    reserved_keys: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(extra_params, dict):
        return params

    blocked = reserved_keys or set()
    for key, value in extra_params.items():
        if key in blocked:
            continue
        params[key] = value
    return params


def request_serpapi(
    params: dict[str, Any],
    timeout: int = 25,
    *,
    use_proxy: bool = True,
    fallback_on_proxy_fail: bool = True,
    allowed_error_substrings: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    final_params = dict(params)
    final_params["api_key"] = get_api_key()
    final_params.setdefault("output", "json")

    response = http_request(
        "GET",
        SERPAPI_ENDPOINT,
        params=final_params,
        timeout=timeout,
        use_proxy=use_proxy,
        fallback_on_proxy_fail=fallback_on_proxy_fail,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"SerpApi request failed with HTTP {response.status_code}.")

    payload = response.json()
    if payload.get("error"):
        error_text = str(payload.get("error"))
        allowed_errors = tuple(allowed_error_substrings or ())
        if any(allowed.lower() in error_text.lower() for allowed in allowed_errors):
            return payload
        raise RuntimeError(f"SerpApi error: {payload.get('error')}")
    return payload


def extract_generic_results(payload: dict[str, Any], engine: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def prime_eligibility(item: dict[str, Any]) -> bool | None:
        prime = item.get("prime")
        if isinstance(prime, bool):
            return prime

        delivery = item.get("delivery")
        delivery_text = " ".join(str(value) for value in delivery) if isinstance(delivery, list) else str(delivery or "")
        if "prime member" in delivery_text.lower() or "prime delivery" in delivery_text.lower():
            return True
        return None

    def normalize_item(item: dict[str, Any], source: str) -> dict[str, Any]:
        return {
            "title": item.get("title"),
            "url": item.get("link_clean") or item.get("link") or item.get("source"),
            "asin": item.get("asin"),
            "price": item.get("price"),
            "extracted_price": item.get("extracted_price"),
            "old_price": item.get("old_price"),
            "extracted_old_price": item.get("extracted_old_price"),
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "prime": item.get("prime"),
            "prime_eligible": prime_eligibility(item),
            "delivery": item.get("delivery"),
            "shipping": item.get("shipping"),
            "stock": item.get("stock"),
            "availability": item.get("availability"),
            "bought_last_month": item.get("bought_last_month"),
            "badges": item.get("badges"),
            "save_with_coupon": item.get("save_with_coupon"),
            "thumbnail": item.get("thumbnail"),
            "source": source,
        }

    if engine == "amazon_product":
        product = payload.get("product_results") or {}
        if product:
            results.append(normalize_item(product, "product_results"))
        return results[:limit]

    candidates = []
    for bucket in ("organic_results", "shopping_results", "news_results", "images_results"):
        values = payload.get(bucket)
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                candidates.append(normalize_item(item, bucket))

    for item in candidates:
        if not item.get("title") and not item.get("url"):
            continue
        results.append(item)
        if len(results) >= limit:
            break

    return results


def extract_maps_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    local_results = payload.get("local_results") or []
    if isinstance(local_results, dict):
        local_results = [local_results]

    for item in local_results:
        if not isinstance(item, dict):
            continue

        links = item.get("links") or {}
        website = item.get("website") or links.get("website")
        place_link = item.get("place_id_search")
        reviews_link = item.get("reviews_link") or links.get("reviews")
        directions_link = links.get("directions")
        results.append(
            {
                "title": item.get("title"),
                "url": website or place_link or reviews_link or directions_link,
                "website": website,
                "place_id_search": place_link,
                "reviews_link": reviews_link,
                "directions_link": directions_link,
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "price": item.get("price"),
                "type": item.get("type"),
                "types": item.get("types"),
                "address": item.get("address"),
                "open_state": item.get("open_state"),
                "hours": item.get("hours"),
                "phone": item.get("phone") or links.get("phone"),
                "description": item.get("description"),
                "gps_coordinates": item.get("gps_coordinates"),
                "place_id": item.get("place_id"),
                "data_id": item.get("data_id"),
                "thumbnail": item.get("thumbnail"),
                "source": "local_results",
            }
        )
        if len(results) >= limit:
            break

    if results:
        return results

    place_result = payload.get("place_results")
    if isinstance(place_result, dict):
        links = place_result.get("links") or {}
        website = place_result.get("website") or links.get("website")
        reviews_link = place_result.get("reviews_link") or links.get("reviews")
        directions_link = links.get("directions")
        return [
            {
                "title": place_result.get("title"),
                "url": website or reviews_link or directions_link,
                "website": website,
                "place_id_search": place_result.get("place_id_search"),
                "reviews_link": reviews_link,
                "directions_link": directions_link,
                "rating": place_result.get("rating"),
                "reviews": place_result.get("reviews"),
                "price": place_result.get("price"),
                "type": place_result.get("type"),
                "types": place_result.get("types"),
                "address": place_result.get("address"),
                "open_state": place_result.get("open_state"),
                "hours": place_result.get("hours"),
                "phone": place_result.get("phone") or links.get("phone"),
                "description": place_result.get("description"),
                "gps_coordinates": place_result.get("gps_coordinates"),
                "place_id": place_result.get("place_id"),
                "data_id": place_result.get("data_id"),
                "thumbnail": place_result.get("thumbnail"),
                "source": "place_results",
            }
        ]
    return results


def extract_hotel_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Normalize Google Hotels properties into compact, follow-up-safe rows.

    `properties` contains the active matches. SerpApi may also return a
    `non_matching_properties` bucket for properties that fail the requested
    filters; those are intentionally excluded here.
    """

    def dict_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            return []
        return [entry for entry in value if isinstance(entry, dict)]

    def string_list(value: Any, maximum: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(entry) for entry in value if str(entry).strip()][:maximum]

    def first_image_url(item: dict[str, Any]) -> str | None:
        if item.get("thumbnail"):
            return item["thumbnail"]
        for image in dict_list(item.get("images")):
            value = image.get("thumbnail") or image.get("original_image")
            if value:
                return value
        return None

    def compact_nearby_places(item: dict[str, Any]) -> list[dict[str, Any]]:
        nearby: list[dict[str, Any]] = []
        for place in dict_list(item.get("nearby_places"))[:5]:
            transport = []
            for option in dict_list(place.get("transportations"))[:3]:
                compact = {
                    "type": option.get("type"),
                    "duration": option.get("duration"),
                }
                if any(value not in (None, "", [], {}) for value in compact.values()):
                    transport.append(compact)
            compact_place = {
                "name": place.get("name"),
                "transportation": transport,
            }
            if compact_place["name"] or transport:
                nearby.append(compact_place)
        return nearby

    def compact_booking_options(prices: Any) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for price in dict_list(prices)[:3]:
            nightly = price.get("rate_per_night") or {}
            total = price.get("total_rate") or {}
            option = {
                "source": price.get("source"),
                "url": price.get("link"),
                "price_per_night": nightly.get("lowest"),
                "extracted_price_per_night": nightly.get("extracted_lowest"),
                "price_total": total.get("lowest"),
                "extracted_price_total": total.get("extracted_lowest"),
                "free_cancellation": price.get("free_cancellation"),
            }
            if any(value not in (None, "", [], {}) for value in option.values()):
                options.append(option)
        return options

    results: list[dict[str, Any]] = []
    for item in dict_list(payload.get("properties")):

        rate_per_night = item.get("rate_per_night") or {}
        total_rate = item.get("total_rate") or {}
        prices = dict_list(item.get("prices"))
        first_price = prices[0] if prices else {}
        booking_options = compact_booking_options(prices)
        free_cancellation = item.get("free_cancellation")
        if free_cancellation is None:
            cancellation_values = [
                price.get("free_cancellation")
                for price in prices
                if isinstance(price, dict) and "free_cancellation" in price
            ]
            free_cancellation = any(cancellation_values) if cancellation_values else None

        results.append(
            {
                "title": item.get("name"),
                # property_token is an opaque Google Hotels property handle,
                # not a credential. Expose it under a neutral name so generic
                # follow-up extraction does not mistake it for an API secret.
                "property_id": item.get("property_token"),
                "url": item.get("link") or first_price.get("link"),
                "type": item.get("type"),
                "description": item.get("description"),
                "address": item.get("address"),
                "phone": item.get("phone"),
                "hotel_class": item.get("hotel_class"),
                "extracted_hotel_class": item.get("extracted_hotel_class"),
                "rating": item.get("overall_rating"),
                "reviews": item.get("reviews"),
                "location_rating": item.get("location_rating"),
                "price_per_night": rate_per_night.get("lowest"),
                "price_total": total_rate.get("lowest"),
                "extracted_price_per_night": rate_per_night.get("extracted_lowest"),
                "extracted_price_total": total_rate.get("extracted_lowest"),
                "before_taxes_fees_per_night": rate_per_night.get("before_taxes_fees"),
                "before_taxes_fees_total": total_rate.get("before_taxes_fees"),
                "extracted_before_taxes_fees_per_night": rate_per_night.get(
                    "extracted_before_taxes_fees"
                ),
                "extracted_before_taxes_fees_total": total_rate.get(
                    "extracted_before_taxes_fees"
                ),
                "check_in_time": item.get("check_in_time"),
                "check_out_time": item.get("check_out_time"),
                "amenities": string_list(item.get("amenities"), 20),
                "essential_info": string_list(item.get("essential_info"), 10),
                "free_cancellation": free_cancellation,
                "gps_coordinates": item.get("gps_coordinates"),
                "thumbnail": first_image_url(item),
                "nearby_places": compact_nearby_places(item),
                "first_price_source": first_price.get("source"),
                "booking_options": booking_options,
                "source": "properties",
            }
        )
        if limit and len(results) >= limit:
            break
    return results


def format_duration_minutes(minutes: Any) -> str | None:
    """Render a minute count as compact travel duration text ("2h 48m")."""
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None

    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _stops_label(stop_count: int) -> str:
    if stop_count <= 0:
        return "Nonstop"
    if stop_count == 1:
        return "1 stop"
    return f"{stop_count} stops"


def _normalize_flight_itinerary(item: dict[str, Any], source: str) -> dict[str, Any]:
    """Flatten one Google Flights itinerary into a compact, LLM-friendly shape.

    Airline logo URLs and marketing extensions are dropped: itineraries nest
    deeply and the tool result budget is shared with the rest of the turn.
    """
    segments_raw = [seg for seg in (item.get("flights") or []) if isinstance(seg, dict)]
    layovers_raw = [lay for lay in (item.get("layovers") or []) if isinstance(lay, dict)]

    segments: list[dict[str, Any]] = []
    airlines: list[str] = []
    flight_numbers: list[str] = []
    for seg in segments_raw:
        departure = seg.get("departure_airport") or {}
        arrival = seg.get("arrival_airport") or {}
        airline = seg.get("airline")
        flight_number = seg.get("flight_number")
        if airline and airline not in airlines:
            airlines.append(airline)
        if flight_number:
            flight_numbers.append(flight_number)

        segments.append(
            {
                "flight_number": flight_number,
                "airline": airline,
                "from": departure.get("id"),
                "to": arrival.get("id"),
                "depart": departure.get("time"),
                "arrive": arrival.get("time"),
                "duration_minutes": seg.get("duration"),
                "duration_display": format_duration_minutes(seg.get("duration")),
                "aircraft": seg.get("airplane"),
                "travel_class": seg.get("travel_class"),
                "legroom": seg.get("legroom"),
                "overnight": seg.get("overnight"),
                "often_delayed": seg.get("often_delayed_by_over_30_min"),
            }
        )

    layovers = [
        {
            "airport": lay.get("id"),
            "airport_name": lay.get("name"),
            "duration_minutes": lay.get("duration"),
            "duration_display": format_duration_minutes(lay.get("duration")),
            "overnight": lay.get("overnight"),
        }
        for lay in layovers_raw
    ]

    first_segment = segments[0] if segments else {}
    last_segment = segments[-1] if segments else {}
    carbon = item.get("carbon_emissions") or {}
    emission_grams = carbon.get("this_flight")

    return {
        "price": item.get("price"),
        "airlines": airlines,
        "flight_numbers": flight_numbers,
        "departure_airport": first_segment.get("from"),
        "departure_time": first_segment.get("depart"),
        "arrival_airport": last_segment.get("to"),
        "arrival_time": last_segment.get("arrive"),
        "total_duration_minutes": item.get("total_duration"),
        "duration_display": format_duration_minutes(item.get("total_duration")),
        "stops": max(0, len(segments) - 1),
        "stops_label": _stops_label(max(0, len(segments) - 1)),
        "travel_class": first_segment.get("travel_class"),
        "layovers": layovers,
        "segments": segments,
        "carbon_kg": round(emission_grams / 1000) if isinstance(emission_grams, (int, float)) else None,
        "often_delayed": any(seg.get("often_delayed") for seg in segments),
        "overnight": any(seg.get("overnight") for seg in segments),
        "source": source,
    }


def extract_flight_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Normalize SerpApi google_flights itineraries from both result buckets.

    SerpApi splits itineraries into `best_flights` (Google's own picks) and
    `other_flights`; when it does not split them, everything lands in
    `other_flights`. Both are read so a price sort sees the full set.
    """
    results: list[dict[str, Any]] = []
    for bucket in ("best_flights", "other_flights"):
        values = payload.get(bucket)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            itinerary = _normalize_flight_itinerary(item, bucket)
            if itinerary.get("price") is None and not itinerary.get("segments"):
                continue
            results.append(itinerary)

    return results[:limit] if limit else results


def extract_price_insights(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the route price context Google returns, minus the history series."""
    insights = payload.get("price_insights")
    if not isinstance(insights, dict):
        return {}

    compact = {
        "lowest_price": insights.get("lowest_price"),
        "price_level": insights.get("price_level"),
        "typical_price_range": insights.get("typical_price_range"),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [])}


def build_search_speech(engine: str, query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        if query:
            return f"No results found for '{query}' on SerpApi engine '{engine}'."
        return f"No results found on SerpApi engine '{engine}'."

    top = results[0]
    top_title = (top.get("title") or "top result").strip()
    top_price = top.get("price")
    if top_price:
        return (
            f"Found {len(results)} result(s) on '{engine}'. "
            f"Top result: {top_title}, price {top_price}."
        )
    return f"Found {len(results)} result(s) on '{engine}'. Top result: {top_title}."


def normalize_amazon_query(query: str) -> str:
    """Convert conversational gift prompts into cleaner Amazon keyword queries."""
    raw = (query or "").strip()
    if not raw:
        return raw

    lowered = raw.lower()
    replacements = {
        "amazong": "amazon",
        "old scholl": "classic",
        "old school": "classic",
        "tech enthusiast": "tech",
    }
    for bad, good in replacements.items():
        lowered = lowered.replace(bad, good)

    budget_match = re.search(r"\$\s*\d+(?:\s*-\s*\$\s*\d+)?", lowered)
    budget_token = budget_match.group(0).replace(" ", "") if budget_match else ""

    cleaned = re.sub(r"[^a-zA-Z0-9$\- ]+", " ", lowered)
    tokens = [token for token in cleaned.split() if token]

    kept: list[str] = []
    has_budget = bool(budget_token)
    for token in tokens:
        if token in AMAZON_QUERY_STOPWORDS:
            continue
        if token.isdigit() and not has_budget:
            continue
        if len(token) <= 1 and not token.isdigit() and not token.startswith("$"):
            continue
        kept.append(token)

    seen = set()
    deduped: list[str] = []
    for token in kept:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)

    if len(deduped) < 3:
        deduped = ["tech", "gift", "ideas"]

    deduped = deduped[:12]
    normalized = " ".join(deduped).strip()

    if budget_token and budget_token not in normalized:
        normalized = f"{normalized} {budget_token}".strip()

    return normalized or raw


def should_optimize_amazon_query(raw_query: str, normalized_query: str) -> bool:
    if not raw_query or not normalized_query or normalized_query == raw_query:
        return False

    raw_tokens = re.findall(r"[a-zA-Z0-9$-]+", raw_query.lower())
    if len(raw_tokens) >= 8:
        return True
    if any(char in raw_query for char in (".", ",", "?", "!", ":")):
        return True
    conversational_markers = ("find", "show", "recommend", "looking for", "let me know", "what")
    lowered = raw_query.lower()
    return any(marker in lowered for marker in conversational_markers)


def fallback_amazon_query(query: str) -> str:
    raw = (query or "").lower()
    if not raw:
        return "tech gifts"

    topics = []
    if any(word in raw for word in ("tech", "gadget", "electronics", "programming", "coding")):
        topics.append("tech")
    if any(word in raw for word in ("gaming", "gamer")):
        topics.append("gaming")
    if any(word in raw for word in ("smart home", "home automation")):
        topics.append("smart home")
    if not topics:
        topics.append("gift")

    parts = topics + ["gifts"]
    budget_range = re.search(r"\$\s*(\d+)\s*-\s*\$?\s*(\d+)", raw)
    if budget_range:
        parts.extend(["under", budget_range.group(2)])
    else:
        budget_single = re.search(r"\$\s*(\d+)", raw)
        if budget_single:
            parts.extend(["under", budget_single.group(1)])

    return " ".join(parts).strip()


def parse_int_list(value: Any) -> list[int]:
    if isinstance(value, list):
        result = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    if isinstance(value, str):
        result = []
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                continue
        return result

    return []
