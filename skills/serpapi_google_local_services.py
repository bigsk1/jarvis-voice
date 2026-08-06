#!/usr/bin/env python3
"""Jarvis Skill: Google Local Services provider discovery through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_LOCAL_SERVICES_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 10
LOCALE_RE = re.compile(r"^[a-z]{2}$")
CID_RE = re.compile(r"^[0-9]+$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "data_cid",
    "hl",
    "job_type",
    "cid",
    "bid",
    "pid",
    "no_cache",
}

# SerpApi's Local Services engine accepts only the provider's documented query
# identifiers, not arbitrary search text. Keep this allowlist in code so the
# public tool schema stays compact while invalid categories fail before using a
# SerpApi search. Source: https://serpapi.com/google-local-services-queries
SUPPORTED_SERVICE_QUERIES = frozenset({
    "acupuncturist",
    "allergist",
    "animal_shelter",
    "appliance_repair",
    "architect",
    "audiologist",
    "auto_body_shop",
    "auto_repair_shop",
    "bankruptcy_lawyer",
    "barber_shop",
    "beauty_school",
    "business_lawyer",
    "car_wash_and_detailing",
    "carpenter",
    "carpet_cleaning",
    "cellphone_and_laptop_repair",
    "child_care",
    "chiropractor",
    "cleaning_service",
    "contract_lawyer",
    "countertop_pro",
    "criminal_lawyer",
    "dance_instructor",
    "dentist",
    "dermatologist",
    "dietitian",
    "disability_lawyer",
    "drain_expert",
    "driving_instructor",
    "dui_lawyer",
    "electrician",
    "estate_lawyer",
    "family_lawyer",
    "fencing_pro",
    "financial_planner",
    "first_aid_trainer",
    "flooring_pro",
    "foundation_pro",
    "funeral_home",
    "garage_door_pro",
    "general_contractor",
    "hair_removal",
    "hair_salon",
    "handyman",
    "home_inspector",
    "home_insulation",
    "home_security",
    "home_theater",
    "hvac",
    "immigration_lawyer",
    "insurance_agency",
    "interior_designer",
    "ip_lawyer",
    "junk_removal",
    "labor_lawyer",
    "landscaper",
    "language_instructor",
    "lawn_care",
    "litigation_lawyer",
    "locksmith",
    "malpractice_lawyer",
    "massage_school",
    "massage_therapist",
    "mover",
    "nail_salon",
    "occupational_therapist",
    "ophthalmologist",
    "optometrist",
    "orthodontist",
    "orthopedic_surgeon",
    "painter",
    "personal_injury_lawyer",
    "personal_trainer",
    "pest_control",
    "pet_adoption",
    "pet_boarding",
    "pet_grooming",
    "pet_trainer",
    "physiotherapist",
    "piercing_studio",
    "plastic_surgeon",
    "plumber",
    "podiatrist",
    "pool_cleaner",
    "pool_contractor",
    "preschool",
    "primary_care",
    "real_estate_agent",
    "real_estate_lawyer",
    "roofer",
    "sewage_pro",
    "siding_pro",
    "snow_removal",
    "solar_energy_contractor",
    "storage",
    "tattoo_studio",
    "tax_lawyer",
    "tax_specialist",
    "tire_shop",
    "towing",
    "traffic_lawyer",
    "tree_service",
    "tutor",
    "veterinarian",
    "water_damage",
    "weight_loss_service",
    "window_cleaner",
    "window_repair",
    "yoga_instructor",
})

# Natural phrases the model or user is likely to provide when they do not know
# SerpApi's canonical identifier. Most supported phrases need no entry because
# spaces and punctuation normalize directly to underscores.
SERVICE_QUERY_ALIASES = {
    "ac_repair": "hvac",
    "air_conditioner_repair": "hvac",
    "air_conditioning_repair": "hvac",
    "arborist": "tree_service",
    "auto_detailing": "car_wash_and_detailing",
    "auto_mechanic": "auto_repair_shop",
    "auto_repair": "auto_repair_shop",
    "automotive_repair": "auto_repair_shop",
    "body_shop": "auto_body_shop",
    "car_body_shop": "auto_body_shop",
    "car_detailing": "car_wash_and_detailing",
    "car_mechanic": "auto_repair_shop",
    "car_repair": "auto_repair_shop",
    "car_repair_shop": "auto_repair_shop",
    "car_wash": "car_wash_and_detailing",
    "cell_phone_repair": "cellphone_and_laptop_repair",
    "electrical_contractor": "electrician",
    "exterminator": "pest_control",
    "garage_door_repair": "garage_door_pro",
    "heating_and_air_conditioning": "hvac",
    "heating_and_cooling": "hvac",
    "home_cleaner": "cleaning_service",
    "home_cleaning": "cleaning_service",
    "house_cleaner": "cleaning_service",
    "house_cleaning": "cleaning_service",
    "hvac_contractor": "hvac",
    "landscape_contractor": "landscaper",
    "landscaping": "landscaper",
    "lawn_service": "lawn_care",
    "locksmith_service": "locksmith",
    "maid": "cleaning_service",
    "maid_service": "cleaning_service",
    "mechanic": "auto_repair_shop",
    "mechanic_shop": "auto_repair_shop",
    "moving_company": "mover",
    "moving_service": "mover",
    "pest_exterminator": "pest_control",
    "plumbing_contractor": "plumber",
    "plumbing_service": "plumber",
    "roof_repair": "roofer",
    "roofing_contractor": "roofer",
    "solar_installer": "solar_energy_contractor",
    "tire_repair": "tire_shop",
    "tow_truck": "towing",
    "towing_service": "towing",
    "tree_trimmer": "tree_service",
    "window_washing": "window_cleaner",
}

# Google Local Services requires a numeric Google city/district CID. These
# aliases avoid a separate Maps lookup for a deliberately small set of common
# locations. All other locations use the bounded resolver below.
COMMON_US_LOCATION_CIDS = {
    "new york": ("14414772292044717666", "New York, New York"),
    "new york city": ("14414772292044717666", "New York, New York"),
    "new york ny": ("14414772292044717666", "New York, New York"),
    "new york new york": ("14414772292044717666", "New York, New York"),
    "nyc": ("14414772292044717666", "New York, New York"),
    "10001": ("14414772292044717666", "New York, New York"),
    "austin": ("6745062158417646970", "Austin, Texas"),
    "austin tx": ("6745062158417646970", "Austin, Texas"),
    "austin texas": ("6745062158417646970", "Austin, Texas"),
    "78701": ("6745062158417646970", "Austin, Texas"),
    "portland": ("2033016683438900625", "Portland, Oregon"),
    "portland or": ("2033016683438900625", "Portland, Oregon"),
    "portland oregon": ("2033016683438900625", "Portland, Oregon"),
    "97201": ("2033016683438900625", "Portland, Oregon"),
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _compact_text(value: Any, maximum: int = 1200) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def _validate_text(value: Any, label: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        raise ValueError(f"'{label}' must be {maximum} characters or fewer.")
    return text


def _numeric_id(value: Any, label: str) -> str:
    identifier = str(value or "").strip()
    if identifier and (len(identifier) > 32 or not CID_RE.fullmatch(identifier)):
        raise ValueError(f"'{label}' must be a numeric identifier.")
    return identifier


def normalize_language(value: Any) -> str:
    language = str(value or "en").strip().lower()
    if not LOCALE_RE.fullmatch(language):
        raise ValueError("'language' must be a two-letter code such as en or es.")
    return language


def normalize_service_query(value: Any) -> tuple[str, str]:
    """Return the requested phrase and SerpApi's supported query identifier."""
    requested = _validate_text(value, "query", 300)
    if not requested:
        raise ValueError("'query' is required.")

    normalized = re.sub(r"[^a-z0-9]+", "_", requested.lower()).strip("_")
    while normalized.startswith(("a_", "an_", "the_")):
        normalized = normalized.split("_", 1)[1]
    provider_query = SERVICE_QUERY_ALIASES.get(normalized, normalized)
    if provider_query not in SUPPORTED_SERVICE_QUERIES and provider_query.endswith("s"):
        singular = provider_query[:-1]
        provider_query = SERVICE_QUERY_ALIASES.get(singular, singular)
    if provider_query not in SUPPORTED_SERVICE_QUERIES:
        raise ValueError(
            f"Unsupported Google Local Services query '{requested}'. Use a supported "
            "profession such as plumber, electrician, auto repair shop, cleaning "
            "service, roofer, or locksmith; use serpapi_google_local for general "
            "business searches."
        )
    return requested, provider_query


def resolve_location_input(explicit_location: Any) -> tuple[str, str]:
    location = _validate_text(explicit_location, "location", 200)
    if location:
        return location, "explicit"

    default_location = _validate_text(
        get_config_value("JARVIS_DEFAULT_LOCATION", ""),
        "JARVIS_DEFAULT_LOCATION",
        200,
    )
    if default_location:
        return default_location, "jarvis_default_location"

    default_postal_code = _validate_text(
        get_config_value("JARVIS_DEFAULT_POSTAL_CODE", ""),
        "JARVIS_DEFAULT_POSTAL_CODE",
        40,
    )
    if default_postal_code:
        return default_postal_code, "jarvis_default_postal_code"

    raise ValueError(
        "Provide 'data_cid' or 'location', or set JARVIS_DEFAULT_LOCATION or "
        "JARVIS_DEFAULT_POSTAL_CODE in the active mode env file."
    )


def _location_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    words = normalized.split()
    while words and words[-1] in {"usa", "us", "united", "states"}:
        words.pop()
    return " ".join(words)


def common_location_cid(location: str) -> tuple[str, str] | None:
    return COMMON_US_LOCATION_CIDS.get(_location_key(location))


def _serpapi_request(params: dict[str, Any]) -> dict[str, Any]:
    # The code stays proxy-capable while proxy_policy=off keeps Jarvis calls direct.
    return request_serpapi(
        params,
        timeout=GOOGLE_LOCAL_SERVICES_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def resolve_data_cid(
    location: str,
    *,
    language: str,
    no_cache: bool,
) -> tuple[str, str, str, dict[str, Any]]:
    """Resolve a US city/district CID, using a static alias before Google Maps."""
    common = common_location_cid(location)
    if common:
        cid, label = common
        return cid, label, "common_location", {}

    payload = _serpapi_request({
        "engine": "google_maps",
        "type": "search",
        "q": location,
        "hl": language,
        "no_cache": "true" if no_cache else "false",
    })
    place = payload.get("place_results")
    place = place if isinstance(place, dict) else {}
    data_cid = str(place.get("data_cid") or "").strip()
    if not CID_RE.fullmatch(data_cid):
        local_results = payload.get("local_results")
        first = (
            local_results[0]
            if isinstance(local_results, list)
            and local_results
            and isinstance(local_results[0], dict)
            else {}
        )
        data_cid = str(first.get("data_cid") or "").strip()
        if not place:
            place = first
    if not CID_RE.fullmatch(data_cid):
        raise ValueError(
            f"Could not resolve a Google city/district CID for '{location}'. "
            "Provide data_cid explicitly."
        )

    country = str(place.get("country") or "").strip()
    if country and country.lower() not in {"us", "usa", "united states"}:
        raise ValueError(
            "Google Local Services returns results only in the United States; "
            f"the resolved location was in {country}."
        )
    label = _compact_text(place.get("title") or place.get("address"), 300) or location
    resolver_metadata = _search_metadata(payload)
    return data_cid, label, "google_maps_resolver", resolver_metadata


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_string_list(value: Any, limit: int, maximum: int = 500) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value[:limit]
        if (text := _compact_text(item, maximum))
    ]


def _normalize_hours(value: Any) -> tuple[str | None, list[dict[str, str]]]:
    hours = value if isinstance(value, dict) else {}
    week: list[dict[str, str]] = []
    for item in _dict_list(hours.get("week"))[:7]:
        compact = {
            str(day): text
            for day, raw in list(item.items())[:1]
            if (text := _compact_text(raw, 100))
        }
        if compact:
            week.append(compact)
    return _compact_text(hours.get("currently"), 100), week


def normalize_provider(
    item: dict[str, Any],
    *,
    position: int,
    focused_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    hours_current, hours_week = _normalize_hours(item.get("hours"))
    images = _compact_string_list(item.get("images"), 8, 2000)
    provider = {
        "position": position,
        "title": _compact_text(item.get("title"), 500),
        "url": str(item.get("link") or item.get("website") or "").strip() or None,
        "website": str(item.get("website") or "").strip() or None,
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "rating_stars": _dict_list(item.get("rating_stars"))[:5] or None,
        "phone": _compact_text(item.get("phone"), 100),
        "badge": _compact_text(item.get("badge"), 100),
        "type": _compact_text(item.get("type"), 200),
        "address": _compact_text(item.get("address"), 500),
        "service_area": _compact_text(item.get("service_area"), 500),
        "years_in_business": item.get("years_in_business"),
        "bookings_nearby": item.get("bookings_nearby"),
        "thumbnail": item.get("thumbnail") or (images[0] if images else None),
        "images": images or None,
        "hours_current": hours_current,
        "hours_week": hours_week or None,
        "checks": _compact_string_list(item.get("checks"), 12),
        "description": _compact_string_list(item.get("description"), 12),
        "services": _compact_string_list(item.get("services"), 30),
        "covid_measures": _compact_string_list(item.get("covid_measures"), 12),
        "at_this_place": _dict_list(item.get("at_this_place"))[:8] or None,
        "cid": _numeric_id(item.get("cid"), "provider cid") or None,
        "bid": _numeric_id(item.get("bid"), "provider bid") or None,
        "pid": _numeric_id(item.get("pid"), "provider pid") or None,
    }
    if focused_ids:
        for key, value in focused_ids.items():
            provider[key] = value
    return {
        key: field
        for key, field in provider.items()
        if field not in (None, "", [], {})
    }


def normalize_providers(
    value: Any,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    raw = _dict_list(value)
    providers = [
        normalize_provider(item, position=index)
        for index, item in enumerate(raw[:limit], 1)
    ]
    providers = [item for item in providers if item.get("title") or item.get("url")]
    return providers, len(raw)


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
        )
        if metadata.get(key) not in (None, "")
    }


def _build_speech(
    query: str,
    location: str | None,
    providers: list[dict[str, Any]],
    *,
    focused: bool,
) -> str:
    where = f" near {location}" if location else ""
    if not providers:
        return (
            f"Google Local Services returned no provider details for '{query}'{where}."
            if focused
            else f"Google Local Services returned no providers for '{query}'{where}."
        )
    top = providers[0]
    details = []
    if top.get("rating") is not None:
        details.append(f"rated {top['rating']}")
    if top.get("badge"):
        details.append(str(top["badge"]).title())
    suffix = f", {', '.join(details)}" if details else ""
    if focused:
        return f"Retrieved Google Local Services details for {top.get('title') or query}{suffix}."
    return (
        f"Found {len(providers)} Google Local Services provider(s) for '{query}'{where}. "
        f"Top result: {top.get('title') or 'local provider'}{suffix}."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query, provider_query = normalize_service_query(input_data.get("query"))
        language = normalize_language(input_data.get("language"))
        job_type = _validate_text(input_data.get("job_type"), "job_type", 200)
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        max_results = _bounded_int(
            input_data.get("max_results"),
            "max_results",
            default=DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=20,
        )
        data_cid = _numeric_id(input_data.get("data_cid"), "data_cid")
        cid = _numeric_id(input_data.get("cid"), "cid")
        bid = _numeric_id(input_data.get("bid"), "bid")
        pid = _numeric_id(input_data.get("pid"), "pid")
        focused_values = [cid, bid, pid]
        if any(focused_values) and not all(focused_values):
            raise ValueError("'cid', 'bid', and 'pid' must be supplied together.")
        focused = all(focused_values)

        explicit_location = _validate_text(input_data.get("location"), "location", 200)
        location: str | None = explicit_location or None
        location_source: str | None = "explicit" if explicit_location else None
        resolved_location: str | None = None
        data_cid_source = "explicit" if data_cid else ""
        resolver_metadata: dict[str, Any] = {}
        searches_used = 1
        if not data_cid:
            location, location_source = resolve_location_input(explicit_location)
            data_cid, resolved_location, data_cid_source, resolver_metadata = resolve_data_cid(
                location,
                language=language,
                no_cache=no_cache,
            )
            if data_cid_source == "google_maps_resolver":
                searches_used += 1

        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_local_services",
            "q": provider_query,
            "data_cid": data_cid,
            "hl": language,
            "no_cache": "true" if no_cache else "false",
        }
        for key, field in (
            ("job_type", job_type),
            ("cid", cid),
            ("bid", bid),
            ("pid", pid),
        ):
            if field:
                params[key] = field
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _serpapi_request(params)
        if focused:
            local_place = payload.get("local_place")
            local_place = local_place if isinstance(local_place, dict) else {}
            provider = normalize_provider(
                local_place,
                position=1,
                focused_ids={"cid": cid, "bid": bid, "pid": pid},
            ) if local_place else {}
            providers = [provider] if provider else []
            provider_results_count = 1 if local_place else 0
        else:
            providers, provider_results_count = normalize_providers(
                payload.get("local_ads"), limit=max_results
            )

        metadata = _search_metadata(payload)
        search_information = payload.get("search_information")
        search_information = search_information if isinstance(search_information, dict) else {}
        public_results_url = str(
            search_information.get("google_local_services_url") or ""
        ).strip()
        location_label = resolved_location or location
        data: dict[str, Any] = {
            "engine": "google_local_services",
            "mode": "provider_details" if focused else "search",
            "query": query,
            "provider_query": provider_query,
            "location": location,
            "location_source": location_source,
            "resolved_location": resolved_location,
            "data_cid": data_cid,
            "data_cid_source": data_cid_source,
            "language": language,
            "job_type": job_type or None,
            "cid": cid or None,
            "bid": bid or None,
            "pid": pid or None,
            "max_results": max_results,
            "results_count": len(providers),
            "provider_results_count": provider_results_count,
            "results": providers,
            "top_results": providers[:5],
            "detail": providers[0] if focused and providers else None,
            "top_url": providers[0].get("url") if providers else None,
            "google_local_services_url": public_results_url or None,
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "resolver_search_metadata": resolver_metadata or None,
            "serpapi_searches_used": searches_used,
            "us_only": True,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Local Services",
        }
        data = {
            key: field
            for key, field in data.items()
            if field not in (None, "", [], {})
        }
        if include_raw:
            data["raw"] = payload

        return_success(
            _build_speech(query, location_label, providers, focused=focused),
            data,
        )
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Local Services request timed out.")
            return 1
        return_error(f"SerpApi Google Local Services error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
