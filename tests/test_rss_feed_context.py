"""RSS evidence stays compact and retains complete article and digest identities."""

import importlib
import json
from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

from lib.rss_feeds.context import project_rss_feed_data
from orchestrator.context_assembler import ContextAssembler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_server_package("rss_context_test_server", PROJECT_ROOT / "jarvis-web/server")
followup = importlib.import_module("rss_context_test_server.services.followup_extractor")
ARTICLE_URL = "https://example.org/" + "complete-segment-" * 25 + "article?edition=2026#details"
BATCH = "b" * 32


def article(number=1):
    return {"id": f"article_{number}", "url": ARTICLE_URL + str(number), "title": f"Research release {number}",
            "source": "Project News", "summary": "A useful feed description.",
            "published_at": "2026-10-27T16:00:00Z", "content": "FULL_BODY_SENTINEL " * 1000,
            "raw": {"api_key": "SECRET_SENTINEL"}}


def result(action="read"):
    payload = {"action": action, "profile": "daily_tech", "batch_id": BATCH, "checked_at": "2026-10-27T16:00:00Z",
               "source_status": [{"error": "RAW_STATUS_SENTINEL"}], "api_key": "SECRET_SENTINEL"}
    if action == "acknowledge":
        payload.update(page_id="page_digest_7", published_count=1, acknowledged=True)
    else:
        key = "selected_items" if action == "resolve_selection" else "items"
        payload[key] = [article()]
        if action == "read":
            payload.update(candidate_count=1, has_items=True)
    return {"ok": True, "data": payload}


def assembler():
    return ContextAssembler.__new__(ContextAssembler)


@pytest.mark.parametrize("action", ["read", "resolve_selection", "acknowledge"])
def test_shared_projection_and_web_followup_keep_canonical_handles_without_raw_fields(action):
    original = result(action)
    before = deepcopy(original)
    projected = project_rss_feed_data(original)
    saved = followup.extract_followup_data({"rss_feed": original})["rss_feed"]
    assert saved == projected
    assert projected["profile"] == "daily_tech"
    assert projected["batch_id"] == BATCH
    assert projected["action"] == action
    encoded = json.dumps(projected)
    assert not any(sentinel in encoded for sentinel in ("FULL_BODY_SENTINEL", "RAW_STATUS_SENTINEL", "SECRET_SENTINEL"))
    if action == "acknowledge":
        assert projected["page_id"] == "page_digest_7"
        assert projected["published_count"] == 1
        assert projected["acknowledged"] is True
    else:
        key = "selected_items" if action == "resolve_selection" else "items"
        row = projected[key][0]
        assert row["url"] == ARTICLE_URL + "1"
        assert row["id"] == "article_1"
        assert row["source"] == "Project News"
        assert row["summary"] == "A useful feed description."
        assert projected["article_content_included"] is False
        assert projected["external_content_trust"] == "untrusted"
    assert original == before


def test_repeated_read_selection_acknowledge_preserve_separate_batches_and_saved_roundtrip():
    runs = [result(action) for action in ("read", "resolve_selection", "acknowledge")]
    compact = followup.extract_followup_data({"rss_feed": runs})["rss_feed"]
    assert compact["runs_count"] == 3
    assert compact["results_truncated"] is False
    assert [row["action"] for row in compact["results"]] == ["read", "resolve_selection", "acknowledge"]
    assert all(row["batch_id"] == BATCH for row in compact["results"])
    assert compact["results"][-1]["page_id"] == "page_digest_7"
    assert project_rss_feed_data(json.loads(json.dumps(compact))) == compact


@pytest.mark.parametrize("budget", [128, 256, 650, 1400, 6000])
def test_projection_bounds_unicode_prose_rows_and_urls_structurally(budget):
    original = result()
    original["data"]["items"] = [{**article(number), "title": "界" * 1000, "summary": "界" * 2000} for number in range(30)]
    original["data"]["candidate_count"] = 30
    original["data"]["items"].append({**article(31), "url": "https://example.org/" + "x" * 3000})
    before = deepcopy(original)
    projected = project_rss_feed_data(original, max_chars=budget)
    encoded = json.dumps(projected, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    assert len(encoded) <= budget
    assert projected["context_truncated"] is True
    valid_urls = {row["url"] for row in original["data"]["items"]}
    for row in projected.get("items", []):
        assert row["url"] in valid_urls
        assert "truncated" not in row["url"]
    assert original == before


def test_oversized_url_and_id_are_omitted_whole_without_losing_control_handles():
    original = result()
    original["data"]["items"] = [{**article(), "url": "https://example.org/" + "x" * 3000, "id": "y" * 300}]
    projected = project_rss_feed_data(original)
    assert projected["batch_id"] == BATCH
    assert projected["context_truncated"] is True
    assert projected["items"][0]["url_omitted"] is True
    assert "url" not in projected["items"][0]
    assert "id" not in projected["items"][0]


def test_repeated_runs_share_one_total_budget_and_mark_omitted_older_runs():
    runs = []
    for number in range(12):
        run = result()
        run["data"].update(profile=f"profile_{number}", items=[article(i) for i in range(20)])
        runs.append(run)
    projected = project_rss_feed_data(runs, max_chars=2000)
    assert len(json.dumps(projected, separators=(",", ":"))) <= 2000
    assert projected["runs_count"] == 12
    assert projected["results_truncated"] is True
    assert len(projected["results"]) <= 5
    assert projected["results"][-1]["profile"] == "profile_11"


def test_tiny_repeated_budget_never_hides_omitted_run_metadata():
    compact = project_rss_feed_data([result(), result("acknowledge")], max_chars=128)
    assert compact["context_truncated"] is True
    assert len(json.dumps(compact, separators=(",", ":"))) <= 128


@pytest.mark.parametrize("budget", [800, 1800, 6000])
def test_provider_continuation_and_tool_preview_are_valid_compact_json(budget):
    original = result("resolve_selection")
    message, metadata = assembler().build_provider_tool_result_message(
        tool_name="rss_feed", arguments={"action": "resolve_selection", "profile": "daily_tech", "batch_id": BATCH},
        result=original, max_chars=budget,
    )
    assert len(message) <= budget
    body = json.loads(message.split("\nResult:\n", 1)[1])
    projected = body["result"]["data"]
    assert projected["profile"] == "daily_tech"
    assert projected["batch_id"] == BATCH
    assert metadata["result_truncated"] == bool(projected.get("context_truncated"))
    assert "FULL_BODY_SENTINEL" not in message
    assert "RAW_STATUS_SENTINEL" not in message
    for row in projected.get("selected_items", []):
        assert row["url"] == ARTICLE_URL + "1"
    preview, _, shown, _ = assembler().build_llm_result_context_preview("rss_feed", original)
    assert shown == len(preview) <= 6000
    assert json.loads(preview)["data"]["selected_items"][0]["url"] == ARTICLE_URL + "1"


def test_synthesis_and_saved_history_use_shared_projection_instead_of_generic_url_slices():
    original = result("resolve_selection")
    instance = assembler()
    synthesis = instance.extract_useful_data({"rss_feed": original}, has_text_summarizer_summary_for_ref=lambda *_: False)
    assert ARTICLE_URL + "1" in synthesis
    assert "FULL_BODY_SENTINEL" not in synthesis
    instance.timezone = ZoneInfo("UTC")
    instance._safe_iso_to_local_datetime = lambda _: None
    history = instance.format_conversation_context("Which article was that?", [{
        "role": "assistant", "content": "Read the feed.", "tools_used": ["rss_feed"], "tool_results": {"rss_feed": original},
    }])
    assert ARTICLE_URL + "1" in history
    assert "FULL_BODY_SENTINEL" not in history
    assert "RAW_STATUS_SENTINEL" not in history
    instance._format_age_seconds = lambda _: "unknown"
    turn = instance.build_turn_context("Which article was that?", [{"tool": "rss_feed", "result": original}])
    assert ARTICLE_URL + "1" in turn
    assert "FULL_BODY_SENTINEL" not in turn
    assert "RAW_STATUS_SENTINEL" not in turn


def test_workflow_projection_and_saved_followup_keep_read_selection_and_published_page():
    workflow = {"ok": True, "data": {"action": "run", "workflow_id": "rss_digest", "results": [
        {"step": number, "tool": "rss_feed", "ok": True, "data": result(action)["data"]}
        for number, action in enumerate(("read", "resolve_selection", "acknowledge"), 1)
    ]}}
    steps = assembler().build_workflow_result_preview(workflow, max_chars=8000)["llm_context_preview"]["step_results"]
    for step in steps:
        projected = json.loads(step["result_preview"])
        assert projected["batch_id"] == BATCH
        assert "FULL_BODY_SENTINEL" not in step["result_preview"]
    assert json.loads(steps[-1]["result_preview"])["page_id"] == "page_digest_7"
    followup_data = followup.extract_followup_data({"workflow": workflow["data"]})["rss_feed"]
    assert followup_data["results"][-1]["page_id"] == "page_digest_7"


def test_failed_acknowledgment_remains_failed_without_stale_publication_evidence():
    original = {"ok": False, "error": "Saved digest could not be verified", "data": result("acknowledge")["data"]}
    compact = project_rss_feed_data(original)
    assert compact["ok"] is False
    assert compact["error"] == original["error"]
    assert compact["batch_id"] == BATCH
    assert "publication_status" not in compact
    assert "acknowledged" not in compact
    workflow = {"action": "run", "results": [{"tool": "rss_feed", "ok": False,
                "data": original["data"], "error": original["error"]}]}
    saved = followup.extract_followup_data({"workflow": workflow})["rss_feed"]
    assert saved["ok"] is False
    assert "acknowledged" not in saved


def test_direct_empty_feed_and_profile_listing_remain_useful_without_body_or_status_dumps():
    empty = project_rss_feed_data({"url": "https://example.org/rss", "title": "Project feed", "items": [], "total_items": 9, "undated_skipped": 9})
    assert empty["url"] == "https://example.org/rss"
    assert empty["items_count"] == 0 and empty["total_items"] == 9
    assert empty["items"] == []
    profiles = project_rss_feed_data({"profiles": [{"profile": "daily_tech", "title": "Technology", "feeds": ["PRIVATE_FEED_SENTINEL"]}]})
    assert profiles["profiles"] == [{"profile": "daily_tech", "title": "Technology",
                                       "feeds": [], "feeds_count": 1, "feeds_truncated": True}]
    assert "PRIVATE_FEED_SENTINEL" not in json.dumps(profiles)


def direct_read(*, content_kind="inline", content=None):
    body = content if content is not None else "DIRECT_FEED_DETAIL " * 150
    return {"ok": True, "data": {"action": "read", "url": "https://example.org/feed.xml", "items": [{
        **article(), "content": body, "content_kind": content_kind, "content_chars": len(body) + 200,
        "content_truncated": True,
    }]}}


def test_direct_read_can_retain_bounded_untrusted_feed_text_without_claiming_article_completeness():
    original = direct_read()
    before = deepcopy(original)
    projected = project_rss_feed_data(original, include_content=True)
    row = projected["items"][0]
    assert "DIRECT_FEED_DETAIL" in row["content_excerpt"]
    assert len(row["content_excerpt"]) <= 1200
    assert row["content_excerpt"].endswith("[truncated]")
    assert row["content_chars"] == original["data"]["items"][0]["content_chars"]
    assert row["content_kind"] == "inline" and row["content_truncated"] is True
    assert projected["article_content_included"] is True
    assert projected["external_content_trust"] == "untrusted"
    assert "complete article coverage is not verified" in projected["article_content_scope"]
    assert row["id"] == "article_1" and row["url"] == ARTICLE_URL + "1"
    assert "content" not in row
    assert original == before


@pytest.mark.parametrize("profile,batch", [("daily_tech", None), (None, BATCH), ("daily_tech", BATCH)])
def test_profile_or_staged_batch_never_inlines_bodies_even_when_requested(profile, batch):
    original = direct_read()
    if profile is not None:
        original["data"]["profile"] = profile
    if batch is not None:
        original["data"]["batch_id"] = batch
    projected = project_rss_feed_data(original, include_content=True)
    assert "content_excerpt" not in projected["items"][0]
    assert projected["article_content_included"] is False


@pytest.mark.parametrize("kind", ["summary", "out_of_line"])
def test_summary_and_out_of_line_content_never_becomes_verified_inline_body(kind):
    projected = project_rss_feed_data(direct_read(content_kind=kind), include_content=True)
    row = projected["items"][0]
    assert row["content_kind"] == kind
    assert "DIRECT_FEED_DETAIL" in row["content_excerpt"]
    assert row["content_truncated"] is True
    assert "complete article coverage is not verified" in projected["article_content_scope"]
    assert row["summary"] == "A useful feed description."


def test_empty_out_of_line_atom_content_never_invents_an_excerpt():
    original = direct_read(content_kind="out_of_line", content="")
    original["data"]["items"][0].update(content_chars=0, content_truncated=False)
    projected = project_rss_feed_data(original, include_content=True)
    assert projected["items"][0]["content_kind"] == "out_of_line"
    assert "content_excerpt" not in projected["items"][0]
    assert projected["article_content_included"] is False


def test_cheap_saved_history_keeps_summary_and_coverage_metadata_without_feed_body():
    original = direct_read()
    saved = followup.extract_followup_data({"rss_feed": original})["rss_feed"]
    assert "DIRECT_FEED_DETAIL" not in json.dumps(saved)
    assert saved["items"][0]["summary"] == "A useful feed description."
    assert saved["items"][0]["content_kind"] == "inline"
    assert saved["items"][0]["content_chars"] == original["data"]["items"][0]["content_chars"]
    assert saved["items"][0]["content_truncated"] is True


def test_actual_current_answer_paths_retain_direct_feed_excerpt_while_web_history_stays_cheap():
    original = direct_read()
    instance = assembler()
    preview = json.loads(instance.build_llm_result_context_preview("rss_feed", original)[0])["data"]
    assert "DIRECT_FEED_DETAIL" in preview["items"][0]["content_excerpt"]
    message, _ = instance.build_provider_tool_result_message(
        tool_name="rss_feed", arguments={"action": "read", "url": "https://example.org/feed.xml"},
        result=original, max_chars=2500,
    )
    body = json.loads(message.split("\nResult:\n", 1)[1])["result"]["data"]
    assert "DIRECT_FEED_DETAIL" in body["items"][0]["content_excerpt"]
    assert body["items"][0]["url"] == ARTICLE_URL + "1"
    assert len(message) <= 2500
    synthesis = instance.extract_useful_data({"rss_feed": original}, has_text_summarizer_summary_for_ref=lambda *_: False)
    assert "DIRECT_FEED_DETAIL" in synthesis
    saved = followup.extract_followup_data({"rss_feed": original})["rss_feed"]
    assert "DIRECT_FEED_DETAIL" not in json.dumps(saved)


def test_budget_shrinks_feed_text_before_removing_complete_article_ids_and_urls():
    original = direct_read()
    original["data"]["items"].append({**original["data"]["items"][0], "id": "article_2", "url": ARTICLE_URL + "2"})
    projected = project_rss_feed_data(original, include_content=True, max_chars=2500)
    assert len(json.dumps(projected, separators=(",", ":"))) <= 2500
    assert [(row["id"], row["url"]) for row in projected["items"]] == [
        ("article_1", ARTICLE_URL + "1"), ("article_2", ARTICLE_URL + "2"),
    ]
    assert projected["context_truncated"] is True
    assert all(row["content_truncated"] for row in projected["items"])
    assert not any("DIRECT_FEED_DETAIL " * 150 in row.get("content_excerpt", "") for row in projected["items"])


def test_profile_list_preserves_feed_names_complete_urls_priorities_and_editorial_preferences():
    original = {"action": "list_profiles", "profiles": [{"profile": "science", "title": "Science Digest",
        "interests": ["research tools", "robotics"], "exclude": ["celebrity gossip"], "max_stories": 8,
        "feeds": [{"name": "Project News", "url": ARTICLE_URL, "priority": "high", "api_key": "SECRET_SENTINEL"},
                  {"name": "Research Notes", "url": "https://example.org/research.atom", "priority": "normal"}],
        "private_debug": "SECRET_SENTINEL"}]}
    projected = project_rss_feed_data(original)
    profile = projected["profiles"][0]
    assert profile["interests"] == original["profiles"][0]["interests"]
    assert profile["exclude"] == ["celebrity gossip"]
    assert profile["max_stories"] == 8
    assert profile["feeds_count"] == 2
    assert profile["feeds"][0] == {"name": "Project News", "url": ARTICLE_URL, "priority": "high"}
    assert "SECRET_SENTINEL" not in json.dumps(projected)
    assert project_rss_feed_data(json.loads(json.dumps(projected))) == projected


def test_profile_and_feed_compaction_is_explicit_without_fake_url_prefixes():
    original = {"profiles": [{"profile": "science", "interests": ["topic" * 100] * 20, "exclude": ["topic"] * 20,
        "feeds": [{"name": f"Source {number}", "url": ARTICLE_URL + str(number), "priority": "normal"} for number in range(10)]}]}
    projected = project_rss_feed_data(original, max_chars=900)
    profile = projected["profiles"][0]
    assert projected["context_truncated"] is True
    assert profile["interests_truncated"] is True
    assert profile["exclude_truncated"] is True
    assert profile["feeds_count"] == 10 and profile["feeds_truncated"] is True
    assert all(row["url"] in {feed["url"] for feed in original["profiles"][0]["feeds"]} for row in profile["feeds"])
    assert len(json.dumps(projected, separators=(",", ":"))) <= 900


def test_profile_listing_keeps_all_seven_configured_feeds_independent_of_article_cap():
    feeds = [{"name": f"Project {n}", "url": f"https://example.org/feed-{n}.xml", "priority": "normal"} for n in range(7)]
    projected = project_rss_feed_data({"profiles": [{"profile": "daily_tech", "feeds": feeds}]}, max_items=5)
    assert projected["profiles"][0]["feeds"] == feeds
    assert projected["profiles"][0]["feeds_count"] == 7
    assert not projected["profiles"][0].get("feeds_truncated")


@pytest.mark.parametrize("failed", [False, True])
def test_classified_failed_feed_names_remain_available_beyond_article_row_cap(failed):
    failures = [{"name": f"Failed feed {number}", "reason": "HTTP 403", "exception": "SECRET_SENTINEL",
                 "id": "SECRET_SENTINEL", "url": "https://private.example.org/SECRET_SENTINEL"} for number in range(12)]
    original = {"ok": not failed, "data": {"profile": "daily_tech", "batch_id": BATCH,
                                           "failed_feeds": failures, "source_status": "RAW_STATUS_SENTINEL"}}
    if failed:
        original["error"] = "No feeds could be checked"
    projected = project_rss_feed_data(original)
    assert projected["failed_feeds_count"] == 12
    assert len(projected["failed_feeds"]) == 12
    assert {row["name"] for row in projected["failed_feeds"]} == {row["name"] for row in failures}
    assert all(row["reason"] == "HTTP 403" for row in projected["failed_feeds"])
    assert "SECRET_SENTINEL" not in json.dumps(projected)
    assert "RAW_STATUS_SENTINEL" not in json.dumps(projected)
    if failed:
        assert projected["ok"] is False


def test_failure_limit_and_tight_budget_drop_whole_rows_with_counts():
    original = {"profile": "daily_tech", "failed_feeds": [{"name": f"Source {n}", "reason": "request failed or timed out"} for n in range(30)]}
    normal = project_rss_feed_data(original)
    assert len(normal["failed_feeds"]) == 16
    assert normal["failed_feeds_count"] == 30 and normal["failed_feeds_truncated"] is True
    compact = project_rss_feed_data(original, max_chars=500)
    assert len(compact["failed_feeds"]) < 16
    assert compact["failed_feeds_count"] == 30 and compact["failed_feeds_truncated"] is True
    assert compact["context_truncated"] is True
    assert len(json.dumps(compact, separators=(",", ":"))) <= 500
