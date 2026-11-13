"""Saved Walmart evidence keeps its schemas available through normal Tool RAG signals."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

from lib.config_loader import config_scope
from orchestrator.context_assembler import ContextAssembler
from orchestrator.router_v2 import (
    _cap_tool_names_for_schema,
    build_tool_retrieval_signals,
    merge_tool_signal_names,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
WALMART = {"serpapi_walmart_search", "serpapi_walmart_product"}
ENABLED = WALMART | {"serpapi_home_depot", "serpapi_amazon_search", "serpapi_ebay_product"}
FOLLOWUP = (
    "Use the returned 4-5 Stars customer-rating filter on the last successful "
    "BLACK+DECKER keyword search; keep ZIP 35007 and maximum price 75."
)
FACET = "customer_rating_range_facet_new_filter_v0:4 - 5 Stars"


@pytest.fixture(autouse=True)
def routing_config():
    with config_scope("cloud", overrides={
        "TOOL_RAG_COMPACT_QUERY_ENABLED": "true",
        "TOOL_RAG_MEMORY_TOOL_SIGNALS_ENABLED": "false",
        "TOOL_RAG_APPEND_POSITIVE_SIGNALS": "true",
        "TOOL_RAG_EXCLUDE_NEGATIVE_SIGNALS": "true",
    }):
        yield


@pytest.fixture
def assembler():
    return ContextAssembler(
        timezone_obj=ZoneInfo("UTC"), auto_context_window=8, auto_context_minutes=180,
        safe_iso_to_local_datetime=lambda _value: None,
        format_age_seconds=lambda _value: "unknown",
        format_gap_for_prompt=lambda _value: "unknown",
        conversation_has_text_summary_for_ref=lambda _history, _ref: False,
        stash_ref_from_result=lambda _result, _arguments: "",
        get_memory_db_fn=Mock(side_effect=AssertionError("Unexpected memory database read")),
        now_utc_fn=lambda: NOW, parse_utc_timestamp_fn=lambda _value: NOW,
    )


@pytest.fixture
def extract_followup():
    alias = "walmart_routing_context_server"
    load_server_package(alias, ROOT / "jarvis-web" / "server")
    return importlib.import_module(f"{alias}.services.followup_extractor").extract_followup_data


def search_result():
    return {"ok": True, "data": {
        "engine": "walmart", "query": "BLACK+DECKER", "store_id": "3586",
        "location_context": {"requested_postal_code": "35007", "store_id": "3586"},
        "requested_filters": {"max_price": 75},
        "filters": [{"name": "Customer Rating", "type": "customer_rating_range_facet_new_filter_v0",
                     "values": [{"id": "4 - 5 Stars", "name": "4 - 5 Stars", "facet": FACET}]}],
        "results": [{"position": 1, "product_id": "BLACKDECKER1", "us_item_id": "100000001",
                     "title": "Fixture BLACK+DECKER product", "price": 49.99, "currency": "USD",
                     "url": "https://www.walmart.com/ip/100000001"}],
    }}


def saved_message(extract_followup, raw_results):
    # Exercise the actual Web projection and JSON persistence before history formatting.
    return {"role": "assistant", "content": "Found shopping results.",
            "tools_used": list(raw_results),
            "tool_results": json.loads(json.dumps(extract_followup(raw_results)))}


def signals_for(assembler, history, query=FOLLOWUP, enabled=ENABLED):
    prompt = assembler.format_conversation_context(query, history, now=NOW)
    return prompt, build_tool_retrieval_signals(prompt, enabled)


def test_saved_filter_followup_promotes_walmart_schemas_through_merge_and_cap(
    assembler, extract_followup,
):
    message = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    prompt, signals = signals_for(assembler, [message])
    assert signals.query == FOLLOWUP
    assert signals.positive_tools == WALMART
    assert FACET in prompt and "35007" in prompt and "3586" in prompt
    assert "BLACK+DECKER" in prompt and '"max_price":75' in prompt
    merged, metadata = merge_tool_signal_names(["serpapi_home_depot"], signals, ENABLED)
    capped = _cap_tool_names_for_schema(merged, limit=2, positive_tools=signals.positive_tools)
    assert set(metadata["appended"]) == WALMART
    assert set(capped) == WALMART


def test_later_walmart_recovery_in_same_message_is_the_saved_source(assembler, extract_followup):
    message = saved_message(extract_followup, {
        "serpapi_home_depot": {"ok": True, "data": {
            "results": [{"product_id": "HD123", "title": "Other retailer product"}],
        }},
        "serpapi_walmart_search": search_result(),
    })
    assert signals_for(assembler, [message])[1].positive_tools == WALMART


def test_product_detail_followup_keeps_both_schemas_available(assembler, extract_followup):
    message = saved_message(extract_followup, {"serpapi_walmart_product": {"ok": True, "data": {
        "engine": "walmart_product", "product_id": "BLACKDECKER1", "store_id": "3586",
        "product_summary": {"product_id": "BLACKDECKER1", "description": "Durable drill."},
    }}})
    prompt, signals = signals_for(assembler, [message], "Show more details for that product.")
    assert signals.positive_tools == WALMART
    assert "BLACKDECKER1" in prompt and "3586" in prompt


def test_successful_saved_run_survives_later_failed_run(assembler, extract_followup):
    message = saved_message(extract_followup, {"serpapi_walmart_search": [
        search_result(), {"ok": False, "error": "Provider unavailable"},
    ]})
    assert message["tool_results"]["serpapi_walmart_search"]["runs_count"] == 2
    assert signals_for(assembler, [message])[1].positive_tools == WALMART


@pytest.mark.parametrize("result", [
    {}, {"ok": False, "error": "Provider unavailable"},
    {"ok": True, "data": {"query": "BLACK+DECKER", "results": []}},
])
def test_failed_or_empty_saved_context_does_not_promote_walmart(
    assembler, extract_followup, result,
):
    message = saved_message(extract_followup, {"serpapi_walmart_search": result})
    assert not signals_for(assembler, [message])[1].positive_tools


@pytest.mark.parametrize("query", [
    "What is the weather today?",
    "Search Amazon for those products instead.",
    "Find the same product at Home Depot.",
    "What does that Python error mean?",
])
def test_unrelated_or_new_retailer_request_does_not_inherit_walmart(
    assembler, extract_followup, query,
):
    message = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    assert not signals_for(assembler, [message], query)[1].positive_tools


def test_explicit_ui_tool_preference_is_preserved(assembler, extract_followup):
    message = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    request = (
        "[CONTEXT - Tool preference for this request]\n"
        "Selected tool hints: serpapi_home_depot.\n[END CONTEXT]\n\n"
        "User's request: Show reviews for that product."
    )
    _, signals = signals_for(assembler, [message], request)
    assert signals.positive_tools == {"serpapi_home_depot"}


@pytest.mark.parametrize("latest_tool", ["serpapi_home_depot", "serpapi_amazon_search", "serpapi_ebay_product"])
def test_newer_usable_other_merchant_result_prevents_stale_walmart_hint(
    assembler, extract_followup, latest_tool,
):
    walmart = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    newer = {"role": "assistant", "content": "Other products.", "tool_results": {
        latest_tool: {"candidates": [{"title": "Newer product", "product_id": "OTHER123"}]},
    }}
    assert not signals_for(assembler, [walmart, newer], "Show reviews for the first product.")[1].positive_tools


def test_failed_other_merchant_does_not_hide_successful_walmart(assembler, extract_followup):
    walmart = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    newer = {"role": "assistant", "content": "Request failed.", "tool_results": {
        "serpapi_home_depot": {"ok": False, "error": "Provider unavailable"},
    }}
    assert signals_for(assembler, [walmart, newer])[1].positive_tools == WALMART


def test_enabled_and_excluded_tool_boundaries_are_preserved(assembler, extract_followup):
    message = saved_message(extract_followup, {"serpapi_walmart_search": search_result()})
    _, signals = signals_for(assembler, [message], enabled={"serpapi_home_depot"})
    assert not signals.positive_tools
    _, signals = signals_for(assembler, [message], enabled={"serpapi_walmart_search"})
    assert signals.positive_tools == {"serpapi_walmart_search"}
    _, signals = signals_for(assembler, [message])
    merged, metadata = merge_tool_signal_names(
        ["serpapi_home_depot"], signals, ENABLED, excluded_tools=WALMART,
    )
    assert merged == ["serpapi_home_depot"]
    assert metadata["appended"] == []
