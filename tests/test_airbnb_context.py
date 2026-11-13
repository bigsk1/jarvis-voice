"""Airbnb destination, date/price basis and listing handles survive every model handoff."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

from lib.serpapi_airbnb_context import project_airbnb_data
from orchestrator.context_assembler import ContextAssembler
from orchestrator.router_v2 import build_tool_retrieval_signals

ROOT = Path(__file__).resolve().parents[1]
WEB_PACKAGE = "airbnb_context_web_server"
load_server_package(WEB_PACKAGE, ROOT / "jarvis-web" / "server")


@pytest.fixture
def assembler():
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    return ContextAssembler(
        timezone_obj=ZoneInfo("UTC"), auto_context_window=8, auto_context_minutes=180,
        safe_iso_to_local_datetime=lambda _value: None,
        format_age_seconds=lambda _value: "unknown", format_gap_for_prompt=lambda _value: "unknown",
        conversation_has_text_summary_for_ref=lambda _history, _ref: False,
        stash_ref_from_result=lambda _result, _arguments: "",
        get_memory_db_fn=Mock(side_effect=AssertionError("Unexpected DB access")),
        now_utc_fn=lambda: now, parse_utc_timestamp_fn=lambda _value: now,
    )


def search_data(query="Phoenix, Arizona"):
    return {
        "engine": "airbnb", "query": query, "currency": "USD", "page": 1,
        "dates_mode": "suggested", "results_count": 10,
        "requested_parameters": {"query": query},
        "effective_parameters": {"q": query, "min_price": 625, "max_price": 1250},
        "search_context": {"query": query, "adults": 2, "pets": 0, "dates_mode": "suggested",
                           "check_in_date": None, "check_out_date": None,
                           "room_type": "entire_home", "property_types": ["house"]},
        "budget_context": {"enabled": True, "min_price_per_night": 125, "max_price_per_night": 250,
                           "filter_nights": 5, "provider_min_price": 625, "provider_max_price": 1250},
        "requested_filters": {"room_type": "entire_home", "property_types": ["house"], "pets": 0},
        "pagination": {"current": 1, "has_next": True, "next_page": 2},
        "results": [{"position": i, "listing_id": f"9007199254740993{i:03d}",
                     "name": f"Desert house {i}", "title": "Home in Phoenix",
                     "url": f"https://www.airbnb.com/rooms/9007199254740993{i:03d}?check_in=2030-06-01&check_out=2030-06-06",
                     "image_url": f"https://a0.muscache.com/im/pictures/house-{i}.jpg",
                     "total_price": 0 if i == 1 else 750, "price_formatted": "$0" if i == 1 else "$750",
                     "price_qualifier": "for 5 nights", "nightly_average": 0 if i == 1 else 150,
                     "nightly_average_note": "Average stay total per night, including fees.",
                     "currency": "USD", "check_in_date": "2030-06-01", "check_out_date": "2030-06-06",
                     "nights": 5, "dates_mode": "suggested", "rating": 0 if i == 1 else 4.9,
                     "reviews": 0 if i == 1 else 42, "free_cancellation": False,
                     "bedrooms": 2, "beds": 2, "bathrooms": 1.5,
                     "description": "A quiet house near the desert."} for i in range(1, 11)],
    }


def extract_saved(data):
    from importlib import import_module

    extractor = import_module(f"{WEB_PACKAGE}.services.followup_extractor")
    return extractor.extract_followup_data({"serpapi_airbnb_search": data})["serpapi_airbnb_search"]


def test_projection_keeps_ten_exact_ids_distinct_price_bases_and_own_photos():
    data = search_data()
    original = deepcopy(data)
    result = project_airbnb_data(data)
    assert len(result["candidates"]) == 10
    for source, row in zip(data["results"], result["candidates"], strict=True):
        for field in ("listing_id", "url", "image_url", "total_price", "nightly_average",
                      "price_qualifier", "check_in_date", "check_out_date", "nights"):
            assert row[field] == source[field]
    assert result["candidates"][0]["rating"] == 0
    assert result["candidates"][0]["reviews"] == 0
    assert result["candidates"][0]["free_cancellation"] is False
    assert result["search_context"]["check_in_date"] is None
    assert result["search_context"]["pets"] == 0
    assert data == original
    assert project_airbnb_data(result) == result


@pytest.mark.parametrize("surface", ["immediate", "native", "saved", "accumulated", "candidates"])
def test_real_model_surfaces_keep_destination_budget_and_suggested_listing_dates(assembler, surface):
    data = search_data()
    envelope = {"ok": True, "data": data}
    if surface == "immediate":
        text, _, _, _ = assembler.build_llm_result_context_preview("serpapi_airbnb_search", envelope)
        result = json.loads(text)["data"]
    elif surface == "native":
        text, _ = assembler.build_provider_tool_result_message(
            tool_name="serpapi_airbnb_search", arguments={"query": data["query"]},
            result=envelope, max_chars=11000,
        )
        result = json.loads(text[text.index('{"result"'):])["result"]["data"]
    elif surface == "saved":
        result = json.loads(json.dumps(extract_saved(data), allow_nan=False))
    elif surface == "accumulated":
        text = assembler.extract_useful_data(
            {"serpapi_airbnb_search": data}, has_text_summarizer_summary_for_ref=lambda *_: False,
        )
        assert data["results"][9]["listing_id"] in text
        assert '"provider_max_price":1250' in text
        assert '"dates_mode":"suggested"' in text
        return
    else:
        candidates = assembler.build_source_candidates_preview(data, max_items=10, tool_name="serpapi_airbnb_search")
        assert len(candidates) == 10
        assert candidates[1]["total_price"] == 750
        assert candidates[1]["nightly_average"] == 150
        assert candidates[1]["price_qualifier"] == "for 5 nights"
        return
    assert result["query"] == data["query"]
    assert result["budget_context"]["provider_max_price"] == 1250
    assert result["search_context"]["adults"] == 2
    assert result["dates_mode"] == "suggested"
    assert len(result["candidates"]) == 10
    assert result["candidates"][9]["listing_id"] == data["results"][9]["listing_id"]
    assert result["candidates"][1]["total_price"] == 750
    assert result["candidates"][1]["nightly_average"] == 150


@pytest.mark.parametrize("budget", [128, 256, 1800, 5600, 9000])
def test_large_evidence_has_explicit_bounded_omissions_without_mutation(budget):
    data = search_data()
    for row in data["results"]:
        row["description"] = "A very long description " * 1000
        row["images"] = [row["image_url"]] * 30
    original = deepcopy(data)
    result = project_airbnb_data(data, max_chars=budget)
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= budget
    assert result["context_truncated"] is True
    assert data == original


def test_saved_repeated_runs_keep_order_and_failure_status():
    runs = [{"ok": True, "data": search_data("Phoenix")},
            {"ok": False, "error": "Provider unavailable", "data": {"query": "Tucson"}}]
    saved = extract_saved(runs)
    assert saved["runs_count"] == 2
    assert saved["results"][0]["query"] == "Phoenix"
    assert saved["results"][1]["query"] == "Tucson"
    assert saved["results"][1]["ok"] is False
    assert saved["results"][1]["error"] == "Provider unavailable"


def test_saved_projection_discards_nested_secrets_and_nonfinite_numbers():
    data = search_data()
    data["api_key"] = "SECRET_SENTINEL"
    data["requested_parameters"]["api_key"] = "SECRET_SENTINEL"
    data["results"][0]["rating"] = float("nan")
    data["results"][0]["price_breakdown"] = [{"description": "Five nights", "price": "$750", "token": "SECRET_SENTINEL"}]
    result = extract_saved(data)
    encoded = json.dumps(result, allow_nan=False)
    assert "SECRET_SENTINEL" not in encoded
    assert result["candidates"][0]["rating"] is None


@pytest.mark.parametrize("query", ["Show cheaper ones with a pool.", "What about Seattle instead?",
                                   "Keep the same dates but add one pet."])
def test_saved_refinements_retrieve_airbnb_without_local_location_defaults(assembler, query):
    history = [{"role": "assistant", "content": "Found houses in Phoenix.",
                "tool_results": {"serpapi_airbnb_search": extract_saved(search_data())}}]
    context = assembler.format_conversation_context(query, history)
    assert "Selected tool hints: serpapi_airbnb_search" in context
    assert "Never substitute local defaults" in context
    signals = build_tool_retrieval_signals(context, {"serpapi_airbnb_search"})
    assert "serpapi_airbnb_search" in signals.positive_tools


def test_newer_hotel_results_stop_unnamed_airbnb_hint_but_explicit_airbnb_can_reuse_it():
    history = [{"tool_results": {"serpapi_airbnb_search": extract_saved(search_data())}},
               {"tool_results": {"serpapi_hotel_search": {"query": "Seattle", "results": [{"title": "Hotel"}]}}}]
    assert ContextAssembler._airbnb_followup_hint("Show cheaper ones.", history) == ""
    assert "serpapi_airbnb_search" in ContextAssembler._airbnb_followup_hint("Cheaper Airbnb ones?", history)
    assert ContextAssembler._airbnb_followup_hint("How is the weather there?", history) == ""


def test_native_empty_search_keeps_destination_and_filters_for_a_refinement():
    data = search_data()
    data.update(results=[], results_count=0)
    saved = extract_saved(data)
    assert saved["candidates"] == []
    assert saved["query"] == data["query"]
    assert saved["budget_context"]["max_price_per_night"] == 250


def test_saved_context_retains_upstream_omissions_and_booking_limitations():
    data = search_data()
    data.update(result_truncated=True, booking_caveat="Availability may change; no reservation made.")
    result = extract_saved(data)
    assert result["context_truncated"] is True
    assert result["result_truncated"] is True
    assert result["booking_caveat"] == data["booking_caveat"]
