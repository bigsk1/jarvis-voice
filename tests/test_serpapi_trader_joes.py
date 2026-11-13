"""Trader Joe's source contracts, exact store validation and leading-zero identities."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import serpapi_trader_joes as trader  # noqa: E402
import serpapi_trader_joes_product as product_tool  # noqa: E402
import serpapi_trader_joes_search as search_tool  # noqa: E402
from tool_child_environment import restrict_child_environment  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


def row(identifier="080794"):
    return {
        "product_id": identifier, "title": "Fixture cold brew coffee",
        "link": f"https://www.traderjoes.com/home/products/pdp/fixture-coffee-{identifier}",
        "thumbnail": "https://www.traderjoes.com/content/dam/fixture.png",
        "category": "Coffee & Tea",
        "category_link": "https://www.traderjoes.com/home/products/category/coffee-tea-194",
        "price": "$1.99", "extracted_price": 1.99, "size": "8.45 Fl Oz",
    }


def search_payload(count=2):
    return {
        "search_metadata": {"id": "search-fixture", "status": "Success"},
        "search_parameters": {"engine": "trader_joes", "q": "coffee"},
        "search_information": {"total_results": 42},
        "organic_results": [row(f"{80794 + index:06d}") for index in range(count)],
        "serpapi_pagination": {"current": 1, "next": "https://serpapi.com/search.json?page=2&api_key=PRIVATE_SENTINEL",
                              "other_pages": {"2": "https://serpapi.com/search.json?page=2"}},
    }


def product_payload(*, available=True):
    product = row()
    product.update({
        "available": available, "characteristics": ["Vegan", "Gluten Free"], "label": "NEW",
        "categories": [{"name": "Beverages", "link": "https://www.traderjoes.com/home/products/category/beverages-182"},
                       {"name": "Coffee & Tea", "link": product["category_link"]}],
        "images": [product["thumbnail"], "https://www.traderjoes.com/content/dam/fixture-back.png"],
        "description": "Fixture article text about this coffee.", "fun_tags": ["Rise & Shine"],
        "ingredients": ["WATER", "COFFEE"], "allergens": ["MAY CONTAIN MILK."],
        "nutrition_facts": [{"title": "Per serving", "serving_size": "1 can", "calories_per_serving": 0,
                             "nutrients": [{"name": "Total Fat", "amount": "0g", "daily_value": "0%"}],
                             "added_sugar": False},
                            {"title": "Per container", "calories_per_serving": "0"}],
    })
    if not available:
        product.pop("price")
        product.pop("extracted_price")
    return {"search_metadata": {"id": "product-fixture", "status": "Success"},
            "search_parameters": {"engine": "trader_joes_product"}, "product_results": product}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    config = {}
    monkeypatch.setattr(trader, "get_config_value", lambda key, default="": config.get(key, default))
    monkeypatch.setattr(trader, "http_request", Mock(side_effect=AssertionError("Unexpected directory request")))
    for tool in (search_tool, product_tool):
        monkeypatch.setattr(tool, "load_config", lambda: None)
        monkeypatch.setattr(tool, "request_serpapi", Mock(side_effect=AssertionError("Unexpected paid request")))
    return config


class DirectoryResponse:
    def __init__(self, payload, *, status=200, raw=None):
        self.status_code = status
        self.body = json.dumps(payload).encode() if raw is None else raw
        self.closed = False

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        self.closed = True


def stores(monkeypatch, payload=None, **kwargs):
    if payload is None:
        payload = [{"store_id": "454", "name": "Fixture store", "address": "100 Main Street",
                    "city": "Austin", "state": "TX", "postal_code": "78759"}]
    response = DirectoryResponse(payload, **kwargs)
    request = Mock(return_value=response)
    monkeypatch.setattr(trader, "http_request", request)
    return request, response


def provider(monkeypatch, tool, payload):
    request = Mock(return_value=deepcopy(payload))
    monkeypatch.setattr(tool, "request_serpapi", request)
    return request


def run(monkeypatch, capsys, tool, arguments):
    monkeypatch.setattr(sys, "argv", [tool.__name__ + ".py", json.dumps(arguments)])
    code = tool.main()
    return code, json.loads(capsys.readouterr().out)


def test_search_uses_exact_documented_filters_csv_and_one_bounded_paid_request(monkeypatch, capsys):
    free, response = stores(monkeypatch)
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, {
        "query": "coffee", "store_id": "454", "category_id": "194", "page": 2,
        "characteristics": ["organic", "vegan"], "tags": ["date_night", "cheese_board"],
        "new_products": False, "sort_by": "price_low_to_high", "no_cache": False,
    })
    assert code == 0 and result["ok"] is True
    assert paid.call_args.args[0] == {
        "engine": "trader_joes", "q": "coffee", "page": 2, "new_products": "false",
        "no_cache": "false", "category_id": "194", "sort_by": "price_low_to_high",
        "characteristics": "organic,vegan", "tags": "date_night,cheese_board", "store_id": "454",
    }
    assert paid.call_args.kwargs["timeout"] == 60
    assert paid.call_args.kwargs["max_response_bytes"] == 2 * 1024 * 1024
    assert paid.call_args.kwargs["use_proxy"] is False
    assert paid.call_count == 1 and free.call_count == 1 and response.closed is True
    assert result["data"]["requested_filters"]["characteristics"] == ["organic", "vegan"]
    assert result["data"]["pagination"] == {"current": 2, "has_next": True, "next_page": 3}
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def test_unselected_store_is_truthfully_all_catalog_and_search_keeps_leading_zero_ids(monkeypatch, capsys):
    paid = provider(monkeypatch, search_tool, search_payload(15))
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee"})
    assert code == 0 and result["ok"] is True
    data = result["data"]
    assert data["results_count"] == 5 and data["provider_results_count"] == 15
    assert data["results_truncated"] is True
    assert data["store_id"] is None and "all-store catalog" in result["speech"]
    assert data["top_product_id"] == "080794"
    first = data["results"][0]
    assert all("search_filters" not in product for product in data["results"])
    assert first["position"] == 1 and first["product_id"] == "080794"
    assert first["price"] == 1.99 and first["price_formatted"] == "$1.99" and first["currency"] == "USD"
    assert first["image_url"] == row()["thumbnail"] and first["category_id"] == "194"
    assert paid.call_args.args[0]["new_products"] == "false"
    assert "store_id" not in paid.call_args.args[0]
    trader.http_request.assert_not_called()


@pytest.mark.parametrize(("count", "expected"), [(0, 1), (100, 10)])
def test_result_limit_clamps_without_product_detail_fanout(monkeypatch, capsys, count, expected):
    paid = provider(monkeypatch, search_tool, search_payload(15))
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee", "num_results": count})
    assert code == 0 and len(result["data"]["results"]) == expected
    assert paid.call_count == 1


@pytest.mark.parametrize("reference", ["080794", "https://www.traderjoes.com/home/products/pdp/coffee-080794",
                                       "https://traderjoes.com/home/products/pdp/080794?utm_source=test"])
def test_product_ids_and_urls_preserve_sku_and_complete_ingredient_nutrition_panels(
    monkeypatch, capsys, reference,
):
    payload = product_payload()
    paid = provider(monkeypatch, product_tool, payload)
    code, result = run(monkeypatch, capsys, product_tool, {"product_id": reference, "no_cache": True})
    assert code == 0 and result["ok"] is True
    assert paid.call_args.args[0] == {"engine": "trader_joes_product", "product_id": "080794", "no_cache": "true"}
    assert paid.call_args.kwargs["timeout"] == 60 and paid.call_args.kwargs["max_response_bytes"] == 2097152
    assert paid.call_count == 1
    detail = result["data"]["product_summary"]
    assert detail == result["data"]["results"][0] and detail["product_id"] == "080794"
    for field in ("available", "characteristics", "label", "description", "fun_tags", "ingredients", "allergens", "nutrition_facts"):
        assert detail[field] == payload["product_results"][field]
    assert len(detail["images"]) == 2 and detail["category_id"] == "194"
    assert detail["nutrition_facts"][0]["calories_per_serving"] == 0
    assert detail["nutrition_facts"][0]["added_sugar"] is False
    assert not {"rating", "reviews", "in_stock"} & detail.keys()


def test_unsold_product_has_false_catalog_availability_and_missing_price_not_free(monkeypatch, capsys):
    stores(monkeypatch)
    paid = provider(monkeypatch, product_tool, product_payload(available=False))
    code, result = run(monkeypatch, capsys, product_tool, {"product_id": "080794", "store_id": "454"})
    assert code == 0 and result["ok"] is True
    detail = result["data"]["product_summary"]
    assert detail["available"] is False
    assert detail["price"] is None and detail["price_formatted"] is None and detail["currency"] is None
    assert "current stock" in result["data"]["availability_note"]
    assert paid.call_args.args[0]["store_id"] == "454"


def test_zero_price_is_not_lost_and_category_id_is_derived_without_integer_coercion():
    item = row()
    item.update(price="$0.00", extracted_price=0,
                category_link="https://www.traderjoes.com/home/products/category/fixture-00194")
    normalized = trader.normalize_product(item)
    assert normalized["price"] == 0 and normalized["price_formatted"] == "$0.00"
    assert normalized["currency"] == "USD" and normalized["category_id"] == "00194"


@pytest.mark.parametrize("reference", [
    80794, True, None, [], "", "abc", "file:///etc/passwd", "https://example.org/home/products/pdp/coffee-080794",
    "https://traderjoes.com.attacker.test/home/products/pdp/coffee-080794",
    "https://name:secret@www.traderjoes.com/home/products/pdp/coffee-080794",
    "https://www.traderjoes.com:9000/home/products/pdp/coffee-080794",
    "https://www.traderjoes.com/home/products/category/coffee-194",
    "https://www.traderjoes.com\\@attacker.test/home/products/pdp/coffee-080794",
])
def test_invalid_product_reference_fails_before_any_network(monkeypatch, capsys, reference):
    code, result = run(monkeypatch, capsys, product_tool, {"product_id": reference})
    assert code == 1 and result["ok"] is False
    product_tool.request_serpapi.assert_not_called()
    trader.http_request.assert_not_called()


@pytest.mark.parametrize("arguments", [
    {}, {"query": ""}, {"query": []}, {"query": "x" * 401}, {"page": 0}, {"page": 101},
    {"page": True}, {"num_results": "10"}, {"sort_by": "rating_high"}, {"category_id": 194},
    {"characteristics": "vegan"}, {"characteristics": ["gluten-free"]}, {"tags": "date_night"},
    {"tags": ["Unknown Occasion"]}, {"tags": [False]}, {"new_products": "false"}, {"no_cache": "false"},
    {"postal_code": "near Austin"}, {"store_id": "../../private"}, {"q": "ignored"},
    {"engine": "google"}, {"extra_params": {"store_id": "999999"}},
])
def test_search_argument_validation_rejects_malformed_filters_before_network(monkeypatch, capsys, arguments):
    inputs = {"query": "coffee", **arguments} if arguments else {}
    code, result = run(monkeypatch, capsys, search_tool, inputs)
    assert code == 1 and result["ok"] is False
    search_tool.request_serpapi.assert_not_called()
    trader.http_request.assert_not_called()


@pytest.mark.parametrize("tool", [search_tool, product_tool])
@pytest.mark.parametrize("arguments", [None, [], "plain text", 123])
def test_nonobject_json_returns_one_failure_envelope_without_network(monkeypatch, capsys, tool, arguments):
    code, result = run(monkeypatch, capsys, tool, arguments)
    assert code == 1 and result["ok"] is False
    tool.request_serpapi.assert_not_called()


@pytest.mark.parametrize("configured", [False, True])
def test_unknown_explicit_or_configured_store_is_rejected_before_paid_query(
    isolated, monkeypatch, capsys, configured,
):
    free, response = stores(monkeypatch)
    options = {"query": "coffee"}
    if configured:
        isolated["JARVIS_TRADER_JOES_STORE_ID"] = "999999"
    else:
        options["store_id"] = "999999"
    code, result = run(monkeypatch, capsys, search_tool, options)
    assert code == 1 and result["ok"] is False
    assert "not in the supported store directory" in result["error"]
    assert free.call_count == 1 and response.closed is True
    search_tool.request_serpapi.assert_not_called()


@pytest.mark.parametrize("failure", ["network", "http", "invalid", "oversized"])
@pytest.mark.parametrize("explicit_store", [True, False])
def test_directory_failure_never_claims_selected_store_and_hides_exception_details(
    monkeypatch, capsys, failure, explicit_store,
):
    response = None
    if failure == "network":
        monkeypatch.setattr(trader, "http_request", Mock(side_effect=requests.ConnectionError(
            "PRIVATE_DIRECTORY_SENTINEL api_key=not-for-output",
        )))
    elif failure == "http":
        _free, response = stores(monkeypatch, status=503)
    elif failure == "invalid":
        _free, response = stores(monkeypatch, raw=b"not JSON")
    else:
        _free, response = stores(monkeypatch, raw=b"x" * (2097152 + 1))
    paid = provider(monkeypatch, search_tool, search_payload())
    options = {"query": "coffee", **({"store_id": "454"} if explicit_store else {"postal_code": "78759"})}
    code, result = run(monkeypatch, capsys, search_tool, options)
    assert result["ok"] is (not explicit_store)
    assert code == (1 if explicit_store else 0)
    assert paid.call_count == (0 if explicit_store else 1)
    assert "PRIVATE_DIRECTORY_SENTINEL" not in json.dumps(result) and "not-for-output" not in json.dumps(result)
    if not explicit_store:
        assert result["data"]["store_id"] is None
        assert "not applied" in result["speech"] and "all-store catalog" in result["speech"]
        assert "store_id" not in paid.call_args.args[0]
    if response:
        assert response.closed is True


def test_zip_override_beats_configured_store_and_reports_exact_multiple_matches(isolated, monkeypatch):
    isolated.update(JARVIS_TRADER_JOES_STORE_ID="999999", JARVIS_DEFAULT_POSTAL_CODE="10001")
    free, response = stores(monkeypatch, [
        {"store_id": "100", "name": "Other", "address": "300 Other Street", "city": "Cambridge", "state": "MA", "postal_code": "02138"},
        {"store_id": "20", "name": "Selected", "address": "100 Main Street", "city": "Cambridge", "state": "MA", "postal_code": "02138"},
        {"store_id": "1", "name": "Nearby", "postal_code": "02139"},
    ])
    location = trader.resolve_location({"postal_code": "02138-1234"})
    assert location["store_id"] == "20" and location["source"] == "postal_code"
    assert location["matching_stores"] == 2 and location["requested_postal_code"] == "02138-1234"
    assert "100 Main Street, Cambridge, MA, 02138" in location["note"]
    assert "2 stores match" in location["note"]
    assert free.call_args.args == ("GET", "https://serpapi.com/trader-joes-stores.json")
    assert free.call_args.kwargs["allow_redirects"] is False and free.call_args.kwargs["use_proxy"] is False
    assert response.closed is True


def test_explicit_store_beats_other_location_defaults_but_is_still_validated(isolated, monkeypatch):
    isolated.update(JARVIS_TRADER_JOES_STORE_ID="999999", JARVIS_DEFAULT_POSTAL_CODE="10001")
    free, _response = stores(monkeypatch)
    location = trader.resolve_location({"store_id": "454", "postal_code": "02138"})
    assert location["store_id"] == "454" and location["source"] == "explicit_store"
    assert location["store_postal_code"] == "78759" and "Austin" in location["note"]
    assert free.call_count == 1


def test_unmatched_zip_never_selects_the_nearest_store(monkeypatch, capsys):
    stores(monkeypatch)
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee", "postal_code": "78758"})
    assert code == 0 and result["ok"] is True
    assert result["data"]["store_id"] is None and "not applied" in result["speech"]
    assert "store_id" not in paid.call_args.args[0]


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_paid_provider_failures_return_structured_error_without_retry(monkeypatch, capsys, tool):
    paid = Mock(side_effect=RuntimeError("SerpApi request failed with HTTP 401."))
    monkeypatch.setattr(tool, "request_serpapi", paid)
    options = {"query": "coffee"} if tool is search_tool else {"product_id": "080794"}
    code, result = run(monkeypatch, capsys, tool, options)
    assert code == 1 and result["ok"] is False and "401" in result["error"]
    assert paid.call_count == 1


@pytest.mark.parametrize("payload", [None, [], {}, {"search_information": {"total_results": 1}},
                                     {"search_information": {"total_results": False}},
                                     {"search_information": {"total_results": 0}, "organic_results": None},
                                     {"search_metadata": {"status": "Processing"}},
                                     {"search_parameters": {"engine": "google"}}, {"error": "provider error"}])
def test_malformed_or_incomplete_provider_payload_is_never_an_empty_success(monkeypatch, capsys, payload):
    provider(monkeypatch, search_tool, payload)
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee"})
    assert code == 1 and result["ok"] is False


@pytest.mark.parametrize("information", [{"total_results": 0}, {"organic_results_state": "Fully empty"}])
def test_explicit_empty_search_information_allows_missing_product_list(monkeypatch, capsys, information):
    paid = provider(monkeypatch, search_tool, {"search_information": information})
    code, result = run(monkeypatch, capsys, search_tool, {"query": "missing", "page": 2})
    assert code == 0 and result["ok"] is True
    assert result["data"]["results"] == [] and result["data"]["results_count"] == 0
    assert result["data"]["search_information"] == information
    assert result["data"]["provider_results_count"] == 0 and result["data"]["results_truncated"] is False
    assert result["data"]["pagination"] == {"current": 2, "has_next": False, "next_page": None}
    assert paid.call_count == 1


def test_empty_search_is_success_but_product_requires_plural_product_results(monkeypatch, capsys):
    provider(monkeypatch, search_tool, {"organic_results": []})
    code, result = run(monkeypatch, capsys, search_tool, {"query": "missing"})
    assert code == 0 and result["data"]["results"] == []
    provider(monkeypatch, product_tool, {"product_result": row()})
    code, result = run(monkeypatch, capsys, product_tool, {"product_id": "080794"})
    assert code == 1 and result["ok"] is False and "product_results" in result["error"]


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_manifest_only_passes_selected_serpapi_key_and_trader_joes_location_settings(tool):
    path = ROOT / "skills" / f"{tool.__name__}.tool.json"
    manifest = json.loads(path.read_text())
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["prompt_guard_policy"] == "web_content" and manifest["proxy_policy"] == "off"
    assert manifest["parameters"]["additionalProperties"] is False
    assert manifest["parameters"]["required"] == (["query"] if tool is search_tool else ["product_id"])
    schema = ToolSchema.from_json_file(str(path))
    assert schema.child_environment_names == frozenset({"SERP_API_KEY", "JARVIS_DEFAULT_POSTAL_CODE", "JARVIS_TRADER_JOES_STORE_ID"})
    child = restrict_child_environment({
        "PATH": "/usr/bin", "JARVIS_MODE": "cloud", "SERP_API_KEY": "mode-key",
        "JARVIS_OVERRIDE_SERP_API_KEY": "selected-key", "JARVIS_DEFAULT_POSTAL_CODE": "02138",
        "JARVIS_TRADER_JOES_STORE_ID": "454", "JARVIS_WALMART_STORE_ID": "other-store",
        "OPENAI_API_KEY": "unrelated-secret",
    }, schema.child_environment_names, home="/tmp/trader-joes-test", proxy_policy="off")
    assert child["SERP_API_KEY"] == "selected-key" and child["JARVIS_DEFAULT_POSTAL_CODE"] == "02138"
    assert child["JARVIS_TRADER_JOES_STORE_ID"] == "454"
    assert "OPENAI_API_KEY" not in child and "JARVIS_WALMART_STORE_ID" not in child


@pytest.mark.parametrize("tool", [search_tool, product_tool])
@pytest.mark.parametrize("postal", ["SW1A1AA", "M5V 3L9"])
def test_foreign_shared_postal_default_uses_all_store_catalog_without_directory(
    isolated, monkeypatch, capsys, tool, postal,
):
    isolated["JARVIS_DEFAULT_POSTAL_CODE"] = postal
    payload = search_payload() if tool is search_tool else product_payload()
    options = {"query": "coffee"} if tool is search_tool else {"product_id": "080794"}
    paid = provider(monkeypatch, tool, payload)
    code, result = run(monkeypatch, capsys, tool, options)
    assert code == 0 and result["ok"] is True and paid.call_count == 1
    assert "store_id" not in paid.call_args.args[0] and result["data"]["store_id"] is None
    assert result["data"]["location_context"]["requested_postal_code"] == postal
    assert result["data"]["location_context"]["source"] == "provider_default"
    assert "not a US ZIP" in result["speech"] and "all-store catalog" in result["speech"]
    assert "no local availability is established" in result["speech"]
    trader.http_request.assert_not_called()


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_configured_store_takes_precedence_over_foreign_shared_postal_default(
    isolated, monkeypatch, capsys, tool,
):
    isolated.update(JARVIS_DEFAULT_POSTAL_CODE="SW1A1AA", JARVIS_TRADER_JOES_STORE_ID="454")
    free, _response = stores(monkeypatch)
    paid = provider(monkeypatch, tool, search_payload() if tool is search_tool else product_payload())
    options = {"query": "coffee"} if tool is search_tool else {"product_id": "080794"}
    code, result = run(monkeypatch, capsys, tool, options)
    assert code == 0 and result["ok"] is True
    assert paid.call_count == 1 and free.call_count == 1 and paid.call_args.args[0]["store_id"] == "454"
    assert result["data"]["location_context"]["source"] == "configured_store"
    assert result["data"]["location_context"]["store_postal_code"] == "78759"
    assert "Selected Trader Joe's store 454" in result["speech"] and "Austin" in result["speech"]


@pytest.mark.parametrize("tool", [search_tool, product_tool])
def test_invalid_explicit_postal_is_rejected_even_with_a_configured_store(
    isolated, monkeypatch, capsys, tool,
):
    isolated["JARVIS_TRADER_JOES_STORE_ID"] = "454"
    options = {"query": "coffee"} if tool is search_tool else {"product_id": "080794"}
    code, result = run(monkeypatch, capsys, tool, {**options, "postal_code": "SW1A1AA"})
    assert code == 1 and result["ok"] is False and "US ZIP" in result["error"]
    tool.request_serpapi.assert_not_called()
    trader.http_request.assert_not_called()


def test_product_display_filters_roundtrip_through_schema_to_exact_provider_csv(monkeypatch, capsys):
    original = product_payload()["product_results"]
    original["characteristics"] = ["Gluten Free", "Vegan", "gluten_free", " vegan "]
    original["fun_tags"] = ["Rise & Shine", "Let's Bake!", 'The "X" Factor', "rise_and_shine", "Merry-making"]
    untouched = deepcopy(original)
    normalized = trader.normalize_product(original, detail=True)
    expected = {"characteristics": ["gluten_free", "vegan"],
                "tags": ["rise_and_shine", "lets_bake", "the_x_factor", "merry_making"]}
    assert normalized["search_filters"] == expected
    assert normalized["characteristics"] == original["characteristics"]
    assert normalized["fun_tags"] == original["fun_tags"] and original == untouched
    options = {"query": "coffee", "characteristics": normalized["characteristics"], "tags": normalized["fun_tags"]}
    options_untouched = deepcopy(options)
    manifest = json.loads((ROOT / "skills/serpapi_trader_joes_search.tool.json").read_text())
    validate(options, manifest["parameters"])
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, options)
    assert code == 0 and result["ok"] is True and paid.call_count == 1
    assert paid.call_args.args[0]["characteristics"] == "gluten_free,vegan"
    assert paid.call_args.args[0]["tags"] == "rise_and_shine,lets_bake,the_x_factor,merry_making"
    assert result["data"]["requested_filters"] == expected and options == options_untouched
    trader.http_request.assert_not_called()


@pytest.mark.parametrize("labels", [{}, {"characteristics": [], "fun_tags": []},
                                   {"characteristics": ["Unknown Dietary Label"], "fun_tags": ["Unknown Occasion"]}])
def test_absent_empty_or_unmapped_provider_labels_do_not_become_empty_derived_evidence(labels):
    product = {**row(), **labels}
    for detail in (False, True):
        normalized = trader.normalize_product(product, detail=detail)
        assert "search_filters" not in normalized
        if detail:
            for field in ("characteristics", "fun_tags"):
                if field in labels:
                    assert normalized[field] == labels[field]


@pytest.mark.parametrize(("labels", "expected"), [
    ({"characteristics": ["Gluten Free"], "fun_tags": []}, {"characteristics": ["gluten_free"]}),
    ({"fun_tags": ["Rise & Shine"]}, {"tags": ["rise_and_shine"]}),
])
def test_only_known_nonempty_filter_fields_are_returned(labels, expected):
    product = {**row(), **labels}
    assert trader.normalize_product(product, detail=True)["search_filters"] == expected


@pytest.mark.parametrize(("label", "identifier"), [
    ("Kosher", "kosher"), ("Organic", "organic"), ("Gluten Free", "gluten_free"),
    ("Vegan", "vegan"), ("Antibiotic Free", "antibiotic_free"), ("Dairy Free", "dairy_free"),
    ("Grass Fed", "grass_fed"), ("Vegetarian", "vegetarian"), ("Fair Trade", "fair_trade"),
])
def test_all_documented_characteristic_labels_accept_case_variants_and_deduplicate(
    monkeypatch, capsys, label, identifier,
):
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, {
        "query": "coffee", "characteristics": [label.swapcase(), identifier, " " + label + " "],
    })
    assert code == 0 and paid.call_args.args[0]["characteristics"] == identifier
    assert result["data"]["requested_filters"]["characteristics"] == [identifier]


def test_normalized_filter_ids_are_reusable_while_unknown_display_labels_stay_unmapped(monkeypatch, capsys):
    original = product_payload()["product_results"]
    original["characteristics"].append("Unrecognized Dietary Label")
    original["fun_tags"].append("Unrecognized Occasion")
    normalized = trader.normalize_product(original, detail=True)
    assert normalized["characteristics"] == original["characteristics"]
    assert normalized["fun_tags"] == original["fun_tags"]
    assert normalized["search_filters"] == {"characteristics": ["vegan", "gluten_free"], "tags": ["rise_and_shine"]}
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee", **normalized["search_filters"]})
    assert code == 0 and result["ok"] is True
    assert paid.call_args.args[0]["characteristics"] == "vegan,gluten_free"
    assert paid.call_args.args[0]["tags"] == "rise_and_shine"


@pytest.mark.parametrize("filters", [
    {"characteristics": ["Unrecognized Dietary Label"]}, {"tags": ["Unrecognized Occasion"]},
    {"tags": ["rise & shine elsewhere"]}, {"tags": ["arbitrary_tag_" + "x" * 80]},
])
def test_unknown_human_filter_labels_fail_before_directory_and_paid_requests(monkeypatch, capsys, filters):
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee", "store_id": "454", **filters})
    assert code == 1 and result["ok"] is False
    search_tool.request_serpapi.assert_not_called()
    trader.http_request.assert_not_called()


def test_valid_snake_case_tags_remain_accepted_without_guessing_human_aliases(monkeypatch, capsys):
    paid = provider(monkeypatch, search_tool, search_payload())
    code, result = run(monkeypatch, capsys, search_tool, {"query": "coffee", "tags": ["future_provider_tag", "date_night"]})
    assert code == 0 and result["ok"] is True
    assert paid.call_args.args[0]["tags"] == "future_provider_tag,date_night"
