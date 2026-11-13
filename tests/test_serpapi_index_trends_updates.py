"""Typed index results and per-query Trends comparisons through the real tool entrypoints."""

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

from skills import serpapi_google_trends, serpapi_search_index


def call_tool(module, arguments, payload):
    stdout = StringIO()
    request_name = "_google_trends_request" if module is serpapi_google_trends else "_search_index_request"
    with (
        patch.object(module, "load_config"),
        patch.object(module, request_name, return_value=payload) as request,
        patch.object(sys, "argv", [module.__name__, json.dumps(arguments)]),
        redirect_stdout(stdout),
    ):
        code = module.main()
    return code, json.loads(stdout.getvalue()), request


TYPED_ROWS = {
    "place": {"data_cid": "8973842359244053980", "place_id": "ChIJ-exact", "address": "Dallas, TX",
              "rating": 4.6, "reviews": 548, "gps_coordinates": {"latitude": 32.79, "longitude": -96.78}},
    "product": {"product_id": "0017450565768136224565", "price": 0, "currency": "USD", "gl": "us"},
    "video": {"video_id": "exact-video", "channel": {"name": "Coffee channel", "link": "https://example.test/channel"},
              "views": 0, "length": "2:43", "thumbnail": {"static": "https://example.test/thumb.jpg"}},
    "publication": {"result_id": "exact-publication", "publication_info": {"summary": "Author, 2024",
                    "authors": [{"name": "An Author"}]},
                    "resources": [{"file_format": "PDF", "link": "https://example.test/paper.pdf"}],
                    "inline_links": {"cited_by": {"total": 0, "cites_id": "16656356389737500750"}}},
}


@pytest.mark.parametrize("corpus", TYPED_ROWS)
def test_typed_corpa_are_real_results_with_exact_followup_handles(corpus):
    row = {"title": "Typed source", "link": "https://example.test/source", **TYPED_ROWS[corpus]}
    code, result, request = call_tool(
        serpapi_search_index, {"query": "coffee", "type": corpus},
        {serpapi_search_index.RESULT_BUCKETS[corpus]: [row]},
    )
    assert code == 0
    assert request.call_args.args[0]["type"] == corpus
    assert result["data"]["provider_results_count"] == 1
    assert result["data"]["result_type"] == corpus
    normalized = result["data"]["results"][0]
    assert normalized["url"] == row["link"]
    assert normalized["result_type"] == corpus
    for key, value in TYPED_ROWS[corpus].items():
        if key != "thumbnail":
            assert normalized[key] == value
    assert "No indexed" not in result["speech"]


def test_typed_filters_from_existing_extra_callers_are_validated_and_retained():
    code, result, request = call_tool(serpapi_search_index, {
        "query": "coffee", "extra_params": {"type": "place", "ll": "@32.7767,-96.797,14z", "radius": 25},
    }, {"place_results": []})
    assert code == 0
    assert result["data"]["filters"] == {"ll": "@32.7767,-96.797,14z", "radius": 25}
    assert request.call_args.args[0]["radius"] == 25
    assert "No indexed places" in result["speech"]


@pytest.mark.parametrize("arguments", [
    {"type": "unknown"}, {"type": "product", "ll": "32,-96"},
    {"type": "place", "radius": 10}, {"type": "place", "ll": "91,0"},
    {"type": "place", "ll": "32,-96", "radius": float("inf")},
    {"type": "place", "ll": "32,-96", "radius": 0},
    {"type": "publication", "as_ylo": 2026, "as_yhi": 2024},
    {"type": "publication", "as_ylo": 24}, {"country": "USA"},
    {"type": "product", "extra_params": {"type": "video"}},
])
def test_invalid_corpus_arguments_fail_without_a_provider_request(arguments):
    code, result, request = call_tool(serpapi_search_index, {"query": "coffee", **arguments}, {})
    assert code == 1 and result["ok"] is False
    request.assert_not_called()


def test_web_mixing_preserves_typed_zero_price_and_limits_large_details():
    rows = serpapi_search_index.extract_search_index_results({"organic_results": [{
        "title": "Indexed product", "link": "https://example.test/product", "product_id": "00012", "price": 0,
        "stores": [{"description": "x" * 10000} for _ in range(30)],
    }]})
    assert rows[0]["price"] == 0
    assert rows[0]["product_id"] == "00012"
    assert rows[0]["result_type"] == "product"
    assert rows[0]["details_truncated"] is True
    assert len(json.dumps(rows)) < 9000


@pytest.mark.parametrize("details", [
    {"stores": [{"name": "Store"} for _ in range(13)]},
    {"address": "a" * 1300},
    {"publication_info": {f"key{index}": "value" for index in range(21)}},
])
def test_field_level_index_omissions_are_reported_even_below_the_total_budget(details):
    row = serpapi_search_index.extract_search_index_results({"product_results": [{
        "title": "Product", "product_id": "00012", **details,
    }]}, result_type="product")
    assert row[0]["details_truncated"] is True


@pytest.mark.parametrize("description", ["a" * 1100, '\\"\x00🛒' * 220])
def test_total_index_envelope_budget_keeps_all_twenty_product_identities(description):
    provider_rows = [{
        "position": index + 1,
        "title": f"Indexed product {index + 1}",
        "link": f"https://example.test/product/{index}?name=%22quoted%22&market=日本",
        "product_id": f"000{index:03d}", "price": 0, "reviews": 0,
        "stores": [{
            "name": f"Merchant {merchant}",
            "link": f"https://example.test/merchant/{merchant}/product/{index}",
            "description": description,
        } for merchant in range(5)],
    } for index in range(20)]
    code, result, request = call_tool(serpapi_search_index, {
        "query": "coffee", "type": "product", "num_results": 20,
    }, {"product_results": provider_rows})

    assert code == 0 and result["ok"] is True
    request.assert_called_once()
    assert len(json.dumps(result).encode("utf-8")) <= serpapi_search_index.MAX_NORMAL_RESULT_BYTES
    data = result["data"]
    assert data["results_count"] == data["provider_results_count"] == 20
    assert data["result_details_truncated"] is True
    assert data["top_results"] == data["results"][:5]
    assert [(row["position"], row["product_id"], row["url"]) for row in data["results"]] == [
        (row["position"], row["product_id"], row["link"]) for row in provider_rows
    ]
    assert all(row["price"] == row["reviews"] == 0 for row in data["results"])
    assert any(row.get("details_truncated") for row in data["results"])
    for row in data["results"]:
        original = provider_rows[row["position"] - 1]
        assert row.get("stores", []) == original["stores"][:len(row.get("stores", []))]
    assert all(len(row["stores"]) == 5 and row["stores"][0]["description"] == description for row in provider_rows)


def test_large_web_titles_and_snippets_fit_the_same_complete_json_budget():
    rows = [{
        "title": "🛒" * 500, "snippet": '\\"\x00🛒' * 250,
        "link": f"https://example.test/article/{index}",
    } for index in range(20)]
    code, result, _ = call_tool(serpapi_search_index, {
        "query": "coffee", "num_results": 20,
    }, {"organic_results": rows})
    assert code == 0
    assert len(json.dumps(result).encode("utf-8")) <= serpapi_search_index.MAX_NORMAL_RESULT_BYTES
    assert [row["url"] for row in result["data"]["results"]] == [row["link"] for row in rows]
    assert result["data"]["result_details_truncated"] is True
    assert any(row.get("details_truncated") for row in result["data"]["results"])


def test_small_index_output_is_not_compacted_or_marked_truncated():
    provider_row = {
        "title": "Indexed product", "link": "https://example.test/product", "product_id": "00012",
        "price": 0, "stores": [{"name": "Merchant", "link": "https://example.test/merchant", "price": 0}],
    }
    code, result, _ = call_tool(serpapi_search_index, {
        "query": "coffee", "type": "product",
    }, {"product_results": [provider_row]})
    assert code == 0
    data = result["data"]
    assert "result_details_truncated" not in data
    assert "details_truncated" not in data["results"][0]
    assert data["results"][0]["stores"] == provider_row["stores"]
    assert data["top_results"] == data["results"]


def test_identity_only_oversize_returns_a_clear_error_without_partial_urls_or_rows():
    rows = [{
        "title": "Product", "product_id": f"000{index:03d}",
        "link": f"https://example.test/product/{index}?exact=" + "x" * 4000,
    } for index in range(20)]
    code, result, request = call_tool(serpapi_search_index, {
        "query": "coffee", "type": "product", "num_results": 20,
    }, {"product_results": rows})
    assert code == 1 and result["ok"] is False
    request.assert_called_once()
    assert "identities exceed the output size limit" in result["error"]
    assert "request fewer results" in result["error"]
    assert "data" not in result and len(json.dumps(result)) < 500


def test_explicit_raw_debug_output_retains_the_uncapped_provider_payload():
    payload = {"product_results": [{
        "title": "Product", "product_id": "00012", "link": "https://example.test/product",
        "stores": [{"description": "x" * 60_000}],
    }]}
    code, result, _ = call_tool(serpapi_search_index, {
        "query": "coffee", "type": "product", "include_raw": True,
    }, payload)
    assert code == 0
    assert result["data"]["raw"] == payload
    assert len(json.dumps(result).encode("utf-8")) > serpapi_search_index.MAX_NORMAL_RESULT_BYTES


def test_repeated_term_comparisons_keep_independent_dates_and_partial_tail():
    payload = {"interest_over_time": {"timeline_data": [
        {"values": [
            {"query": "coffee", "query_index": 0, "date": "Jan 1, 2025", "timestamp": "1735689600", "extracted_value": 20},
            {"query": "coffee", "query_index": 1, "date": "Feb 1, 2026", "timestamp": "1769904000", "extracted_value": 70},
        ]},
        {"values": [
            {"query": "coffee", "query_index": 0, "date": "Jan 2, 2025", "timestamp": "1735776000", "extracted_value": 25},
            {"query": "coffee", "query_index": 1, "date": "Feb 2, 2026", "timestamp": "1769990400", "extracted_value": 80},
        ]},
        {"values": [
            {"query": "coffee", "query_index": 1, "date": "Feb 3, 2026", "timestamp": "1770076800", "extracted_value": 0},
        ]},
    ]}}
    code, result, request = call_tool(serpapi_google_trends, {
        "query": ["coffee", "coffee"], "geo": ["US", "GB"],
        "date": ["2025-01-01 2025-01-02", "2026-02-01 2026-02-03"],
    }, payload)
    assert code == 0
    params = request.call_args.args[0]
    assert params["q"] == "coffee,coffee" and params["geo"] == "US,GB"
    assert params["date"] == "2025-01-01 2025-01-02,2026-02-01 2026-02-03"
    data = result["data"]
    assert data["multiple_comparisons"] is True
    first, second = data["results"]
    assert first["query_index"] == 0 and second["query_index"] == 1
    assert (first["latest_value"], second["latest_value"]) == (25, 0)
    assert (first["latest_date"], second["latest_date"]) == ("Jan 2, 2025", "Feb 3, 2026")
    assert first["geo"] == "US" and second["geo"] == "GB"
    assert data["timeline_data"][-1]["values"][0]["timestamp"] == "1770076800"
    assert "US" in first["title"] and "GB" in second["title"]


@pytest.mark.parametrize("arguments", [
    {"query": ["a", "b"], "geo": ["US", "GB", "CA"]},
    {"query": ["a", "b"], "date": ["now 7-d", "today 3-m", "all"]},
    {"query": ["a", "b"], "data_type": "compared_by_region", "geo": "US,GB"},
    {"query": "a", "geo": []}, {"query": "a", "date": []},
])
def test_invalid_comparison_alignment_is_rejected_before_network(arguments):
    code, result, request = call_tool(serpapi_google_trends, arguments, {})
    assert code == 1 and result["ok"] is False
    request.assert_not_called()


@pytest.mark.parametrize("query", ["coffee", ["coffee"]])
def test_one_topic_broadcasts_across_regions_in_one_request_with_neutral_interpretation(query):
    payload = {"interest_over_time": {"timeline_data": [{"date": "Nov 13, 2026", "values": [
        {"query": "coffee", "query_index": 0, "extracted_value": 57},
        {"query": "coffee", "query_index": 1, "extracted_value": 36},
    ]}]}}
    code, result, request = call_tool(serpapi_google_trends, {
        "query": query, "geo": ["US", "GB"], "date": "now 7-d",
    }, payload)
    assert code == 0
    request.assert_called_once()
    params = request.call_args.args[0]
    assert params["q"] == "coffee,coffee" and params["geo"] == "US,GB" and params["date"] == "now 7-d"
    data = result["data"]
    assert data["queries"] == ["coffee", "coffee"] and data["results_count"] == 2
    assert [(row["query_index"], row["geo"], row["latest_value"]) for row in data["results"]] == [
        (0, "US", 57), (1, "GB", 36),
    ]
    note = data["interpretation_note"]
    assert "normalized relative search interest (0–100)" in note
    assert "not absolute search counts" in note and "equal regional scores" in note
    assert note in result["speech"] and "independently" not in result["speech"]


@pytest.mark.parametrize("dates", [
    ["2025-01-01 2025-01-07", "2026-01-01 2026-01-07"],
    ["2025-01-01T00 2025-01-08T00", "2026-01-01T00 2026-01-08T00"],
])
def test_one_topic_broadcasts_custom_periods_and_pairs_regions_positionally(dates):
    code, result, request = call_tool(serpapi_google_trends, {
        "query": "coffee", "geo": ["US", "GB"], "date": dates,
    }, {})
    assert code == 0
    request.assert_called_once()
    assert request.call_args.args[0]["q"] == "coffee,coffee"
    assert request.call_args.args[0]["date"] == ",".join(dates)
    assert [(row["query"], row["date"], row["geo"]) for row in result["data"]["comparisons"]] == [
        ("coffee", dates[0], "US"), ("coffee", dates[1], "GB"),
    ]
    assert len(result["data"]["comparisons"]) == 2


def test_one_region_broadcasts_and_single_worldwide_hourly_scope_stays_supported():
    dates = ["2025-02-28 2025-03-01", "2026-02-28 2026-03-01"]
    code, result, request = call_tool(serpapi_google_trends, {
        "query": "coffee", "geo": "US", "date": dates,
    }, {})
    assert code == 0 and request.call_args.args[0]["geo"] == "US"
    assert [row["geo"] for row in result["data"]["comparisons"]] == ["US", "US"]
    code, result, request = call_tool(serpapi_google_trends, {
        "query": ["coffee", "tea"], "geo": "Worldwide", "date": "2024-02-29T00 2024-03-01T23",
    }, {})
    assert code == 0 and "geo" not in request.call_args.args[0]
    assert request.call_args.args[0]["q"] == "coffee,tea"
    assert result["data"]["geo"] == "Worldwide"


def test_five_region_shortcut_keeps_all_five_positional_slots():
    regions = ["US", "GB", "CA", "AU", "NZ"]
    code, result, request = call_tool(serpapi_google_trends, {"query": "coffee", "geo": regions}, {})
    assert code == 0 and request.call_count == 1
    assert request.call_args.args[0]["q"] == ",".join(["coffee"] * 5)
    assert [row["geo"] for row in result["data"]["comparisons"]] == regions


@pytest.mark.parametrize("arguments, message", [
    ({"geo": ["US", "GB"], "date": ["2025-01-01 2025-01-07"] * 3}, "comparison slot"),
    ({"geo": ["US", "GB", "CA", "AU", "NZ", "JP"]}, "at most 5"),
    ({"geo": ["US", ""]}, "Worldwide"),
    ({"geo": ["Worldwide", "GB"]}, "Worldwide"),
    ({"geo": "US,Worldwide"}, "Worldwide"),
    ({"date": ["now 7-d", "today 3-m"]}, "custom"),
    ({"date": ["2025-01-01 2025-01-07", "now 7-d"]}, "custom"),
    ({"date": ["2025-01-01 2025-01-07", "2026-01-01T00 2026-01-07T00"]}, "same"),
    ({"date": "2026-02-30 2026-03-01"}, "valid calendar"),
    ({"date": "2025-02-29 2025-03-01"}, "valid calendar"),
    ({"date": "2026-03-02 2026-03-01"}, "precede"),
    ({"date": "2026-01-01T24 2026-01-02T00"}, "hours"),
    ({"date": "2026-01-01T23 2026-01-01T22"}, "precede"),
    ({"date": "2026-01-01T00 2026-01-08T01"}, "one week"),
    ({"date": "2026-01-01 2026-01-02T00"}, "both"),
    ({"data_type": "related_queries", "geo": ["US", "GB"]}, "interest_over_time"),
])
def test_unsupported_comparison_and_calendar_shapes_fail_before_any_provider_request(arguments, message):
    code, result, request = call_tool(serpapi_google_trends, {"query": "coffee", **arguments}, {})
    assert code == 1 and result["ok"] is False and message in result["error"]
    request.assert_not_called()


def test_rising_percentages_do_not_receive_the_zero_to_hundred_interest_note():
    code, result, _ = call_tool(serpapi_google_trends, {
        "query": "coffee", "data_type": "related_queries",
    }, {"related_queries": {"rising": [{"query": "coffee near me", "value": "+2300%", "extracted_value": 2300}]}})
    assert code == 0 and result["data"]["results"][0]["extracted_value"] == 2300
    assert "interpretation_note" not in result["data"] and "0–100" not in result["speech"]


@pytest.mark.parametrize("view, query", [("interest_by_region", "coffee"), ("compared_by_region", ["coffee", "tea"])])
def test_regional_relative_interest_has_the_neutral_interpretation_note(view, query):
    code, result, request = call_tool(serpapi_google_trends, {"query": query, "data_type": view}, {})
    assert code == 0 and request.call_count == 1
    assert "normalized relative search interest (0–100)" in result["data"]["interpretation_note"]
    assert result["data"]["interpretation_note"] in result["speech"]
