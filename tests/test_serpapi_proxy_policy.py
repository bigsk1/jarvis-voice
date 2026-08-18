#!/usr/bin/env python3
"""Keep every SerpApi-backed tool on one explicit proxy-policy contract."""

import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.resolve()
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SKILLS))

import serpapi_home_depot  # noqa: E402


EXPECTED_SERPAPI_TOOLS = {
    "flight_search",
    "serpapi_ebay_product",
    "serpapi_ebay_search",
    "serpapi_home_depot",
    "serpapi_hotel_search",
    "serpapi_google_events",
    "serpapi_google_local",
    "serpapi_google_local_services",
    "serpapi_google_images_light",
    "serpapi_google_news_light",
    "serpapi_google_shopping_light",
    "serpapi_google_sports",
    "serpapi_google_trends",
    "serpapi_google_trending_now",
    "serpapi_travel_explore",
    "serpapi_maps_search",
    "serpapi_open_table_reviews",
    "serpapi_amazon_search",
    "serpapi_search_index",
    "serpapi_tripadvisor",
    "serpapi_yelp_search",
    "serpapi_youtube",
    "serpapi_youtube_search",
}


def test_every_serpapi_backed_manifest_explicitly_defaults_proxy_off():
    discovered = {}
    for manifest_path in SKILLS.glob("*.tool.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        script_name = manifest.get("script")
        if not script_name:
            continue
        script_path = SKILLS / script_name
        if not script_path.is_file():
            continue
        source = script_path.read_text(encoding="utf-8")
        if "request_serpapi(" in source:
            discovered[manifest["name"]] = manifest

    assert set(discovered) == EXPECTED_SERPAPI_TOOLS
    assert {
        name: manifest.get("proxy_policy")
        for name, manifest in discovered.items()
    } == {name: "off" for name in EXPECTED_SERPAPI_TOOLS}


def test_home_depot_request_stays_proxy_capable_behind_manifest_policy():
    with patch(
        "serpapi_home_depot.request_serpapi",
        return_value={"products": []},
    ) as request:
        serpapi_home_depot._home_depot_serpapi(
            {"engine": "home_depot", "q": "drill"}
        )

    request.assert_called_once_with(
        {"engine": "home_depot", "q": "drill"},
        timeout=serpapi_home_depot.HOME_DEPOT_SERPAPI_TIMEOUT,
    )
