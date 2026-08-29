#!/usr/bin/env python3
"""Regression coverage for Weather location resolution."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import weather as weather_tool  # noqa: E402


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
        result = weather_tool._geocode_openweathermap_resolution(
            "Newport, Oregon",
            "test-key",
        )

    assert result is not None
    assert result.latitude == 44.6368
    assert result.longitude == -124.0535
    assert result.display_name == "Newport, Oregon"
    assert result.country_code == "US"
    assert request.call_args.kwargs["params"]["q"] == "Newport,OR,US"
    assert request.call_args.kwargs["params"]["limit"] == 5
    assert request.call_args.args[1].startswith("https://")


def test_openweathermap_skips_first_same_city_in_wrong_state():
    payload = [
        {
            "name": "Newport",
            "state": "Rhode Island",
            "country": "US",
            "lat": 41.4901,
            "lon": -71.3128,
        },
        {
            "name": "Newport",
            "state": "Oregon",
            "country": "US",
            "lat": 44.6368,
            "lon": -124.0535,
        },
    ]
    with patch("weather.http_request", return_value=_response(payload)):
        result = weather_tool._geocode_openweathermap_resolution(
            "Newport, Oregon",
            "test-key",
        )

    assert result is not None
    assert result.display_name == "Newport, Oregon"


def test_openweathermap_does_not_substitute_a_different_explicit_state():
    payload = [
        {
            "name": "Newport",
            "state": "Rhode Island",
            "country": "US",
            "lat": 41.4901,
            "lon": -71.3128,
        }
    ]
    with patch("weather.http_request", return_value=_response(payload)):
        result = weather_tool._geocode_openweathermap_resolution(
            "Newport, Oregon",
            "test-key",
        )

    assert result is None


def test_openweathermap_geocoder_does_not_log_api_key_urls(capsys):
    error = RuntimeError(
        "401 for https://api.openweathermap.org/geo/1.0/direct?appid=secret-key"
    )
    error.response = Mock(status_code=401)
    with patch("weather.http_request", side_effect=error):
        result = weather_tool._geocode_openweathermap_resolution(
            "Newport, Oregon",
            "secret-key",
        )

    assert result is None
    stderr = capsys.readouterr().err
    assert "secret-key" not in stderr
    assert "HTTP 401" in stderr


def test_openweathermap_accepts_ca_as_a_country_from_candidate_data():
    payload = [
        {
            "name": "Toronto",
            "state": "Ontario",
            "country": "CA",
            "lat": 43.7001,
            "lon": -79.4163,
        }
    ]
    with patch("weather.http_request", return_value=_response(payload)) as request:
        resolved = weather_tool._geocode_openweathermap_resolution(
            "Toronto, CA",
            "test-key",
        )

    assert resolved is not None
    assert resolved.display_name == "Toronto, Ontario, Canada"
    assert request.call_args.kwargs["params"]["q"] == "Toronto, CA"


def test_openweathermap_falls_through_to_ambiguous_us_state_interpretation():
    california = [
        {
            "name": "San Diego",
            "state": "California",
            "country": "US",
            "lat": 32.7157,
            "lon": -117.1611,
        }
    ]
    with patch(
        "weather.http_request",
        side_effect=[_response([]), _response(california)],
    ) as request:
        resolved = weather_tool._geocode_openweathermap_resolution(
            "San Diego, CA",
            "test-key",
        )

    assert resolved is not None
    assert resolved.display_name == "San Diego, California"
    assert [call.kwargs["params"]["q"] for call in request.call_args_list] == [
        "San Diego, CA",
        "San Diego, CA, US",
    ]


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
    with patch("weather.http_request", return_value=_response(payload)) as request:
        result = weather_tool._geocode_open_meteo_resolution("Newport, Oregon")

    assert result is not None
    assert result.latitude == 44.6368
    assert result.longitude == -124.0535
    assert result.display_name == "Newport, Oregon"
    assert result.country == "United States"
    assert request.call_args.kwargs["params"]["name"] == "Newport, Oregon"


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
        result = weather_tool._geocode_open_meteo_resolution("Newport, Oregon")

    assert result is None


def test_open_meteo_broadens_only_after_qualified_queries_are_exhausted():
    canada = {
        "results": [
            {
                "name": "Toronto",
                "admin1": "Ontario",
                "country": "Canada",
                "country_code": "CA",
                "latitude": 43.7001,
                "longitude": -79.4163,
            }
        ]
    }
    with patch(
        "weather.http_request",
        side_effect=[_response({}), _response(canada)],
    ) as request:
        resolved = weather_tool._geocode_open_meteo_resolution("Toronto, CA")

    assert resolved is not None
    assert resolved.display_name == "Toronto, Ontario, Canada"
    assert [call.kwargs["params"]["name"] for call in request.call_args_list] == [
        "Toronto, CA",
        "Toronto",
    ]


def _newport_resolution(region="Oregon"):
    return weather_tool.ResolvedWeatherLocation(
        requested_location="Newport, Oregon",
        latitude=44.6368,
        longitude=-124.0535,
        city="Newport",
        region=region,
        country="United States",
        country_code="US",
        geocoder="Open-Meteo",
    )


def _wttr_payload(region="Oregon", city="Newport"):
    return {
        "current_condition": [
            {
                "temp_F": "59",
                "FeelsLikeF": "59",
                "humidity": "97",
                "weatherDesc": [{"value": "Fog"}],
                "windspeedMiles": "6",
            }
        ],
        "nearest_area": [
            {
                "areaName": [{"value": city}],
                "region": [{"value": region}],
                "country": [{"value": "United States of America"}],
                "latitude": "44.637",
                "longitude": "-124.052",
            }
        ],
        "weather": [
            {
                "date": "2026-08-28",
                "maxtempF": "64",
                "mintempF": "54",
                "hourly": [
                    {"weatherDesc": [{"value": "Fog"}]}
                    for _ in range(5)
                ],
            }
        ],
    }


def test_wttr_uses_shared_coordinates_and_preserves_region_in_provenance():
    resolved = _newport_resolution()
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload()),
    ) as request:
        data, speech = weather_tool.fetch_wttr(
            "Newport, Oregon",
            True,
            resolved_location=resolved,
        )

    assert request.call_args.args[1].endswith("/44.636800,-124.053500")
    assert data["location"] == "Newport, Oregon"
    assert data["provider_location_used"] == (
        "Newport, Oregon, United States of America"
    )
    assert data["location_region"] == "Oregon"
    assert data["latitude"] == 44.6368
    assert "Newport, Oregon" in speech


def test_wttr_geocoder_validates_clean_city_and_state():
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload()),
    ) as request:
        resolved = weather_tool._geocode_wttr_resolution("Newport, Oregon")

    assert resolved is not None
    assert resolved.display_name == "Newport, Oregon"
    assert resolved.geocoder == "wttr.in"
    assert resolved.latitude == 44.637
    assert request.call_args.args[1].endswith("/Newport%2C%20Oregon")


def test_wttr_geocoder_accepts_provider_city_when_region_still_matches():
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload()),
    ):
        resolved = weather_tool._geocode_wttr_resolution(
            "today till Thursday in Newport, Oregon"
        )

    assert resolved is not None
    assert resolved.display_name == "Newport, Oregon"
    assert resolved.requested_location == "today till Thursday in Newport, Oregon"


def test_wttr_geocoder_accepts_a_neighborhood_label_in_the_requested_region():
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload(city="South Beach")),
    ):
        resolved = weather_tool._geocode_wttr_resolution("Newport, Oregon")

    assert resolved is not None
    assert resolved.display_name == "South Beach, Oregon"


def test_resolver_uses_validated_wttr_when_other_geocoders_are_unavailable():
    expected = _newport_resolution()
    with (
        patch("weather._geocode_open_meteo_resolution", return_value=None),
        patch("weather._geocode_openweathermap_resolution", return_value=None),
        patch("weather._geocode_wttr_resolution", return_value=expected) as fallback,
    ):
        resolved = weather_tool.resolve_weather_location(
            "Newport, Oregon",
            "configured-test-key",
        )

    assert resolved is expected
    fallback.assert_called_once_with("Newport, Oregon")


def test_wttr_coordinate_response_may_name_a_nearby_area_in_same_state():
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload(city="South Beach")),
    ):
        data, _speech = weather_tool.fetch_wttr(
            "Newport, Oregon",
            False,
            resolved_location=_newport_resolution(),
        )

    assert data["location"] == "Newport, Oregon"
    assert data["provider_location_used"].startswith("South Beach, Oregon")


def test_wttr_rejects_a_region_conflicting_with_shared_resolution():
    with patch(
        "weather.http_request",
        return_value=_response(_wttr_payload(region="Rhode Island")),
    ):
        with pytest.raises(ValueError, match="conflicts with the requested region"):
            weather_tool.fetch_wttr(
                "Newport, Oregon",
                False,
                resolved_location=_newport_resolution(),
            )


def test_main_fallback_reuses_resolution_and_reports_reason():
    resolved = _newport_resolution()
    captured = {}

    def config_value(key, default=None):
        return {
            "WEATHER_PROVIDER": "openweathermap",
            "OPENWEATHER_API_KEY": "configured-test-key",
        }.get(key, default)

    def success(speech, data=None):
        captured.update({"speech": speech, "data": data})

    with (
        patch.object(sys, "argv", ["weather.py", '{"location":"Newport, Oregon"}']),
        patch("weather.load_config"),
        patch("weather.get_config_value", side_effect=config_value),
        patch("weather.resolve_weather_location", return_value=resolved),
        patch("weather.fetch_openweathermap", side_effect=TimeoutError("slow")) as primary,
        patch(
            "weather.fetch_wttr",
            return_value=(
                {
                    "location": "Newport, Oregon",
                    "provider": "wttr.in",
                    "temperature": 59,
                },
                "Weather in Newport, Oregon.",
            ),
        ) as fallback,
        patch("weather.get_proxy_config", return_value=None),
        patch("weather.return_success", side_effect=success),
    ):
        assert weather_tool.main() == 0

    assert primary.call_args.kwargs["resolved_location"] is resolved
    assert fallback.call_args.kwargs["resolved_location"] is resolved
    assert captured["data"]["fallback_used"] is True
    assert captured["data"]["fallback_reason"] == (
        "OpenWeatherMap request timed out"
    )
    assert captured["data"]["location"] == "Newport, Oregon"
    assert captured["data"]["requested_location"] == "Newport, Oregon"
    assert "authentication" not in captured["speech"].lower()
    assert "timed out" not in captured["speech"].lower()


def test_main_reports_an_exact_resolution_failure():
    captured = {}

    def config_value(key, default=None):
        return {
            "WEATHER_PROVIDER": "openweathermap",
            "OPENWEATHER_API_KEY": "configured-test-key",
        }.get(key, default)

    with (
        patch.object(sys, "argv", ["weather.py", '{"location":"Missing, Oregon"}']),
        patch("weather.load_config"),
        patch("weather.get_config_value", side_effect=config_value),
        patch("weather.resolve_weather_location", return_value=None),
        patch(
            "weather.return_error",
            side_effect=lambda speech, data=None: captured.update({"speech": speech}),
        ),
    ):
        assert weather_tool.main() == 1

    assert captured["speech"].startswith(
        "Weather location could not be resolved exactly: Missing, Oregon"
    )


def test_main_current_and_daily_forecast_share_one_resolution():
    resolved = _newport_resolution()
    captured = {}

    def config_value(key, default=None):
        return {
            "WEATHER_PROVIDER": "openweathermap",
            "OPENWEATHER_API_KEY": "configured-test-key",
        }.get(key, default)

    def success(speech, data=None):
        captured.update({"speech": speech, "data": data})

    with (
        patch.object(
            sys,
            "argv",
            ["weather.py", '{"location":"Newport, Oregon","forecast":true,"days":7}'],
        ),
        patch("weather.load_config"),
        patch("weather.get_config_value", side_effect=config_value),
        patch("weather.resolve_weather_location", return_value=resolved),
        patch(
            "weather.fetch_openweathermap",
            return_value=(
                {
                    "location": "Newport, Oregon",
                    "provider": "OpenWeatherMap",
                    "temperature": 59,
                    "forecast": [{"time": "08 PM", "temp": 58}],
                },
                "Weather in Newport, Oregon.",
            ),
        ) as current,
        patch(
            "weather.fetch_open_meteo_daily_forecast",
            return_value=[
                {
                    "date": "2026-08-28",
                    "day": "Fri",
                    "high": 64,
                    "low": 54,
                    "condition": "fog",
                }
            ],
        ) as daily,
        patch("weather.get_proxy_config", return_value=None),
        patch("weather.return_success", side_effect=success),
    ):
        assert weather_tool.main() == 0

    assert current.call_args.kwargs["resolved_location"] is resolved
    assert daily.call_args.kwargs["resolved_location"] is resolved
    assert captured["data"]["fallback_used"] is False
    assert captured["data"]["forecast_provider"] == "OpenWeatherMap"
    assert captured["data"]["daily_forecast_provider"] == "Open-Meteo"
    assert captured["data"]["daily_forecast_location"] == "Newport, Oregon"


def test_main_records_empty_daily_forecast_as_an_error():
    resolved = _newport_resolution()
    captured = {}

    def config_value(key, default=None):
        return {
            "WEATHER_PROVIDER": "openweathermap",
            "OPENWEATHER_API_KEY": "configured-test-key",
        }.get(key, default)

    with (
        patch.object(
            sys,
            "argv",
            ["weather.py", '{"location":"Newport, Oregon","forecast":true,"days":7}'],
        ),
        patch("weather.load_config"),
        patch("weather.get_config_value", side_effect=config_value),
        patch("weather.resolve_weather_location", return_value=resolved),
        patch(
            "weather.fetch_openweathermap",
            return_value=(
                {
                    "location": "Newport, Oregon",
                    "provider": "OpenWeatherMap",
                    "temperature": 59,
                },
                "Weather in Newport, Oregon.",
            ),
        ),
        patch("weather.fetch_open_meteo_daily_forecast", return_value=None),
        patch("weather.get_proxy_config", return_value=None),
        patch(
            "weather.return_success",
            side_effect=lambda speech, data=None: captured.update(
                {"speech": speech, "data": data}
            ),
        ),
    ):
        assert weather_tool.main() == 0

    assert captured["data"]["forecast_days"] == 0
    assert captured["data"]["daily_forecast_error"] == (
        "Open-Meteo returned no daily forecast data"
    )
    assert "couldn't fetch a full 7-day forecast" in captured["speech"]
