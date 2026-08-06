#!/usr/bin/env python3
"""Regression tests for incident-aware SerpApi failure diagnostics."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import serpapi_client


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def incident(
    name="[Home Depot API] Performance Degradation",
    *,
    status="investigating",
    impact="critical",
    update="We're seeing a very low success rate on the Home Depot API.",
):
    return {
        "name": name,
        "status": status,
        "impact": impact,
        "started_at": "2026-08-01T03:25:38.316Z",
        "updated_at": "2026-08-01T03:25:38.316Z",
        "shortlink": "https://stspg.io/example",
        "components": [{"name": "Search API", "status": "major_outage"}],
        "incident_updates": [
            {
                "status": status,
                "body": update,
            }
        ],
    }


class SerpApiStatusDiagnosticTests(unittest.TestCase):
    def test_timeout_matches_active_engine_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[incident()],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                "SerpApi Home Depot search timed out.",
            )

        self.assertIsNotNone(result)
        self.assertIn("[Home Depot API] Performance Degradation", result["speech"])
        self.assertIn("very low success rate", result["speech"])
        self.assertTrue(result["data"]["retry_recommended"])
        self.assertEqual(result["data"]["failure_reason"], "active_provider_incident")
        self.assertEqual(result["data"]["serpapi_incident"]["engine"], "home_depot")

    def test_search_does_not_match_product_only_incident(self):
        product_incident = incident(name="[Home Depot Product API] Performance Degradation")
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[product_incident],
        ):
            search_result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                "Timeout",
            )
            product_result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_home_depot",
                {"product_id": "123456"},
                "Timeout",
            )

        self.assertIsNone(search_result)
        self.assertEqual(
            product_result["data"]["serpapi_incident"]["engine"],
            "home_depot_product",
        )

    def test_tripadvisor_actions_match_search_place_and_reviews_incidents(self):
        cases = (
            ({"action": "search"}, "Tripadvisor Search API", "tripadvisor"),
            ({"action": "details"}, "Tripadvisor Place API", "tripadvisor_place"),
            ({"action": "reviews"}, "Tripadvisor Reviews API", "tripadvisor_reviews"),
        )

        for arguments, incident_label, expected_engine in cases:
            with self.subTest(action=arguments["action"]), patch.object(
                serpapi_client,
                "fetch_serpapi_unresolved_incidents",
                return_value=[
                    incident(
                        name=f"[{incident_label}] Performance Degradation",
                        update=f"We are investigating the {incident_label}.",
                    )
                ],
            ):
                result = serpapi_client.diagnose_serpapi_tool_failure(
                    "serpapi_tripadvisor",
                    arguments,
                    "Tool serpapi_tripadvisor timed out",
                    force=True,
                )

            self.assertIsNotNone(result)
            self.assertEqual(
                result["data"]["serpapi_incident"]["engine"],
                expected_engine,
            )
            self.assertEqual(result["data"]["failure_reason"], "active_provider_incident")
            self.assertIn(incident_label, result["speech"])
            self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_search_index_timeout_matches_search_index_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Search Index API] Performance Degradation",
                    update="We are investigating Search Index API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_search_index",
                {"query": "PostgreSQL queues", "mode": "deep"},
                "Tool serpapi_search_index timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"], "search_index"
        )
        self.assertIn("Search Index API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_trends_timeout_matches_google_trends_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Google Trends API] Performance Degradation",
                    update="We are investigating Google Trends API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_google_trends",
                {"query": "AI agents", "data_type": "interest_over_time"},
                "Tool serpapi_google_trends timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"], "google_trends"
        )
        self.assertIn("Google Trends API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_news_light_timeout_matches_news_light_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Google News Light API] Performance Degradation",
                    update="We are investigating Google News Light API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_google_news_light",
                {"query": "agentic AI"},
                "Tool serpapi_google_news_light timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"],
            "google_news_light",
        )
        self.assertIn("Google News Light API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_shopping_light_timeout_matches_shopping_light_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Google Shopping Light API] Performance Degradation",
                    update="We are investigating Google Shopping Light API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_google_shopping_light",
                {"query": "headphones"},
                "Tool serpapi_google_shopping_light timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"],
            "google_shopping_light",
        )
        self.assertIn("Google Shopping Light API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_images_light_timeout_matches_images_light_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Google Images Light API] Performance Degradation",
                    update="We are investigating Google Images Light API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_google_images_light",
                {"query": "red Mustang"},
                "Tool serpapi_google_images_light timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"],
            "google_images_light",
        )
        self.assertIn("Google Images Light API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_local_timeout_matches_google_local_incident(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[
                incident(
                    name="[Google Local API] Performance Degradation",
                    update="We are investigating Google Local API latency.",
                )
            ],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_google_local",
                {"query": "coffee", "location": "Portland"},
                "Tool serpapi_google_local timed out",
                force=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["data"]["serpapi_incident"]["engine"],
            "google_local",
        )
        self.assertIn("Google Local API", result["speech"])
        self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_local_services_timeout_matches_direct_or_resolver_incident(self):
        cases = (
            (
                {"query": "plumber", "data_cid": "123"},
                "[Google Local Services API] Performance Degradation",
                "google_local_services",
            ),
            (
                {"query": "plumber", "location": "Phoenix"},
                "[Google Maps API] Performance Degradation",
                "google_maps",
            ),
        )
        for arguments, incident_name, expected_engine in cases:
            with self.subTest(engine=expected_engine), patch.object(
                serpapi_client,
                "fetch_serpapi_unresolved_incidents",
                return_value=[
                    incident(
                        name=incident_name,
                        update=f"We are investigating {incident_name} latency.",
                    )
                ],
            ):
                result = serpapi_client.diagnose_serpapi_tool_failure(
                    "serpapi_google_local_services",
                    arguments,
                    "Tool serpapi_google_local_services timed out",
                    force=True,
                )

            self.assertIsNotNone(result)
            self.assertEqual(
                result["data"]["serpapi_incident"]["engine"],
                expected_engine,
            )
            self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_google_trending_now_actions_match_discovery_and_news_incidents(self):
        cases = (
            (
                {"action": "trending_now", "geo": "US"},
                "Google Trends Trending Now API",
                "google_trends_trending_now",
            ),
            (
                {"action": "news", "page_token": "token"},
                "Google Trends News API",
                "google_trends_news",
            ),
        )

        for arguments, incident_label, expected_engine in cases:
            with self.subTest(action=arguments["action"]), patch.object(
                serpapi_client,
                "fetch_serpapi_unresolved_incidents",
                return_value=[
                    incident(
                        name=f"[{incident_label}] Performance Degradation",
                        update=f"We are investigating the {incident_label}.",
                    )
                ],
            ):
                result = serpapi_client.diagnose_serpapi_tool_failure(
                    "serpapi_google_trending_now",
                    arguments,
                    "Tool serpapi_google_trending_now timed out",
                    force=True,
                )

            self.assertIsNotNone(result)
            self.assertEqual(
                result["data"]["serpapi_incident"]["engine"],
                expected_engine,
            )
            self.assertIn(incident_label, result["speech"])
            self.assertIn(serpapi_client.SERPAPI_STATUS_PAGE_URL, result["speech"])

    def test_unrelated_incident_does_not_replace_original_failure(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[incident(name="[eBay Search API] Performance Degradation")],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                "Timeout",
            )

        self.assertIsNone(result)

    def test_non_transient_failure_skips_status_request(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
        ) as fetch_incidents:
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_maps_search",
                {},
                "Parameter 'query' is required.",
            )

        self.assertIsNone(result)
        fetch_incidents.assert_not_called()

    def test_status_fetch_is_public_direct_and_bounded(self):
        response = FakeResponse(payload={"incidents": [incident()]})
        with patch.object(serpapi_client, "http_request", return_value=response) as request:
            incidents = serpapi_client.fetch_serpapi_unresolved_incidents()

        self.assertEqual(len(incidents), 1)
        request.assert_called_once_with(
            "GET",
            serpapi_client.SERPAPI_UNRESOLVED_INCIDENTS_ENDPOINT,
            timeout=serpapi_client.SERPAPI_STATUS_TIMEOUT,
            use_proxy=False,
            fallback_on_proxy_fail=False,
        )

    def test_status_fetch_failure_is_silent(self):
        with patch.object(serpapi_client, "http_request", side_effect=TimeoutError("slow")):
            self.assertEqual(serpapi_client.fetch_serpapi_unresolved_incidents(), [])

    def test_flight_is_only_serpapi_backed_when_key_is_configured(self):
        with patch.object(serpapi_client, "get_config_value", return_value=""):
            self.assertEqual(serpapi_client.serpapi_engines_for_tool("flight_search", {}), ())
        with patch.object(serpapi_client, "get_config_value", return_value="x" * 20):
            self.assertEqual(
                serpapi_client.serpapi_engines_for_tool("flight_search", {}),
                ("google_flights",),
            )

    def test_force_only_bypasses_transient_text_check(self):
        with patch.object(
            serpapi_client,
            "fetch_serpapi_unresolved_incidents",
            return_value=[incident()],
        ):
            result = serpapi_client.diagnose_serpapi_tool_failure(
                "serpapi_home_depot",
                {"query": "cordless drill"},
                "Tool process stopped",
                force=True,
            )

        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
