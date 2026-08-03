#!/usr/bin/env python3
"""Regression tests for the flight_status live aircraft tracker."""

import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import flight_status
from flight_status import (
    callsign_candidates,
    compass_point,
    describe_aircraft,
    haversine_nm,
    main,
    normalize_aircraft,
)


AIRBORNE = {
    "hex": "abe448",
    "flight": "UAL2056 ",
    "r": "N86534",
    "t": "B738",
    "desc": "BOEING 737-800",
    "ownOp": "UNITED AIRLINES INC",
    "year": "2016",
    "alt_baro": 21400,
    "gs": 395.8,
    "track": 310.0,
    "baro_rate": 2624,
    "squawk": "7220",
    "emergency": "none",
    "lat": 33.917309,
    "lon": -118.841114,
    "seen_pos": 0.4,
}
GROUNDED = {
    "hex": "a1b2c3",
    "flight": "AAL2301 ",
    "r": "N900AA",
    "t": "B738",
    "alt_baro": "ground",
    "gs": 12.0,
    "lat": 33.94,
    "lon": -118.40,
}


def run_tool(args, *, aircraft=None, provider="airplanes.live", geocode=None, side_effect=None):
    buffer = StringIO()
    fetch = side_effect or (lambda path: (aircraft if aircraft is not None else [], provider))
    with patch.object(sys, "argv", ["flight_status.py", json.dumps(args)]), patch(
        "flight_status.load_config"
    ), patch(
        "flight_status.fetch_adsb", side_effect=fetch
    ), patch(
        "flight_status.geocode_open_meteo", return_value=geocode
    ), redirect_stdout(buffer):
        exit_code = main()
    return exit_code, json.loads(buffer.getvalue())


class CallsignCandidateTests(unittest.TestCase):
    def test_iata_flight_number_maps_to_icao_callsign(self):
        self.assertEqual(callsign_candidates("UA2056")[0], "UAL2056")
        self.assertEqual(callsign_candidates("ua 2056")[0], "UAL2056")

    def test_spoken_airline_name_maps_to_icao_callsign(self):
        self.assertEqual(callsign_candidates("United 2056")[0], "UAL2056")
        self.assertEqual(callsign_candidates("southwest 349")[0], "SWA349")

    def test_raw_callsign_is_always_tried(self):
        self.assertIn("UAL2056", callsign_candidates("UAL2056"))

    def test_candidates_are_deduplicated(self):
        candidates = callsign_candidates("UA2056")
        self.assertEqual(len(candidates), len(set(candidates)))

    def test_unknown_airline_falls_back_to_the_literal_input(self):
        self.assertEqual(callsign_candidates("ZZ1234"), ["ZZ1234"])

    def test_blank_input_yields_no_candidates(self):
        self.assertEqual(callsign_candidates("  "), [])


class UnitConversionTests(unittest.TestCase):
    def test_compass_points_cover_the_cardinals(self):
        self.assertEqual(compass_point(0), "north")
        self.assertEqual(compass_point(90), "east")
        self.assertEqual(compass_point(180), "south")
        self.assertEqual(compass_point(270), "west")
        self.assertEqual(compass_point(359), "north")
        self.assertIsNone(compass_point(None))

    def test_haversine_matches_a_known_distance(self):
        # LAX to JFK is roughly 2144 nautical miles.
        distance = haversine_nm(33.9425, -118.408, 40.6413, -73.7781)
        self.assertAlmostEqual(distance, 2144, delta=15)


class NormalizeAircraftTests(unittest.TestCase):
    def test_airborne_record_is_converted_to_plain_units(self):
        entry = normalize_aircraft(AIRBORNE)
        self.assertEqual(entry["callsign"], "UAL2056")
        self.assertEqual(entry["airline"], "United")
        self.assertEqual(entry["altitude_ft"], 21400)
        self.assertEqual(entry["vertical_trend"], "climbing")
        self.assertEqual(entry["heading"], "northwest")
        self.assertFalse(entry["on_ground"])
        self.assertEqual(entry["map_url"], "https://globe.airplanes.live/?icao=abe448")

    def test_ground_string_altitude_becomes_an_on_ground_flag(self):
        entry = normalize_aircraft(GROUNDED)
        self.assertTrue(entry["on_ground"])
        self.assertIsNone(entry["altitude_ft"])
        self.assertEqual(entry["vertical_trend"], "on the ground")

    def test_level_flight_is_not_reported_as_climbing(self):
        entry = normalize_aircraft({**AIRBORNE, "baro_rate": 64})
        self.assertEqual(entry["vertical_trend"], "level")
        entry = normalize_aircraft({**AIRBORNE, "baro_rate": -1200})
        self.assertEqual(entry["vertical_trend"], "descending")

    def test_no_emergency_is_reported_as_none_rather_than_the_word_none(self):
        self.assertIsNone(normalize_aircraft(AIRBORNE)["emergency"])
        self.assertEqual(normalize_aircraft({**AIRBORNE, "emergency": "7700"})["emergency"], "7700")

    def test_distance_is_computed_when_the_provider_omits_it(self):
        entry = normalize_aircraft(AIRBORNE, origin=(33.9425, -118.408))
        self.assertIsNotNone(entry["distance_nm"])
        self.assertLess(entry["distance_nm"], 30)

    def test_provider_supplied_distance_wins(self):
        entry = normalize_aircraft({**AIRBORNE, "dst": 21.968, "dir": 266.6}, origin=(33.9425, -118.408))
        self.assertEqual(entry["distance_nm"], 22.0)
        self.assertEqual(entry["bearing"], "west")

    def test_unknown_operator_falls_back_to_the_registry_owner(self):
        entry = normalize_aircraft({**AIRBORNE, "flight": "XYZ123 "})
        self.assertEqual(entry["airline"], "UNITED AIRLINES INC")


class SpeechTests(unittest.TestCase):
    def test_airborne_description_reads_as_a_sentence(self):
        speech = describe_aircraft(normalize_aircraft(AIRBORNE))
        self.assertTrue(speech.startswith("United 2056 is at 21,400 feet"))
        self.assertIn("climbing", speech)
        self.assertIn("BOEING 737-800", speech)

    def test_grounded_aircraft_does_not_claim_an_altitude(self):
        speech = describe_aircraft(normalize_aircraft(GROUNDED))
        self.assertIn("on the ground", speech)
        self.assertNotIn("feet", speech)

    def test_emergency_squawk_is_called_out(self):
        speech = describe_aircraft(normalize_aircraft({**AIRBORNE, "emergency": "7700"}))
        self.assertIn("emergency", speech)


class ProviderFallbackTests(unittest.TestCase):
    def test_second_network_is_used_when_the_first_fails(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            if "airplanes.live" in url:
                raise RuntimeError("connection refused")
            return type("R", (), {"status_code": 200, "json": lambda self: {"ac": [AIRBORNE]}})()

        with patch("flight_status.http_request", side_effect=fake_request):
            aircraft, provider = flight_status.fetch_adsb("/hex/abe448")

        self.assertEqual(provider, "adsb.lol")
        self.assertEqual(len(aircraft), 1)
        self.assertEqual(len(calls), 2)

    def test_all_networks_failing_raises_with_both_reasons(self):
        with patch("flight_status.http_request", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError) as ctx:
                flight_status.fetch_adsb("/hex/abe448")
        self.assertIn("airplanes.live", str(ctx.exception))
        self.assertIn("adsb.lol", str(ctx.exception))


class ToolBehaviorTests(unittest.TestCase):
    def test_flight_lookup_returns_the_aircraft(self):
        exit_code, result = run_tool({"flight": "UA2056"}, aircraft=[AIRBORNE])
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["query_type"], "callsign")
        self.assertEqual(result["data"]["results"][0]["callsign"], "UAL2056")
        self.assertIn("limitations", result["data"])

    def test_untracked_flight_succeeds_and_explains_why(self):
        exit_code, result = run_tool({"flight": "UA2056"}, aircraft=[])
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["results_count"], 0)
        self.assertIn("not taken off yet", result["speech"])

    def test_area_search_hides_ground_traffic_by_default(self):
        _, result = run_tool(
            {"location": "Portland, OR"},
            aircraft=[AIRBORNE, GROUNDED],
            geocode=(45.52, -122.68, "Portland, Oregon, United States"),
        )
        self.assertEqual(result["data"]["results_count"], 1)
        self.assertEqual(result["data"]["airborne_count"], 1)
        self.assertFalse(result["data"]["results"][0]["on_ground"])

    def test_include_ground_keeps_parked_aircraft(self):
        _, result = run_tool(
            {"location": "Portland, OR", "include_ground": True},
            aircraft=[AIRBORNE, GROUNDED],
            geocode=(45.52, -122.68, "Portland, Oregon, United States"),
        )
        self.assertEqual(result["data"]["results_count"], 2)
        self.assertEqual(result["data"]["airborne_count"], 1)

    def test_area_results_are_ordered_by_distance(self):
        far = {**AIRBORNE, "hex": "aaa111", "flight": "FAR1 ", "lat": 47.6, "lon": -122.3}
        _, result = run_tool(
            {"location": "Portland, OR"},
            aircraft=[far, AIRBORNE],
            geocode=(45.52, -122.68, "Portland"),
        )
        distances = [entry["distance_nm"] for entry in result["data"]["results"]]
        self.assertEqual(distances, sorted(distances))

    def test_explicit_coordinates_skip_geocoding(self):
        _, result = run_tool(
            {"latitude": 45.52, "longitude": -122.68, "radius_nm": 40},
            aircraft=[AIRBORNE],
        )
        self.assertEqual(result["data"]["query_type"], "area")
        self.assertEqual(result["data"]["radius_nm"], 40)
        self.assertEqual(result["data"]["latitude"], 45.52)

    def test_radius_and_result_count_are_clamped(self):
        _, result = run_tool(
            {"latitude": 45.52, "longitude": -122.68, "radius_nm": 9000, "num_results": 500},
            aircraft=[AIRBORNE],
        )
        self.assertEqual(result["data"]["radius_nm"], 250)
        self.assertLessEqual(len(result["data"]["results"]), 20)

    def test_no_identifier_is_rejected(self):
        exit_code, result = run_tool({})
        self.assertEqual(exit_code, 1)
        self.assertIn("registration", result["error"])

    def test_unresolvable_location_is_rejected(self):
        exit_code, result = run_tool({"location": "Nowherecityxyz"}, geocode=None)
        self.assertEqual(exit_code, 1)
        self.assertIn("Could not find", result["error"])

    def test_callsign_variants_are_sent_in_one_request(self):
        paths = []

        def fake_fetch(path):
            paths.append(path)
            return [AIRBORNE], "airplanes.live"

        run_tool({"flight": "UA 2056"}, side_effect=fake_fetch)
        self.assertEqual(len(paths), 1)
        self.assertIn("UAL2056", paths[0])

    def test_network_failure_surfaces_as_an_error(self):
        def fake_fetch(path):
            raise RuntimeError("No ADS-B network responded. airplanes.live: down")

        exit_code, result = run_tool({"flight": "UA2056"}, side_effect=fake_fetch)
        self.assertEqual(exit_code, 1)
        self.assertIn("No ADS-B network responded", result["error"])


if __name__ == "__main__":
    unittest.main()
