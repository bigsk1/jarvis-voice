"""Current SerpApi evidence survives immediate model context and saved follow-ups."""

import importlib
import json
from pathlib import Path

import pytest
from server_package_utils import load_server_package

from orchestrator.context_assembler import ContextAssembler
from skills.serpapi_search_index import extract_search_index_results

ROOT = Path(__file__).resolve().parents[1]
load_server_package("serpapi_release_context_server", ROOT / "jarvis-web/server")
FOLLOWUP = importlib.import_module("serpapi_release_context_server.services.followup_extractor")


def model_preview(name, data):
    assembler = ContextAssembler.__new__(ContextAssembler)
    text, _, shown, _ = assembler.build_llm_result_context_preview(
        name, {"ok": True, "data": {**data, "raw": "irrelevant" * 10000}},
    )
    assert shown <= 6000
    return json.loads(text)["llm_context_preview"]


def saved(name, data):
    first = FOLLOWUP.extract_followup_data({name: {"ok": True, "data": data}})[name]
    reloaded = json.loads(json.dumps(first, allow_nan=False))
    return first, FOLLOWUP.extract_followup_data({name: reloaded})[name]


@pytest.mark.parametrize("corpus,extra", [
    ("place", {"data_cid": "8973842359244053980", "address": "Dallas, TX", "rating": 4.6}),
    ("product", {"product_id": "00017450565768136224565", "price": 0, "currency": "USD"}),
    ("video", {"video_id": "exact-video", "channel": {"name": "Author"}, "length": "2:43"}),
    ("publication", {"result_id": "exact-publication", "resources": [{"file_format": "PDF", "link": "https://example.test/paper.pdf"}],
                     "inline_links": {"cited_by": {"total": 0, "cites_id": "16656356389737500750"}}}),
])
def test_typed_index_evidence_survives_preview_save_reload_and_reextraction(corpus, extra):
    rows = extract_search_index_results({f"{corpus}_results": [{
        "title": "Indexed source", "link": "https://example.test/source", **extra,
    }]}, result_type=corpus)
    data = {"engine": "search_index", "query": "coffee", "result_type": corpus,
            "filters": {"gl": "us"}, "results_count": 1, "results": rows}
    preview = model_preview("serpapi_search_index", data)
    assert preview["data_preview"]["result_type"] == corpus
    assert preview["data_preview"]["filters"] == {"gl": "us"}
    candidates = [preview["source_candidates"][0], *[run["candidates"][0] for run in saved("serpapi_search_index", data)]]
    for row in candidates:
        assert row["result_type"] == corpus
        for key, value in extra.items():
            assert row[key] == value


def test_product_evidence_and_lookup_provenance_survive_large_result_previews():
    amazon = model_preview("serpapi_amazon_search", {
        "amazon_domain": "amazon.ae", "delivery_city": "Dubai", "delivery_localized": True,
        "results": [{"title": "Product", "asin": "EXACT-ASIN", "item_ingredients": ["Coffee"],
                     "important_information": [{"title": "Warning", "text": "Contains caffeine"}]}],
    })
    assert amazon["data_preview"]["delivery_city"] == "Dubai"
    assert amazon["source_candidates"][0]["item_ingredients"] == ["Coffee"]
    assert amazon["source_candidates"][0]["important_information"][0]["text"] == "Contains caffeine"
    depot = model_preview("serpapi_home_depot", {
        "requested_store_sku": "000123", "product_id": "resolved-product", "lookup_note": "SKU may match more than one product",
        "results": [{"title": "Product", "product_id": "resolved-product", "availability_type": "Discontinued"}],
    })
    assert depot["data_preview"]["requested_store_sku"] == "000123"
    assert depot["source_candidates"][0]["availability_type"] == "Discontinued"


def test_events_preferences_and_maps_ranking_notes_survive_model_preview():
    event_token = "opaque-event-handle-" * 60
    event = model_preview("serpapi_google_events", {
        "query_preferences": {"date_filter": "week", "virtual": True},
        "query_preferences_note": "Search preferences are not strict filters", "pagination_supported": False,
        "results": [{"title": "Conference", "event_token": event_token}],
    })
    assert event["data_preview"]["query_preferences"]["virtual"] is True
    assert event["data_preview"]["pagination_supported"] is False
    assert "filters" not in event["data_preview"]
    assert event["source_candidates"][0]["event_token"] == event_token
    maps = model_preview("serpapi_maps_search", {
        "requested_filters": {"min_rating": 4.5}, "effective_filters": {"min_rating": 4.5},
        "filter_notes": ["Minimum rating is a preference; lower-rated places may appear"],
        "results": [{"title": "Coffee shop", "rating": 4.1}],
    })
    assert maps["data_preview"]["effective_filters"] == {"min_rating": 4.5}
    assert "preference" in maps["data_preview"]["filter_notes"][0]


def test_youtube_and_live_football_details_survive_compact_model_context():
    video = {"video_id": "exact", "channel_id": "UCexact", "length_seconds": 0,
             "age_restricted": False, "made_with_ai": False, "comment_count": 0,
             "chapters": [{"title": "Introduction", "time_start": 0, "auto_generated": True}],
             "music": [{"title": "Theme", "artist": "Artist"}]}
    preview = model_preview("serpapi_youtube", video)["data_preview"]
    for key in video:
        assert preview[key] == video[key]
    for run in saved("serpapi_youtube", video):
        assert run["channel_id"] == "UCexact"
        assert run["made_with_ai"] is False
        assert run["chapters"][0]["time_start"] == 0
    sports = model_preview("serpapi_google_sports", {
        "results_kind": "game", "results": [{"title": "Game", "down_and_distance": "3rd & 8",
            "teams": [{"name": "Home", "score": 0, "timeouts_remaining": 0, "possession": False}]}],
    })
    row = sports["source_candidates"][0]
    assert row["down_and_distance"] == "3rd & 8"
    assert row["teams"][0]["timeouts_remaining"] == 0
    assert row["teams"][0]["possession"] is False


def test_trends_query_identity_and_per_value_dates_survive_every_handoff():
    data = {"query": "coffee, coffee", "queries": ["coffee", "coffee"], "data_type": "interest_over_time",
            "multiple_comparisons": True,
            "interpretation_note": "Relative interest, not absolute search counts",
            "comparisons": [{"query_index": 0, "query": "coffee", "geo": "US", "date": "now 7-d"},
                            {"query_index": 1, "query": "coffee", "geo": "GB", "date": "today 3-m"}],
            "results": [{"title": "Coffee US", "query": "coffee", "query_index": 0, "geo": "US", "latest_value": 0},
                        {"title": "Coffee GB", "query": "coffee", "query_index": 1, "geo": "GB", "latest_value": 80}],
            "timeline_data": [{"values": [{"query": "coffee", "query_index": 1, "date": "Feb 3, 2026", "timestamp": "1770076800", "extracted_value": 0}]}]}
    preview = model_preview("serpapi_google_trends", data)
    assert preview["source_candidates"][0]["query_index"] == 0
    assert preview["data_preview"]["comparisons"][1]["geo"] == "GB"
    assert preview["data_preview"]["interpretation_note"] == data["interpretation_note"]
    for run in saved("serpapi_google_trends", data):
        assert run["interpretation_note"] == data["interpretation_note"]
        assert run["candidates"][0]["latest_value"] == 0
        assert run["candidates"][1]["query_index"] == 1
        assert run["latest_timeline"][0]["values"][0]["timestamp"] == "1770076800"
