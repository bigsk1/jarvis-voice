#!/usr/bin/env python3
"""Keyless place lookup via the Open-Meteo geocoding API.

Shared by tools that need coordinates for a spoken place name. Open-Meteo
needs no credentials, so this works in every Jarvis mode and profile.
"""

from __future__ import annotations

from http_client import http_request


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Abbreviation to full name, because the geocoder reports regions spelled out
# and prefix matching gets this wrong ("ME" is not a prefix of "Maine").
US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia',
}

US_STATE_CODES = frozenset(US_STATES)


def geocode_open_meteo(location: str, timeout: int = 10) -> tuple[float, float, str] | None:
    """Resolve a place name to (latitude, longitude, display_name).

    A trailing US state code is honored ("Portland, OR" must not land in
    Maine); otherwise the API's own top match wins. Returns None when the
    place cannot be resolved.
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

    target = parts[1].upper() if len(parts) >= 2 else None
    best = None
    if target:
        # A bare two-letter US state also implies the country, which lets
        # "Portland, OR" beat the more populous Portland, Maine.
        us_hint = target in US_STATE_CODES
        region = US_STATES.get(target, target).upper()
        for item in results:
            country_code = (item.get("country_code") or "").upper()
            country = (item.get("country") or "").upper()
            admin1 = (item.get("admin1") or "").upper()
            if admin1 and admin1 == region:
                best = item
                break
            if country_code == target or country == region:
                best = item
                break
            if us_hint and country_code == "US" and best is None:
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
