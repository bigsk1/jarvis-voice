#!/usr/bin/env python3
"""Jarvis Skill: Google Local business discovery through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_LOCAL_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 10
DEFAULT_MAX_ADS = 3
DEFAULT_MAX_DISCOVER = 5
LOCALE_RE = re.compile(r"^[a-z]{2}$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")
CID_RE = re.compile(r"^[0-9]+$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "location",
    "uule",
    "google_domain",
    "gl",
    "hl",
    "ludocid",
    "tbs",
    "start",
    "device",
    "no_cache",
}
LINK_KEYS = (
    "website",
    "directions",
    "phone",
    "order",
    "menu",
    "reservations",
    "appointments",
    "schedule",
)


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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


def normalize_locale(value: Any, label: str) -> str | None:
    locale = str(value or "").strip().lower()
    if not locale:
        return None
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError(f"'{label}' must be a two-letter code such as us or en.")
    return locale


def normalize_google_domain(value: Any) -> str:
    domain = str(value or "google.com").strip().lower()
    if len(domain) > 100 or not DOMAIN_RE.fullmatch(domain) or ".." in domain:
        raise ValueError("'google_domain' must be a Google domain such as google.com or google.co.uk.")
    return domain


def normalize_device(value: Any) -> str:
    device = str(value or "desktop").strip().lower()
    if device not in {"desktop", "tablet", "mobile"}:
        raise ValueError("'device' must be desktop, tablet, or mobile.")
    return device


def _validate_text(value: Any, label: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        raise ValueError(f"'{label}' must be {maximum} characters or fewer.")
    return text


def resolve_location(
    explicit_location: Any,
    uule: Any,
) -> tuple[str | None, str | None, str]:
    """Resolve explicit or mode-scoped location without inheriting proxy geography."""
    location = _validate_text(explicit_location, "location", 200)
    encoded_location = str(uule or "").strip()
    if len(encoded_location) > 500:
        raise ValueError("'uule' must be 500 characters or fewer.")
    if location and encoded_location:
        raise ValueError("'location' and 'uule' cannot be used together.")
    if location:
        return location, None, "explicit"
    if encoded_location:
        return None, encoded_location, "explicit_uule"

    default_location = _validate_text(
        get_config_value("JARVIS_DEFAULT_LOCATION", ""),
        "JARVIS_DEFAULT_LOCATION",
        200,
    )
    if default_location:
        return default_location, None, "jarvis_default_location"

    default_postal_code = _validate_text(
        get_config_value("JARVIS_DEFAULT_POSTAL_CODE", ""),
        "JARVIS_DEFAULT_POSTAL_CODE",
        40,
    )
    if default_postal_code:
        return default_postal_code, None, "jarvis_default_postal_code"

    raise ValueError(
        "Provide 'location' or 'uule', or set JARVIS_DEFAULT_LOCATION or "
        "JARVIS_DEFAULT_POSTAL_CODE in the active mode env file."
    )


def _compact_links(value: Any) -> dict[str, str]:
    links = value if isinstance(value, dict) else {}
    return {
        key: str(links[key]).strip()
        for key in LINK_KEYS
        if links.get(key) not in (None, "")
    }


def _compact_service_options(value: Any) -> dict[str, bool]:
    options = value if isinstance(value, dict) else {}
    return {
        str(key): option
        for key, option in list(options.items())[:20]
        if isinstance(option, bool)
    }


def normalize_places(
    value: Any,
    *,
    limit: int,
    sponsored: bool,
) -> tuple[list[dict[str, Any]], int]:
    raw_places = _dict_list(value)
    places: list[dict[str, Any]] = []
    for fallback_position, item in enumerate(raw_places, 1):
        links = _compact_links(item.get("links"))
        website = str(item.get("website") or links.get("website") or "").strip()
        place_id_search = str(item.get("place_id_search") or "").strip()
        directions_url = str(links.get("directions") or "").strip()
        place_id = str(item.get("place_id") or "").strip()
        google_maps_url = (
            f"https://www.google.com/maps?cid={place_id}"
            if CID_RE.fullmatch(place_id)
            else ""
        )
        title = _compact_text(item.get("title"), 500)
        if not title and not (website or google_maps_url or directions_url or place_id_search):
            continue
        place = {
            "position": item.get("position") or fallback_position,
            "title": title,
            "url": website or directions_url or google_maps_url or place_id_search or None,
            "website": website or None,
            "directions_url": directions_url or None,
            "google_maps_url": google_maps_url or None,
            "place_id_search": place_id_search or None,
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "reviews_original": _compact_text(item.get("reviews_original"), 100),
            "price": _compact_text(item.get("price"), 50),
            "type": _compact_text(item.get("type"), 200),
            "address": _compact_text(item.get("address"), 500),
            "hours": _compact_text(item.get("hours"), 300),
            "description": _compact_text(item.get("description")),
            "place_id": place_id or None,
            "provider_id": str(item.get("provider_id") or "").strip() or None,
            "thumbnail": item.get("thumbnail_large") or item.get("thumbnail"),
            "thumbnail_small": item.get("thumbnail"),
            "gps_coordinates": item.get("gps_coordinates")
            if isinstance(item.get("gps_coordinates"), dict)
            else None,
            "extensions": [
                _compact_text(extension, 300)
                for extension in (item.get("extensions") or [])[:10]
                if _compact_text(extension, 300)
            ] if isinstance(item.get("extensions"), list) else None,
            "links": links or None,
            "service_options": _compact_service_options(item.get("service_options")) or None,
            "sponsored": sponsored,
            "ad_title": _compact_text(item.get("ad_title"), 300) if sponsored else None,
            "displayed_link": _compact_text(item.get("displayed_link"), 300)
            if sponsored
            else None,
        }
        places.append(
            {key: field for key, field in place.items() if field not in (None, "", [], {})}
        )
        if len(places) >= limit:
            break
    return places, len(raw_places)


def normalize_discover_more(value: Any, *, limit: int) -> tuple[list[dict[str, Any]], int]:
    raw_rows = _dict_list(value)
    rows: list[dict[str, Any]] = []
    for item in raw_rows:
        title = _compact_text(item.get("title"), 300)
        url = str(item.get("link") or "").strip()
        if not title and not url:
            continue
        places = item.get("places")
        if isinstance(places, list):
            places = [_compact_text(place, 200) for place in places[:8] if _compact_text(place, 200)]
        elif places not in (None, ""):
            places = _compact_text(places, 800)
        rows.append({
            key: field
            for key, field in {
                "title": title,
                "url": url or None,
                "thumbnail": item.get("thumbnail"),
                "places": places,
                "images": [str(image) for image in (item.get("images") or [])[:3] if image]
                if isinstance(item.get("images"), list)
                else None,
            }.items()
            if field not in (None, "", [], {})
        })
        if len(rows) >= limit:
            break
    return rows, len(raw_rows)


def _pagination_start(value: Any) -> int | None:
    if not value:
        return None
    try:
        raw_start = parse_qs(urlparse(str(value)).query).get("start", [None])[0]
        return int(raw_start) if raw_start is not None else None
    except (TypeError, ValueError):
        return None


def normalize_pagination(payload: dict[str, Any], *, start: int) -> dict[str, Any]:
    pagination = payload.get("serpapi_pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    next_start = _pagination_start(pagination.get("next") or pagination.get("next_link"))
    previous_start = _pagination_start(pagination.get("previous"))
    return {
        key: field
        for key, field in {
            "current": pagination.get("current"),
            "start": start,
            "has_more": next_start is not None,
            "next_start": next_start,
            "previous_start": previous_start,
        }.items()
        if field not in (None, "") or key == "has_more"
    }


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
            "google_local_url",
        )
        if metadata.get(key) not in (None, "")
    }


def _google_local_request(params: dict[str, Any]) -> dict[str, Any]:
    # The code stays proxy-capable while proxy_policy=off keeps Jarvis calls direct.
    return request_serpapi(
        params,
        timeout=GOOGLE_LOCAL_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def build_speech(
    query: str,
    location_label: str,
    results: list[dict[str, Any]],
    ads: list[dict[str, Any]],
) -> str:
    if not results and not ads:
        return f"Google Local returned no places for '{query}' near {location_label}."
    count_text = f"Found {len(results)} Google Local result(s) for '{query}' near {location_label}"
    if ads:
        count_text += f" plus {len(ads)} sponsored result(s)"
    top = results[0] if results else ads[0]
    details = []
    if top.get("rating") is not None:
        details.append(f"rated {top['rating']}")
    if top.get("address"):
        details.append(str(top["address"]))
    suffix = f", {', '.join(details)}" if details else ""
    return f"{count_text}. Top result: {top.get('title') or 'local place'}{suffix}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = _validate_text(input_data.get("query"), "query", 500)
        if not query:
            raise ValueError("'query' is required.")

        location, uule, location_source = resolve_location(
            input_data.get("location"), input_data.get("uule")
        )
        google_domain = normalize_google_domain(input_data.get("google_domain"))
        country = normalize_locale(input_data.get("country"), "country")
        language = normalize_locale(input_data.get("language"), "language")
        device = normalize_device(input_data.get("device"))
        start = _bounded_int(input_data.get("start"), "start", default=0, minimum=0, maximum=1000)
        max_results = _bounded_int(
            input_data.get("max_results"),
            "max_results",
            default=DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=20,
        )
        max_ads = _bounded_int(
            input_data.get("max_ads"),
            "max_ads",
            default=DEFAULT_MAX_ADS,
            minimum=0,
            maximum=10,
        )
        max_discover = _bounded_int(
            input_data.get("max_discover_more"),
            "max_discover_more",
            default=DEFAULT_MAX_DISCOVER,
            minimum=0,
            maximum=10,
        )
        ludocid = str(input_data.get("place_id") or "").strip()
        if ludocid and (len(ludocid) > 32 or not CID_RE.fullmatch(ludocid)):
            raise ValueError("'place_id' must be a numeric Google CID.")
        tbs = str(input_data.get("tbs") or "").strip()
        if len(tbs) > 1000:
            raise ValueError("'tbs' must be 1000 characters or fewer.")
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_local",
            "q": query,
            "google_domain": google_domain,
            "start": start,
            "device": device,
            "no_cache": "true" if no_cache else "false",
        }
        for key, field in (
            ("location", location),
            ("uule", uule),
            ("gl", country),
            ("hl", language),
            ("ludocid", ludocid),
            ("tbs", tbs),
        ):
            if field not in (None, ""):
                params[key] = field
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _google_local_request(params)
        results, provider_results_count = normalize_places(
            payload.get("local_results"), limit=max_results, sponsored=False
        )
        ads, provider_ads_count = normalize_places(
            payload.get("ads_results"), limit=max_ads, sponsored=True
        ) if max_ads else ([], len(_dict_list(payload.get("ads_results"))))
        discover_more, provider_discover_more_count = normalize_discover_more(
            payload.get("discover_more_places"), limit=max_discover
        ) if max_discover else ([], len(_dict_list(payload.get("discover_more_places"))))
        pagination = normalize_pagination(payload, start=start)
        metadata = _search_metadata(payload)
        search_parameters = payload.get("search_parameters")
        search_parameters = search_parameters if isinstance(search_parameters, dict) else {}
        local_map = payload.get("local_map")
        local_map = local_map if isinstance(local_map, dict) else {}
        provider_location_used = _compact_text(search_parameters.get("location_used"), 300)
        provider_location_requested = _compact_text(
            search_parameters.get("location_requested"), 300
        )
        location_label = provider_location_used or location or "the encoded location"

        data: dict[str, Any] = {
            "engine": "google_local",
            "query": query,
            "location": location,
            "location_source": location_source,
            "uule_used": bool(uule),
            "provider_location_requested": provider_location_requested,
            "provider_location_used": provider_location_used,
            "country": country,
            "language": language,
            "google_domain": google_domain,
            "device": device,
            "start": start,
            "place_id": ludocid or None,
            "tbs": tbs or None,
            "max_results": max_results,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "ads_count": len(ads),
            "provider_ads_count": provider_ads_count,
            "ads": ads,
            "discover_more_count": len(discover_more),
            "provider_discover_more_count": provider_discover_more_count,
            "discover_more_places": discover_more,
            "local_map_image": local_map.get("image"),
            "top_url": (
                results[0].get("url") if results else ads[0].get("url") if ads else None
            ),
            "pagination": pagination,
            "has_more": pagination.get("has_more", False),
            "next_start": pagination.get("next_start"),
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "google_local_url": metadata.get("google_local_url"),
            "serpapi_searches_used": 1,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Local",
        }
        data = {key: field for key, field in data.items() if field not in (None, "")}
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(query, location_label, results, ads), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Local request timed out.")
            return 1
        return_error(f"SerpApi Google Local error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
