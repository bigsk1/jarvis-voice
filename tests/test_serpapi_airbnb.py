"""Airbnb destination, date, price and listing identity contracts without paid calls."""
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

import config_loader  # noqa: E402
import serpapi_airbnb as airbnb  # noqa: E402
import serpapi_airbnb_search as tool  # noqa: E402
from tool_child_environment import restrict_child_environment  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


def listing(identifier="1516509370603548960", **overrides):
    return {
        "listing_id": identifier, "name": "Fixture garden house", "title": "Home in Austin",
        "description": "A quiet garden house.", "position": 1,
        "link": f"https://www.airbnb.com/rooms/{identifier}?check_in=2026-12-11&check_out=2026-12-15&adults=2",
        "price": "$792", "extracted_price": 792, "price_qualifier": "for 4 nights",
        "old_price": "$900", "extracted_old_price": 900,
        "price_breakdown": [{"description": "4 nights x $200", "price": "$800.00", "extracted_price": 800},
                            {"description": "Discount", "price": "-$8.00", "extracted_price": -8}],
        "check_in_date": "2026-12-11", "check_out_date": "2026-12-15",
        "rating": 4.93, "reviews": 440, "bedrooms": 2, "beds": 2, "bathrooms": 1.5,
        "details": ["2 bedrooms", "2 beds", "1.5 baths"], "badges": ["Guest favorite"],
        "highlights": ["Pay $0 today", "Free cancellation"], "free_cancellation": True,
        "gps_coordinates": {"latitude": 30.24956, "longitude": -97.74774},
        "thumbnail": f"https://a0.muscache.com/im/pictures/{identifier}/front.jpeg",
        "images": [f"https://a0.muscache.com/im/pictures/{identifier}/front.jpeg",
                   f"https://a0.muscache.com/im/pictures/{identifier}/back.jpeg"],
        **overrides,
    }


def payload(count=2):
    return {
        "search_metadata": {"status": "Success", "id": "fixture-search", "json_endpoint": "https://serpapi.com/private?api_key=PRIVATE_SENTINEL"},
        "search_parameters": {"engine": "airbnb", "currency": "USD"},
        "search_information": {"total_results": 500, "query_displayed": "Austin, TX"},
        "organic_results": [listing(str(1516509370603548960 + index)) for index in range(count)],
        "serpapi_pagination": {"next": "https://serpapi.com/search.json?page=2&api_key=PRIVATE_SENTINEL",
                              "other_pages": {str(index): "https://serpapi.com/private?api_key=PRIVATE_SENTINEL" for index in range(2, 100)}},
    }


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(tool, "load_config", lambda: None)
    monkeypatch.setattr(tool, "request_serpapi", Mock(side_effect=AssertionError("Unexpected paid request")))


def provider(monkeypatch, value=None):
    request = Mock(return_value=deepcopy(payload() if value is None else value))
    monkeypatch.setattr(tool, "request_serpapi", request)
    return request


def run(monkeypatch, capsys, options):
    monkeypatch.setattr(sys, "argv", ["serpapi_airbnb_search.py", json.dumps(options)])
    code = tool.main()
    return code, json.loads(capsys.readouterr().out)


def test_default_search_uses_explicit_destination_and_converts_nightly_budget_once(monkeypatch, capsys):
    request = provider(monkeypatch)
    monkeypatch.setattr(config_loader, "get_config_value", Mock(side_effect=AssertionError("No location lookup allowed")))
    monkeypatch.setenv("JARVIS_DEFAULT_LOCATION", "Never use this city")
    monkeypatch.setenv("JARVIS_DEFAULT_POSTAL_CODE", "99999")
    code, result = run(monkeypatch, capsys, {"query": " Austin, TX "})
    assert code == 0 and result["ok"] is True and request.call_count == 1
    assert request.call_args.args[0] == {
        "engine": "airbnb", "q": "Austin, TX", "currency": "USD", "room_type": "entire_home",
        "property_types": "house", "adults": 2, "page": 1, "no_cache": "false", "min_price": 625, "max_price": 1250,
    }
    assert request.call_args.kwargs == {"timeout": 60, "max_response_bytes": 2097152,
                                        "use_proxy": False, "fallback_on_proxy_fail": False}
    data = result["data"]
    assert data["dates_mode"] == "suggested" and data["search_context"]["check_in_date"] is None
    assert data["budget_context"]["filter_nights"] == 5
    assert data["budget_context"]["min_price_per_night"] == 125 and data["budget_context"]["max_price_per_night"] == 250
    assert data["search_context"]["property_types"] == ["house"]
    assert "suggested dates" in result["speech"] and "stay totals" in result["speech"]
    assert "5 nights" in data["budget_context"]["note"] and "actual stay lengths can differ" in data["budget_context"]["note"]
    assert "not guaranteed detached" in data["booking_caveat"] and "no smoke-free or pet-free" in data["booking_caveat"].lower()
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    assert data["pagination"] == {"current": 1, "has_next": True, "next_page": 2}
    assert data["requested_parameters"] == {"query": " Austin, TX "}
    assert data["effective_parameters"] == request.call_args.args[0]
    assert "entire homes; houses; 2 adults" in result["speech"]
    assert "USD 125 to 250 per night" in result["speech"]
    assert "multiplied" not in result["speech"]


def test_explicit_dates_convert_custom_budget_and_forward_documented_filters(monkeypatch, capsys):
    request = provider(monkeypatch)
    options = {
        "query": "Austin, TX", "check_in_date": "2026-12-11", "check_out_date": "2026-12-15",
        "adults": 4, "children": 1, "infants": 1, "pets": 2, "property_types": ["house", "guesthouse", "house"],
        "amenities": ["wifi", "smoking_allowed", "wifi"], "bedrooms": 2, "beds": 3, "bathrooms": 1.5,
        "instant_book": True, "self_check_in": False, "guest_favorite": True, "luxe": False,
        "min_price_per_night": 125.25, "max_price_per_night": 249.99, "currency": "EUR", "page": 2, "no_cache": True,
    }
    untouched = deepcopy(options)
    code, result = run(monkeypatch, capsys, options)
    sent = request.call_args.args[0]
    assert code == 0 and request.call_count == 1 and options == untouched
    assert sent["min_price"] == 501 and sent["max_price"] == 999.96
    assert sent["property_types"] == "house,guesthouse" and sent["amenities"] == "wifi,smoking_allowed"
    assert sent["instant_book"] == "true" and sent["self_check_in"] == "false"
    assert sent["guest_favorite"] == "true" and sent["luxe"] == "false" and sent["no_cache"] == "true"
    assert sent["children"] == 1 and sent["infants"] == 1 and sent["pets"] == 2
    assert sent["bedrooms"] == 2 and sent["beds"] == 3 and sent["bathrooms"] == 1.5
    assert result["data"]["dates_mode"] == "explicit" and result["data"]["search_context"]["nights"] == 4
    assert result["data"]["requested_filters"]["self_check_in"] is False
    assert result["data"]["results"][0]["currency"] == "EUR"
    speech = result["speech"]
    assert "houses, guesthouses" in speech
    assert "4 adults, 1 child, 1 infant, 2 pets" in speech
    assert "Required amenities: Wi-Fi, smoking allowed" in speech
    assert "EUR 125.25 to 249.99 per night" in speech
    assert "2026-12-11 to 2026-12-15" in speech


def test_speech_reports_the_reviewed_party_and_amenities_without_another_request(monkeypatch, capsys):
    request = provider(monkeypatch)
    code, result = run(monkeypatch, capsys, {"query": "Austin", "children": 3, "infants": 1,
                                          "pets": 2, "amenities": ["pool", "wifi"]})
    assert code == 0 and request.call_count == 1
    assert "entire homes; houses; 2 adults, 3 children, 1 infant, 2 pets" in result["speech"]
    assert "Required amenities: pool, Wi-Fi" in result["speech"]
    assert "USD 125 to 250 per night" in result["speech"]
    assert "budget assumes 5 nights" in result["speech"]


@pytest.mark.parametrize(("extra", "expected", "absent"), [
    ({"max_price_per_night": 100}, "USD up to 100 per night", "125"),
    ({"min_price_per_night": 0}, "USD at least 0 per night", "250"),
    ({"use_price_filter": False}, "No price filter applied", "per night"),
    ({"room_type": "private_room"}, "private rooms; any property type; 2 adults", "houses"),
    ({"room_type": "private_room", "property_types": ["apartment"], "adults": 1, "pets": 1},
     "private rooms; apartments; 1 adult, 1 pet", "2 adults"),
])
def test_speech_preserves_one_sided_and_disabled_budgets_and_property_overrides(
    monkeypatch, capsys, extra, expected, absent,
):
    provider(monkeypatch)
    code, result = run(monkeypatch, capsys, {"query": "Austin", **extra})
    assert code == 0 and expected in result["speech"]
    assert absent not in result["speech"]
    assert "0 pets" not in result["speech"] and "pet-free" not in result["speech"]


@pytest.mark.parametrize(("extra", "expected"), [
    ({"max_price_per_night": 100}, {"max_price": 500}),
    ({"min_price_per_night": 300}, {"min_price": 1500}),
    ({"use_price_filter": False}, {}),
    ({"use_price_filter": False, "min_price_per_night": 0, "max_price_per_night": 100}, {}),
])
def test_custom_single_bound_replaces_defaults_and_price_filter_can_be_disabled(monkeypatch, capsys, extra, expected):
    request = provider(monkeypatch)
    code, result = run(monkeypatch, capsys, {"query": "Lake Tahoe", **extra})
    assert code == 0 and {key: value for key, value in request.call_args.args[0].items() if key in {"min_price", "max_price"}} == expected
    if extra.get("use_price_filter") is False:
        assert result["data"]["budget_context"]["enabled"] is False
        assert "No price filter applied" in result["data"]["budget_context"]["note"]


@pytest.mark.parametrize(("extra", "expected"), [
    ({"room_type": "private_room"}, None), ({"property_types": []}, None),
    ({"room_type": "private_room", "property_types": ["apartment"]}, "apartment"),
])
def test_room_override_does_not_retain_a_conflicting_default_house(monkeypatch, capsys, extra, expected):
    request = provider(monkeypatch)
    code, _result = run(monkeypatch, capsys, {"query": "Austin", "pets": 0, **extra})
    assert code == 0 and request.call_args.args[0].get("property_types") == expected
    assert "pets" not in request.call_args.args[0]


@pytest.mark.parametrize("options", [
    {}, {"query": ""}, {"query": " "}, {"query": 12}, {"query": "x" * 401},
    {"query": "Austin", "check_in_date": "2026-12-11"},
    {"query": "Austin", "check_out_date": "2026-12-15"},
    {"query": "Austin", "check_in_date": "2026-02-30", "check_out_date": "2026-03-02"},
    {"query": "Austin", "check_in_date": "2026-1-01", "check_out_date": "2026-12-15"},
    {"query": "Austin", "check_in_date": "2026-12-15", "check_out_date": "2026-12-15"},
    {"query": "Austin", "check_in_date": "2026-12-16", "check_out_date": "2026-12-15"},
    *[{"query": "Austin", **bad} for bad in [
        {"adults": 0}, {"adults": True}, {"children": -1}, {"pets": "1"}, {"infants": 51},
        {"page": 0}, {"page": 16}, {"num_results": "5"}, {"min_price_per_night": -1},
        {"min_price_per_night": True}, {"max_price_per_night": float("inf")}, {"bathrooms": float("nan")},
        {"min_price_per_night": 300, "max_price_per_night": 100}, {"currency": "usd"}, {"currency": "US"},
        {"room_type": "shared_room"}, {"property_types": ["castle"]}, {"amenities": ["non_smoking"]},
        {"amenities": ["pet_free"]}, {"amenities": "wifi"}, {"instant_book": "false"},
        {"raw": True}, {"extra_params": {"q": "elsewhere"}}, {"map_bounds": "30,-97,29,-98"},
    ]], None, [], "Austin", 12,
])
def test_invalid_inputs_fail_before_any_paid_request(monkeypatch, capsys, options):
    code, result = run(monkeypatch, capsys, options)
    assert code == 1 and result["ok"] is False
    tool.request_serpapi.assert_not_called()


def test_listing_owns_its_images_dates_total_breakdown_and_fee_inclusive_average(monkeypatch, capsys):
    source = payload()
    source["organic_results"][1].update(check_in_date="2026-12-20", check_out_date="2026-12-25", price_qualifier="for 5 nights")
    provider(monkeypatch, source)
    code, result = run(monkeypatch, capsys, {"query": "Austin"})
    first, second = result["data"]["results"]
    assert code == 0 and first["listing_id"] == "1516509370603548960"
    assert first["url"] == source["organic_results"][0]["link"]
    assert first["image_url"] == source["organic_results"][0]["thumbnail"] and first["image_url"] != second["image_url"]
    assert first["total_price"] == 792 and first["price_formatted"] == "$792" and first["price_qualifier"] == "for 4 nights"
    assert first["nightly_average"] == 198 and "including fees" in first["nightly_average_note"]
    assert first["nights"] == 4 and second["nights"] == 5 and second["nightly_average"] == 158.4
    assert first["check_in_date"] == "2026-12-11" and second["check_in_date"] == "2026-12-20"
    assert first["price_breakdown"][1]["extracted_price"] == -8
    assert first["old_total_price"] == 900 and first["old_price_formatted"] == "$900"
    assert first["bedrooms"] == 2 and first["bathrooms"] == 1.5 and first["reviews"] == 440


def test_zero_false_and_missing_fields_remain_distinct():
    zero = airbnb.normalize_listing(listing(extracted_price=0, price="$0", rating=0, reviews=0, bedrooms=0,
                                          beds=0, bathrooms=0, free_cancellation=False, is_new_listing=False,
                                          gps_coordinates={"latitude": 0, "longitude": 0}),
                                    currency="USD", dates_mode="explicit", position=1)
    assert zero is not None
    assert zero["total_price"] == 0 and zero["nightly_average"] == 0 and zero["price_formatted"] == "$0"
    assert zero["rating"] == zero["reviews"] == zero["bedrooms"] == zero["beds"] == zero["bathrooms"] == 0
    assert zero["free_cancellation"] is False and zero["is_new_listing"] is False
    assert zero["gps_coordinates"] == {"latitude": 0, "longitude": 0}
    missing = airbnb.normalize_listing({"listing_id": "000123"}, currency="USD", dates_mode="suggested", position=2)
    assert missing is not None and missing["listing_id"] == "000123"
    assert all(missing[key] is None for key in ("total_price", "price_formatted", "nightly_average", "free_cancellation", "rating", "reviews", "nights"))


@pytest.mark.parametrize(("overrides", "nights", "average"), [
    ({"check_in_date": None, "check_out_date": None, "price_qualifier": "for 4 nights"}, 4, 198),
    ({"check_in_date": None, "check_out_date": None, "price_qualifier": "total"}, None, None),
    ({"price_qualifier": "for 5 nights"}, 4, None),
    ({"check_in_date": "not a date", "check_out_date": "bad", "price_qualifier": "total"}, None, None),
])
def test_average_uses_returned_nights_and_never_the_default_filter_assumption(overrides, nights, average):
    result = airbnb.normalize_listing(listing(**overrides), currency="USD", dates_mode="suggested", position=1)
    assert result is not None and result["nights"] == nights and result["nightly_average"] == average


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/rooms/1516509370603548960", "file:///etc/passwd", "https://airbnb.com.attacker.test/rooms/1516509370603548960",
    "https://user:pass@www.airbnb.com/rooms/1516509370603548960", "https://www.airbnb.com:9000/rooms/1516509370603548960",
    "https://www.airbnb.com\\@attacker.test/rooms/1516509370603548960", "https://www.airbnb.com/s/Austin/homes",
])
def test_invalid_listing_urls_cannot_become_clickable_sources(url):
    result = airbnb.normalize_listing(listing(link=url), currency="USD", dates_mode="suggested", position=1)
    assert result is not None and result["url"] is None


def test_mismatched_listing_identity_is_rejected_and_url_can_supply_missing_identity():
    assert airbnb.normalize_listing(listing(listing_id="123"), currency="USD", dates_mode="suggested", position=1) is None
    result = airbnb.normalize_listing(listing(listing_id=None), currency="USD", dates_mode="suggested", position=1)
    assert result is not None and result["listing_id"] == "1516509370603548960"


@pytest.mark.parametrize(("count", "expected"), [(0, 1), (100, 10)])
def test_bounded_listing_count_never_fans_out_to_extra_paid_calls(monkeypatch, capsys, count, expected):
    request = provider(monkeypatch, payload(18))
    code, result = run(monkeypatch, capsys, {"query": "Austin", "num_results": count})
    assert code == 0 and len(result["data"]["results"]) == expected and request.call_count == 1
    assert result["data"]["provider_results_count"] == 18 and result["data"]["results_truncated"] is True


@pytest.mark.parametrize("value", [None, [], {}, {"organic_results": None}, {"search_metadata": {"status": "Processing"}},
                                    {"search_parameters": {"engine": "google"}}, {"error": "api_key=PRIVATE_SENTINEL"}])
def test_malformed_incomplete_and_wrong_engine_results_are_structured_failures(monkeypatch, capsys, value):
    monkeypatch.setattr(tool, "request_serpapi", Mock(return_value=value))
    code, result = run(monkeypatch, capsys, {"query": "Austin"})
    assert code == 1 and result["ok"] is False and "PRIVATE_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize("value", [{"organic_results": []}, {"search_information": {"total_results": 0}}])
def test_explicit_empty_searches_are_success_without_invented_listings(monkeypatch, capsys, value):
    provider(monkeypatch, value)
    code, result = run(monkeypatch, capsys, {"query": "Austin", "page": 15})
    assert code == 0 and result["data"]["results"] == [] and result["data"]["results_count"] == 0
    assert result["data"]["pagination"]["has_next"] is False


def test_paid_errors_are_redacted_without_retry(monkeypatch, capsys):
    request = Mock(side_effect=RuntimeError("HTTP 401 api_key=PRIVATE_SENTINEL"))
    monkeypatch.setattr(tool, "request_serpapi", request)
    code, result = run(monkeypatch, capsys, {"query": "Austin"})
    assert code == 1 and result["ok"] is False and "401" in result["error"]
    assert "PRIVATE_SENTINEL" not in json.dumps(result) and request.call_count == 1


def test_oversized_unicode_details_and_pagination_fit_guard_budget_keep_ten_ids(monkeypatch, capsys):
    value = payload(10)
    for item in value["organic_results"]:
        item.update(description="房" * 10000, details=["detail" * 1000] * 20,
                    price_breakdown=[{"description": "line" * 1000, "price": "$1", "extracted_price": 1}] * 30,
                    images=[item["thumbnail"] + "?x=" + str(index) for index in range(30)])
    request = provider(monkeypatch, value)
    code, result = run(monkeypatch, capsys, {"query": "Austin", "num_results": 10})
    assert code == 0 and request.call_count == 1
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 60 * 1024
    assert len(result["data"]["results"]) == 10 and result["data"]["result_truncated"] is True
    assert [row["listing_id"] for row in result["data"]["results"]] == [row["listing_id"] for row in value["organic_results"]]


def test_manifest_accepts_documented_filters_and_child_has_only_serpapi_credential():
    manifest = json.loads((ROOT / "skills/serpapi_airbnb_search.tool.json").read_text())
    assert manifest["parameters"]["required"] == ["query"] and manifest["parameters"]["additionalProperties"] is False
    assert manifest["prompt_guard_policy"] == "web_content" and manifest["proxy_policy"] == "off"
    validate({"query": "Austin", "property_types": ["house"], "amenities": ["smoking_allowed"],
              "bathrooms": 1.5, "pets": 0, "self_check_in": False}, manifest["parameters"])
    schema = ToolSchema.from_json_file(str(ROOT / "skills/serpapi_airbnb_search.tool.json"))
    assert schema.child_environment_names == frozenset({"SERP_API_KEY"})
    child = restrict_child_environment({"PATH": "/usr/bin", "JARVIS_MODE": "cloud", "SERP_API_KEY": "mode-key",
                                        "JARVIS_OVERRIDE_SERP_API_KEY": "selected-key", "JARVIS_DEFAULT_LOCATION": "private city",
                                        "JARVIS_DEFAULT_POSTAL_CODE": "12345", "OPENAI_API_KEY": "other-secret"},
                                       schema.child_environment_names, home="/tmp/airbnb-test", proxy_policy="off")
    assert child["SERP_API_KEY"] == "selected-key"
    assert not {"JARVIS_DEFAULT_LOCATION", "JARVIS_DEFAULT_POSTAL_CODE", "OPENAI_API_KEY"} & child.keys()
