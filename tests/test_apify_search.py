"""Search compilation is deterministic; no provider calls or operator settings."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from lib.apify_actors import actor_input
from lib.apify_actors.zillow_search import compile_search


def states(criteria):
    prepared = compile_search("maxcopell/zillow-scraper", criteria,
        location_bounds=lambda _location: {"west": -123.2, "east": -123.0, "south": 44.5, "north": 44.7})
    return prepared, [json.loads(parse_qs(urlsplit(item["url"]).query)["searchQueryState"][0])
                      for item in prepared["searchUrls"]]


def test_two_locations_compile_sale_single_family_without_invented_geography():
    prepared, rows = states({"locations": ["Albany, OR", "Lebanon, OR"],
        "listing_status": "for_sale", "property_types": ["single_family"],
        "price_min": 300000, "price_max": 600000, "max_days_on_zillow": 60,
        "results_per_location": 5})
    assert prepared["resultsLimit"] == 5
    assert [row["usersSearchTerm"] for row in rows] == ["Albany, OR", "Lebanon, OR"]
    assert all("regionSelection" not in row and "mapBounds" in row for row in rows)
    for row in rows:
        f = row["filterState"]
        assert f["price"] == {"min": 300000, "max": 600000}
        assert f["doz"] == {"value": "60"}
        assert all(f[key] == {"value": True} for key in ("fsba", "fsbo", "nc", "cmsn", "auc", "fore", "sf"))
        assert all(f[key] == {"value": False} for key in ("fr", "rs", "con", "tow", "apa", "mf", "manu", "land"))


@pytest.mark.parametrize("status,flag", [("for_rent", "fr"), ("sold", "rs")])
def test_statuses_are_mutually_exclusive_and_unspecified_types_stay_unrestricted(status, flag):
    _, rows = states({"locations": ["02108"], "listing_status": status})
    row = rows[0]
    assert row["usersSearchTerm"] == "02108"
    assert row["filterState"][flag] == {"value": True}
    assert all(row["filterState"][key] == {"value": False} for key in ("fsba", "fsbo", "nc", "cmsn", "auc", "fore"))
    assert "sf" not in row["filterState"]


@pytest.mark.parametrize("patch", [
    {"locations": []}, {"locations": ["https://internal/path"]},
    {"locations": ["Albany\nOR"]}, {"locations": [None]},
    {"listing_status": "active"}, {"property_types": ["SINGLE_FAMILY"]},
    {"price_min": 600000, "price_max": 300000}, {"price_min": True},
    {"price_max": float("inf")}, {"max_days_on_zillow": 0},
    {"results_per_location": 0}, {"results_per_location": 101}, {"unrecognized": True},
])
def test_invalid_criteria_fail_before_submission(patch):
    with pytest.raises(ValueError):
        states({"locations": ["Albany, OR"], "listing_status": "for_sale", **patch})


def test_duplicate_locations_do_not_multiply_paid_searches():
    prepared, _ = states({"locations": ["Albany, OR", "  albany,   OR  "], "listing_status": "for_sale"})
    assert len(prepared["searchUrls"]) == 1


def test_existing_generic_input_is_preserved_and_mutually_exclusive():
    raw = {"query": "requested input"}
    assert actor_input({"actor": "other/scraper", "input": raw}) is raw
    for args in ({"actor": "other/scraper"}, {"input": raw, "search": {}},
                 {"actor": "other/scraper", "search": {}}):
        with pytest.raises(ValueError):
            actor_input(args)
