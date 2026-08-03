#!/usr/bin/env python3
"""Tests for the shared keyless Open-Meteo geocoder."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import geocode
from geocode import geocode_open_meteo


PORTLAND_ME = {
    "name": "Portland", "latitude": 43.66, "longitude": -70.26,
    "country_code": "US", "admin1": "Maine", "country": "United States",
}
PORTLAND_OR = {
    "name": "Portland", "latitude": 45.52, "longitude": -122.68,
    "country_code": "US", "admin1": "Oregon", "country": "United States",
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def run_geocode(location, results):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["params"] = kwargs.get("params")
        return FakeResponse({"results": results})

    with patch.object(geocode, "http_request", side_effect=fake_request):
        return geocode_open_meteo(location), captured


class GeocodeTests(unittest.TestCase):
    def test_us_state_code_disambiguates_same_named_cities(self):
        # Maine is listed first, but "Portland, OR" must not land there.
        result, _ = run_geocode("Portland, OR", [PORTLAND_ME, PORTLAND_OR])
        self.assertEqual(result, (45.52, -122.68, "Portland, Oregon, United States"))

    def test_full_state_name_also_matches(self):
        result, _ = run_geocode("Portland, Oregon", [PORTLAND_ME, PORTLAND_OR])
        self.assertEqual(result[0], 45.52)

    def test_abbreviation_that_is_not_a_prefix_of_its_state_still_matches(self):
        # "ME" is not a prefix of "Maine", which is what a prefix match gets wrong.
        result, _ = run_geocode("Portland, ME", [PORTLAND_OR, PORTLAND_ME])
        self.assertEqual(result[0], 43.66)

    def test_bare_city_takes_the_top_match(self):
        result, _ = run_geocode("Portland", [PORTLAND_ME, PORTLAND_OR])
        self.assertEqual(result[0], 43.66)

    def test_only_the_city_part_is_queried(self):
        _, captured = run_geocode("Portland, OR", [PORTLAND_OR])
        self.assertEqual(captured["params"]["name"], "Portland")

    def test_country_code_qualifier_selects_the_right_country(self):
        toronto = {
            "name": "Toronto", "latitude": 43.70, "longitude": -79.42,
            "country_code": "CA", "admin1": "Ontario", "country": "Canada",
        }
        toronto_us = {
            "name": "Toronto", "latitude": 40.46, "longitude": -80.60,
            "country_code": "US", "admin1": "Ohio", "country": "United States",
        }
        result, _ = run_geocode("Toronto, CA", [toronto_us, toronto])
        self.assertEqual(result[0], 43.70)

    def test_spelled_out_country_qualifier_matches(self):
        paris_fr = {
            "name": "Paris", "latitude": 48.85, "longitude": 2.35,
            "country_code": "FR", "admin1": "Ile-de-France", "country": "France",
        }
        paris_tx = {
            "name": "Paris", "latitude": 33.66, "longitude": -95.55,
            "country_code": "US", "admin1": "Texas", "country": "United States",
        }
        result, _ = run_geocode("Paris, France", [paris_tx, paris_fr])
        self.assertEqual(result[0], 48.85)

    def test_no_results_returns_none(self):
        result, _ = run_geocode("Nowherecityxyz", [])
        self.assertIsNone(result)

    def test_display_name_omits_missing_region(self):
        result, _ = run_geocode(
            "Tokyo",
            [{"name": "Tokyo", "latitude": 35.68, "longitude": 139.69, "country": "Japan"}],
        )
        self.assertEqual(result[2], "Tokyo, Japan")


if __name__ == "__main__":
    unittest.main()
