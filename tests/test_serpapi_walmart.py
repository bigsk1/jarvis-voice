"""Walmart search/product contracts with controlled store localization and transport."""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import serpapi_walmart as walmart  # noqa: E402
import serpapi_walmart_product as product_tool  # noqa: E402
import serpapi_walmart_search as search_tool  # noqa: E402
from tool_child_environment import restrict_child_environment  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


def product_row(index=1):
    return {
        "product_id": f"ABCDEF{index:06d}", "us_item_id": str(100000000 + index),
        "title": f"Fixture product {index}", "description": "A useful product description.",
        "product_page_url": f"https://www.walmart.com/ip/fixture-product/{100000000 + index}",
        "thumbnail": "https://i5.walmartimages.com/fixture.jpg",
        "rating": 4.5, "reviews": 12, "seller_id": "fixture-seller", "seller_name": "Walmart",
        "two_day_shipping": False, "sponsored": False,
        "primary_offer": {"offer_price": 12.5, "currency": "USD"},
    }


def search_payload(count=2):
    return {
        "search_metadata": {"id": "walmart-search-fixture", "status": "Success", "cached": False},
        "search_parameters": {"engine": "walmart", "query": "coffee", "store_id": "3081"},
        "search_information": {
            "query_displayed": "coffee", "total_results": 1234,
            "location": {"postal_code": "95829", "city": "Sacramento",
                         "province_code": "CA", "store_id": "3081"},
        },
        "organic_results": [product_row(i) for i in range(1, count + 1)],
    }


def product_payload():
    row = product_row()
    row.update({
        "price_map": {"price": 9.99, "currency": "USD", "was_price": {"price": 12.5}},
        "in_stock": False, "rating": 0, "reviews": 0,
        "short_description_html": "<p>Useful <strong>description</strong>.</p>",
        "images": ["https://i5.walmartimages.com/large.jpg"],
        "shipping_option": {"available": False}, "pickup_option": {"available": False},
        "delivery_option": {"available": True, "price": "0.00", "location": "Sacramento, 95829"},
    })
    return {
        "search_metadata": {"id": "walmart-product-fixture", "status": "Success", "cached": False},
        "search_parameters": {"engine": "walmart_product", "product_id": row["product_id"]},
        "search_information": search_payload()["search_information"],
        "product_result": row,
    }


@pytest.fixture(autouse=True)
def isolated_tools(monkeypatch):
    values = {}
    monkeypatch.setattr(walmart, "get_config_value", lambda key, default="": values.get(key, default))
    monkeypatch.setattr(walmart, "http_request", Mock(
        side_effect=AssertionError("Unexpected store lookup"),
    ))
    for tool in (search_tool, product_tool):
        monkeypatch.setattr(tool, "load_config", lambda: None)
        monkeypatch.setattr(tool, "request_serpapi", Mock(
            side_effect=AssertionError("Unexpected paid provider request"),
        ))
    return values


def provider(monkeypatch, tool, payload):
    request = Mock(return_value=deepcopy(payload))
    monkeypatch.setattr(tool, "request_serpapi", request)
    return request


def run_main(monkeypatch, capsys, tool, arguments):
    monkeypatch.setattr(sys, "argv", [tool.__name__ + ".py", json.dumps(arguments)])
    code = tool.main()
    return code, json.loads(capsys.readouterr().out)


def test_search_uses_documented_engine_filters_and_bounded_provider_request(monkeypatch, capsys):
    request = provider(monkeypatch, search_tool, search_payload())
    code, result = run_main(monkeypatch, capsys, search_tool, {
        "query": "coffee", "sort_by": "price_low", "min_price": 0, "max_price": 25,
        "page": 2, "facet": "brand:Fixture||condition:New", "soft_sort": False,
        "store_id": "3081", "no_cache": False,
    })
    assert code == 0 and result["ok"] is True
    params = request.call_args.args[0]
    assert params["engine"] == "walmart" and params["query"] == "coffee"
    assert params["sort"] == "price_low" and "sort_by" not in params
    assert params["min_price"] == 0 and params["max_price"] == 25
    assert params["page"] == 2 and params["store_id"] == "3081"
    assert params["facet"] == "brand:Fixture||condition:New"
    assert params["soft_sort"] == "false" and params["no_cache"] == "false"
    assert request.call_args.kwargs["timeout"] == 60
    assert request.call_args.kwargs["max_response_bytes"] == 2 * 1024 * 1024
    assert request.call_count == 1
    walmart.http_request.assert_not_called()


def test_category_only_search_avoids_inventing_query(monkeypatch, capsys):
    request = provider(monkeypatch, search_tool, search_payload())
    code, result = run_main(monkeypatch, capsys, search_tool, {"cat_id": "976759_976787"})
    assert code == 0 and result["ok"] is True
    assert request.call_args.args[0]["cat_id"] == "976759_976787"
    assert not request.call_args.args[0].get("query")


@pytest.mark.parametrize(("value", "expected"), [(0, 1), (1, 1), (100, 10)])
def test_search_clamps_result_count_without_multiplying_provider_calls(
    monkeypatch, capsys, value, expected,
):
    request = provider(monkeypatch, search_tool, search_payload(12))
    code, result = run_main(monkeypatch, capsys, search_tool, {
        "query": "coffee", "num_results": value,
    })
    assert code == 0 and result["ok"] is True
    assert len(result["data"]["results"]) == expected
    assert request.call_count == 1


@pytest.mark.parametrize("arguments", [
    {}, {"query": ""}, {"query": []}, {"cat_id": {}}, {"page": 0}, {"page": 101},
    {"min_price": -1}, {"min_price": 25, "max_price": 5}, {"sort_by": "random"},
    {"soft_sort": "false"}, {"no_cache": "false"}, {"store_id": "../../private"},
    {"postal_code": "not-a-ZIP"}, {"walmart_domain": "walmart.com.attacker.test"},
    {"extra_params": {"engine": "google"}}, {"engine": "google"}, {"raw": True},
])
def test_invalid_search_input_fails_before_network(monkeypatch, capsys, arguments):
    inputs = {"query": "coffee", **arguments} if arguments else {}
    code, result = run_main(monkeypatch, capsys, search_tool, inputs)
    assert code == 1 and result["ok"] is False
    search_tool.request_serpapi.assert_not_called()
    walmart.http_request.assert_not_called()


@pytest.mark.parametrize(("identifier", "expected"), [
    ("ABCDEF000001", "ABCDEF000001"), ("147423982", "147423982"),
    ("https://www.walmart.com/ip/Fixture-product/147423982", "147423982"),
    ("https://walmart.com/ip/147423982?selectedSellerId=0", "147423982"),
])
def test_product_accepts_provider_ids_item_ids_and_walmart_product_urls(
    monkeypatch, capsys, identifier, expected,
):
    request = provider(monkeypatch, product_tool, product_payload())
    code, result = run_main(monkeypatch, capsys, product_tool, {"product_id": identifier})
    assert code == 0 and result["ok"] is True
    params = request.call_args.args[0]
    assert params["engine"] == "walmart_product" and params["product_id"] == expected
    assert params["no_cache"] == "false"
    assert request.call_args.kwargs["timeout"] == 60
    assert request.call_args.kwargs["max_response_bytes"] == 2 * 1024 * 1024
    assert request.call_count == 1


@pytest.mark.parametrize("identifier", [
    "", None, [], "../123", "file:///etc/passwd", "https://example.org/ip/123",
    "https://walmart.com.attacker.test/ip/123", "https://user:secret@www.walmart.com/ip/123",
    "https://www.walmart.com/search?q=coffee", "http://127.0.0.1/ip/123",
    "https://www.walmart.com\\@example.org/ip/123",
])
def test_product_rejects_invalid_or_disguised_walmart_ids_before_network(
    monkeypatch, capsys, identifier,
):
    code, result = run_main(monkeypatch, capsys, product_tool, {"product_id": identifier})
    assert code == 1 and result["ok"] is False
    product_tool.request_serpapi.assert_not_called()
    walmart.http_request.assert_not_called()


@pytest.mark.parametrize("tool", [search_tool, product_tool])
@pytest.mark.parametrize("arguments", [None, [], "text", 123])
def test_non_object_json_has_one_failure_envelope_without_network(monkeypatch, capsys, tool, arguments):
    code, result = run_main(monkeypatch, capsys, tool, arguments)
    assert code == 1 and result["ok"] is False
    tool.request_serpapi.assert_not_called()


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_provider_errors_are_not_reported_as_empty_success_or_retried(monkeypatch, capsys, tool):
    request = Mock(side_effect=RuntimeError("SerpApi request failed with HTTP 401."))
    monkeypatch.setattr(tool, "request_serpapi", request)
    arguments = {"query": "coffee"} if tool is search_tool else {"product_id": "147423982"}
    code, result = run_main(monkeypatch, capsys, tool, arguments)
    assert code == 1 and result["ok"] is False and "401" in result["error"]
    assert request.call_count == 1


class StoreResponse:
    def __init__(self, payload, *, raw=None, status=200):
        self.body = raw if raw is not None else json.dumps(payload).encode()
        self.status = status
        self.closed = False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"HTTP {self.status}")

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


def directory(monkeypatch, payload, **kwargs):
    response = StoreResponse(payload, **kwargs)
    request = Mock(return_value=response)
    monkeypatch.setattr(walmart, "http_request", request)
    return request, response


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_explicit_store_beats_configured_store_and_postal_defaults_without_lookup(
    isolated_tools, monkeypatch, capsys, tool,
):
    isolated_tools.update(JARVIS_WALMART_STORE_ID="100", JARVIS_DEFAULT_POSTAL_CODE="10001")
    payload = search_payload() if tool is search_tool else product_payload()
    request = provider(monkeypatch, tool, payload)
    arguments = {"query": "coffee"} if tool is search_tool else {"product_id": "147423982"}
    code, result = run_main(monkeypatch, capsys, tool, {**arguments, "store_id": "3081"})
    assert code == 0 and result["ok"] is True
    assert request.call_args.args[0]["store_id"] == "3081"
    assert result["data"]["location_context"]["source"] == "explicit_store"
    assert result["data"]["location_context"]["requested_postal_code"] == "10001"
    assert result["data"]["search_information"]["location"]["store_id"] == "3081"
    walmart.http_request.assert_not_called()


def test_explicit_zip_overrides_configured_store_and_maps_only_exact_us_zip(
    isolated_tools, monkeypatch,
):
    isolated_tools.update(JARVIS_WALMART_STORE_ID="999", JARVIS_DEFAULT_POSTAL_CODE="10001")
    request, response = directory(monkeypatch, [
        {"store_id": "100", "postal_code": "95829", "address": "South Sacramento, CA, US"},
        {"store_id": "20", "postal_code": "95829", "address": "Sacramento, CA, US"},
        {"store_id": "1", "postal_code": "95828", "address": "Nearby Sacramento, CA, US"},
        {"store_id": "2", "postal_code": "95829", "country": "MX", "address": "Mexico"},
        {"store_id": "3", "postal_code": "95829", "country": None, "address": "Somewhere, MX"},
        {"store_id": "not-an-id", "postal_code": "95829", "address": "Broken record"},
    ])
    location = walmart.resolve_location({"postal_code": "95829-1234"})
    assert location["store_id"] == "20" and location["source"] == "postal_code"
    assert location["requested_postal_code"] == "95829-1234"
    assert location["store_address"] == "Sacramento, CA, US" and location["matching_stores"] == 2
    assert request.call_args.args == ("GET", "https://serpapi.com/walmart-stores.json")
    assert request.call_args.kwargs["timeout"] == 10 and request.call_args.kwargs["stream"] is True
    assert not request.call_args.kwargs.get("params")
    assert "Authorization" not in request.call_args.kwargs.get("headers", {})
    assert response.closed is True


def test_configured_store_precedes_configured_postal_without_directory_lookup(isolated_tools):
    isolated_tools.update(JARVIS_WALMART_STORE_ID="3081", JARVIS_DEFAULT_POSTAL_CODE="95829")
    location = walmart.resolve_location({})
    assert location["store_id"] == "3081" and location["source"] == "configured_store"
    walmart.http_request.assert_not_called()


def test_configured_zip_is_used_when_no_store_is_selected(isolated_tools, monkeypatch):
    isolated_tools["JARVIS_DEFAULT_POSTAL_CODE"] = "95829"
    directory(monkeypatch, [{"store_id": "3081", "postal_code": "95829"}])
    location = walmart.resolve_location({})
    assert location["store_id"] == "3081" and location["requested_postal_code"] == "95829"
    assert location["source"] == "postal_code"


def test_unmatched_zip_never_selects_nearby_store_and_keeps_provider_location_truthful(
    monkeypatch, capsys,
):
    directory(monkeypatch, [{"store_id": "10", "postal_code": "95828"}])
    request = provider(monkeypatch, search_tool, search_payload())
    code, result = run_main(monkeypatch, capsys, search_tool, {
        "query": "coffee", "postal_code": "95829",
    })
    assert code == 0 and result["ok"] is True
    assert "store_id" not in request.call_args.args[0]
    location = result["data"]["location_context"]
    assert location["store_id"] is None and location["source"] == "provider_default"
    assert location["requested_postal_code"] == "95829"
    assert "not applied" in location["note"] and "not applied" in result["speech"]
    assert result["data"]["search_information"]["location"]["postal_code"] == "95829"


@pytest.mark.parametrize("failure", ["network", "http", "invalid", "oversized"])
def test_directory_failures_are_bounded_closed_and_do_not_expose_exception_details(
    monkeypatch, failure,
):
    response = None
    if failure == "network":
        monkeypatch.setattr(walmart, "http_request", Mock(side_effect=requests.ConnectionError(
            "PRIVATE_LOOKUP_ERROR_SENTINEL api_key=private-token",
        )))
    elif failure == "http":
        _request, response = directory(monkeypatch, [], status=503)
    elif failure == "invalid":
        _request, response = directory(monkeypatch, {}, raw=b"not JSON")
    else:
        _request, response = directory(monkeypatch, [], raw=b"x" * (2 * 1024 * 1024 + 1))
    location = walmart.resolve_location({"postal_code": "95829"})
    assert location["store_id"] is None and location["source"] == "provider_default"
    assert "not applied" in location["note"]
    assert "PRIVATE_LOOKUP_ERROR_SENTINEL" not in json.dumps(location)
    assert "private-token" not in json.dumps(location)
    if response:
        assert response.closed is True


def test_mexico_does_not_inherit_us_store_or_zip_defaults(isolated_tools, monkeypatch, capsys):
    isolated_tools.update(JARVIS_WALMART_STORE_ID="3081", JARVIS_DEFAULT_POSTAL_CODE="95829")
    request = provider(monkeypatch, search_tool, search_payload())
    code, result = run_main(monkeypatch, capsys, search_tool, {
        "query": "coffee", "walmart_domain": "walmart.com.mx", "sort_by": "price_low",
    })
    assert code == 0 and result["ok"] is True
    params = request.call_args.args[0]
    assert params["walmart_domain"] == "walmart.com.mx" and params["sort"] == "price_low"
    assert "store_id" not in params and "soft_sort" not in params
    assert result["data"]["country"] == "mx"
    assert result["data"]["location_context"]["requested_postal_code"] is None
    walmart.http_request.assert_not_called()


@pytest.mark.parametrize("options", [
    {"cat_id": "976759_976787"}, {"sort_by": "rating_high"}, {"sort_by": "best_seller"},
    {"sort_by": "new"}, {"soft_sort": False}, {"next_day": True}, {"postal_code": "95829"},
])
def test_unsupported_mexico_filters_fail_before_provider_request(monkeypatch, capsys, options):
    code, result = run_main(monkeypatch, capsys, search_tool, {
        "query": "coffee", "walmart_domain": "walmart.com.mx", **options,
    })
    assert code == 1 and result["ok"] is False
    search_tool.request_serpapi.assert_not_called()
    walmart.http_request.assert_not_called()


def test_search_normalizes_offers_and_preserves_zero_and_false_fields(monkeypatch, capsys):
    payload = search_payload()
    payload["organic_results"][0].update(rating=0, reviews=0, quantity=0, sponsored=False)
    payload["organic_results"][0]["primary_offer"]["offer_price"] = 0
    payload["organic_results"][1].pop("primary_offer")
    provider(monkeypatch, search_tool, payload)
    code, result = run_main(monkeypatch, capsys, search_tool, {"query": "coffee"})
    assert code == 0 and result["ok"] is True
    first, second = result["data"]["results"]
    assert first["product_id"] == "ABCDEF000001" and first["us_item_id"] == "100000001"
    assert first["url"] == product_row()["product_page_url"]
    assert first["price"] == 0 and first["rating"] == 0 and first["reviews"] == 0
    assert first["quantity"] == 0 and first["sponsored"] is False
    assert first["two_day_shipping"] is False
    assert first["currency"] == "USD" and first["price_formatted"]
    assert second.get("price") is None and second.get("price_formatted") is None
    assert result["data"]["top_product_id"] == first["product_id"]


def test_product_keeps_detail_offer_fulfillment_and_reviews_without_losing_false_values(
    monkeypatch, capsys,
):
    payload = product_payload()
    payload["reviews_results"] = {"ratings": [{"stars": 1, "count": 0}],
                                  "reviews": [{"title": "Specific experience", "text": "Useful detail."}]}
    provider(monkeypatch, product_tool, payload)
    code, result = run_main(monkeypatch, capsys, product_tool, {"product_id": "ABCDEF000001"})
    assert code == 0 and result["ok"] is True
    detail = result["data"]["product_summary"]
    assert detail == result["data"]["results"][0]
    assert detail["price"] == 9.99 and detail["price_was"] == {"price": 12.5}
    assert detail["rating"] == 0 and detail["reviews"] == 0 and detail["in_stock"] is False
    assert detail["shipping_option"]["available"] is False
    assert detail["pickup_option"]["available"] is False
    assert detail["delivery_option"]["price"] == "0.00"
    assert detail["image_url"] == "https://i5.walmartimages.com/large.jpg"
    assert detail["description"] == "Useful description."
    assert result["data"]["reviews_results"] == payload["reviews_results"]


def test_description_parser_keeps_readable_text_and_discards_scripts_and_styles():
    assert walmart.description_text(
        "<p>Useful &amp; clear.</p><script>SECRET_SCRIPT_SENTINEL</script>"
        "<style>SECRET_STYLE_SENTINEL</style><p>Next <b>paragraph</b>.</p>",
    ) == "Useful & clear.\nNext paragraph."


def test_search_empty_results_are_explicit_success_and_detail_missing_product_is_failure(
    monkeypatch, capsys,
):
    provider(monkeypatch, search_tool, {"organic_results": []})
    code, result = run_main(monkeypatch, capsys, search_tool, {"query": "unavailable"})
    assert code == 0 and result["ok"] is True
    assert result["data"]["results_count"] == 0 and result["data"]["results"] == []
    assert "No Walmart products" in result["speech"]
    provider(monkeypatch, product_tool, {"product_result": {}})
    code, result = run_main(monkeypatch, capsys, product_tool, {"product_id": "147423982"})
    assert code == 1 and result["ok"] is False and "No product_result" in result["error"]


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_malformed_provider_response_returns_one_json_failure(monkeypatch, capsys, tool):
    provider(monkeypatch, tool, ["unexpected-list"])
    arguments = {"query": "coffee"} if tool is search_tool else {"product_id": "147423982"}
    code, result = run_main(monkeypatch, capsys, tool, arguments)
    assert code == 1 and result["ok"] is False


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_manifests_use_restricted_selected_key_and_localization_only(tool):
    path = ROOT / "skills" / f"{tool.__name__}.tool.json"
    manifest = json.loads(path.read_text())
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["proxy_policy"] == "off"
    assert manifest["parameters"]["additionalProperties"] is False
    schema = ToolSchema.from_json_file(str(path))
    assert schema.child_environment_names == frozenset({
        "SERP_API_KEY", "JARVIS_WALMART_STORE_ID", "JARVIS_DEFAULT_POSTAL_CODE",
    })
    child = restrict_child_environment({
        "PATH": "/usr/bin", "JARVIS_MODE": "cloud", "SERP_API_KEY": "mode-key",
        "JARVIS_OVERRIDE_SERP_API_KEY": "selected-key", "JARVIS_WALMART_STORE_ID": "3081",
        "JARVIS_DEFAULT_POSTAL_CODE": "95829", "OPENAI_API_KEY": "unrelated-secret",
    }, schema.child_environment_names, home="/tmp/jarvis-walmart-test", proxy_policy="off")
    assert child["SERP_API_KEY"] == "selected-key"
    assert child["JARVIS_WALMART_STORE_ID"] == "3081"
    assert child["JARVIS_DEFAULT_POSTAL_CODE"] == "95829"
    assert "OPENAI_API_KEY" not in child


def search_context_data():
    results = []
    for position in range(1, 11):
        row = walmart.normalize_product(product_row(position))
        row.update(position=position, description="Useful product facts. " * 1200)
        results.append(row)
    results[0].update(rating=0, reviews=0, sponsored=False, in_stock=False)
    results[1].update(price=None, price_formatted=None)
    return walmart.result_data(search_payload(10), results, {
        "store_id": "3081", "source": "explicit_store", "requested_postal_code": "95829",
    }, "walmart")


def product_context_data():
    payload = product_payload()
    payload["reviews_results"] = {"reviews": {
        "rating": 0, "count": 0, "recommended_percentage": 0,
        "top_positive": {"title": "Positive evidence", "text": "POSITIVE_REVIEW_SENTINEL " * 500,
                         "rating": 5},
        "top_negative": {"title": "Negative evidence", "text": "NEGATIVE_REVIEW_SENTINEL " * 500,
                         "rating": 1},
        "customer_reviews": [{"text": "Customer detail. " * 1000, "rating": 0} for _ in range(8)],
    }, "ratings": [{"stars": 1, "count": 0}, {"stars": 5, "count": 4}]}
    row = walmart.normalize_product(payload["product_result"], detail=True)
    row["position"] = 1
    data = walmart.result_data(payload, [row], {"store_id": "3081", "source": "explicit_store"},
                               "walmart_product")
    data.update(product_summary=row, product_id=row["product_id"],
                reviews_results=payload["reviews_results"])
    return data


@pytest.fixture
def assembler():
    from orchestrator.context_assembler import ContextAssembler

    fixed_now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    return ContextAssembler(
        timezone_obj=ZoneInfo("UTC"), auto_context_window=8, auto_context_minutes=180,
        safe_iso_to_local_datetime=lambda _value: None,
        format_age_seconds=lambda _value: "unknown",
        format_gap_for_prompt=lambda _value: "unknown",
        conversation_has_text_summary_for_ref=lambda _history, _ref: False,
        stash_ref_from_result=lambda _result, _arguments: "",
        get_memory_db_fn=Mock(side_effect=AssertionError("Unexpected memory database read")),
        now_utc_fn=lambda: fixed_now, parse_utc_timestamp_fn=lambda _value: fixed_now,
    )


def assert_search_identities(projected):
    assert projected["store_id"] == "3081"
    assert projected["location_context"]["store_id"] == "3081"
    assert len(projected["candidates"]) == 10
    for position, row in enumerate(projected["candidates"], 1):
        assert row["position"] == position
        assert row["product_id"] == f"ABCDEF{position:06d}"
        assert row["us_item_id"] == str(100000000 + position)
        assert row["url"] == product_row(position)["product_page_url"]
    first, second = projected["candidates"][:2]
    assert first["rating"] == 0 and first["reviews"] == 0
    assert first["sponsored"] is False and first["in_stock"] is False
    assert second["price"] is None and second["price_formatted"] is None


def test_shared_context_projector_keeps_all_ten_shopping_handles_and_missing_values():
    from lib.serpapi_walmart_context import project_walmart_data

    data = search_context_data()
    original = deepcopy(data)
    projected = project_walmart_data(data, max_chars=9000)
    assert len(json.dumps(projected, ensure_ascii=False)) <= 9000
    assert projected["context_truncated"] is True
    assert_search_identities(projected)
    assert data == original


def test_immediate_context_preserves_all_ten_ordered_products_after_optional_detail_compaction(assembler):
    result = {"ok": True, "speech": "Found ten Walmart products.", "data": search_context_data()}
    original = deepcopy(result)
    rendered, total, shown, truncated = assembler.build_llm_result_context_preview(
        "serpapi_walmart_search", result,
    )
    payload = json.loads(rendered)
    assert shown == len(rendered) <= 10000 and total > shown
    assert truncated is True and payload["data"]["context_truncated"] is True
    assert_search_identities(payload["data"])
    assert result == original


def test_native_continuation_preserves_ordered_products_store_and_valid_json(assembler):
    result = {"ok": True, "data": search_context_data()}
    message, metadata = assembler.build_provider_tool_result_message(
        tool_name="serpapi_walmart_search", arguments={"query": "coffee", "num_results": 10},
        result=result, max_chars=6000,
    )
    assert len(message) <= 6000
    payload = json.loads(message.split("\nResult:\n", 1)[1])
    assert "result_preview_text" not in payload
    assert payload["result_truncated"] is True and metadata["result_truncated"] is True
    assert_search_identities(payload["result"]["data"])


@pytest.mark.parametrize("budget", [9000, 6000])
def test_product_projector_keeps_positive_and_negative_review_evidence_with_explicit_omissions(budget):
    from lib.serpapi_walmart_context import project_walmart_data

    data = product_context_data()
    projected = project_walmart_data(data, max_chars=budget)
    assert len(json.dumps(projected, ensure_ascii=False)) <= budget
    assert projected["context_truncated"] is True
    assert projected["store_id"] == "3081"
    assert projected["candidates"][0]["us_item_id"] == "100000001"
    assert projected["candidates"][0]["in_stock"] is False
    assert projected["reviews"]["rating"] == 0 and projected["reviews"]["count"] == 0
    assert projected["reviews"]["recommended_percentage"] == 0
    assert "POSITIVE_REVIEW_SENTINEL" in projected["reviews"]["top_positive"]["text"]
    assert "NEGATIVE_REVIEW_SENTINEL" in projected["reviews"]["top_negative"]["text"]
    assert projected["ratings"][0]["count"] == 0


@pytest.mark.parametrize("surface", ["immediate", "native"])
def test_product_model_context_preserves_both_review_views_and_false_stock(assembler, surface):
    result = {"ok": True, "data": product_context_data()}
    if surface == "immediate":
        rendered, _total, shown, truncated = assembler.build_llm_result_context_preview(
            "serpapi_walmart_product", result,
        )
        payload = json.loads(rendered)
        assert shown == len(rendered) <= 10000 and truncated is True
    else:
        message, metadata = assembler.build_provider_tool_result_message(
            tool_name="serpapi_walmart_product", arguments={"product_id": "ABCDEF000001"},
            result=result, max_chars=6000,
        )
        assert len(message) <= 6000
        payload = json.loads(message.split("\nResult:\n", 1)[1])["result"]
        assert metadata["result_truncated"] is True
    data = payload["data"]
    assert data["store_id"] == "3081" and data["candidates"][0]["in_stock"] is False
    assert data["candidates"][0]["rating"] == 0 and data["candidates"][0]["reviews"] == 0
    assert "POSITIVE_REVIEW_SENTINEL" in data["reviews"]["top_positive"]["text"]
    assert "NEGATIVE_REVIEW_SENTINEL" in data["reviews"]["top_negative"]["text"]


def test_projected_product_reviews_and_truncation_notice_survive_a_second_context_handoff():
    from lib.serpapi_walmart_context import project_walmart_data

    first = project_walmart_data(product_context_data(), max_chars=9000)
    second = project_walmart_data(first, max_chars=9000)
    assert second == first
    assert second["context_truncated"] is True
    assert "POSITIVE_REVIEW_SENTINEL" in second["reviews"]["top_positive"]["text"]
    assert "NEGATIVE_REVIEW_SENTINEL" in second["reviews"]["top_negative"]["text"]


def test_saved_history_and_accumulated_context_keep_tenth_product_and_balanced_reviews(assembler):
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    saved = followup.extract_followup_data({
        "serpapi_walmart_search": {"ok": True, "data": search_context_data()},
        "serpapi_walmart_product": {"ok": True, "data": product_context_data()},
    })
    persisted = json.loads(json.dumps(saved))
    assert_search_identities(persisted["serpapi_walmart_search"])
    detail = persisted["serpapi_walmart_product"]
    reviews = detail.get("reviews") or detail.get("reviews_results", {}).get("reviews", {})
    assert "POSITIVE_REVIEW_SENTINEL" in reviews["top_positive"]["text"]
    assert "NEGATIVE_REVIEW_SENTINEL" in reviews["top_negative"]["text"]
    context = assembler.format_conversation_context("Open the tenth product at the same store.", [{
        "role": "assistant", "content": "Found ten products and checked one.",
        "tools_used": ["serpapi_walmart_search", "serpapi_walmart_product"], "tool_results": persisted,
    }])
    assert "ABCDEF000010" in context and "100000010" in context and "3081" in context
    assert "POSITIVE_REVIEW_SENTINEL" in context and "NEGATIVE_REVIEW_SENTINEL" in context
    accumulated = assembler.extract_useful_data(
        persisted, has_text_summarizer_summary_for_ref=lambda _item, _ref: False,
    )
    assert "ABCDEF000010" in accumulated and "100000010" in accumulated
    assert "POSITIVE_REVIEW_SENTINEL" in accumulated and "NEGATIVE_REVIEW_SENTINEL" in accumulated


def test_shared_source_candidate_api_prefers_ten_results_over_top_five_slice(assembler):
    rows = assembler.build_source_candidates_preview(
        search_context_data(), tool_name="serpapi_walmart_search", max_items=10,
    )
    assert len(rows) == 10
    for index, row in enumerate(rows, 1):
        assert row["product_id"] == f"ABCDEF{index:06d}"
        assert row["us_item_id"] == str(100000000 + index)
        assert row["position"] == index
    assert rows[0]["rating"] == 0 and rows[0]["reviews"] == 0


def test_executor_timeout_and_pipeline_classification_match_walmart_search_and_detail():
    from orchestrator.executor import ToolExecutor
    from orchestrator.pipeline_executor import PipelineExecutor

    executor = ToolExecutor.__new__(ToolExecutor)
    pipeline = PipelineExecutor.__new__(PipelineExecutor)
    for name in ("serpapi_walmart_search", "serpapi_walmart_product"):
        assert executor._get_subprocess_timeout(name, {}) == 90
    assert pipeline._is_search_tool("serpapi_walmart_search") is True
    assert pipeline._is_search_tool("serpapi_walmart_product") is False


def test_large_provider_pagination_never_crowds_out_ten_immediate_product_handles(assembler):
    data = search_context_data()
    data["pagination"] = {"current": 1, "other_pages": {
        str(page): "https://www.walmart.com/search?query=fixture&" + "filter=long-metadata&" * 8
                   + f"page={page}" for page in range(2, 302)
    }}
    assert len(json.dumps(data["pagination"])) > 50000
    preview, _total, shown, truncated = assembler.build_llm_result_context_preview(
        "serpapi_walmart_search", {"ok": True, "data": data},
    )
    projected = json.loads(preview)["data"]
    assert shown == len(preview) <= 10000 and truncated is True
    assert_search_identities(projected)
    assert "pagination" not in projected


def test_search_returns_only_compact_next_page_state_instead_of_provider_page_url_directory(
    monkeypatch, capsys,
):
    payload = search_payload()
    payload["pagination"] = {"current": 4, "next": "https://www.walmart.com/search?page=5",
                             "other_pages": {str(i): f"https://www.walmart.com/search?page={i}"
                                             for i in range(1, 101)}}
    provider(monkeypatch, search_tool, payload)
    code, result = run_main(monkeypatch, capsys, search_tool, {"query": "coffee", "page": 4})
    assert code == 0 and result["ok"] is True
    assert result["data"]["pagination"] == {"current": 4, "has_next": True, "next_page": 5}


def short_saved_product_data():
    data = product_context_data()
    reviews = data["reviews_results"]["reviews"]
    reviews["top_positive"]["text"] = "POSITIVE_REVIEW_SENTINEL useful positive experience."
    reviews["top_negative"]["text"] = "NEGATIVE_REVIEW_SENTINEL useful negative experience."
    reviews["customer_reviews"] = []
    summary = data["product_summary"]
    summary["variants"] = ["actual_color-blue", "clothing_size-m"]
    summary["variant_swatches"] = [{"name": "Color", "available_selections": [
        {"name": "Blue", "products": [{"product_id": "VARIANT00001", "in_stock": False}]},
    ]}]
    summary["offers"] = [{"seller_name": "Other fixture seller", "price": 8.5}]
    return data


def test_saved_product_summary_keeps_variants_offers_and_balanced_review_evidence():
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    data = short_saved_product_data()
    saved = followup.extract_followup_data({"serpapi_walmart_product": {"ok": True, "data": data}})
    detail = saved["serpapi_walmart_product"]
    summary = detail["product_summary"]
    assert summary["variants"] == data["product_summary"]["variants"]
    assert summary["offers"] == data["product_summary"]["offers"]
    variant_evidence = json.dumps(summary.get("variant_options", summary.get("variant_swatches")))
    assert '"product_id": "VARIANT00001"' in variant_evidence
    assert '"in_stock": false' in variant_evidence
    rendered = json.dumps(detail)
    assert "POSITIVE_REVIEW_SENTINEL" in rendered and "NEGATIVE_REVIEW_SENTINEL" in rendered


def test_saved_repeated_run_wrapper_keeps_counts_store_identity_and_latest_product_evidence(assembler):
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    runs = []
    for index in range(4):
        data = short_saved_product_data()
        data["store_id"] = str(3080 + index)
        data["location_context"]["store_id"] = str(3080 + index)
        data["product_id"] = f"RUN{index}ITEM"
        runs.append({"ok": True, "data": data})
    saved = followup.extract_followup_data({"serpapi_walmart_product": runs})["serpapi_walmart_product"]
    assert saved["runs_count"] == 4 and saved["results_truncated"] is True
    assert [run["store_id"] for run in saved["results"]] == ["3081", "3082", "3083"]
    assert [run["product_id"] for run in saved["results"]] == ["RUN1ITEM", "RUN2ITEM", "RUN3ITEM"]
    context = assembler.extract_useful_data(
        {"serpapi_walmart_product": saved},
        has_text_summarizer_summary_for_ref=lambda _item, _ref: False,
    )
    wrapper = json.loads(context.split("=== serpapi_walmart_product ===", 1)[1].strip())
    assert wrapper["runs_count"] == 4 and wrapper["results_truncated"] is True
    assert [run["store_id"] for run in wrapper["results"]] == ["3081", "3082", "3083"]
    assert "POSITIVE_REVIEW_SENTINEL" in context and "NEGATIVE_REVIEW_SENTINEL" in context


def twenty_color_swatches():
    return [{"name": "Color", "available_selections": [{
        "id": f"color-{index}", "name": f"Color {index}",
        "swatch_image_url": "https://i5.walmartimages.com/" + "x" * 5000,
        "products": [{"product_id": f"COLOR{index:07d}", "in_stock": False,
                      "price_map": {"price": 0, "currency": "USD"}}],
    } for index in range(20)]}]


def test_compact_variant_options_keep_twenty_color_ids_without_large_swatch_images():
    from lib.serpapi_walmart_context import compact_variant_options

    options = compact_variant_options(twenty_color_swatches())
    assert len(options) == 20
    for index, option in enumerate(options):
        assert option["product_id"] == f"COLOR{index:07d}"
        assert option["group"] == "Color" and option["name"] == f"Color {index}"
        assert option["selection_id"] == f"color-{index}"
        assert option["in_stock"] is False and option["price_map"]["price"] == 0
    assert "swatch_image_url" not in json.dumps(options)
    assert len(json.dumps(options)) < 5000


def test_immediate_and_saved_context_keep_color_options_and_zero_false_shipping_evidence(assembler):
    import importlib

    from server_package_utils import load_server_package

    from lib.serpapi_walmart_context import project_walmart_data

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    data = short_saved_product_data()
    data["product_summary"]["variant_swatches"] = twenty_color_swatches()
    for row in data["results"]:
        row.update(free_shipping=False, two_day_shipping=False, free_shipping_with_walmart_plus=False,
                   quantity=0, price_per_unit=0)
    projected = project_walmart_data(data, max_chars=9000)
    assert len(projected["product_summary"]["variant_options"]) == 20
    preview, _total, shown, _truncated = assembler.build_llm_result_context_preview(
        "serpapi_walmart_product", {"ok": True, "data": data},
    )
    assert shown == len(preview) <= 10000
    immediate = json.loads(preview)["data"]
    saved = followup.extract_followup_data({"serpapi_walmart_product": {"ok": True, "data": data}})
    detail = saved["serpapi_walmart_product"]
    for result in (projected, immediate, detail):
        option_ids = [option["product_id"] for option in result["product_summary"]["variant_options"]]
        assert option_ids == [f"COLOR{index:07d}" for index in range(20)]
        candidate = result["candidates"][0]
        assert candidate["free_shipping"] is False and candidate["two_day_shipping"] is False
        assert candidate["free_shipping_with_walmart_plus"] is False
        assert candidate["quantity"] == 0 and candidate["price_per_unit"] == 0
    assert len(json.dumps(detail, ensure_ascii=False)) <= 7500


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("price", [0, 12.5])
def test_missing_provider_currency_preserves_price_without_inventing_formatted_currency(detail, price):
    item = product_row()
    key, amount = ("price_map", "price") if detail else ("primary_offer", "offer_price")
    item[key] = {amount: price}
    normalized = walmart.normalize_product(item, detail=detail)
    assert normalized["price"] == price and normalized["currency"] is None
    assert normalized["price_formatted"] is None


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_exact_zip_match_speech_names_chosen_store_address_and_multiple_match_count(
    monkeypatch, capsys, tool,
):
    selected_address = "100 Main Street, Sacramento, CA, US"
    directory(monkeypatch, [
        {"store_id": "100", "postal_code": "95829", "address": "300 Other Street, Sacramento, CA, US"},
        {"store_id": "20", "postal_code": "95829", "address": selected_address},
    ])
    provider(monkeypatch, tool, search_payload() if tool is search_tool else product_payload())
    inputs = {"query": "coffee"} if tool is search_tool else {"product_id": "147423982"}
    code, result = run_main(monkeypatch, capsys, tool, {**inputs, "postal_code": "95829"})
    assert code == 0 and result["ok"] is True
    assert result["data"]["store_id"] == "20"
    assert result["data"]["location_context"]["matching_stores"] == 2
    speech = result["speech"]
    assert selected_address in speech
    assert re.search(r"store\s*#?\s*20\b", speech, re.IGNORECASE)
    assert re.search(r"\b2\s+(?:matching\s+)?stores?\b", speech, re.IGNORECASE)


def provider_filter_catalog():
    return [{"name": "Brand", "type": "brand", "values": [
        {"id": "opaque_brand_8471", "name": "Fixture Brand", "type": "brand",
         "serpapi_url": "https://serpapi.com/search.json?api_key=FILTER_SECRET_SENTINEL"},
    ]}, {"name": "Customer Rating", "type": "customer_rating_range_facet_new_filter_v0", "values": [
        {"id": "4 - 5 Stars", "name": "Highly rated"},
    ]}, {"name": "Departments", "type": "cat_id", "values": [
        {"id": "4044_90548_90546", "name": "Fixture department", "type": "cat_id"},
    ]}]


def assert_filter_catalog(projected):
    rows = projected["filters"]
    options = [option for group in rows for option in group["options"]]
    assert {option["value"] for option in options} == {
        "brand:opaque_brand_8471", "customer_rating_range_facet_new_filter_v0:4 - 5 Stars",
        "4044_90548_90546",
    }
    assert {option["param"] for option in options} == {"facet", "cat_id"}
    assert next(option for option in options if option["label"] == "Fixture Brand")["value"] == "brand:opaque_brand_8471"
    assert "FILTER_SECRET_SENTINEL" not in json.dumps(rows)
    assert projected.get("filters_truncated", False) is False


def test_search_requests_available_filters_for_followup_facet_selection(monkeypatch, capsys):
    payload = search_payload()
    payload["filters"] = provider_filter_catalog()
    request = provider(monkeypatch, search_tool, payload)
    code, result = run_main(monkeypatch, capsys, search_tool, {"query": "coffee"})
    assert code == 0 and result["ok"] is True
    assert request.call_args.args[0]["include_filters"] == "true"
    assert result["data"]["filters"]
    assert request.call_count == 1


def test_compact_filter_catalog_preserves_provider_facet_keys_and_ids():
    from lib.serpapi_walmart_context import compact_walmart_filters

    rows = compact_walmart_filters(provider_filter_catalog())
    assert_filter_catalog({"filters": rows})
    assert compact_walmart_filters(rows) == rows


def test_filter_controls_preserve_nested_categories_zero_ranges_and_selected_facet_identity():
    from lib.serpapi_walmart_context import compact_walmart_filters, project_walmart_data

    catalog = compact_walmart_filters([
        {"name": "Departments", "type": "cat_id", "values": [
            {"id": "4044", "name": "Home", "values": [
                {"id": "4044_90548", "name": "Coffee makers", "item_count": 0},
            ]},
        ]},
        {"name": "Price", "type": "price", "min": 0, "max": 100, "step_size": 1},
        {"name": "Brand", "type": "brand", "values": [
            {"id": "opaque-selected-brand", "name": "Selected brand", "selected": True,
             "url": "https://www.walmart.com/search?facet=brand%3Adifferent-brand"},
        ]},
    ])
    nested = catalog[0]["options"][1]
    assert nested["value"] == "4044_90548" and nested["param"] == "cat_id"
    assert nested["item_count"] == 0
    assert catalog[1]["min"] == 0 and catalog[1]["options"] == []
    assert catalog[2]["options"][0]["value"] == "brand:opaque-selected-brand"
    assert catalog[2]["options"][0]["selected"] is True
    assert "different-brand" not in json.dumps(catalog)
    projected = project_walmart_data({"filters": catalog, "related_queries": [
        {"suggested": "coffee filters", "serpapi_suggested_url": "https://example.com/?api_key=SECRET"},
    ], "requested_filters": {"facet": "brand:opaque-selected-brand", "max_price": 75}})
    assert projected["related_queries"] == ["coffee filters"]
    assert projected["requested_filters"]["facet"] == "brand:opaque-selected-brand"
    assert "SECRET" not in json.dumps(projected)


def test_facet_catalog_survives_immediate_native_and_saved_reload_context(assembler):
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    data = search_context_data()
    data["filters"] = provider_filter_catalog()
    result = {"ok": True, "data": data}
    preview, _total, shown, _truncated = assembler.build_llm_result_context_preview(
        "serpapi_walmart_search", result,
    )
    assert shown == len(preview) <= 10000
    assert_filter_catalog(json.loads(preview)["data"])
    message, _metadata = assembler.build_provider_tool_result_message(
        tool_name="serpapi_walmart_search", arguments={"query": "coffee"}, result=result,
        max_chars=6000,
    )
    assert len(message) <= 6000
    assert_filter_catalog(json.loads(message.split("\nResult:\n", 1)[1])["result"]["data"])
    saved = followup.extract_followup_data({"serpapi_walmart_search": result})
    persisted = json.loads(json.dumps(saved))
    assert_filter_catalog(persisted["serpapi_walmart_search"])
    history = assembler.format_conversation_context("Use the highly rated filter.", [{
        "role": "assistant", "content": "Found coffee options.",
        "tools_used": ["serpapi_walmart_search"], "tool_results": persisted,
    }])
    assert "brand:opaque_brand_8471" in history
    assert "customer_rating_range_facet_new_filter_v0:4 - 5 Stars" in history
    assert "FILTER_SECRET_SENTINEL" not in history


def test_oversized_filter_catalog_omissions_are_marked_without_dropping_product_ids():
    from lib.serpapi_walmart_context import project_walmart_data

    data = search_context_data()
    data["filters"] = [{"name": "Brand", "type": "brand", "values": [
        {"id": "opaque_" + str(index) + "x" * 300, "name": f"Brand {index}"}
        for index in range(100)
    ]}]
    projected = project_walmart_data(data, max_chars=9000)
    assert len(json.dumps(projected, ensure_ascii=False)) <= 9000
    assert projected["filters_truncated"] is True and projected["context_truncated"] is True
    assert_search_identities(projected)


def twenty_two_filter_groups():
    attribute_types = (
        "fulfillment_method", "fulfillment_speed", "retailer", "coffee_form", "container_type",
        "roast_type", "dietary_requirement", "flavor", "manufacturer", "product_line",
        "special_offer", "condition", "subscription", "package_quantity", "product_size",
        "certification", "availability",
    )
    # Put important controls last so the budget policy must prioritize usable
    # choices, rather than spending the entire allowance on early headers.
    extras = [{"name": kind.replace("_", " ").title(), "type": kind, "values": [
        {"id": f"provider_token_{index}_{value}", "name": f"Option {value}"}
        for value in range(4)
    ]} for index, kind in enumerate(attribute_types)]
    return [*extras, *provider_filter_catalog(),
            {"name": "Price", "type": "price", "min": 0, "max": 75, "step_size": 1},
            {"name": "Sort", "type": "sort", "values": [
                {"id": "rating_high", "name": "Highest rated"},
            ]}]


def assert_priority_filter_choices(catalog):
    options = [option for group in catalog for option in group.get("options", [])]
    tokens = {option["value"] for option in options}
    assert "brand:opaque_brand_8471" in tokens
    assert "customer_rating_range_facet_new_filter_v0:4 - 5 Stars" in tokens
    for group in catalog:
        assert group.get("options") or group["type"] in {"price", "price_range", "range"}


def test_small_catalog_budget_keeps_executable_brand_and_rating_choices_before_empty_headers():
    from lib.serpapi_walmart_context import bounded_walmart_filters

    source = twenty_two_filter_groups()
    assert len(source) == 22
    catalog, omitted = bounded_walmart_filters(source, max_chars=500)
    assert len(json.dumps(catalog, ensure_ascii=False)) <= 500
    assert omitted is True
    assert_priority_filter_choices(catalog)


def test_sort_catalog_control_uses_sort_by_instead_of_a_fabricated_facet():
    from lib.serpapi_walmart_context import compact_walmart_filters

    catalog = compact_walmart_filters([{"name": "Sort", "type": "sort", "values": [
        {"id": "rating_high", "name": "Highest rated"},
    ]}])
    assert catalog[0]["options"] == [{
        "label": "Highest rated", "value": "rating_high", "param": "sort_by",
    }]


@pytest.mark.parametrize("budget", [9000, 6000])
def test_large_catalog_keeps_real_facet_choices_and_ten_product_ids_in_projected_budget(budget):
    from lib.serpapi_walmart_context import project_walmart_data

    data = search_context_data()
    data["filters"] = twenty_two_filter_groups()
    projected = project_walmart_data(data, max_chars=budget)
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"))) <= budget
    assert projected["filters_truncated"] is True and projected["context_truncated"] is True
    assert_priority_filter_choices(projected["filters"])
    assert_search_identities(projected)


def test_twenty_two_group_catalog_remains_actionable_in_native_and_saved_history(assembler):
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    data = search_context_data()
    data["filters"] = twenty_two_filter_groups()
    result = {"ok": True, "data": data}
    preview, _total, shown, _truncated = assembler.build_llm_result_context_preview(
        "serpapi_walmart_search", result,
    )
    immediate = json.loads(preview)["data"]
    assert shown == len(preview) <= 10000
    assert_priority_filter_choices(immediate["filters"])
    assert_search_identities(immediate)
    message, _metadata = assembler.build_provider_tool_result_message(
        tool_name="serpapi_walmart_search", arguments={"query": "coffee", "num_results": 10},
        result=result, max_chars=6000,
    )
    assert len(message) <= 6000
    native = json.loads(message.split("\nResult:\n", 1)[1])["result"]["data"]
    assert_priority_filter_choices(native["filters"])
    assert_search_identities(native)
    saved = followup.extract_followup_data({"serpapi_walmart_search": result})
    persisted = json.loads(json.dumps(saved))
    assert_priority_filter_choices(persisted["serpapi_walmart_search"]["filters"])
    assert_search_identities(persisted["serpapi_walmart_search"])
    history = assembler.format_conversation_context("Filter these by highly rated Fixture Brand.", [{
        "role": "assistant", "content": "Found ten products.",
        "tools_used": ["serpapi_walmart_search"], "tool_results": persisted,
    }])
    assert "brand:opaque_brand_8471" in history
    assert "customer_rating_range_facet_new_filter_v0:4 - 5 Stars" in history
    assert "ABCDEF000010" in history


def test_large_catalog_preserves_each_leading_products_own_photo_across_model_and_saved_handoffs(assembler):
    import importlib

    from server_package_utils import load_server_package

    load_server_package("walmart_core_context_server", ROOT / "jarvis-web" / "server")
    followup = importlib.import_module("walmart_core_context_server.services.followup_extractor")
    data = search_context_data()
    data["filters"] = twenty_two_filter_groups()
    for index, row in enumerate(data["results"]):
        row.update(image_url=f"https://images.example/product-{index}-" + "a" * 150 + ".jpeg",
                   free_shipping=False, two_day_shipping=False, free_shipping_with_walmart_plus=False,
                   product_type="Fixture product type", price_per_unit={"amount": "33.3 cents/oz", "currency": "USD"})
    result = {"ok": True, "data": data}
    preview, *_ = assembler.build_llm_result_context_preview("serpapi_walmart_search", result)
    immediate = json.loads(preview)["data"]
    message, _ = assembler.build_provider_tool_result_message(
        tool_name="serpapi_walmart_search", arguments={"query": "coffee"}, result=result, max_chars=6000,
    )
    native = json.loads(message.split("\nResult:\n", 1)[1])["result"]["data"]
    saved = followup.extract_followup_data({"serpapi_walmart_search": result})
    persisted = json.loads(json.dumps(saved))["serpapi_walmart_search"]
    for projection in (immediate, native, persisted):
        assert_priority_filter_choices(projection["filters"])
        for expected, actual in zip(data["results"][:3], projection["candidates"][:3], strict=True):
            assert actual["product_id"] == expected["product_id"]
            assert actual["image_url"] == expected["image_url"]
    assert len(preview) <= 10000 and len(message) <= 6000
    assert len(persisted["candidates"]) == 10
    history = assembler.format_conversation_context("Compare those three products.", [{
        "role": "assistant", "content": "Found products.", "tool_results": saved,
    }])
    assert all(row["image_url"] in history for row in data["results"][:3])
