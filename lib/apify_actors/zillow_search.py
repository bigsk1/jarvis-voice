"""Compile explicit Zillow criteria without model-generated region IDs or flags.

This is input preparation for the existing generic Actor gateway. It performs
no requests, grants no Actor permission, and never submits work.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from .zillow_location import resolve_bounds

ZILLOW_SEARCH = frozenset({"maxcopell/zillow-scraper", "X46xKaa20oUA1fRiP"})
PROPERTY_TYPES = {
    "single_family": "sf", "condo": "con", "townhouse": "tow",
    "multi_family": "mf", "apartment": "apa", "manufactured": "manu", "land": "land",
}
_KEYS = frozenset({"locations", "listing_status", "property_types", "price_min",
                   "price_max", "max_days_on_zillow", "results_per_location"})


def _integer(search: dict, key: str, maximum: int, *, minimum: int = 0) -> int | None:
    value = search.get(key)
    if value is not None and (type(value) is not int or not minimum <= value <= maximum):
        raise ValueError(f"search.{key} must be an integer between {minimum} and {maximum}")
    return value


def compile_search(actor: Any, search: Any, *, location_bounds=None) -> dict[str, Any]:
    """Use Zillow's text-location route and explicit mutually exclusive statuses.

    A geocoder supplies the map bounds; Jarvis does not invent a geographic
    boundary or region ID. Returned listings remain evidence to check, rather
    than proof that the website honored every input filter.
    """
    if not isinstance(actor, str) or actor not in ZILLOW_SEARCH:
        raise ValueError("search is supported by maxcopell/zillow-scraper; use input for other Actors")
    if not isinstance(search, dict) or set(search) - _KEYS:
        raise ValueError("Invalid Zillow search criteria")
    locations = search.get("locations")
    if not isinstance(locations, list) or not 1 <= len(locations) <= 5:
        raise ValueError("search.locations requires 1 to 5 city/state names or ZIP codes")
    cleaned = []
    for location in locations:
        if (not isinstance(location, str) or not 1 <= len(location.strip()) <= 120
                or not re.fullmatch(r"[\w\s,.'’()-]+", location, re.UNICODE)
                or any(ord(char) < 32 for char in location)):
            raise ValueError("Use a city and state, named region, or ZIP code in search.locations")
        location = " ".join(location.split())
        if location.casefold() not in {item.casefold() for item in cleaned}:
            cleaned.append(location)
    status = search.get("listing_status")
    if status not in {"for_sale", "for_rent", "sold"}:
        raise ValueError("search.listing_status must be for_sale, for_rent or sold")
    types = search.get("property_types")
    if types is not None and (not isinstance(types, list) or not types
            or any(not isinstance(item, str) or item not in PROPERTY_TYPES for item in types)):
        raise ValueError("Invalid search.property_types")
    low = _integer(search, "price_min", 1_000_000_000)
    high = _integer(search, "price_max", 1_000_000_000)
    if low is not None and high is not None and low > high:
        raise ValueError("search.price_min must not exceed price_max")
    days = _integer(search, "max_days_on_zillow", 1095, minimum=1)
    limit = _integer(search, "results_per_location", 100, minimum=1)
    filters: dict[str, Any] = {"sort": {"value": "days"}}
    filters.update({key: {"value": status == "for_sale"}
                    for key in ("fsba", "fsbo", "nc", "cmsn", "auc", "fore")})
    filters.update(fr={"value": status == "for_rent"}, rs={"value": status == "sold"})
    if types is not None:
        filters.update({key: {"value": name in types} for name, key in PROPERTY_TYPES.items()})
    if low is not None or high is not None:
        filters["price"] = {key: value for key, value in (("min", low), ("max", high)) if value is not None}
    if days is not None:
        filters["doz"] = {"value": str(days)}
    urls = []
    location_bounds = location_bounds or resolve_bounds
    for location in cleaned:
        state = {"usersSearchTerm": location, "isMapVisible": True, "isListVisible": True,
                 "mapBounds": location_bounds(location),
                 "pagination": {}, "filterState": filters}
        path = quote(location.replace(" ", "-"), safe=",-'")
        query = quote(json.dumps(state, separators=(",", ":")), safe="")
        urls.append({"url": f"https://www.zillow.com/homes/{path}_rb/?searchQueryState={query}"})
    return {"searchUrls": urls, "extractionMethod": "PAGINATION", "resultsLimit": limit or 20}
