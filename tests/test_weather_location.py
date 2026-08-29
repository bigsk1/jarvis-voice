#!/usr/bin/env python3
"""Regression coverage for provider-independent weather location matching."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "lib"))

from weather_location import (  # noqa: E402
    candidate_match_score,
    canonical_city,
    location_constraints,
    open_meteo_queries,
    openweathermap_queries,
)


@pytest.mark.parametrize(
    ("requested", "city", "region", "country", "country_code"),
    [
        ("Toronto, CA", "Toronto", "Ontario", "Canada", "CA"),
        ("Toronto, CA", "Toronto", "California", "United States", "US"),
        ("Mumbai, IN", "Mumbai", "Maharashtra", "India", "IN"),
        ("Berlin, DE", "Berlin", "Berlin", "Germany", "DE"),
        ("Tbilisi, Georgia", "Tbilisi", "T'bilisi", "Georgia", "GE"),
        ("Tbilisi, Georgia", "Tbilisi", "Georgia", "United States", "US"),
        ("Sao Paulo, Brazil", "São Paulo", "São Paulo", "Brazil", "BR"),
        (
            "Washington, DC",
            "Washington D.C.",
            "District of Columbia",
            "United States",
            "US",
        ),
    ],
)
def test_ambiguous_and_provider_variant_candidates_are_candidate_driven(
    requested,
    city,
    region,
    country,
    country_code,
):
    score = candidate_match_score(
        location_constraints(requested),
        city=city,
        region=region,
        country=country,
        country_code_value=country_code,
    )

    assert score is not None


def test_explicit_three_part_location_rejects_contradictory_region_and_country():
    constraints = location_constraints("Paris, Texas, France")

    texas = candidate_match_score(
        constraints,
        city="Paris",
        region="Texas",
        country="United States",
        country_code_value="US",
    )
    france = candidate_match_score(
        constraints,
        city="Paris",
        region="Île-de-France",
        country="France",
        country_code_value="FR",
    )

    assert texas is None
    assert france is None


def test_city_suffix_is_not_globally_removed():
    assert canonical_city("Kansas City") != canonical_city("Kansas")
    assert canonical_city("New York City") == canonical_city("New York")


def test_open_meteo_queries_are_qualified_before_broadening():
    assert open_meteo_queries("Newport, Rhode Island") == [
        "Newport, Rhode Island",
        "Newport",
    ]
    assert open_meteo_queries("Washington, DC") == [
        "Washington, DC",
        "Washington",
        "Washington, District of Columbia",
    ]


def test_openweathermap_keeps_both_meanings_of_ambiguous_state_codes():
    assert openweathermap_queries("Toronto, CA") == [
        "Toronto, CA",
        "Toronto, CA, US",
    ]
    assert openweathermap_queries("Newport, Oregon") == ["Newport,OR,US"]
    assert openweathermap_queries("Newport Oregon") == ["Newport,OR,US"]
