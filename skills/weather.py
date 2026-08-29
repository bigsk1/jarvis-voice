#!/usr/bin/env python3
"""
Jarvis Skill: Weather
Get current weather and forecast from configurable weather APIs.

Providers:
  - openweathermap (default): Free tier - 60 calls/min, 5-day/3-hour forecast
  - wttr.in (fallback): No API key needed, limited data

Input: { "location": "Seattle", "forecast": false }
Output: { "ok": bool, "speech": str, "data": dict }
"""
import json
import os
import sys
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

# Add lib to path for config_loader and http_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import get_config_value, load_config
from http_client import get_proxy_config, http_request
from weather_location import (
    ResolvedWeatherLocation,
    candidate_match_score,
    country_code,
    country_display_name,
    location_constraints,
    open_meteo_queries,
    openweathermap_queries,
    pick_best_candidate,
    resolve_us_state,
)


def _provider_failure_reason(provider: str, exc: Exception) -> str:
    """Return a bounded, credential-safe provider failure reason."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return f"{provider} authentication failed (HTTP {status_code})"
    if status_code:
        return f"{provider} request failed (HTTP {status_code})"
    error_name = type(exc).__name__
    if "timeout" in error_name.lower() or "timeout" in str(exc).lower():
        return f"{provider} request timed out"
    if "connection" in error_name.lower():
        return f"{provider} connection failed"
    return f"{provider} request failed ({error_name})"


# ============================================================================
# PROVIDER IMPLEMENTATIONS
# ============================================================================

def _geocode_openweathermap_resolution(
    location: str,
    api_key: str,
) -> ResolvedWeatherLocation | None:
    """Resolve a location through OpenWeatherMap and reject qualifier mismatches."""
    constraints = location_constraints(location)
    geo_url = "https://api.openweathermap.org/geo/1.0/direct"
    item = None
    for query in openweathermap_queries(location):
        try:
            response = http_request(
                'GET',
                geo_url,
                params={"q": query, "limit": 5, "appid": api_key},
                timeout=10,
                use_proxy=True,
                fallback_on_proxy_fail=True,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as exc:
            print(
                f"[Weather] {_provider_failure_reason('OpenWeatherMap geocoding', exc)}",
                file=sys.stderr,
            )
            return None

        item = pick_best_candidate(
            results,
            constraints,
            city_key="name",
            region_key="state",
            country_key="country",
            country_code_key="country",
        )
        if item:
            break

    if not item:
        print(f"[Weather] OpenWeatherMap returned no exact match for {location}", file=sys.stderr)
        return None

    country_code = str(item.get("country") or "").upper()
    return ResolvedWeatherLocation(
        requested_location=location,
        latitude=float(item["lat"]),
        longitude=float(item["lon"]),
        city=str(item.get("name") or constraints.city or location),
        region=str(item.get("state") or ""),
        country=country_display_name(country_code, country_code),
        country_code=country_code,
        geocoder="OpenWeatherMap",
    )


def fetch_openweathermap(
    location: str,
    forecast: bool,
    api_key: str,
    resolved_location: ResolvedWeatherLocation | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Fetch weather from OpenWeatherMap API.
    
    Uses Geocoding API first for accurate lat/lon, then fetches weather.
    
    Free tier limits:
    - 60 calls/minute
    - Current weather + 5-day/3-hour forecast
    
    Returns: (data_dict, speech_text)
    """
    base_url = "https://api.openweathermap.org/data/2.5"
    
    resolved = resolved_location or resolve_weather_location(location, api_key)
    if not resolved:
        raise ValueError(f"Could not resolve an exact weather location for {location}")

    params = {
        "lat": resolved.latitude,
        "lon": resolved.longitude,
        "appid": api_key,
        "units": "imperial",
    }
    
    # Get current weather
    current_url = f"{base_url}/weather"
    
    response = http_request(
        'GET',
        current_url,
        params=params,
        timeout=15,
        use_proxy=True,
        fallback_on_proxy_fail=True
    )
    response.raise_for_status()
    current = response.json()
    
    # Extract current weather data
    temp = round(current["main"]["temp"])
    feels_like = round(current["main"]["feels_like"])
    humidity = current["main"]["humidity"]
    condition = current["weather"][0]["description"]
    wind_speed = round(current["wind"]["speed"])
    
    provider_city = str(current.get("name") or resolved.city)
    provider_country = str(current.get("sys", {}).get("country") or "")
    provider_location = (
        f"{provider_city}, {provider_country}" if provider_country else provider_city
    )
    
    # Get forecast if requested
    forecast_data = None
    forecast_speech = ""
    
    if forecast:
        forecast_url = f"{base_url}/forecast"
        forecast_response = http_request(
            'GET',
            forecast_url,
            params=params,
            timeout=15,
            use_proxy=True,
            fallback_on_proxy_fail=True
        )
        forecast_response.raise_for_status()
        forecast_raw = forecast_response.json()
        
        # Extract next 24 hours (8 x 3-hour intervals)
        forecast_list = []
        for item in forecast_raw["list"][:8]:
            dt = datetime.fromtimestamp(item["dt"])
            forecast_list.append({
                "time": dt.strftime("%I %p"),
                "temp": round(item["main"]["temp"]),
                "condition": item["weather"][0]["description"],
                "humidity": item["main"]["humidity"]
            })
        
        forecast_data = forecast_list
        
        # Get high/low for next 24h
        temps = [f["temp"] for f in forecast_list]
        high = max(temps)
        low = min(temps)
        forecast_speech = f" Today's high is {high}, low is {low}."
    
    # Build speech response
    speech = f"It's currently {temp} degrees and {condition} in {resolved.display_name}."
    if feels_like != temp:
        speech += f" Feels like {feels_like}."
    speech += forecast_speech
    
    data = {
        "location": resolved.display_name,
        "temperature": temp,
        "feels_like": feels_like,
        "humidity": humidity,
        "condition": condition,
        "wind_speed": wind_speed,
        "wind_unit": "mph",
        "provider": "OpenWeatherMap",
        "current_weather_provider": "OpenWeatherMap",
        "provider_location_used": provider_location,
        "forecast": forecast_data
    }
    data.update(resolved.metadata())
    
    return data, speech


def _geocode_open_meteo_resolution(
    location: str,
) -> ResolvedWeatherLocation | None:
    """Resolve a location through Open-Meteo and reject qualifier mismatches."""
    constraints = location_constraints(location)

    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    item = None
    query = location
    for query in open_meteo_queries(location):
        try:
            response = http_request(
                'GET',
                geo_url,
                params={
                    "name": query,
                    "count": 10,
                    "language": "en",
                    "format": "json",
                },
                timeout=10,
                use_proxy=True,
                fallback_on_proxy_fail=True,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(
                f"[Weather] {_provider_failure_reason('Open-Meteo geocoding', exc)}",
                file=sys.stderr,
            )
            return None

        item = pick_best_candidate(
            data.get("results", []) if isinstance(data, dict) else [],
            constraints,
            city_key="name",
            region_key="admin1",
            country_key="country",
            country_code_key="country_code",
        )
        if item:
            break

    if not item:
        print(f"[Weather] Open-Meteo returned no exact match for {location}", file=sys.stderr)
        return None
    return ResolvedWeatherLocation(
        requested_location=location,
        latitude=float(item["latitude"]),
        longitude=float(item["longitude"]),
        city=str(item.get("name") or query),
        region=str(item.get("admin1") or ""),
        country=str(item.get("country") or ""),
        country_code=str(item.get("country_code") or "").upper(),
        geocoder="Open-Meteo",
    )


def _geocode_wttr_resolution(
    location: str,
) -> ResolvedWeatherLocation | None:
    """Resolve through wttr.in as a final, validated geocoder fallback."""
    encoded_location = quote(location, safe="")
    url = f"https://wttr.in/{encoded_location}"
    try:
        response = http_request(
            'GET',
            url,
            params={"format": "j1"},
            headers={"User-Agent": "Jarvis-Weather/1.0"},
            timeout=15,
            use_proxy=True,
            fallback_on_proxy_fail=True,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"[Weather] wttr.in geocoding failed: {exc}", file=sys.stderr)
        return None

    areas = data.get("nearest_area", []) if isinstance(data, dict) else []
    if not areas or not isinstance(areas[0], dict):
        return None

    area = areas[0]
    city = _wttr_area_value(area, "areaName")
    region = _wttr_area_value(area, "region")
    country = _wttr_area_value(area, "country")
    score = candidate_match_score(
        location_constraints(location),
        city=city,
        region=region,
        country=country,
        country_code_value="",
        require_city_match=False,
    )
    if score is None:
        print(
            f"[Weather] wttr.in returned no exact match for {location}",
            file=sys.stderr,
        )
        return None

    try:
        latitude = float(area["latitude"])
        longitude = float(area["longitude"])
    except (KeyError, TypeError, ValueError):
        return None

    resolved_country_code = country_code(country) or ""
    state = resolve_us_state(region) if resolved_country_code == 'US' else None
    canonical_region = state[1] if state else region
    canonical_country = country_display_name(resolved_country_code, country)
    constraints = location_constraints(location)
    return ResolvedWeatherLocation(
        requested_location=location,
        latitude=latitude,
        longitude=longitude,
        city=city or constraints.city or location,
        region=canonical_region,
        country=canonical_country,
        country_code=resolved_country_code,
        geocoder="wttr.in",
    )


def resolve_weather_location(
    location: str,
    api_key: str = "",
) -> ResolvedWeatherLocation | None:
    """Resolve one exact location for all current and forecast providers."""
    resolved = _geocode_open_meteo_resolution(location)
    if resolved:
        return resolved
    if api_key:
        resolved = _geocode_openweathermap_resolution(location, api_key)
        if resolved:
            return resolved
    return _geocode_wttr_resolution(location)


def fetch_open_meteo_daily_forecast(
    location: str,
    days: int,
    resolved_location: ResolvedWeatherLocation | None = None,
) -> list[dict[str, Any]] | None:
    """
    Fetch daily weather forecast from Open-Meteo (no API key required).

    Returns list of daily forecasts with high/low/precip data.
    """
    resolved = resolved_location or resolve_weather_location(location)
    if not resolved:
        return None

    forecast_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": resolved.latitude,
        "longitude": resolved.longitude,
        "timezone": "auto",
        "forecast_days": max(1, min(days, 10)),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,wind_speed_10m_max"
    }

    response = http_request(
        'GET',
        forecast_url,
        params=params,
        timeout=15,
        use_proxy=True,
        fallback_on_proxy_fail=True
    )
    response.raise_for_status()
    data = response.json()
    daily = data.get("daily", {})

    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip_probs = daily.get("precipitation_probability_max", [])
    weather_codes = daily.get("weathercode", [])
    wind_maxes = daily.get("wind_speed_10m_max", [])

    if not times:
        return None

    code_map = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "light drizzle",
        53: "drizzle",
        55: "dense drizzle",
        56: "freezing drizzle",
        57: "freezing drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        66: "freezing rain",
        67: "freezing rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        77: "snow grains",
        80: "rain showers",
        81: "rain showers",
        82: "heavy rain showers",
        85: "snow showers",
        86: "heavy snow showers",
        95: "thunderstorm",
        96: "thunderstorm with hail",
        99: "thunderstorm with hail",
    }

    daily_forecast = []
    for i, iso_day in enumerate(times):
        try:
            day_obj = date.fromisoformat(iso_day)
            day_name = day_obj.strftime("%a")
        except Exception:
            day_name = iso_day

        code = weather_codes[i] if i < len(weather_codes) else None
        daily_forecast.append({
            "date": iso_day,
            "day": day_name,
            "high": round(highs[i]) if i < len(highs) and highs[i] is not None else None,
            "low": round(lows[i]) if i < len(lows) and lows[i] is not None else None,
            "wind_max": round(wind_maxes[i]) if i < len(wind_maxes) and wind_maxes[i] is not None else None,
            "condition": code_map.get(code, "unknown"),
            "precip_probability": precip_probs[i] if i < len(precip_probs) else None,
            "weather_code": code
        })

    return daily_forecast


def _wttr_area_value(area: dict[str, Any], key: str) -> str:
    value = area.get(key)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("value") or "").strip()
    return str(value or "").strip()


def fetch_wttr(
    location: str,
    forecast: bool,
    resolved_location: ResolvedWeatherLocation | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Fetch weather from wttr.in (no API key required).
    Fallback provider with basic data.
    
    Returns: (data_dict, speech_text)
    """
    resolved = resolved_location or resolve_weather_location(location)
    if not resolved:
        raise ValueError(f"Could not resolve an exact weather location for {location}")

    # Query by the shared validated coordinates, never by an ambiguous free-form phrase.
    coordinate_query = f"{resolved.latitude:.6f},{resolved.longitude:.6f}"
    url = f"https://wttr.in/{coordinate_query}"
    params = {"format": "j1"}
    
    response = http_request(
        'GET',
        url,
        params=params,
        headers={"User-Agent": "Jarvis-Weather/1.0"},
        timeout=15,
        use_proxy=True,
        fallback_on_proxy_fail=True
    )
    response.raise_for_status()
    data = response.json()
    
    current = data["current_condition"][0]
    area = data["nearest_area"][0]
    
    temp = int(current["temp_F"])
    feels_like = int(current["FeelsLikeF"])
    humidity = int(current["humidity"])
    condition = str(current["weatherDesc"][0]["value"]).strip()
    wind_speed = int(current["windspeedMiles"])
    
    city = _wttr_area_value(area, "areaName")
    region = _wttr_area_value(area, "region")
    country = _wttr_area_value(area, "country")
    provider_location_parts = [city, region, country]
    provider_location = ", ".join(part for part in provider_location_parts if part)

    score = candidate_match_score(
        location_constraints(resolved.requested_location),
        city=city,
        region=region,
        country=country,
        country_code_value="",
        require_city_match=False,
    )
    if score is None:
        raise ValueError(
            "wttr.in returned a location that conflicts with the requested region: "
            f"{provider_location or 'unknown'}"
        )
    
    # Get forecast if requested
    forecast_data = None
    forecast_speech = ""
    
    if forecast and "weather" in data:
        # Get today's forecast
        today = data["weather"][0]
        high = int(today["maxtempF"])
        low = int(today["mintempF"])
        forecast_speech = f" Today's high is {high}, low is {low}."
        
        forecast_data = [{
            "date": today["date"],
            "high": high,
            "low": low,
            "condition": str(
                today["hourly"][4]["weatherDesc"][0]["value"]
            ).strip(),  # Midday
        }]
    
    speech = f"It's currently {temp} degrees and {condition} in {resolved.display_name}."
    if abs(feels_like - temp) >= 3:
        speech += f" Feels like {feels_like}."
    speech += forecast_speech
    
    result_data = {
        "location": resolved.display_name,
        "temperature": temp,
        "feels_like": feels_like,
        "humidity": humidity,
        "condition": condition,
        "wind_speed": wind_speed,
        "wind_unit": "mph",
        "provider": "wttr.in",
        "current_weather_provider": "wttr.in",
        "provider_location_used": provider_location,
        "forecast": forecast_data
    }
    result_data.update(resolved.metadata())
    
    return result_data, speech


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Get weather from configured provider."""
    try:
        # Load config
        load_config()
        
        # Read input from command line argument
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1
        
        # Extract parameters
        location = str(input_data.get("location") or "").strip()
        forecast = input_data.get("forecast", False)
        days_raw = input_data.get("days")
        if days_raw is None:
            days = 7 if forecast else 1
        else:
            try:
                days = int(days_raw)
            except (ValueError, TypeError):
                days = 7 if forecast else 1
        days = max(1, min(days, 10))
        
        if not location:
            return_error("Location is required. Example: 'Seattle' or 'London, UK'")
            return 1
        
        # Get provider config
        provider = str(
            get_config_value('WEATHER_PROVIDER', 'openweathermap') or 'openweathermap'
        ).strip().lower()
        api_key = str(get_config_value('OPENWEATHER_API_KEY', '') or '')
        
        # Check if API key is a placeholder
        if api_key and ('YOUR_' in api_key or 'REPLACE' in api_key or len(api_key) < 10):
            api_key = ''  # Treat as not set
        
        if provider not in {'openweathermap', 'wttr'}:
            return_error(f"Unknown weather provider: {provider}")
            return 1

        resolved = resolve_weather_location(location, api_key)
        if not resolved:
            return_error(
                f"Weather location could not be resolved exactly: {location}. "
                "Include a city with its state/region or country."
            )
            return 1

        fallback_used = False
        fallback_reason = None

        if provider == 'openweathermap' and api_key:
            try:
                data, speech = fetch_openweathermap(
                    location,
                    forecast,
                    api_key,
                    resolved_location=resolved,
                )
            except Exception as exc:
                fallback_used = True
                fallback_reason = _provider_failure_reason("OpenWeatherMap", exc)
                data, speech = fetch_wttr(
                    location,
                    forecast,
                    resolved_location=resolved,
                )
        elif provider == 'openweathermap':
            fallback_used = True
            fallback_reason = "OpenWeatherMap API key is not configured"
            data, speech = fetch_wttr(
                location,
                forecast,
                resolved_location=resolved,
            )
        else:
            data, speech = fetch_wttr(
                location,
                forecast,
                resolved_location=resolved,
            )

        data.update(resolved.metadata())
        data["provider_requested"] = provider
        data["fallback_used"] = fallback_used
        if fallback_reason:
            data["fallback_reason"] = fallback_reason
        
        # Check if proxy was used
        proxy_enabled = get_proxy_config() is not None
        data["proxy_enabled"] = proxy_enabled

        if forecast and data.get("forecast"):
            data["forecast_provider"] = data.get("provider")

        # Add true multi-day forecast when requested.
        # OpenWeatherMap free endpoint is limited; Open-Meteo provides daily forecasts.
        if forecast and days > 1:
            data["forecast_days"] = 0
            try:
                daily_forecast = fetch_open_meteo_daily_forecast(
                    location,
                    days,
                    resolved_location=resolved,
                )
                if daily_forecast:
                    data["daily_forecast"] = daily_forecast
                    data["forecast_days"] = min(days, len(daily_forecast))
                    data["daily_forecast_provider"] = "Open-Meteo"
                    data["daily_forecast_location"] = resolved.display_name

                    preview = daily_forecast[:3]
                    preview_parts = []
                    for day in preview:
                        day_label = day.get("day", "")
                        high = day.get("high")
                        low = day.get("low")
                        condition = day.get("condition", "unknown")
                        if high is not None and low is not None:
                            preview_parts.append(f"{day_label} {high}/{low} {condition}")
                    if preview_parts:
                        speech += " Next days: " + "; ".join(preview_parts) + "."
                else:
                    daily_reason = "Open-Meteo returned no daily forecast data"
                    data["daily_forecast_error"] = daily_reason
                    speech += f" I couldn't fetch a full {days}-day forecast."
            except Exception as daily_err:
                # Keep current weather result but report capability limit honestly.
                daily_reason = _provider_failure_reason("Open-Meteo", daily_err)
                data["daily_forecast_error"] = daily_reason
                speech += f" I couldn't fetch a full {days}-day forecast: {daily_reason}."
        
        return_success(speech=speech, data=data)
        return 0
        
    except Exception as e:
        error_msg = str(e)
        
        # Handle specific errors
        if "404" in error_msg:
            return_error(f"Location not found: {location}. Try a different city name.")
        elif "timeout" in error_msg.lower() or "Timeout" in type(e).__name__:
            return_error("Weather API request timed out. Try again.")
        elif "Connection" in type(e).__name__:
            return_error(f"Failed to connect to weather service: {error_msg}")
        else:
            return_error(f"Weather error: {error_msg}")
        return 1


def return_success(speech: str, data: dict | None = None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict | None = None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
