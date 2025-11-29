#!/usr/bin/env python3
"""
Jarvis Skill: Current Time and Date with Timezone Support
Returns current time/date for any location worldwide.

Input: { "location": "Tokyo" } or { "timezone": "Asia/Tokyo" } or {}
Output: { "ok": true, "speech": "...", "data": {...} }
"""

import sys
import os
import json
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

# Try to use zoneinfo (Python 3.9+), fall back to pytz
try:
    from zoneinfo import ZoneInfo
    HAS_ZONEINFO = True
except ImportError:
    try:
        import pytz
        HAS_ZONEINFO = False
    except ImportError:
        HAS_ZONEINFO = None  # No timezone support

# Common city/location to IANA timezone mapping
# This allows natural queries like "What time is it in Tokyo?"
LOCATION_TIMEZONES = {
    # Asia
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore",
    "seoul": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "south korea": "Asia/Seoul",
    "bangkok": "Asia/Bangkok",
    "thailand": "Asia/Bangkok",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "dubai": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "manila": "Asia/Manila",
    "philippines": "Asia/Manila",
    "jakarta": "Asia/Jakarta",
    "indonesia": "Asia/Jakarta",
    "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei",
    "hanoi": "Asia/Ho_Chi_Minh",
    "vietnam": "Asia/Ho_Chi_Minh",
    "ho chi minh": "Asia/Ho_Chi_Minh",
    
    # Europe
    "london": "Europe/London",
    "uk": "Europe/London",
    "england": "Europe/London",
    "britain": "Europe/London",
    "paris": "Europe/Paris",
    "france": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "rome": "Europe/Rome",
    "italy": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam",
    "netherlands": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "belgium": "Europe/Brussels",
    "vienna": "Europe/Vienna",
    "austria": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "switzerland": "Europe/Zurich",
    "stockholm": "Europe/Stockholm",
    "sweden": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "norway": "Europe/Oslo",
    "helsinki": "Europe/Helsinki",
    "finland": "Europe/Helsinki",
    "copenhagen": "Europe/Copenhagen",
    "denmark": "Europe/Copenhagen",
    "dublin": "Europe/Dublin",
    "ireland": "Europe/Dublin",
    "lisbon": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    "athens": "Europe/Athens",
    "greece": "Europe/Athens",
    "moscow": "Europe/Moscow",
    "russia": "Europe/Moscow",
    "warsaw": "Europe/Warsaw",
    "poland": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "czech": "Europe/Prague",
    
    # Americas
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "miami": "America/New_York",
    "atlanta": "America/New_York",
    "washington dc": "America/New_York",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "vegas": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "hawaii": "Pacific/Honolulu",
    "honolulu": "Pacific/Honolulu",
    "anchorage": "America/Anchorage",
    "alaska": "America/Anchorage",
    "toronto": "America/Toronto",
    "montreal": "America/Toronto",
    "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "lima": "America/Lima",
    "peru": "America/Lima",
    "bogota": "America/Bogota",
    "colombia": "America/Bogota",
    
    # Oceania
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "australia": "Australia/Sydney",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "auckland": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland",
    
    # Africa / Middle East
    "cairo": "Africa/Cairo",
    "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "south africa": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "nigeria": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "kenya": "Africa/Nairobi",
    "tel aviv": "Asia/Jerusalem",
    "israel": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem",
    "istanbul": "Europe/Istanbul",
    "turkey": "Europe/Istanbul",
    
    # Common abbreviations
    "est": "America/New_York",
    "edt": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "gmt": "Europe/London",
    "utc": "UTC",
    "bst": "Europe/London",
    "cet": "Europe/Paris",
    "jst": "Asia/Tokyo",
    "kst": "Asia/Seoul",
    "ist": "Asia/Kolkata",
    "aest": "Australia/Sydney",
    "aedt": "Australia/Sydney",
}


def get_timezone(tz_name: str):
    """Get timezone object from name."""
    if HAS_ZONEINFO is True:
        return ZoneInfo(tz_name)
    elif HAS_ZONEINFO is False:
        return pytz.timezone(tz_name)
    else:
        return None


def get_time_for_location(location: str = None, timezone: str = None):
    """
    Get current time for a location or timezone.
    
    Args:
        location: City/country name (e.g., "Tokyo", "Paris")
        timezone: IANA timezone (e.g., "Asia/Tokyo", "Europe/Paris")
    
    Returns:
        dict with time info
    """
    now = datetime.now()
    tz_name = None
    display_location = None
    
    # Determine timezone
    if timezone:
        # Direct timezone specified
        tz_name = timezone
        display_location = timezone
    elif location:
        # Look up location in our mapping
        location_lower = location.lower().strip()
        if location_lower in LOCATION_TIMEZONES:
            tz_name = LOCATION_TIMEZONES[location_lower]
            display_location = location.title()
        else:
            # Try to use location as timezone directly
            tz_name = location
            display_location = location
    
    # Get the time
    if tz_name and HAS_ZONEINFO is not None:
        try:
            tz = get_timezone(tz_name)
            if HAS_ZONEINFO:
                now = datetime.now(tz)
            else:
                now = datetime.now(tz)
        except Exception as e:
            # Invalid timezone, fall back to local
            return {
                "ok": False,
                "error": f"Unknown timezone or location: {location or timezone}",
                "speech": f"I don't recognize that location. Try a major city like Tokyo, Paris, or New York."
            }
    
    # Format the response
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%A, %B %d, %Y")
    full_str = now.strftime("%I:%M %p on %A, %B %d")
    hour = int(now.strftime("%H"))
    
    # Build speech response
    if display_location:
        if hour < 12:
            speech = f"It's {time_str} in {display_location}"
        else:
            speech = f"It's currently {time_str} in {display_location}"
    else:
        # Local time
        if hour < 12:
            speech = f"Good morning! It's {full_str}"
        elif hour < 18:
            speech = f"It's currently {full_str}"
        else:
            speech = f"It's {full_str}"
    
    return {
        "ok": True,
        "speech": speech,
        "data": {
            "time": now.strftime("%H:%M"),
            "time_12h": time_str,
            "date": now.strftime("%Y-%m-%d"),
            "date_formatted": date_str,
            "day_of_week": now.strftime("%A"),
            "timezone": tz_name or "local",
            "location": display_location,
            "utc_offset": now.strftime("%z") if tz_name else None
        }
    }


def main():
    try:
        # Parse input
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            try:
                args = json.load(sys.stdin)
            except:
                args = {}
        
        # Extract parameters
        location = args.get("location")
        timezone = args.get("timezone")
        
        # Get time
        result = get_time_for_location(location, timezone)
        
        print(json.dumps(result))
        
        if not result.get("ok", True):
            sys.exit(1)
            
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error getting time: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

