"""Google panel evidence survives the real orchestration and saved-turn seams."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from server_package_utils import load_server_package

from lib.serpapi_google_context import (
    google_prompt_evidence,
    google_prompt_evidence_parts,
    google_workflow_receipt,
    project_google_runs,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))
from context_assembler import ContextAssembler  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402

load_server_package("google_context_server", ROOT / "jarvis-web" / "server")
from google_context_server.services.followup_extractor import extract_followup_data  # noqa: E402
from google_context_server.sockets.chat import ChatHandler  # noqa: E402

TOOL = "serpapi_google_search"
TAIL = "THE_RETAINED_ANSWER_END"


def google_result(*, text_chars=11000, context_chars=20000):
    text = "Bounded local evidence. " * (text_chars // 24) + TAIL
    panels = [
        {"key": "knowledge_graph", "path": "/knowledge_graph", "type": "object", "count": 3,
         "preview": {"title": "Star Wars: A New Hope", "year": "1977",
                     "available_on": [{"name": f"Provider {i}", "link": f"https://example.test/{i}"}
                                      for i in range(8)]},
         "preview_count": 3, "truncated": False},
        {"key": "answer_box", "path": "/answer_box", "type": "object", "count": 1,
         "preview": {"snippet": text}, "preview_count": 1, "truncated": False},
        *[{"key": f"future_panel_{i}", "path": f"/future_panel_{i}", "type": "scalar", "count": 1,
           "preview": f"Fact {i}", "preview_count": 1, "truncated": False} for i in range(16)],
    ]
    return {"ok": True, "data": {
        "contract": "external_result_v1",
        "source": {"provider": "serpapi", "tool": TOOL, "mode": "cloud"},
        "execution": {"status": "SUCCEEDED", "search_id": "fixture-search"},
        "result": {"kind": "google_search", "query": "where to watch Star Wars 1977",
                   "search_url": "https://www.google.com/search?q=star+wars+1977",
                   "searched_at": "2026-11-11T12:00:00Z", "request": {"country": "us", "language": "en"},
                   "panels": panels, "pagination": {"has_more": True, "next_start": 10}},
        "artifacts": [], "raw_ref": "stash://google-fixture/full-search",
        "limits": {"truncated": False, "context_max_chars": context_chars},
    }}


@pytest.fixture
def assembler():
    value = ContextAssembler.__new__(ContextAssembler)
    value.timezone = ZoneInfo("UTC")
    value._safe_iso_to_local_datetime = lambda _value: None
    value._format_age_seconds = lambda _value: "unknown"
    return value


def test_large_google_evidence_and_all_panel_names_survive_immediate_and_saved_context(assembler):
    result = google_result()
    before = deepcopy(result)
    text, _total, shown, _truncated = assembler.build_llm_result_context_preview(TOOL, result)
    assert TAIL in text and 10000 < shown <= 20000
    projected = json.loads(text)["data"]
    assert len(projected["result"]["panels"]) == 18
    assert projected["raw_ref"] == result["data"]["raw_ref"]
    followup = extract_followup_data({TOOL: result})
    saved = json.loads(json.dumps(followup))
    assert TAIL in json.dumps(saved) and len(saved[TOOL]["result"]["panels"]) == 18
    history = assembler.format_conversation_context("Explain the last result", [{
        "role": "assistant", "content": "Search completed.", "tools_used": [TOOL],
        "tool_results": saved,
    }])
    assert TAIL in history and "action=read_result" in history
    assert "Star Wars: A New Hope" in history and "Provider 7" in history
    assert result == before


@pytest.mark.parametrize("provider", ["openai", "xai"])
def test_native_provider_continuations_use_google_budget_not_the_generic_6k(assembler, provider):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.timezone = ZoneInfo("UTC")
    orchestrator.router = SimpleNamespace(model_name="fixture-model")
    orchestrator._config_int = lambda _name, default: default
    orchestrator._get_context_assembler = lambda: assembler
    build = getattr(orchestrator, f"_build_{provider}_provider_continuation")
    result = google_result(text_chars=26000, context_chars=40000)
    continuation = build(route={"response_id": "response-1", "tool_call_id": "call-1"},
                         tool_name=TOOL, arguments={"action": "search", "query": "star wars"},
                         result=result, duration_ms=10)
    assert continuation and TAIL in continuation["result_message"]
    assert len(continuation["result_message"]) > 20000
    assert continuation["result_meta"]["result_chars_shown"] > 20000
    assert assembler.provider_result_max_chars({"ok": True, "data": {}}, 6000) == 6000


def test_accumulated_synthesis_keeps_google_evidence_above_old_9900_total(assembler):
    text = assembler.extract_useful_data({
        "clock": {"title": "Other evidence"}, TOOL: google_result(),
    }, has_text_summarizer_summary_for_ref=lambda *_: False)
    assert TAIL in text and "Other evidence" in text
    assert len(text) > 10000


def test_default_provider_message_keeps_google_evidence_and_explicit_tiny_budget_keeps_archive(assembler):
    result = google_result()
    rendered, _meta = assembler.build_provider_tool_result_message(
        tool_name=TOOL, arguments={"action": "search", "query": "Star Wars"}, result=result,
    )
    assert TAIL in rendered and len(rendered) > 10000
    tiny, metadata = assembler.build_provider_tool_result_message(
        tool_name=TOOL, arguments={}, result=result, max_chars=800,
    )
    assert len(tiny) <= 800 and result["data"]["raw_ref"] in tiny
    assert metadata["result_truncated"] is True


def test_repeated_local_pages_keep_latest_evidence_and_all_exact_read_receipts():
    search = google_result()
    runs = [search]
    for offset in (0, 10, 20, 30):
        read = deepcopy(search)
        read["data"]["result"]["panels"].append({
            "key": "available_on", "path": "/knowledge_graph/available_on", "type": "array",
            "count": 100, "preview": [{"name": f"Option {index}"} for index in range(offset, offset + 10)],
            "preview_count": 10, "truncated": True,
        })
        read["data"]["result"].update(selected_path="/knowledge_graph/available_on",
                                     offset=offset, returned_count=10, has_more=True, next_offset=offset + 10)
        runs.extend([read, deepcopy(read)])
    projected = project_google_runs(runs)
    assert len(json.dumps(projected, separators=(",", ":"))) <= 20000
    assert len(projected["results"]) == 1
    assert TAIL in json.dumps(projected)
    assert projected["retained_reads_count"] == 5
    assert [row.get("offset") for row in projected["retained_reads"]] == [None, 0, 10, 20, 30]
    assert projected["results"][0]["result"]["next_offset"] == 40
    replayed = project_google_runs(projected)
    assert replayed["retained_reads"] == projected["retained_reads"]


def test_web_completion_guard_and_recovery_do_not_prefix_slice_google_evidence():
    value = {TOOL: google_result(), "other_tool": {"text": "other" * 3000}}
    before = deepcopy(value)
    rendered = ChatHandler._truncate_for_prompt(value, max_chars=4500)
    parsed = json.loads(rendered)
    assert TAIL in rendered and len(parsed[TOOL]["result"]["panels"]) == 18
    assert "other context truncated" in parsed["other_context_preview"]
    assert value == before
    assert google_prompt_evidence({"other_tool": "x"}, other_max_chars=4500) is None
    assert ChatHandler._truncate_for_prompt({"other_tool": "x" * 6000}, max_chars=4500).endswith("[truncated]")


def _completion_guard_audit_prompt(monkeypatch, data):
    prompts = []

    def chat(prompt, **_kwargs):
        prompts.append(prompt)
        return json.dumps({"recommended_action": "accept", "task_status": "complete",
                           "risk_level": "low", "repair_worthwhile": False})

    handler = ChatHandler.__new__(ChatHandler)
    handler._create_completion_guard_eval_provider = lambda **_kwargs: (
        "openai", "fixture-model", SimpleNamespace(chat=chat)
    )
    handler._get_completion_guard_location_context = lambda _mode: "Fixture location"
    handler._get_completion_guard_policy = lambda: SimpleNamespace(reminder_guidance=lambda _record: "")
    monkeypatch.setattr(sys.modules[ChatHandler.__module__], "load_model_prompt_override", lambda **_kwargs: {})
    result = handler._evaluate_completion_guard_auto({
        "mode": "cloud", "tool_policy": "auto", "query": "Explain the saved evidence",
        "raw_llm_response": "Answer.", "speech": "Answer.", "data": data,
    })
    assert result["recommended_action"] == "accept"
    assert len(prompts) == 1
    return prompts[0]


def _audit_json_section(prompt, heading):
    return prompt.split(heading, 1)[1].split("```json\n", 1)[1].split("\n```", 1)[0]


def test_completion_guard_spends_one_google_budget_across_both_real_prompt_sections(monkeypatch):
    google = google_result(text_chars=42000, context_chars=60000)
    data = {TOOL: google, "other_tool": {"text": "current evidence " * 1500},
            "_effective_evidence": {
                "supporting_tool_results": {TOOL: deepcopy(google), "prior_tool": "prior evidence " * 1000},
                "derived_from_prior": True,
            }}
    before = deepcopy(data)
    prompt = _completion_guard_audit_prompt(monkeypatch, data)
    effective = _audit_json_section(prompt, "Effective evidence (structured grounding;")
    current = _audit_json_section(prompt, "Structured result data:")
    shared = _audit_json_section(prompt, "Retained Google evidence (shared by the sections above):")
    assert prompt.count(TAIL) == 1
    assert 30000 < len(shared) <= 60000
    assert json.loads(shared)["raw_ref"] == google["data"]["raw_ref"]
    assert len(effective) <= 4500 + len("\n... [truncated]")
    assert len(current) <= 7000 + len("\n... [truncated]")
    assert "prior evidence" in effective and "current evidence" in current
    assert TAIL not in effective and TAIL not in current
    assert data == before


def test_shared_google_audit_preserves_distinct_archives_and_read_receipts():
    prior = google_result(text_chars=500)
    prior["data"]["raw_ref"] = "stash://prior-google/search"
    first = google_result(text_chars=500)
    first["data"]["result"].update(selected_path="/available_on", offset=0,
                                  returned_count=4, has_more=True, next_offset=4)
    second = deepcopy(first)
    second["data"]["result"].update(offset=4, has_more=False, next_offset=None)
    values = [{"supporting_tool_results": {TOOL: {"results": [prior, first]}}},
              {TOOL: second}]
    before = deepcopy(values)
    others, evidence = google_prompt_evidence_parts(values)
    assert evidence is not None
    assert {row["raw_ref"] for row in evidence["results"]} == {
        "stash://prior-google/search", "stash://google-fixture/full-search",
    }
    assert [row.get("offset") for row in evidence["retained_reads"]] == [None, 0, 4]
    assert evidence["results"][-1]["result"]["offset"] == 4
    assert "Bounded local evidence" not in json.dumps(others)
    assert values == before


@pytest.mark.parametrize("effective_first", [False, True])
def test_completion_guard_nested_prior_copy_cannot_replace_current_read_page(monkeypatch, effective_first):
    prior = google_result(text_chars=500)
    prior["data"]["result"].update(selected_path="/available_on", offset=0,
                                  returned_count=4, has_more=True, next_offset=4)
    prior["data"]["result"]["panels"][-1]["preview"] = "PRIOR_PAGE_ONLY"
    current = deepcopy(prior)
    current["data"]["result"].update(offset=4, has_more=False, next_offset=None)
    current["data"]["result"]["panels"][-1]["preview"] = "CURRENT_PAGE_ONLY"
    effective = {"supporting_tool_results": {TOOL: prior}, "derived_from_prior": True}
    data = {"_effective_evidence": effective, TOOL: current} if effective_first else {
        TOOL: current, "_effective_evidence": effective,
    }
    before = deepcopy(data)
    prompt = _completion_guard_audit_prompt(monkeypatch, data)
    shared = json.loads(_audit_json_section(prompt, "Retained Google evidence (shared by the sections above):"))
    assert shared["results"][0]["result"]["offset"] == 4
    assert [row["offset"] for row in shared["retained_reads"]] == [0, 4]
    assert "CURRENT_PAGE_ONLY" in prompt and "PRIOR_PAGE_ONLY" not in prompt
    assert data == before


def test_completion_guard_non_google_sections_keep_the_original_caps_and_format(monkeypatch):
    data = {"other_tool": "current evidence " * 1500,
            "_effective_evidence": {"supporting_tool_results": {"prior_tool": "prior evidence " * 1000}}}
    prompt = _completion_guard_audit_prompt(monkeypatch, data)
    assert "Retained Google evidence" not in prompt
    assert _audit_json_section(prompt, "Effective evidence (structured grounding;") == (
        ChatHandler._truncate_for_prompt(data["_effective_evidence"], max_chars=4500)
    )
    assert _audit_json_section(prompt, "Structured result data:") == (
        ChatHandler._truncate_for_prompt(data, max_chars=7000)
    )


def test_workflow_handoff_keeps_exact_read_handle_instead_of_cutting_nested_json(assembler):
    result = google_result()
    receipt = google_workflow_receipt(result, max_chars=650)
    assert receipt["raw_ref"] == result["data"]["raw_ref"]
    assert receipt["read_action"] == "read_result" and receipt["panel_count"] == 18
    assert len(json.dumps(receipt, separators=(",", ":"))) <= 650
    workflow = {"ok": True, "data": {"results": [{
        "step": 1, "tool": TOOL, "ok": True, "data": result["data"],
    }]}}
    preview = assembler.build_workflow_result_preview(workflow, max_chars=8000)
    assert "stash://google-fixture/full-search" in json.dumps(preview)
    assert "read_result" in json.dumps(preview)


def test_selected_panel_read_retains_full_section_inventory_and_native_panel_count():
    read = google_result()
    result = read["data"]["result"]
    result["section_inventory"] = [{key: panel[key] for key in ("key", "path", "type", "count")}
                                   for panel in result["panels"]]
    result["panels_count"] = 18
    result["panels"] = result["panels"][:2]
    result.update(selected_path="/answer_box", offset=0, returned_count=1, has_more=False, next_offset=None)
    followup = extract_followup_data({TOOL: read})[TOOL]
    assert len(followup["result"]["section_inventory"]) == 18
    assert followup["result"]["section_inventory"][-1]["path"] == "/future_panel_15"
    assert TAIL in json.dumps(followup)
    receipt = google_workflow_receipt(read, max_chars=650)
    assert receipt["panel_count"] == 18
    assert receipt.get("panel_keys_truncated") is True or len(receipt["panel_keys"]) == 18


def test_oversized_old_read_manifest_is_omitted_whole_without_losing_latest_archive():
    runs = []
    for index in range(12):
        row = google_result(text_chars=500)
        row["data"]["result"]["panels"].append({
            "key": "long-key", "path": "/" + "a" * 2000, "type": "array", "count": 20,
            "preview": [{"name": f"Option {index}"}], "preview_count": 1, "truncated": True,
        })
        row["data"]["result"].update(selected_path="/" + "a" * 2000, offset=index,
                                      returned_count=1, has_more=True, next_offset=index + 1)
        runs.append(row)
    projected = project_google_runs(runs)
    assert len(json.dumps(projected, separators=(",", ":"))) <= 20000
    assert projected["retained_reads_truncated"] is True
    assert projected["retained_reads_count"] == 12
    assert projected["results"][-1]["result"]["next_offset"] == 12


def test_reprojected_read_receipt_uses_the_visible_page_cursor():
    search = google_result(text_chars=500)
    read = google_result(text_chars=500)
    pointer = "/answer_box/snippet"
    read["data"]["result"]["panels"] = [read["data"]["result"]["panels"][0], {
        "key": "snippet", "path": pointer, "type": "scalar", "count": 30000,
        "preview": "x" * 30000, "preview_count": 30000, "truncated": True,
    }]
    read["data"]["result"].update(selected_path=pointer, offset=0, returned_count=30000,
                                 has_more=False, next_offset=None)
    result = project_google_runs([search, read])
    preview = result["results"][0]["result"]
    receipt = result["retained_reads"][-1]
    assert 0 < preview["returned_count"] < 30000
    assert receipt["next_offset"] == preview["next_offset"] == preview["returned_count"]
    assert receipt["has_more"] is True
