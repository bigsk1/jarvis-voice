"""Provider-independent weather location parsing and candidate validation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

US_STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut',
    'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
    'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine',
    'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan',
    'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
    'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico',
    'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota',
    'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon',
    'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
    'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'DC': 'District of Columbia',
}
US_STATE_CODES = frozenset(US_STATE_NAMES)
US_STATE_NAME_TO_CODE = {
    state_name.upper(): state_code
    for state_code, state_name in US_STATE_NAMES.items()
}

COUNTRY_ALIASES = {
    'US': 'US',
    'USA': 'US',
    'UNITED STATES': 'US',
    'UNITED STATES OF AMERICA': 'US',
    'GB': 'GB',
    'UK': 'GB',
    'UNITED KINGDOM': 'GB',
    'GREAT BRITAIN': 'GB',
    'CA': 'CA',
    'CANADA': 'CA',
    'JP': 'JP',
    'JAPAN': 'JP',
    'AU': 'AU',
    'AUSTRALIA': 'AU',
}

COUNTRY_DISPLAY_NAMES = {
    'US': 'United States',
    'GB': 'United Kingdom',
    'CA': 'Canada',
    'JP': 'Japan',
    'AU': 'Australia',
}

ADMIN_REGION_ALIASES = {
    'AB': 'ALBERTA',
    'BC': 'BRITISH COLUMBIA',
    'MB': 'MANITOBA',
    'NB': 'NEW BRUNSWICK',
    'NL': 'NEWFOUNDLAND AND LABRADOR',
    'NS': 'NOVA SCOTIA',
    'NT': 'NORTHWEST TERRITORIES',
    'NU': 'NUNAVUT',
    'ON': 'ONTARIO',
    'PE': 'PRINCE EDWARD ISLAND',
    'QC': 'QUEBEC',
    'SK': 'SASKATCHEWAN',
    'YT': 'YUKON',
}

CITY_ALIASES = {
    'NYC': 'NEW YORK',
    'NEW YORK CITY': 'NEW YORK',
    'WASHINGTON DC': 'WASHINGTON',
    'WASHINGTON DISTRICT OF COLUMBIA': 'WASHINGTON',
}


def match_text(value: Any) -> str:
    """Return an accent-insensitive, punctuation-normalized comparison value."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.replace("'", '').replace('\N{RIGHT SINGLE QUOTATION MARK}', '')
    return ' '.join(re.sub(r'[^A-Za-z0-9]+', ' ', text).upper().split())


def canonical_city(value: Any) -> str:
    """Normalize benign locality variants without changing distinct city names."""
    normalized = match_text(value).replace(' D C', ' DC')
    if normalized.startswith('SAINT '):
        normalized = f"ST {normalized[6:]}"
    return CITY_ALIASES.get(normalized, normalized)


def resolve_us_state(region: Any) -> tuple[str, str] | None:
    """Return canonical ``(code, name)`` for a U.S. state token."""
    normalized = match_text(region)
    if normalized in US_STATE_CODES:
        return normalized, US_STATE_NAMES[normalized]
    state_code = US_STATE_NAME_TO_CODE.get(normalized)
    if state_code:
        return state_code, US_STATE_NAMES[state_code]
    return None


def split_location_parts(location: str) -> list[str]:
    """Split comma parts and recognize a trailing state or country code."""
    compact = ' '.join(str(location or '').strip().split())
    if not compact:
        return []
    if ',' in compact:
        return [part.strip() for part in compact.split(',') if part.strip()]

    normalized = match_text(compact)
    for state_code, state_name in sorted(
        US_STATE_NAMES.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        for suffix in (state_name.upper(), state_code):
            marker = f' {suffix}'
            if normalized.endswith(marker):
                city = compact[: -len(marker)].strip()
                if city:
                    original_qualifier = compact[-len(suffix):]
                    return [city, original_qualifier]

    code_match = re.fullmatch(r'(.+?)\s+([A-Za-z]{2})', compact)
    if code_match:
        return [code_match.group(1).strip(), code_match.group(2)]
    return [compact]


def country_code(value: Any) -> str | None:
    normalized = match_text(value)
    if not normalized:
        return None
    alias = COUNTRY_ALIASES.get(normalized)
    if alias:
        return alias
    if len(normalized) == 2 and normalized.isalpha():
        return normalized
    return None


def country_display_name(code: str, fallback: str = '') -> str:
    return COUNTRY_DISPLAY_NAMES.get(str(code or '').upper(), fallback or code)


def canonical_region(value: Any) -> str:
    normalized = match_text(value)
    state = resolve_us_state(normalized)
    if state:
        return state[1].upper()
    return ADMIN_REGION_ALIASES.get(normalized, normalized)


@dataclass(frozen=True)
class LocationConstraints:
    """Candidate-driven interpretation of a requested location."""

    requested_location: str
    city: str
    qualifier: str | None = None
    region: str | None = None
    country: str | None = None

    @property
    def has_explicit_qualifier(self) -> bool:
        return bool(self.qualifier or self.region or self.country)


def location_constraints(location: str) -> LocationConstraints:
    parts = split_location_parts(location)
    city = parts[0] if parts else ''
    if len(parts) >= 3:
        return LocationConstraints(
            requested_location=location,
            city=city,
            region=parts[1],
            country=parts[2],
        )
    return LocationConstraints(
        requested_location=location,
        city=city,
        qualifier=parts[1] if len(parts) == 2 else None,
    )


def _matches_region(expected: str, candidate_region: Any) -> bool:
    return canonical_region(expected) == canonical_region(candidate_region)


def _matches_country(
    expected: str,
    candidate_country: Any,
    candidate_country_code: Any,
) -> bool:
    expected_text = match_text(expected)
    expected_code = country_code(expected)
    actual_text = match_text(candidate_country)
    actual_code = country_code(candidate_country_code) or country_code(candidate_country)
    if expected_code and actual_code == expected_code:
        return True
    return bool(expected_text and actual_text == expected_text)


def candidate_match_score(
    constraints: LocationConstraints,
    *,
    city: Any,
    region: Any,
    country: Any,
    country_code_value: Any,
    require_city_match: bool = True,
) -> int | None:
    """Score a candidate while rejecting explicit qualifier contradictions."""
    requested_city = canonical_city(constraints.city)
    candidate_city = canonical_city(city)
    if (
        require_city_match
        and constraints.has_explicit_qualifier
        and requested_city
        and candidate_city != requested_city
    ):
        return None

    score = 10 if requested_city and candidate_city == requested_city else 0
    if constraints.region or constraints.country:
        if constraints.region and not _matches_region(constraints.region, region):
            return None
        if constraints.country and not _matches_country(
            constraints.country,
            country,
            country_code_value,
        ):
            return None
        if constraints.region:
            score += 5
        if constraints.country:
            score += 3
        return score

    if constraints.qualifier:
        matches_region = _matches_region(constraints.qualifier, region)
        matches_country = _matches_country(
            constraints.qualifier,
            country,
            country_code_value,
        )
        if not (matches_region or matches_country):
            return None
        score += 5
    return score


def pick_best_candidate(
    candidates: Any,
    constraints: LocationConstraints,
    *,
    city_key: str,
    region_key: str,
    country_key: str,
    country_code_key: str,
    require_city_match: bool = True,
) -> dict[str, Any] | None:
    """Return the highest-scoring validated provider candidate."""
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(candidates if isinstance(candidates, list) else []):
        if not isinstance(item, dict):
            continue
        score = candidate_match_score(
            constraints,
            city=item.get(city_key),
            region=item.get(region_key),
            country=item.get(country_key),
            country_code_value=item.get(country_code_key),
            require_city_match=require_city_match,
        )
        if score is not None:
            ranked.append((score, -index, item))
    if not ranked:
        return None
    return max(ranked, key=lambda row: (row[0], row[1]))[2]


def _dedupe_queries(queries: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for query in queries:
        compact = ', '.join(part.strip() for part in query.split(',') if part.strip())
        key = match_text(compact)
        if compact and key not in seen:
            seen.add(key)
            result.append(compact)
    return result


def open_meteo_queries(location: str) -> list[str]:
    """Prefer a qualified lookup, then broaden without dropping validation."""
    constraints = location_constraints(location)
    parts = split_location_parts(location)
    qualified = ', '.join(parts)
    queries = [qualified, constraints.city]
    qualifier = constraints.qualifier
    state = resolve_us_state(qualifier) if qualifier else None
    if state:
        queries.append(f'{constraints.city}, {state[1]}')
    return _dedupe_queries(queries)


def openweathermap_queries(location: str) -> list[str]:
    """Build candidate queries without forcing ambiguous state/country tokens."""
    constraints = location_constraints(location)
    parts = split_location_parts(location)
    if constraints.region or constraints.country:
        country = country_code(constraints.country)
        state = resolve_us_state(constraints.region)
        if country == 'US' and state:
            return [f'{constraints.city},{state[0]},US']
        return [','.join(parts)]

    if not constraints.qualifier:
        return [constraints.city]

    raw = f'{constraints.city},{constraints.qualifier}'
    state = resolve_us_state(constraints.qualifier)
    if not state:
        return [raw]

    state_query = f'{constraints.city},{state[0]},US'
    qualifier = match_text(constraints.qualifier)
    if len(qualifier) == 2 or qualifier == 'GEORGIA':
        return _dedupe_queries([raw, state_query])
    return [state_query]


@dataclass(frozen=True)
class ResolvedWeatherLocation:
    """One validated location shared by every weather-data provider."""

    requested_location: str
    latitude: float
    longitude: float
    city: str
    region: str
    country: str
    country_code: str
    geocoder: str

    @property
    def display_name(self) -> str:
        if self.country_code == 'US' and self.region:
            return f'{self.city}, {self.region}'
        if self.region and self.country:
            return f'{self.city}, {self.region}, {self.country}'
        if self.country:
            return f'{self.city}, {self.country}'
        return self.city

    def metadata(self) -> dict[str, Any]:
        return {
            'requested_location': self.requested_location,
            'location': self.display_name,
            'resolved_location': self.display_name,
            'location_region': self.region or None,
            'location_country': self.country or None,
            'location_country_code': self.country_code or None,
            'latitude': round(self.latitude, 6),
            'longitude': round(self.longitude, 6),
            'location_geocoder': self.geocoder,
        }
