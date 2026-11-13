"""Regression coverage for current retailer request and product-evidence contracts."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))

import serpapi_amazon_search as amazon  # noqa: E402
import serpapi_ebay_search as ebay  # noqa: E402
import serpapi_home_depot as home_depot  # noqa: E402
from serpapi_client import extract_generic_results  # noqa: E402
from tool_child_environment import restrict_child_environment  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for tool in (amazon, ebay, home_depot):
        monkeypatch.setattr(tool, "load_config", lambda: None)
        monkeypatch.setattr(tool, "get_proxy_enabled", lambda: False)
        monkeypatch.setattr(tool, "request_serpapi", Mock(side_effect=AssertionError("Unexpected paid request")))
    for tool in (amazon, home_depot):
        monkeypatch.setattr(tool, "get_config_value", Mock(return_value="12345"))


def run(monkeypatch, capsys, tool, options):
    monkeypatch.setattr(sys, "argv", [tool.__name__ + ".py", json.dumps(options)])
    code = tool.main()
    return code, json.loads(capsys.readouterr().out)


def amazon_payload(*, detail=False):
    product = {"title": "Fixture coffee", "asin": "B000000001", "price": "$10",
               "link": "https://www.amazon.com/dp/B000000001", "prime": False, "stock": "In Stock"}
    if detail:
        return {"product_results": product, "item_ingredients": ["COFFEE", "WATER"],
                "important_information": [{"title": "Safety Information", "text": "Contains caffeine."},
                                          {"title": "Directions", "text": "Keep chilled."}]}
    return {"organic_results": [product]}


@pytest.mark.parametrize("domain", ["amazon.ae", "amazon.eg", "amazon.sa"])
@pytest.mark.parametrize("engine", ["amazon", "amazon_product"])
def test_city_marketplaces_never_borrow_configured_postal_and_city_is_optional(monkeypatch, capsys, domain, engine):
    request = Mock(return_value=amazon_payload(detail=engine == "amazon_product"))
    monkeypatch.setattr(amazon, "request_serpapi", request)
    options = {"engine": engine, "query": "coffee", "asin": "B000000001", "amazon_domain": domain, "optimize_query": False}
    code, result = run(monkeypatch, capsys, amazon, options)
    assert code == 0 and result["ok"] is True and request.call_count == 1
    sent = request.call_args.args[0]
    assert "delivery_zip" not in sent and "delivery_city" not in sent and "language" not in sent
    amazon.get_config_value.assert_not_called()
    assert result["data"]["delivery_localized"] is False and result["data"]["delivery_location_source"] == "none"
    assert "provider defaults apply" in result["data"]["delivery_location_note"]


@pytest.mark.parametrize("advanced", [False, True])
def test_city_and_domain_are_reused_for_every_enriched_product(monkeypatch, capsys, advanced):
    request = Mock(side_effect=[amazon_payload(), amazon_payload(detail=True)])
    monkeypatch.setattr(amazon, "request_serpapi", request)
    options = {"engine": "amazon", "query": "coffee", "amazon_domain": "amazon.ae", "language": "en_AE",
               "shipping_location": "AE", "include_product_details": True, "optimize_query": False}
    options.update({"extra_params": {"delivery_city": "Dubai"}} if advanced else {"delivery_city": "Dubai"})
    code, result = run(monkeypatch, capsys, amazon, options)
    assert code == 0 and request.call_count == 2
    for call in request.call_args_list:
        assert call.args[0]["delivery_city"] == "Dubai" and "delivery_zip" not in call.args[0]
        assert call.args[0]["amazon_domain"] == "amazon.ae" and call.args[0]["language"] == "en_AE"
        assert call.args[0]["shipping_location"] == "AE"
    data = result["data"]
    assert data["delivery_city"] == "Dubai" and data["delivery_zip"] is None
    assert data["delivery_localized"] is True and data["delivery_location_source"] == "explicit_city"
    assert data["results"][0]["item_ingredients"] == ["COFFEE", "WATER"]
    assert data["results"][0]["important_information"][0]["text"] == "Contains caffeine."
    assert data["results"][0]["product_evidence_truncated"] is False


@pytest.mark.parametrize("options", [
    {"amazon_domain": "amazon.ae", "delivery_zip": "12345"},
    {"amazon_domain": "amazon.com", "delivery_city": "Dubai"},
    {"amazon_domain": "amazon.ae", "delivery_city": "Dubai", "delivery_zip": "12345"},
    {"amazon_domain": "amazon.ae", "delivery_city": "Dubai", "extra_params": {"delivery_city": "Cairo"}},
    {"amazon_domain": "amazon.ae", "extra_params": {"delivery_city": 123}},
])
def test_conflicting_or_unsupported_delivery_arguments_fail_before_request(monkeypatch, capsys, options):
    code, result = run(monkeypatch, capsys, amazon, {"engine": "amazon", "query": "coffee", **options})
    assert code == 1 and result["ok"] is False and "delivery_" in result["error"]
    amazon.request_serpapi.assert_not_called()


def test_us_postal_default_and_existing_advanced_filters_are_preserved(monkeypatch, capsys):
    request = Mock(return_value=amazon_payload())
    monkeypatch.setattr(amazon, "request_serpapi", request)
    code, result = run(monkeypatch, capsys, amazon, {
        "engine": "amazon", "query": "coffee", "extra_params": {"delivery_zip": None, "emi": "merchant", "i": "grocery"},
    })
    assert code == 0 and request.call_count == 1
    sent = request.call_args.args[0]
    assert sent["delivery_zip"] == "12345" and sent["language"] == "en_US"
    assert sent["emi"] == "merchant" and sent["i"] == "grocery"
    assert result["data"]["delivery_location_source"] == "jarvis_default"


def test_focused_product_evidence_is_available_without_raw_and_keeps_source_unchanged(monkeypatch, capsys):
    source = amazon_payload(detail=True)
    untouched = deepcopy(source)
    monkeypatch.setattr(amazon, "request_serpapi", Mock(return_value=source))
    code, result = run(monkeypatch, capsys, amazon, {"engine": "amazon_product", "asin": "B000000001"})
    assert code == 0 and "raw" not in result["data"] and source == untouched
    row = result["data"]["results"][0]
    assert row["item_ingredients"] == source["item_ingredients"]
    assert row["important_information"] == source["important_information"]
    assert row["prime"] is False and row["product_evidence_truncated"] is False


def test_large_product_evidence_is_bounded_and_marked_while_warnings_keep_room():
    source = amazon_payload(detail=True)
    source["item_ingredients"] = ["ingredient " * 1000] * 40
    source["important_information"] = [{"title": "Safety Information", "text": "注意" * 10000}] * 40
    row = extract_generic_results(source, "amazon_product", 1)[0]
    ingredients = sum(map(len, row["item_ingredients"]))
    warnings = sum(len(value) for section in row["important_information"] for value in section.values())
    assert ingredients <= 1500 and ingredients + warnings <= 4000
    assert row["important_information"][0]["title"] == "Safety Information"
    assert len(row["important_information"][0]["text"]) >= 1000
    assert row["product_evidence_truncated"] is True


@pytest.mark.parametrize("size", [60, 120, 240])
def test_current_ebay_page_sizes_are_forwarded_with_ordinary_filters(monkeypatch, capsys, size):
    request = Mock(return_value={"organic_results": []})
    monkeypatch.setattr(ebay, "request_serpapi", request)
    code, result = run(monkeypatch, capsys, ebay, {"query": "coffee", "_ipg": size, "show_only": "FS,RPA"})
    assert code == 0 and result["ok"] is True and request.call_count == 1
    assert request.call_args.args[0]["_ipg"] == size and request.call_args.args[0]["show_only"] == "FS,RPA"


@pytest.mark.parametrize("options", [
    *[{"_ipg": value} for value in (25, 50, 100, 200, 33, True, 120.5, "120")],
    *[{"show_only": value} for value in ("Sold", "Complete", "sold,FS", " FR , CoMpLeTe ", "Completed")],
])
def test_obsolete_ebay_filters_and_page_sizes_are_rejected_before_network(monkeypatch, capsys, options):
    code, result = run(monkeypatch, capsys, ebay, {"query": "coffee", **options})
    assert code == 1 and result["ok"] is False
    ebay.request_serpapi.assert_not_called()
    assert "supported" in result["error"]


def hd_payload(*, available="Discontinued"):
    return {"product_results": {"product_id": "304163165", "store_sku_number": "1002991354", "title": "Fixture cement board",
                                "link": "https://www.homedepot.com/p/fixture/304163165", "price": 0,
                                "availability_type": available}}


def test_store_sku_lookup_returns_resolved_id_and_discloses_ambiguity_without_raw(monkeypatch, capsys):
    source = hd_payload()
    request = Mock(return_value=source)
    monkeypatch.setattr(home_depot, "request_serpapi", request)
    code, result = run(monkeypatch, capsys, home_depot, {
        "store_sku": "1002991354", "store_id": "123", "extra_params": {"store_sku": "999", "delivery_zip": "99999"},
    })
    assert code == 0 and request.call_count == 1
    sent = request.call_args.args[0]
    assert sent["engine"] == "home_depot_product" and sent["store_sku"] == "1002991354" and "product_id" not in sent
    assert sent["delivery_zip"] == "12345" and sent["store_id"] == "123"
    data = result["data"]
    assert data["product_id"] == "304163165" and data["requested_store_sku"] == "1002991354"
    assert "can match several products" in data["lookup_note"] and "can vary" in result["speech"]
    assert "raw" not in data and data["product_details"]["availability_type"] == "Discontinued"
    assert data["results"][0]["price"] == 0
    assert data["results"][0]["product_id"] != data["requested_store_sku"]


@pytest.mark.parametrize("status", ["Available", "Limited Stock", "In Stock Nearby", "Limited Stock Nearby", "Unavailable", "Out of Stock", "Discontinued"])
def test_product_availability_is_preserved_exactly_in_focused_results(monkeypatch, capsys, status):
    monkeypatch.setattr(home_depot, "request_serpapi", Mock(return_value=hd_payload(available=status)))
    code, result = run(monkeypatch, capsys, home_depot, {"product_id": "304163165"})
    assert code == 0 and result["data"]["results"][0]["availability_type"] == status
    assert result["data"]["product_details"]["availability_type"] == status


@pytest.mark.parametrize(("country", "field", "size"), [("us", "ps", 24), ("ca", "pagesize", 40)])
def test_current_home_depot_page_caps_forward_at_the_boundary(monkeypatch, capsys, country, field, size):
    request = Mock(return_value={"products": []})
    monkeypatch.setattr(home_depot, "request_serpapi", request)
    code, _result = run(monkeypatch, capsys, home_depot, {"query": "drill", "country": country, field: size})
    assert code == 0 and request.call_args.args[0][field] == size
    if country == "ca":
        assert "delivery_zip" not in request.call_args.args[0]


@pytest.mark.parametrize("options", [
    {"query": "drill", "ps": 48}, {"query": "drill", "ps": 25}, {"query": "drill", "ps": True},
    {"query": "drill", "country": "ca", "pagesize": 41}, {"store_sku": 1002991354},
    {"store_sku": "../../private"}, {"store_sku": "1002991354", "query": "board"},
    {"store_sku": "1002991354", "product_id": "304163165"}, {"store_sku": "1002991354", "country": "ca"},
])
def test_invalid_home_depot_caps_or_sku_combinations_fail_without_paid_request(monkeypatch, capsys, options):
    code, result = run(monkeypatch, capsys, home_depot, options)
    assert code == 1 and result["ok"] is False
    home_depot.request_serpapi.assert_not_called()


@pytest.mark.parametrize(("tool", "optional"), [(amazon, {"JARVIS_DEFAULT_POSTAL_CODE"}), (home_depot, {"JARVIS_DEFAULT_POSTAL_CODE"}), (ebay, set())])
def test_updated_tools_pass_only_reviewed_credentials_and_optional_defaults(tool, optional):
    path = ROOT / "skills" / (tool.__name__ + ".tool.json")
    schema = ToolSchema.from_json_file(str(path))
    assert schema.child_environment_names == frozenset({"SERP_API_KEY", *optional})
    manifest = json.loads(path.read_text())
    assert manifest["prompt_guard_policy"] == "web_content"
    child = restrict_child_environment({"PATH": "/usr/bin", "JARVIS_MODE": "cloud", "SERP_API_KEY": "selected-key",
                                        "JARVIS_DEFAULT_POSTAL_CODE": "12345", "OPENAI_API_KEY": "unrelated-secret"},
                                       schema.child_environment_names, home="/tmp/retailer-test", proxy_policy="off")
    assert child["SERP_API_KEY"] == "selected-key" and "OPENAI_API_KEY" not in child
    assert ("JARVIS_DEFAULT_POSTAL_CODE" in child) == bool(optional)


def test_updated_schemas_accept_new_arguments_and_declare_current_limits():
    schemas = {name: json.loads((ROOT / "skills" / f"serpapi_{name}.tool.json").read_text())["parameters"]
               for name in ("amazon_search", "ebay_search", "home_depot")}
    validate({"engine": "amazon", "query": "coffee", "amazon_domain": "amazon.ae", "delivery_city": "Dubai"}, schemas["amazon_search"])
    validate({"query": "coffee", "_ipg": 240}, schemas["ebay_search"])
    validate({"store_sku": "1002991354"}, schemas["home_depot"])
    assert schemas["ebay_search"]["properties"]["_ipg"]["enum"] == [60, 120, 240]
    assert schemas["home_depot"]["properties"]["ps"]["maximum"] == 24
    assert schemas["home_depot"]["properties"]["pagesize"]["maximum"] == 40
