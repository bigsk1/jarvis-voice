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
import sys
import os
import json
from datetime import datetime, date
from typing import Any

# Add lib to path for config_loader and http_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from http_client import http_request, get_proxy_config


# ============================================================================
# US STATE CODES (for location normalization)
# ============================================================================

US_STATE_CODES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
}

def normalize_location(location: str) -> str:
    """
    Normalize location string for OpenWeatherMap API.
    
    Converts "City, STATE" to "City,US" since OWM doesn't understand US state codes.
    Examples:
        "Hillsboro, OR" -> "Hillsboro,US"
        "Portland, OR" -> "Portland,US"
        "London, UK" -> "London,UK" (unchanged)
        "Seattle" -> "Seattle" (unchanged)
    """
    # Split on comma
    parts = [p.strip() for p in location.split(',')]
    
    if len(parts) == 2:
        city, region = parts
        # Check if region is a US state code
        if region.upper() in US_STATE_CODES:
            return f"{city},US"
        # Otherwise keep as-is (might be country code)
        return f"{city},{region}"
    
    # Single word or already formatted
    return location


# ============================================================================
# PROVIDER IMPLEMENTATIONS
# ============================================================================

def geocode_location(location: str, api_key: str) -> tuple[float, float, str, str] | None:
    """
    Use OpenWeatherMap Geocoding API to get coordinates for a location.
    
    Returns: (lat, lon, city_name, country) or None if not found
    """
    # Normalize location for geocoding query
    # Convert "City, STATE" to "City,STATE,US" for better US state matching
    parts = [p.strip() for p in location.split(',')]
    
    if len(parts) == 2:
        city, region = parts
        if region.upper() in US_STATE_CODES:
            # Add US country code for US states
            query = f"{city},{region},US"
        else:
            query = f"{city},{region}"
    else:
        query = location
    
    geo_url = "http://api.openweathermap.org/geo/1.0/direct"
    params = {
        "q": query,
        "limit": 1,
        "appid": api_key
    }
    
    try:
        response = http_request(
            'GET',
            geo_url,
            params=params,
            timeout=10,
            use_proxy=True,
            fallback_on_proxy_fail=True
        )
        response.raise_for_status()
        results = response.json()
        
        if results and len(results) > 0:
            loc = results[0]
            city_name = loc.get("name", "Unknown")
            country = loc.get("country", "")
            state = loc.get("state", "")
            
            # Build display name with state for US locations
            if country == "US" and state:
                display_name = f"{city_name}, {state}"
            else:
                display_name = f"{city_name}, {country}" if country else city_name
            
            return (loc["lat"], loc["lon"], display_name, country)
    except Exception as e:
        print(f"[Weather] Geocoding failed: {e}", file=sys.stderr)
    
    return None


def fetch_openweathermap(location: str, forecast: bool, api_key: str) -> tuple[dict[str, Any], str]:
    """
    Fetch weather from OpenWeatherMap API.
    
    Uses Geocoding API first for accurate lat/lon, then fetches weather.
    
    Free tier limits:
    - 60 calls/minute
    - Current weather + 5-day/3-hour forecast
    
    Returns: (data_dict, speech_text)
    """
    base_url = "https://api.openweathermap.org/data/2.5"
    
    # Step 1: Geocode location to get accurate lat/lon
    geo_result = geocode_location(location, api_key)
    
    if geo_result:
        lat, lon, location_str, country = geo_result
        # Use coordinates for weather (most accurate)
        params = {
            "lat": lat,
            "lon": lon,
            "appid": api_key,
            "units": "imperial"  # Fahrenheit
        }
    else:
        # Fallback to city name query (less accurate)
        normalized_location = normalize_location(location)
        params = {
            "q": normalized_location,
            "appid": api_key,
            "units": "imperial"
        }
        location_str = None  # Will get from response
    
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
    
    # Use geocoded location string if available, otherwise from response
    if not location_str:
        city_name = current["name"]
        country = current["sys"].get("country", "")
        location_str = f"{city_name}, {country}" if country else city_name
    
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
    speech = f"It's currently {temp} degrees and {condition} in {location_str}."
    if feels_like != temp:
        speech += f" Feels like {feels_like}."
    speech += forecast_speech
    
    data = {
        "location": location_str,
        "temperature": temp,
        "feels_like": feels_like,
        "humidity": humidity,
        "condition": condition,
        "wind_speed": wind_speed,
        "wind_unit": "mph",
        "provider": "OpenWeatherMap",
        "forecast": forecast_data
    }
    
    return data, speech


def geocode_open_meteo(location: str) -> tuple[float, float, str] | None:
    """
    Geocode location via Open-Meteo geocoding API.

    Returns: (lat, lon, display_name) or None
    """
    parts = [p.strip() for p in location.split(',')]
    query = parts[0] if parts else location

    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": query,
        "count": 5,
        "language": "en",
        "format": "json"
    }

    response = http_request(
        'GET',
        geo_url,
        params=params,
        timeout=10,
        use_proxy=True,
        fallback_on_proxy_fail=True
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
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


def fetch_open_meteo_daily_forecast(location: str, days: int) -> list[dict[str, Any]] | None:
    """
    Fetch daily weather forecast from Open-Meteo (no API key required).

    Returns list of daily forecasts with high/low/precip data.
    """
    geo = geocode_open_meteo(location)
    if not geo:
        return None

    lat, lon, _ = geo
    forecast_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
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


def fetch_wttr(location: str, forecast: bool) -> tuple[dict[str, Any], str]:
    """
    Fetch weather from wttr.in (no API key required).
    Fallback provider with basic data.
    
    Returns: (data_dict, speech_text)
    """
    # Use JSON format
    url = f"https://wttr.in/{location}"
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
    condition = current["weatherDesc"][0]["value"]
    wind_speed = int(current["windspeedMiles"])
    
    # Build location string
    city = area["areaName"][0]["value"]
    country = area["country"][0]["value"]
    location_str = f"{city}, {country}"
    
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
            "condition": today["hourly"][4]["weatherDesc"][0]["value"]  # Midday
        }]
    
    speech = f"It's currently {temp} degrees and {condition} in {location_str}."
    if abs(feels_like - temp) >= 3:
        speech += f" Feels like {feels_like}."
    speech += forecast_speech
    
    result_data = {
        "location": location_str,
        "temperature": temp,
        "feels_like": feels_like,
        "humidity": humidity,
        "condition": condition,
        "wind_speed": wind_speed,
        "wind_unit": "mph",
        "provider": "wttr.in",
        "forecast": forecast_data
    }
    
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
        location = input_data.get("location", "").strip()
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
        provider = get_config_value('WEATHER_PROVIDER', 'openweathermap').lower()
        api_key = get_config_value('OPENWEATHER_API_KEY', '')
        
        # Check if API key is a placeholder
        if api_key and ('YOUR_' in api_key or 'REPLACE' in api_key or len(api_key) < 10):
            api_key = ''  # Treat as not set
        
        # Fetch weather based on provider
        if provider == 'openweathermap' and api_key:
            try:
                data, speech = fetch_openweathermap(location, forecast, api_key)
            except Exception as e:
                # Fallback to wttr.in if OpenWeatherMap fails
                if "401" in str(e) or "403" in str(e):
                    return_error(f"OpenWeatherMap API key invalid or expired")
                    return 1
                # Try fallback
                data, speech = fetch_wttr(location, forecast)
                speech += " (via wttr.in fallback)"
        elif provider == 'wttr' or not api_key:
            # Use wttr.in (no API key needed)
            if provider == 'openweathermap' and not api_key:
                # Warn but continue with fallback
                pass
            data, speech = fetch_wttr(location, forecast)
        else:
            return_error(f"Unknown weather provider: {provider}")
            return 1
        
        # Check if proxy was used
        proxy_enabled = get_proxy_config() is not None
        data["proxy_enabled"] = proxy_enabled

        # Add true multi-day forecast when requested.
        # OpenWeatherMap free endpoint is limited; Open-Meteo provides daily forecasts.
        if forecast and days > 1:
            try:
                daily_forecast = fetch_open_meteo_daily_forecast(location, days)
                if daily_forecast:
                    data["daily_forecast"] = daily_forecast
                    data["forecast_days"] = min(days, len(daily_forecast))
                    data["daily_forecast_provider"] = "Open-Meteo"

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
            except Exception as daily_err:
                # Keep current weather result but report capability limit honestly.
                speech += f" I couldn't fetch a full {days}-day forecast right now: {daily_err}"
        
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
