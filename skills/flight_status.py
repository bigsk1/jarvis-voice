#!/usr/bin/env python3
"""
Jarvis Skill: Flight Status (live aircraft positions)

Answers "where is that flight right now" and "what is flying over me" from
community ADS-B receiver networks. No API key, no account, no new dependency.

Providers, tried in order:
  1. airplanes.live — carries aircraft description, operator, and build year.
  2. adsb.lol — same response shape, used when the first is unreachable.

Deliberate boundary: this reports transponder positions, not airline
operations. Gates, delays, cancellations, and scheduled times live in keyed
commercial services, and an aircraft that has not departed or lacks ADS-B
will not appear at all.
"""
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from geocode import geocode_open_meteo
from http_client import http_request


PROVIDERS = (
    ("airplanes.live", "https://api.airplanes.live/v2"),
    ("adsb.lol", "https://api.adsb.lol/v2"),
)
REQUEST_TIMEOUT = 15
GLOBE_URL = "https://globe.airplanes.live/?icao="

# Spoken flight numbers use IATA codes ("UA 2056"); transponders broadcast the
# ICAO callsign ("UAL2056"). Covers the carriers people actually ask about.
AIRLINE_CODES = {
    "AA": ("AAL", "American"), "AS": ("ASA", "Alaska"), "B6": ("JBU", "JetBlue"),
    "DL": ("DAL", "Delta"), "F9": ("FFT", "Frontier"), "G4": ("AAY", "Allegiant"),
    "HA": ("HAL", "Hawaiian"), "NK": ("NKS", "Spirit"), "SY": ("SCX", "Sun Country"),
    "UA": ("UAL", "United"), "WN": ("SWA", "Southwest"), "MQ": ("ENY", "Envoy"),
    "OO": ("SKW", "SkyWest"), "YX": ("RPA", "Republic"), "9E": ("EDV", "Endeavor"),
    "OH": ("JIA", "PSA"), "QX": ("QXE", "Horizon"), "ZW": ("AWI", "Air Wisconsin"),
    "5X": ("UPS", "UPS"), "FX": ("FDX", "FedEx"),
    "AC": ("ACA", "Air Canada"), "WS": ("WJA", "WestJet"), "PD": ("POE", "Porter"),
    "F8": ("FLE", "Flair"), "AM": ("AMX", "Aeromexico"), "Y4": ("VOI", "Volaris"),
    "VB": ("VIV", "Viva Aerobus"),
    "BA": ("BAW", "British Airways"), "LH": ("DLH", "Lufthansa"), "AF": ("AFR", "Air France"),
    "KL": ("KLM", "KLM"), "IB": ("IBE", "Iberia"), "AZ": ("ITY", "ITA Airways"),
    "LX": ("SWR", "Swiss"), "OS": ("AUA", "Austrian"), "SN": ("BEL", "Brussels Airlines"),
    "SK": ("SAS", "SAS"), "AY": ("FIN", "Finnair"), "TP": ("TAP", "TAP Air Portugal"),
    "EI": ("EIN", "Aer Lingus"), "FR": ("RYR", "Ryanair"), "U2": ("EZY", "easyJet"),
    "W6": ("WZZ", "Wizz Air"), "VS": ("VIR", "Virgin Atlantic"), "LO": ("LOT", "LOT"),
    "TK": ("THY", "Turkish Airlines"), "A3": ("AEE", "Aegean"), "DY": ("NOZ", "Norwegian"),
    "VY": ("VLG", "Vueling"), "EW": ("EWG", "Eurowings"), "HV": ("TRA", "Transavia"),
    "EK": ("UAE", "Emirates"), "EY": ("ETD", "Etihad"), "QR": ("QTR", "Qatar Airways"),
    "SV": ("SVA", "Saudia"), "SQ": ("SIA", "Singapore Airlines"), "CX": ("CPA", "Cathay Pacific"),
    "JL": ("JAL", "Japan Airlines"), "NH": ("ANA", "All Nippon"), "KE": ("KAL", "Korean Air"),
    "OZ": ("AAR", "Asiana"), "CI": ("CAL", "China Airlines"), "BR": ("EVA", "EVA Air"),
    "TG": ("THA", "Thai Airways"), "MH": ("MAS", "Malaysia Airlines"), "GA": ("GIA", "Garuda"),
    "VN": ("HVN", "Vietnam Airlines"), "AI": ("AIC", "Air India"), "6E": ("IGO", "IndiGo"),
    "CA": ("CCA", "Air China"), "MU": ("CES", "China Eastern"), "CZ": ("CSN", "China Southern"),
    "HU": ("CHH", "Hainan"), "PR": ("PAL", "Philippine Airlines"), "QF": ("QFA", "Qantas"),
    "NZ": ("ANZ", "Air New Zealand"), "VA": ("VOZ", "Virgin Australia"), "JQ": ("JST", "Jetstar"),
    "LA": ("LAN", "LATAM"), "AV": ("AVA", "Avianca"), "CM": ("CMP", "Copa"),
    "AR": ("ARG", "Aerolineas Argentinas"), "G3": ("GLO", "GOL"), "AD": ("AZU", "Azul"),
    "ET": ("ETH", "Ethiopian"), "SA": ("SAA", "South African"), "MS": ("MSR", "EgyptAir"),
    "AT": ("RAM", "Royal Air Maroc"), "KQ": ("KQA", "Kenya Airways"),
}
AIRLINE_NAMES = {name.lower(): iata for iata, (_, name) in AIRLINE_CODES.items()}
ICAO_TO_AIRLINE = {icao: name for icao, name in AIRLINE_CODES.values()}

COMPASS = (
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
)

LIMITATIONS = (
    "Live ADS-B transponder positions only. No gate, delay, cancellation, or scheduled "
    "time data. Aircraft that have not departed, have already landed, or do not broadcast "
    "ADS-B will not appear."
)


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def callsign_candidates(flight: str) -> list[str]:
    """Build the callsign spellings a transponder might actually broadcast.

    "UA 2056", "United 2056", and "UAL2056" all have to reach UAL2056, and the
    providers accept a comma-separated list, so every candidate costs one call.
    """
    raw = " ".join(str(flight or "").split()).upper()
    if not raw:
        return []

    candidates: list[str] = []
    compact = raw.replace(" ", "").replace("-", "")

    # "UNITED 2056" -> airline name plus number
    for name, iata in AIRLINE_NAMES.items():
        prefix = name.upper()
        if raw.startswith(prefix + " ") and raw[len(prefix):].strip().isdigit():
            candidates.append(f"{AIRLINE_CODES[iata][0]}{raw[len(prefix):].strip()}")
            break

    # "UA2056" -> ICAO prefix swap
    if len(compact) > 2 and compact[2:].isdigit() and compact[:2] in AIRLINE_CODES:
        candidates.append(f"{AIRLINE_CODES[compact[:2]][0]}{compact[2:]}")

    if compact:
        candidates.append(compact)

    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def compass_point(degrees: Any) -> str | None:
    try:
        value = float(degrees)
    except (TypeError, ValueError):
        return None
    return COMPASS[int((value % 360) / 22.5 + 0.5) % 16]


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_nm * 2 * math.asin(math.sqrt(a))


def fetch_adsb(path: str) -> tuple[list[dict[str, Any]], str]:
    """Query the ADS-B networks in order, returning (aircraft, provider used)."""
    errors = []
    for name, base_url in PROVIDERS:
        try:
            response = http_request(
                "GET",
                f"{base_url}{path}",
                timeout=REQUEST_TIMEOUT,
                use_proxy=True,
                fallback_on_proxy_fail=True,
            )
            if response.status_code >= 400:
                errors.append(f"{name} HTTP {response.status_code}")
                continue
            payload = response.json()
            aircraft = payload.get("ac")
            if not isinstance(aircraft, list):
                errors.append(f"{name} returned an unexpected response")
                continue
            return [item for item in aircraft if isinstance(item, dict)], name
        except Exception as provider_error:
            errors.append(f"{name}: {provider_error}")

    raise RuntimeError("No ADS-B network responded. " + "; ".join(errors))


def normalize_aircraft(
    item: dict[str, Any],
    origin: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Flatten one ADS-B record into plain units and plain language."""
    altitude = item.get("alt_baro")
    on_ground = altitude == "ground"
    altitude_ft = None if on_ground or not isinstance(altitude, (int, float)) else int(altitude)

    rate = item.get("baro_rate")
    if on_ground:
        trend = "on the ground"
    elif isinstance(rate, (int, float)) and rate >= 300:
        trend = "climbing"
    elif isinstance(rate, (int, float)) and rate <= -300:
        trend = "descending"
    else:
        trend = "level"

    callsign = str(item.get("flight") or "").strip() or None
    hex_code = str(item.get("hex") or "").strip().lower() or None
    latitude, longitude = item.get("lat"), item.get("lon")

    distance_nm = item.get("dst")
    bearing_deg = item.get("dir")
    if (
        distance_nm is None
        and origin
        and isinstance(latitude, (int, float))
        and isinstance(longitude, (int, float))
    ):
        distance_nm = round(haversine_nm(origin[0], origin[1], latitude, longitude), 1)

    airline = None
    if callsign and len(callsign) > 3 and callsign[:3] in ICAO_TO_AIRLINE:
        airline = ICAO_TO_AIRLINE[callsign[:3]]

    emergency = item.get("emergency")
    return {
        "callsign": callsign,
        "airline": airline or (item.get("ownOp") or None),
        "registration": item.get("r"),
        "hex": hex_code,
        "aircraft_type": item.get("t"),
        "aircraft": item.get("desc"),
        "year": item.get("year"),
        "on_ground": on_ground,
        "altitude_ft": altitude_ft,
        "vertical_trend": trend,
        "vertical_rate_fpm": int(rate) if isinstance(rate, (int, float)) else None,
        "ground_speed_kt": round(item.get("gs"), 1) if isinstance(item.get("gs"), (int, float)) else None,
        "track_deg": item.get("track"),
        "heading": compass_point(item.get("track")),
        "latitude": latitude,
        "longitude": longitude,
        "distance_nm": round(distance_nm, 1) if isinstance(distance_nm, (int, float)) else None,
        "bearing": compass_point(bearing_deg),
        "squawk": item.get("squawk"),
        "emergency": emergency if emergency and emergency != "none" else None,
        "position_age_seconds": round(item.get("seen_pos"), 1) if isinstance(item.get("seen_pos"), (int, float)) else None,
        "map_url": f"{GLOBE_URL}{hex_code}" if hex_code else None,
    }


def describe_aircraft(entry: dict[str, Any]) -> str:
    label = entry.get("callsign") or entry.get("registration") or "That aircraft"
    airline = entry.get("airline")
    if airline and entry.get("callsign") and entry["callsign"][:3] in ICAO_TO_AIRLINE:
        label = f"{airline} {entry['callsign'][3:]}"

    if entry.get("on_ground"):
        sentence = f"{label} is on the ground"
    else:
        altitude = entry.get("altitude_ft")
        altitude_text = f"at {altitude:,} feet" if altitude else "at an unreported altitude"
        sentence = f"{label} is {altitude_text}"
        if entry.get("vertical_trend") in ("climbing", "descending"):
            sentence += f" and {entry['vertical_trend']}"
        speed = entry.get("ground_speed_kt")
        if speed:
            sentence += f", doing {round(speed)} knots"
        heading = entry.get("heading")
        if heading:
            sentence += f" heading {heading}"

    aircraft = entry.get("aircraft") or entry.get("aircraft_type")
    if aircraft:
        sentence += f". It's a {aircraft}"
    sentence += "."

    if entry.get("emergency"):
        sentence += f" It is squawking an emergency: {entry['emergency']}."
    return sentence


def search_by_identifier(kind: str, value: str) -> tuple[list[dict[str, Any]], str]:
    if kind == "callsign":
        candidates = callsign_candidates(value)
        if not candidates:
            return [], ""
        aircraft, provider = fetch_adsb(f"/callsign/{','.join(candidates)}")
    elif kind == "registration":
        aircraft, provider = fetch_adsb(f"/reg/{value.strip().upper()}")
    else:
        aircraft, provider = fetch_adsb(f"/hex/{value.strip().lower()}")
    return [normalize_aircraft(item) for item in aircraft], provider


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        flight = str(input_data.get("flight", "")).strip()
        registration = str(input_data.get("registration", "")).strip()
        hex_code = str(input_data.get("hex", "")).strip()
        location = str(input_data.get("location", "")).strip()
        latitude = input_data.get("latitude")
        longitude = input_data.get("longitude")
        has_coords = isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))

        if not any([flight, registration, hex_code, location, has_coords]):
            return_error(
                "Provide 'flight' (like UA2056), 'registration' (tail number), 'hex', "
                "or a 'location' to list aircraft overhead."
            )
            return 1

        try:
            num_results = max(1, min(20, int(input_data.get("num_results", 5))))
        except (TypeError, ValueError):
            num_results = 5
        try:
            radius_nm = max(1, min(250, int(input_data.get("radius_nm", 25))))
        except (TypeError, ValueError):
            radius_nm = 25
        include_ground = bool(input_data.get("include_ground", False))

        data: dict[str, Any] = {"limitations": LIMITATIONS}

        if flight or registration or hex_code:
            if flight:
                kind, value, label = "callsign", flight, flight.upper()
            elif registration:
                kind, value, label = "registration", registration, registration.upper()
            else:
                kind, value, label = "hex", hex_code, hex_code.lower()

            results, provider = search_by_identifier(kind, value)
            data.update(
                {
                    "query_type": kind,
                    "query": label,
                    "provider": provider,
                    "results_count": len(results),
                    "results": results[:num_results],
                }
            )
            if not results:
                return_success(
                    speech=(
                        f"{label} is not broadcasting a position right now. That usually means it has "
                        "not taken off yet, has already landed, or is out of receiver range."
                    ),
                    data=data,
                )
                return 0

            data["map_url"] = results[0].get("map_url")
            return_success(speech=describe_aircraft(results[0]), data=data)
            return 0

        # Area search: what is flying over a place.
        if has_coords:
            place = f"{round(float(latitude), 4)}, {round(float(longitude), 4)}"
            lat, lon = float(latitude), float(longitude)
        else:
            resolved = geocode_open_meteo(location)
            if not resolved:
                return_error(f"Could not find a location called '{location}'.")
                return 1
            lat, lon, place = resolved

        aircraft, provider = fetch_adsb(f"/point/{lat}/{lon}/{radius_nm}")
        results = [normalize_aircraft(item, origin=(lat, lon)) for item in aircraft]
        airborne_total = sum(1 for entry in results if not entry["on_ground"])
        if not include_ground:
            results = [entry for entry in results if not entry["on_ground"]]
        results.sort(key=lambda entry: entry["distance_nm"] if entry["distance_nm"] is not None else 9999)

        data.update(
            {
                "query_type": "area",
                "location": place,
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "radius_nm": radius_nm,
                "provider": provider,
                "include_ground": include_ground,
                "airborne_count": airborne_total,
                "results_count": len(results),
                "results": results[:num_results],
            }
        )

        if not results:
            return_success(
                speech=f"No aircraft are being tracked within {radius_nm} nautical miles of {place} right now.",
                data=data,
            )
            return 0

        closest = results[0]
        where = ""
        if closest.get("distance_nm") is not None:
            where = f", {closest['distance_nm']} nautical miles"
            if closest.get("bearing"):
                where += f" to the {closest['bearing']}"
        speech = (
            f"Tracking {len(results)} aircraft within {radius_nm} nautical miles of {place}. "
            f"Closest{where}: {describe_aircraft(closest)}"
        )
        return_success(speech=speech, data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return_error("The ADS-B network timed out. Try again in a moment.")
            return 1
        return_error(f"Flight status error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
