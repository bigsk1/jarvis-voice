"""Provider-neutral evidence survives retention, bounded context and follow-ups."""

import importlib
import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import stash_helper
from config_loader import config_scope
from server_package_utils import load_server_package
from stash_helper import get_space, parse_stash_ref

from lib.external_results import (
    external_result_from_mcp,
    is_external_result,
    make_external_result_data,
    project_external_result,
)

ROOT = Path(__file__).resolve().parents[1]
load_server_package("external_results_test_server", ROOT / "jarvis-web/server")
followup = importlib.import_module("external_results_test_server.services.followup_extractor")
SPEC = importlib.util.spec_from_file_location(
    "external_results_test_context", ROOT / "orchestrator/context_assembler.py",
)
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


def _data(*, rows=None, run_id="run_exact", **kwargs):
    if rows is None:
        rows = [
            {"id": "repeated", "nested": {"array": [False, None, 0, {}, []]}},
            {"id": "repeated", "different": [1, "two"]},
            None, False, 0, [1, {"nested": "value"}],
        ]
    return make_external_result_data(
        provider="example", tool="read_result", execution={
            "run_id": run_id, "actor_id": "actor_exact", "status": "SUCCEEDED",
        }, result={
            "kind": "dataset", "items": rows, "returned_count": len(rows),
            "total_items": None, "complete": None, "dataset_id": "dataset_exact",
            "offset": 40, "limit": 20,
            "pagination": {"has_more": True, "next_cursor": "opaque+/=" * 80},
        }, raw_ref="stash://space_example/f_raw", stash_raw=False, **kwargs,
    )


def test_nested_heterogeneous_values_and_duplicate_rows_remain_exact():
    data = _data()
    before = deepcopy(data)
    projected = project_external_result({"ok": True, "data": data}, sample_limit=20)

    assert is_external_result(data)
    assert is_external_result({"ok": True, "data": data})
    assert not is_external_result({"source": {"provider": "example"}, "result": {}})
    assert projected["result"]["items"] == data["result"]["items"]
    assert projected["result"]["sample_count"] == 6
    assert projected["result"]["items"][0]["nested"]["array"] == [False, None, 0, {}, []]
    assert projected["result"]["items"][0]["id"] == projected["result"]["items"][1]["id"]
    assert data == before
    projected["result"]["items"][0]["id"] = "edited"
    assert data == before


@pytest.mark.parametrize("budget", [1800, 4000, 6000])
def test_samples_shrink_structurally_before_exact_handles_and_counts(budget):
    data = _data(rows=[
        {"name": "row", "record_id": f"record_{index}", "deep": {"values": [{
            "description": "Evidence " * 150, "nested": {"key": "value"},
        }]}}
        for index in range(20)
    ])
    before = deepcopy(data)

    compact = project_external_result(data, max_chars=budget, sample_limit=10)
    serialized = json.dumps(compact, allow_nan=False, separators=(",", ":"))

    assert len(serialized) <= budget
    assert compact["execution"] == data["execution"]
    for key in ("dataset_id", "returned_count", "total_items", "complete", "offset", "limit", "pagination"):
        assert compact["result"][key] == data["result"][key]
    assert compact["raw_ref"] == data["raw_ref"]
    assert compact["limits"]["truncated"] is True
    assert compact["result"]["sample_count"] == len(compact["result"]["items"])
    assert isinstance(compact["result"]["items"], list)
    assert data == before


def test_complete_raw_response_is_saved_once_in_the_request_stash_root(tmp_path):
    raw = {"items": [{"id": index, "nested": [False, None, "é"]} for index in range(60)]}
    with config_scope("local", {"STASH_DIR": str(tmp_path)}):
        data = make_external_result_data(
            provider="example", tool="read", raw_payload=raw,
            result={"kind": "array", "items": raw["items"], "returned_count": 60},
        )
        space_id, file_id = parse_stash_ref(data["raw_ref"])
        space = get_space(space_id)
        saved = next(item for item in space.meta["files"] if item["file_id"] == file_id)
        assert json.loads((space.space_path / saved["stored_name"]).read_bytes()) == raw
        assert len(space.meta["files"]) == 1
        assert space.space_path.parent == tmp_path
        project_external_result(data)
        project_external_result({"data": data})
        assert len(get_space(space_id).meta["files"]) == 1

    assert data["source"]["mode"] == "local"
    assert data["artifacts"][0]["mode"] == "local"
    assert data["result"]["returned_count"] == 60
    assert data["result"]["sample_count"] == 20
    assert data["limits"]["sample_truncated"] is True


def test_existing_archive_is_reused_and_projection_never_writes(tmp_path):
    with config_scope("cloud", {"STASH_DIR": str(tmp_path)}):
        data = make_external_result_data(
            provider="example", tool="read", raw_ref="stash://space_existing/raw",
            raw_payload={"exact": "original"}, result={"kind": "object", "value": {}},
        )
        project_external_result(data)
    assert not list(tmp_path.iterdir())
    assert data["raw_ref"] == "stash://space_existing/raw"


def test_retention_failure_keeps_provider_evidence_and_does_not_echo_private_error(tmp_path, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(stash_helper.StashFile, "save_binary", unavailable)
    with config_scope("cloud", {"STASH_DIR": str(tmp_path)}):
        data = make_external_result_data(
            provider="example", tool="read", execution={"run_id": "already_submitted"},
            result={"kind": "object", "value": {"receipt": True}},
            raw_payload={"complete": "provider response"},
        )
    assert data["execution"]["run_id"] == "already_submitted"
    assert data["result"]["value"] == {"receipt": True}
    assert data["limits"]["raw_retention_error"] == "OSError"
    assert data["raw_ref"] is None
    assert "private filesystem detail" not in json.dumps(data)


def test_unsafe_integers_reach_browser_as_exact_text_while_raw_keeps_json_numbers(tmp_path):
    unsafe = 9007199254740993
    raw = {"rows": [{"record_id": unsafe, "nested": [False, None, -unsafe]}],
           "total": unsafe, "safe_edge": 9007199254740991}
    with config_scope("cloud", {"STASH_DIR": str(tmp_path)}):
        data = make_external_result_data(
            provider="example", tool="read", raw_payload=raw,
            execution={"run_id": "run_exact"}, result={
                "kind": "dataset", "sample_items": raw["rows"], "total_items": unsafe,
                "value": {"safe_edge": raw["safe_edge"], "large": unsafe},
            },
        )
        space_id, file_id = parse_stash_ref(data["raw_ref"])
        space = get_space(space_id)
        saved = next(item for item in space.meta["files"] if item["file_id"] == file_id)
        retained = json.loads((space.space_path / saved["stored_name"]).read_bytes())
    assert retained == raw
    assert type(retained["rows"][0]["record_id"]) is int
    assert data["limits"]["integer_strings"] is True
    assert data["limits"]["integer_string_paths_count"] == 4
    wire = json.dumps(project_external_result(data), allow_nan=False)
    subprocess.run(["node", "-e", """
const assert = require('node:assert/strict');
const data = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
assert.equal(data.result.sample_items[0].record_id, '9007199254740993');
assert.equal(data.result.sample_items[0].nested[2], '-9007199254740993');
assert.equal(data.result.sample_items[0].nested[0], false);
assert.equal(data.result.sample_items[0].nested[1], null);
assert.equal(data.result.total_items, '9007199254740993');
assert.equal(data.result.value.large, '9007199254740993');
assert.equal(data.result.value.safe_edge, 9007199254740991);
assert.equal(data.limits.integer_strings, true);
assert.ok(data.raw_ref.startsWith('stash://'));
"""], input=wire, text=True, check=True)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), {1: "coerced"}, (1, 2)])
def test_non_json_or_non_finite_evidence_is_rejected_before_retention(tmp_path, invalid):
    with config_scope("cloud", {"STASH_DIR": str(tmp_path)}):
        with pytest.raises(ValueError, match="JSON|keys"):
            make_external_result_data(provider="example", tool="read", raw_payload=invalid)
    assert not list(tmp_path.iterdir())


def test_mcp_conversion_uses_native_structure_without_guessing_run_ids():
    response = {"content": [{"type": "text", "text": "Presentation only"}],
                "structuredContent": {"id": "not-necessarily-a-run", "rows": [False, None]}}
    data = external_result_from_mcp("example", "lookup", response, stash_raw=False)

    assert data["result"]["value"] == response["structuredContent"]
    assert data["execution"] == {"mcp_is_error": False}
    assert "run_id" not in data["execution"]
    assert "total_items" not in data["result"]


def test_mcp_text_json_and_invalid_json_remain_distinct():
    parsed = external_result_from_mcp("example", "lookup", {
        "content": [{"type": "text", "text": '[null,false,{"id":"first"},{"id":"first"}]'}],
    }, stash_raw=False)
    assert parsed["result"]["items"] == [None, False, {"id": "first"}, {"id": "first"}]
    assert parsed["result"]["returned_count"] == 4
    assert parsed["result"]["total_items"] is None
    text = external_result_from_mcp("example", "lookup", {
        "content": [{"type": "text", "text": '{"bad":NaN}'}],
    }, stash_raw=False)
    assert text["result"]["kind"] == "text"
    assert text["result"]["text"] == '{"bad":NaN}'


def test_same_turn_synthesis_and_saved_followup_use_the_shared_projection():
    result = {"ok": True, "speech": "Saved.", "data": _data()}
    assembler = context.ContextAssembler.__new__(context.ContextAssembler)
    message, _total, shown, truncated = assembler.build_llm_result_context_preview("new_provider_tool", result)
    projected = json.loads(message)["data"]
    saved = followup.extract_followup_data({"new_provider_tool": result})["new_provider_tool"]
    synthesis = assembler.extract_useful_data(
        {"new_provider_tool": result}, has_text_summarizer_summary_for_ref=lambda *_args: False,
    )
    assert projected == saved
    assert projected["execution"]["run_id"] == "run_exact"
    assert projected["result"]["items"][0]["nested"]["array"] == [False, None, 0, {}, []]
    assert shown == len(message) <= 6000
    assert truncated is True  # Six retained rows are sampled to five.
    assert "run_exact" in synthesis and "dataset_exact" in synthesis
    assert "result_preview_text" not in synthesis


def test_followup_keeps_repeated_runs_separate_without_deduplication():
    runs = [{"ok": True, "data": _data(run_id=f"run_{index}")} for index in range(4)]
    saved = followup.extract_followup_data({"new_provider_tool": runs})["new_provider_tool"]
    assert saved["runs_count"] == 4
    assert saved["results_truncated"] is True
    assert [item["execution"]["run_id"] for item in saved["results"]] == ["run_1", "run_2", "run_3"]
    assert all(len(item["result"]["items"]) == 5 for item in saved["results"])


@pytest.mark.parametrize("budget", [1800, 6000, 10000])
def test_native_provider_budgets_keep_json_structure_and_recovery_handles(budget):
    data = _data(rows=[{"record_id": f"row_{index}", "content": "Evidence " * 1000}
                       for index in range(20)])
    assembler = context.ContextAssembler.__new__(context.ContextAssembler)
    message, metadata = assembler.build_provider_tool_result_message(
        tool_name="apify_read_result", arguments={"dataset_id": "dataset_exact"},
        result={"ok": False, "data": data}, max_chars=budget,
    )
    body = message.split("\nResult:\n", 1)[1]
    parsed = json.loads(body)
    assert len(message) <= budget
    assert metadata["result_chars_shown"] == len(body)
    assert parsed["result"]["ok"] is False
    assert parsed["result"]["data"]["execution"]["run_id"] == "run_exact"
    assert parsed["result"]["data"]["raw_ref"] == "stash://space_example/f_raw"
    assert "result_preview_text" not in parsed
