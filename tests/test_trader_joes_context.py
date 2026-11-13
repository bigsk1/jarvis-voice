"""Trader Joe's evidence survives native, saved and retailer-implicit follow-ups."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

from lib.config_loader import config_scope
from lib.serpapi_trader_joes_context import TRADER_JOES_TOOLS, project_trader_joes_data
from orchestrator.context_assembler import ContextAssembler
from orchestrator.router_v2 import (
    _cap_tool_names_for_schema,
    build_tool_retrieval_signals,
    merge_tool_signal_names,
)


@pytest.fixture
def assembler():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    return ContextAssembler(
        timezone_obj=ZoneInfo("UTC"), auto_context_window=8, auto_context_minutes=180,
        safe_iso_to_local_datetime=lambda _value: None,
        format_age_seconds=lambda _value: "unknown", format_gap_for_prompt=lambda _value: "unknown",
        conversation_has_text_summary_for_ref=lambda _history, _ref: False,
        stash_ref_from_result=lambda _result, _arguments: "",
        get_memory_db_fn=Mock(side_effect=AssertionError("Unexpected DB access")),
        now_utc_fn=lambda: now, parse_utc_timestamp_fn=lambda _value: now,
    )


def search_data():
    return {
        "engine": "trader_joes", "query": "coffee", "store_id": "454",
        "location_context": {"store_id": "454", "source": "explicit_store"},
        "requested_filters": {"characteristics": ["vegan"], "new_products": False},
        "results_count": 10,
        "results": [{"position": i, "product_id": f"{i:06d}", "title": f"Coffee {i}",
                     "url": f"https://www.traderjoes.com/home/products/pdp/coffee-{i:06d}",
                     "image_url": f"https://images.example/coffee-{i}.jpg",
                     "price": 0 if i == 1 else 9.99, "currency": "USD", "size": "14 Oz",
                     "available": False if i == 1 else True} for i in range(1, 11)],
    }


def product_data():
    data = search_data()
    data.update(engine="trader_joes_product", product_id="000001", results_count=1)
    data["results"] = data["results"][:1]
    data["product_summary"] = {
        **data["results"][0], "description": "Unsweetened cold brew coffee.",
        "ingredients": ["Water", "Coffee"], "allergens": ["Contains milk"],
        "characteristics": ["Vegetarian"], "fun_tags": ["Morning"],
        "nutrition_facts": [{"title": "Per serving", "serving_size": "8.45 Fl Oz",
                             "servings_per_container": "1", "calories_per_serving": "0",
                             "nutrients": [{"name": "Sugar", "amount": "0 g", "daily_value": "0%"}]}],
    }
    return data


def test_projection_preserves_ten_ordered_skus_store_photos_and_false_zero_values():
    data = search_data()
    original = deepcopy(data)
    projected = project_trader_joes_data(data)
    assert len(projected["candidates"]) == 10
    for expected, row in zip(data["results"], projected["candidates"], strict=True):
        assert row["product_id"] == expected["product_id"]
        assert row["image_url"] == expected["image_url"]
    assert projected["candidates"][0]["price"] == 0
    assert projected["candidates"][0]["available"] is False
    assert projected["requested_filters"]["new_products"] is False
    assert projected["store_id"] == "454"
    assert data == original


def test_product_summary_keeps_ingredient_allergen_serving_and_zero_nutrition_evidence():
    data = product_data()
    data["api_key"] = "SECRET_SENTINEL"
    data["product_summary"]["nutrition_facts"][0]["api_key"] = "SECRET_SENTINEL"
    projected = project_trader_joes_data(data)
    detail = projected["product_summary"]
    assert detail["allergens"] == ["Contains milk"]
    assert detail["ingredients"] == ["Water", "Coffee"]
    assert detail["available"] is False
    panel = detail["nutrition_facts"][0]
    assert panel["serving_size"] == "8.45 Fl Oz" and panel["calories_per_serving"] == "0"
    assert panel["nutrients"][0]["amount"] == "0 g"
    assert "SECRET_SENTINEL" not in json.dumps(projected)
    assert project_trader_joes_data(projected) == projected


@pytest.mark.parametrize("budget", [128, 256, 1800, 5600, 9000])
def test_large_product_evidence_is_bounded_without_mutating_its_source(budget):
    data = product_data()
    data["product_summary"]["description"] = "Product evidence. " * 1000
    data["product_summary"]["ingredients"] *= 100
    data["product_summary"]["nutrition_facts"][0]["nutrients"] *= 100
    original = deepcopy(data)
    projected = project_trader_joes_data(data, max_chars=budget)
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"))) <= budget
    assert projected["context_truncated"] is True
    if budget >= 1800:
        assert projected["candidates"][0]["product_id"] == "000001"
        assert projected["product_summary"]["allergens"] == ["Contains milk"]
    assert data == original


@pytest.mark.parametrize("surface", ["immediate", "native", "accumulated"])
def test_model_handoffs_retain_product_nutrition_and_exact_selected_store(assembler, surface):
    data = product_data()
    result = {"ok": True, "data": data}
    if surface == "immediate":
        text, *_ = assembler.build_llm_result_context_preview("serpapi_trader_joes_product", result)
    elif surface == "native":
        text, _ = assembler.build_provider_tool_result_message(
            tool_name="serpapi_trader_joes_product", arguments={"product_id": "000001"},
            result=result, max_chars=6000,
        )
        assert len(text) <= 6000
    else:
        text = assembler.extract_useful_data(
            {"serpapi_trader_joes_product": project_trader_joes_data(data)},
            has_text_summarizer_summary_for_ref=lambda _item, _ref: False,
        )
    for value in ("000001", "454", "Contains milk", "serving_size", "8.45 Fl Oz", "0 g"):
        assert value in text


def test_repeated_store_runs_preserve_separate_identity_completion_and_truncation():
    runs = []
    for store in ("454", "455", "456"):
        run = product_data()
        run.update(store_id=store, ok=True, completion="completed")
        run["product_summary"]["description"] *= 100
        runs.append(run)
    data = {"runs_count": 3, "results": runs}
    projected = project_trader_joes_data(data, max_chars=7500)
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"))) <= 7500
    assert projected["context_truncated"] is True
    assert [run["store_id"] for run in projected["results"]] == ["454", "455", "456"]
    assert all(run["completion"] == "completed" for run in projected["results"])


@pytest.mark.parametrize("query", [
    "Show ingredients and allergens for the second product.",
    "Keep those products vegan and organic.",
    "How much sugar does it have?",
])
def test_saved_retailer_implicit_followup_promotes_trader_joes_instead_of_walmart(assembler, query):
    history = [{"role": "assistant", "content": "Found coffee.", "tool_results": {
        "serpapi_trader_joes_search": json.loads(json.dumps(project_trader_joes_data(search_data()))),
    }}]
    with config_scope("cloud", overrides={"TOOL_RAG_APPEND_POSITIVE_SIGNALS": "true"}):
        prompt = assembler.format_conversation_context(query, history)
        enabled = set(TRADER_JOES_TOOLS) | {"serpapi_walmart_search"}
        signals = build_tool_retrieval_signals(prompt, enabled)
        merged, _ = merge_tool_signal_names(["serpapi_walmart_search"], signals, enabled)
        capped = _cap_tool_names_for_schema(merged, limit=2, positive_tools=signals.positive_tools)
    assert signals.positive_tools == set(TRADER_JOES_TOOLS)
    assert set(capped) == set(TRADER_JOES_TOOLS)


def test_explicit_new_retailer_does_not_reuse_the_previous_retailers_hint(assembler):
    for old, query in (("serpapi_trader_joes_search", "Find those products at Walmart."),
                       ("serpapi_walmart_search", "Find those products at Trader Joe's.")):
        history = [{"role": "assistant", "tool_results": {old: project_trader_joes_data(search_data())}}]
        assert "Selected tool hints:" not in assembler.format_conversation_context(query, history)


@pytest.mark.parametrize("older_is_walmart", [False, True])
@pytest.mark.parametrize("same_message", [False, True])
def test_named_older_retailer_and_unnamed_latest_retailer_survive_mixed_saved_history(
    assembler, older_is_walmart, same_message,
):
    import importlib

    alias = "trader_joes_routing_review_server"
    load_server_package(alias, Path(__file__).resolve().parents[1] / "jarvis-web" / "server")
    extract = importlib.import_module(f"{alias}.services.followup_extractor").extract_followup_data
    walmart = {"serpapi_walmart_search", "serpapi_walmart_product"}
    trader = set(TRADER_JOES_TOOLS)
    older, newer = (walmart, trader) if older_is_walmart else (trader, walmart)
    older_tool = next(name for name in older if name.endswith("search"))
    newer_tool = next(name for name in newer if name.endswith("search"))
    def saved(tool):
        data = search_data()
        data["engine"] = "walmart" if tool in walmart else "trader_joes"
        return extract({tool: {"ok": True, "data": data}})
    first, second = saved(older_tool), saved(newer_tool)
    history = ([{"role": "assistant", "tool_results": {**first, **second}}] if same_message else [
        {"role": "assistant", "tool_results": first}, {"role": "assistant", "tool_results": second},
    ])
    history = json.loads(json.dumps(history))
    named = "Walmart" if older_is_walmart else "Trader Joe's"
    for query, expected in ((f"Show ingredients for those {named} products.", older),
                            ("Show ingredients for the second product.", newer)):
        signals = build_tool_retrieval_signals(assembler.format_conversation_context(query, history), walmart | trader)
        assert signals.positive_tools == expected


@pytest.mark.parametrize("surface", ["immediate", "native", "saved"])
def test_similar_product_filter_ids_keep_their_display_labels_through_handoffs(assembler, surface):
    import importlib

    data = product_data()
    detail = data["product_summary"]
    detail.update(characteristics=["Gluten Free", "Kosher"], fun_tags=["Rise & Shine"],
                  search_filters={"characteristics": ["gluten_free", "kosher"], "tags": ["rise_and_shine"]})
    result = {"ok": True, "data": data}
    if surface == "immediate":
        text, *_ = assembler.build_llm_result_context_preview("serpapi_trader_joes_product", result)
        projected = json.loads(text)["data"]
    elif surface == "native":
        text, _ = assembler.build_provider_tool_result_message(
            tool_name="serpapi_trader_joes_product", arguments={"product_id": "000001"},
            result=result, max_chars=6000,
        )
        projected = json.loads(text.split("\nResult:\n", 1)[1])["result"]["data"]
    else:
        alias = "trader_joes_filter_review_server"
        load_server_package(alias, Path(__file__).resolve().parents[1] / "jarvis-web" / "server")
        extract = importlib.import_module(f"{alias}.services.followup_extractor").extract_followup_data
        projected = json.loads(json.dumps(extract({"serpapi_trader_joes_product": result})))["serpapi_trader_joes_product"]
    assert projected["product_summary"]["characteristics"] == ["Gluten Free", "Kosher"]
    assert projected["product_summary"]["fun_tags"] == ["Rise & Shine"]
    assert projected["product_summary"]["search_filters"] == detail["search_filters"]
