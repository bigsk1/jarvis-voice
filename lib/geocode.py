#!/usr/bin/env python3
"""Keyless place lookup via the Open-Meteo geocoding API.

Shared by tools that need coordinates for a spoken place name. Open-Meteo
needs no credentials, so this works in every Jarvis mode and profile.
"""

from __future__ import annotations

from http_client import http_request


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

US_STATE_CODES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
}


def geocode_open_meteo(location: str, timeout: int = 10) -> tuple[float, float, str] | None:
    """Resolve a place name to (latitude, longitude, display_name).

    Returns None when the place cannot be resolved.
    """
    parts = [part.strip() for part in location.split(',')]
    query = parts[0] if parts else location

    response = http_request(
        'GET',
        GEOCODE_URL,
        params={"name": query, "count": 5, "language": "en", "format": "json"},
        timeout=timeout,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return None

    target_state = parts[1].upper() if len(parts) >= 2 else None
    best = None
    for item in results:
        country_code = (item.get("country_code") or "").upper()
        admin1 = (item.get("admin1") or "")
        # Prefer US state match when user provided one like "Hillsboro, OR"
        if target_state and country_code == "US":
            if target_state in US_STATE_CODES and admin1.upper() == target_state:
                best = item
                break
            # Second best: match expanded state name
            if target_state in US_STATE_CODES and admin1.lower().startswith(target_state.lower()):
                best = item
                break
        # Fallback to first US hit for US-like queries
        if target_state and target_state in US_STATE_CODES and country_code == "US" and best is None:
            best = item
    if best is None:
        best = results[0]

    city = best.get("name", query)
    admin1 = best.get("admin1")
    country = best.get("country")
    if admin1 and country:
        display_name = f"{city}, {admin1}, {country}"
    elif country:
        display_name = f"{city}, {country}"
    else:
        display_name = city

    return (best["latitude"], best["longitude"], display_name)
