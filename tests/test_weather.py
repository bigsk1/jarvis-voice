#!/usr/bin/env python3
"""Regression coverage for Weather location resolution."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import weather as weather_tool


def _response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_full_state_name_is_canonicalized_for_openweathermap():
    with patch(
        "weather.http_request",
        return_value=_response(
            [
                {
                    "name": "Newport",
                    "state": "Oregon",
                    "country": "US",
                    "lat": 44.6368,
                    "lon": -124.0535,
                }
            ]
        ),
    ) as request:
        result = weather_tool.geocode_location("Newport, Oregon", "test-key")

    assert result == (44.6368, -124.0535, "Newport, Oregon", "US")
    assert request.call_args.kwargs["params"]["q"] == "Newport,OR,US"
    assert weather_tool.normalize_location("Newport, Oregon") == "Newport,OR,US"


def test_open_meteo_prefers_exact_full_state_over_first_same_city_result():
    payload = {
        "results": [
            {
                "name": "Newport",
                "admin1": "Rhode Island",
                "country": "United States",
                "country_code": "US",
                "latitude": 41.4901,
                "longitude": -71.3128,
            },
            {
                "name": "Newport",
                "admin1": "Oregon",
                "country": "United States",
                "country_code": "US",
                "latitude": 44.6368,
                "longitude": -124.0535,
            },
        ]
    }
    with patch("weather.http_request", return_value=_response(payload)):
        result = weather_tool.geocode_open_meteo("Newport, Oregon")

    assert result == (
        44.6368,
        -124.0535,
        "Newport, Oregon, United States",
    )


def test_open_meteo_does_not_substitute_a_different_explicit_state():
    payload = {
        "results": [
            {
                "name": "Newport",
                "admin1": "Rhode Island",
                "country": "United States",
                "country_code": "US",
                "latitude": 41.4901,
                "longitude": -71.3128,
            }
        ]
    }
    with patch("weather.http_request", return_value=_response(payload)):
        result = weather_tool.geocode_open_meteo("Newport, Oregon")

    assert result is None
