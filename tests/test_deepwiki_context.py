"""DeepWiki research survives provider budgets, saved history, and workflows."""

import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lib import deepwiki
from lib.deepwiki_context import DEEPWIKI_TOOL_NAMES, project_deepwiki_data
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
load_server_package("deepwiki_test_server", ROOT / "jarvis-web/server")
followup = importlib.import_module("deepwiki_test_server.services.followup_extractor")
CONTEXT_SPEC = importlib.util.spec_from_file_location(
    "deepwiki_test_context", ROOT / "orchestrator/context_assembler.py",
)
context = importlib.util.module_from_spec(CONTEXT_SPEC)
CONTEXT_SPEC.loader.exec_module(context)
TOOL = "mcp_deepwiki_ask_question"
SOURCE = "https://deepwiki.com/pallets/flask/1-overview"
ARGS = {"repoName": "pallets/flask", "question": "How are requests dispatched?"}


def _result(answer=None):
    if answer is None:
        answer = "Request dispatch uses the routing map. " * 135 + f"\n[Overview]({SOURCE})"
    return deepwiki.normalize_deepwiki_result(
        "ask_question", {"content": [{"type": "text", "text": answer}]}, ARGS,
    )


def _assembler():
    return context.ContextAssembler.__new__(context.ContextAssembler)


@pytest.mark.parametrize("tool", sorted(DEEPWIKI_TOOL_NAMES))
def test_research_answer_and_tail_citation_survive_context_and_saved_followup(tool):
    result = _result()
    before = deepcopy(result)
    answer = result["data"]["answer"]
    assert 5000 < len(answer) < 6000
    assembler = _assembler()

    preview, _total, shown, truncated = assembler.build_llm_result_context_preview(tool, result)
    projected = json.loads(preview)["data"]
    assert shown == len(preview) <= 10000
    assert projected["answer"] == answer
    assert projected["answer_truncated"] is False
    assert truncated is False
    assert projected["sources"] == [{"title": "Overview", "url": SOURCE}]
    assert "raw" not in projected and "full_text" not in projected
    assert preview.count("Request dispatch uses the routing map.") == 135

    saved = followup.extract_followup_data({tool: result})[tool]
    assert saved["answer"] == answer
    assert saved["question"] == ARGS["question"]
    assert saved["repo_names"] == ["pallets/flask"]
    assert saved["sources"][0]["url"] == SOURCE
    assert saved["external_content_trust"] == "untrusted"
    assert result == before


@pytest.mark.parametrize("budget", [1800, 6000, 10000])
def test_native_provider_continuation_keeps_complete_sources_and_stash_handle(budget):
    result = _result()
    result["data"]["stash_ref"] = "stash://research/full_answer"
    result["data"]["answer_chars"] = 18000
    result["data"]["answer_truncated"] = True
    before = deepcopy(result)

    message, metadata = _assembler().build_provider_tool_result_message(
        tool_name=TOOL, arguments=ARGS, result=result, max_chars=budget,
    )
    body = message.split("\nResult:\n", 1)[1]
    wrapped = json.loads(body)
    projected = wrapped["result"]["data"]
    assert len(message) <= budget
    assert metadata["result_chars_shown"] == len(body)
    assert wrapped["result_truncated"] == metadata["result_truncated"]
    assert projected["stash_ref"] == "stash://research/full_answer"
    assert projected["sources"] == [{"title": "Overview", "url": SOURCE}]
    assert projected["answer_chars"] == 18000
    assert projected["answer_truncated"] is True
    assert result == before


def test_legacy_mcp_result_uses_request_trace_and_normalizes_citations_without_stash(monkeypatch):
    def forbidden_save(*args, **kwargs):
        pytest.fail("Replaying history must not write Stash artifacts")

    monkeypatch.setattr(deepwiki, "_save_answer", forbidden_save)
    text = "Legacy architecture detail. " * 300 + (
        '\n<wiki_page repo_name="pallets/flask" id="1" page_name="Overview" />'
    )
    legacy = {"full_text": text, "raw": [{"type": "text", "text": text}]}
    compact = followup.extract_followup_data({
        TOOL: legacy,
        "_tool_trace": [{"tool": TOOL, "ok": True, "arguments": ARGS}],
    })[TOOL]

    assert compact["repo_names"] == ["pallets/flask"]
    assert compact["question"] == ARGS["question"]
    assert compact["answer_truncated"] is True
    assert compact["sources"] == [{"title": "Overview", "url": SOURCE}]
    assert "stash_ref" not in compact
    assert "raw" not in compact and "full_text" not in compact
    assert "<wiki_page" not in compact["answer"]


@pytest.mark.parametrize("budget", [256, 600, 1400, 7500, 9900])
def test_projection_bounds_unicode_huge_metadata_and_sources_without_cutting_handles(budget):
    sources = [
        {"title": "Details " + "界" * 500, "url": f"https://github.com/pallets/flask/blob/main/src/{i}.py"}
        for i in range(100)
    ]
    sources += [
        {"title": "Bad", "url": "https://127.0.0.1/private"},
        {"title": "Long", "url": "https://deepwiki.com/" + "x" * 4000},
    ]
    result = {"ok": True, "data": {
        "repo_names": ["pallets/flask"], "question": "界" * 20000,
        "answer": "界" * 6000, "answer_chars": 60000, "answer_truncated": True,
        "sources": sources, "stash_ref": "stash://research/full_answer",
        "artifact_warning": "Warning " * 1000, "api_token": "SECRET_SENTINEL",
        "raw": "RAW_SENTINEL", "full_text": "RAW_SENTINEL",
    }}
    projected = project_deepwiki_data(result, max_chars=budget)
    encoded = json.dumps(projected, separators=(",", ":"))
    assert len(encoded) <= budget
    assert "SECRET_SENTINEL" not in encoded and "RAW_SENTINEL" not in encoded
    assert projected["answer_truncated"] is True
    assert projected["sources_truncated"] is True
    if budget >= 600:
        assert projected["stash_ref"] == "stash://research/full_answer"
    assert len(projected.get("sources", [])) <= 12
    for row in projected.get("sources", []):
        assert row["url"] in {source["url"] for source in sources}
        assert "truncated" not in row["url"]
        assert row["url"].startswith("https://github.com/")


def test_failed_request_stays_error_without_research_or_artifact_fields():
    result = deepwiki.normalize_deepwiki_result("ask_question", {
        "isError": True,
        "content": [{"type": "text", "text": "Repository not found. Visit https://deepwiki.com/bigsk1/jarvis-voice to index it."}],
    }, {"repoName": "bigsk1/jarvis-voice", "question": "Explain architecture"})
    # An error must stay an error even if an old cached payload has answer-like fields.
    result["data"].update({"answer": "Stale answer", "sources": [{"title": "stale", "url": SOURCE}], "stash_ref": "stash://stale/answer"})
    assembler = _assembler()
    preview = json.loads(assembler.build_llm_result_context_preview(TOOL, result)[0])
    assert preview["ok"] is False
    saved = followup.extract_followup_data({TOOL: result})[TOOL]
    for projected in (preview["data"], saved):
        assert projected["ok"] is False
        assert "Repository not found" in projected["error"]
        assert projected["repo_names"] == ["bigsk1/jarvis-voice"]
        assert not {"answer", "sources", "stash_ref"} & projected.keys()


def test_comparison_retains_all_ten_repositories_when_they_fit():
    repos = [f"owner/repo{i}" for i in range(10)]
    result = deepwiki.normalize_deepwiki_result("ask_question", {
        "content": [{"type": "text", "text": "Compared the repositories."}],
    }, {"repoName": repos})
    projected = project_deepwiki_data(result)
    assert projected["repo_names"] == repos
    assert not projected.get("repo_names_truncated")


def test_already_bounded_sources_keep_original_count_and_omission_flag():
    result = _result("A complete short answer.")
    result["data"].update({
        "sources": [{"title": "Overview", "url": SOURCE}],
        "sources_count": 1280,
        "sources_truncated": True,
        "stash_ref": "stash://research/full_answer",
    })
    preview = _assembler().build_llm_result_context_preview(TOOL, result)
    assert preview[3] is True
    saved = followup.extract_followup_data({TOOL: result})[TOOL]
    for projected in (json.loads(preview[0])["data"], saved):
        assert projected["sources_count"] == 1280
        assert projected["sources_truncated"] is True
        assert projected["sources"] == [{"title": "Overview", "url": SOURCE}]
        assert projected["stash_ref"] == "stash://research/full_answer"
    # An upstream omission flag remains meaningful even with no count supplied.
    result["data"].pop("sources_count")
    projected = project_deepwiki_data(result)
    assert projected["sources_count"] == 1
    assert projected["sources_truncated"] is True


@pytest.mark.parametrize("legacy", [False, True])
def test_relative_file_citations_keep_revision_caveat_after_projection(legacy):
    text = "Request context uses [ctx.py](src/flask/ctx.py)."
    result = {"full_text": text} if legacy else _result(text)
    projected = project_deepwiki_data(result, arguments=ARGS)
    assert projected["sources"][0]["url"] == "https://github.com/pallets/flask/blob/HEAD/src/flask/ctx.py"
    assert projected["citation_revision_note"] == deepwiki.DEEPWIKI_CITATION_REVISION_NOTE
    assert "HEAD" in projected["sources"][0]["title"]


def test_repeated_calls_keep_own_request_context_and_total_budget():
    runs, trace = [], []
    for number in range(7):
        runs.append({"full_text": f"Repository {number} evidence. " * 100})
        trace.append({"tool": TOOL, "ok": True, "arguments": {
            "repoName": f"owner/repo{number}", "question": f"Question {number}",
        }})
    saved = followup.extract_followup_data({TOOL: runs, "_tool_trace": trace})[TOOL]
    assert saved["runs_count"] == 7
    assert saved["results_truncated"] is True
    assert len(saved["results"]) == 5
    assert len(json.dumps(saved, separators=(",", ":"))) < 7500
    for number, row in enumerate(saved["results"], 2):
        assert row["repo_names"] == [f"owner/repo{number}"]
        assert row["question"] == f"Question {number}"
        assert row["answer"].startswith(f"Repository {number} evidence.")

    missing_trace = followup.extract_followup_data({TOOL: runs[:2], "_tool_trace": trace[-1:]})[TOOL]
    assert all(not row["repo_names"] for row in missing_trace["results"])


def test_workflow_projection_and_followup_keep_bound_research_then_canvas():
    result = _result()
    result["data"]["stash_ref"] = "stash://research/full_answer"
    workflow = {"ok": True, "data": {"action": "run", "workflow_id": "repo_notes", "results": [
        {"tool": TOOL, "ok": True, "data": result["data"], "_workflow_source_arguments": ARGS},
        {"tool": "canvas", "ok": True, "data": {"page_id": "architecture", "title": "Architecture"}},
    ]}}
    steps = _assembler().build_workflow_result_preview(workflow, max_chars=8000)["llm_context_preview"]["step_results"]
    evidence = json.loads(steps[0]["result_preview"])
    assert evidence["stash_ref"] == "stash://research/full_answer"
    assert evidence["sources"][0]["url"] == SOURCE
    saved = followup.extract_followup_data({"workflow": workflow["data"]})
    assert saved[TOOL]["answer"] == result["data"]["answer"]
    assert saved["canvas"]["page_id"] == "architecture"

    workflow["data"]["results"][0]["data"] = {"full_text": "Legacy workflow answer."}
    saved = followup.extract_followup_data({"workflow": workflow["data"]})
    assert saved[TOOL]["repo_names"] == ["pallets/flask"]
    assert saved[TOOL]["question"] == ARGS["question"]


def test_saved_history_and_fallback_synthesis_retain_useful_answer(tmp_path):
    result = _result()
    saved = followup.extract_followup_data({TOOL: result})
    history_file = tmp_path / "conversation.json"
    history_file.write_text(json.dumps([{"role": "assistant", "content": "Explained routing.", "tools_used": [TOOL], "tool_results": saved}]))
    assembler = _assembler()
    assembler.timezone = ZoneInfo("UTC")
    assembler._safe_iso_to_local_datetime = lambda value: None
    history = assembler.format_conversation_context("Save this to Canvas", json.loads(history_file.read_text()))
    assert SOURCE in history
    assert ARGS["question"] in history
    synthesis = assembler.extract_useful_data(
        {TOOL: result["data"]}, has_text_summarizer_summary_for_ref=lambda *args: False,
    )
    assert SOURCE in synthesis
    assert synthesis.count("Request dispatch uses the routing map.") == 135


def test_workflow_foreach_keeps_latest_evidence_and_explicit_omission():
    outputs = [_result("First repository evidence."), _result("Latest repository evidence.")]
    outputs[-1]["data"]["stash_ref"] = "stash://research/latest"
    workflow = {"ok": True, "data": {"results": [
        {"tool": TOOL, "ok": True, "outputs": outputs},
    ]}}
    steps = _assembler().build_workflow_result_preview(workflow, max_chars=8000)["llm_context_preview"]["step_results"]
    evidence = json.loads(steps[0]["result_preview"])
    assert evidence["runs_count"] == 2
    assert evidence["results_truncated"] is True
    assert evidence["latest_result"]["answer"] == "Latest repository evidence."
    assert evidence["latest_result"]["stash_ref"] == "stash://research/latest"


def test_failed_workflow_step_is_not_replayed_as_successful_research():
    workflow = {"action": "run", "results": [
        {"tool": TOOL, "ok": False, "error": "Repository not indexed.", "data": {"answer": "Stale content"}},
    ]}
    saved = followup.extract_followup_data({"workflow": workflow})[TOOL]
    assert saved["ok"] is False
    assert saved["error"] == "Repository not indexed."
    assert "answer" not in saved
