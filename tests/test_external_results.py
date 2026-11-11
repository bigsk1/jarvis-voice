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
    select_external_followup_results,
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


def test_apify_followup_keeps_disjoint_page_references_and_latest_failed_status():
    base = _data()
    base["source"]["provider"] = "apify"
    base["result"]["kind"] = "dataset"
    base["result"]["dataset_id"] = "dataset_exact"
    base["result"]["sample_items"] = [{"address": "A retained property", "price": 420000,
        "listing_status": "for_sale", "days_on_zillow": None}]
    base["result"].pop("items", None)
    earlier = deepcopy(base)
    earlier["result"]["offset"] = 0
    latest = deepcopy(base)
    latest["result"]["offset"] = 20
    latest["result"]["pagination"] = {"next_offset": 40, "run_id": "run_exact"}
    status = deepcopy(base)
    status["result"] = {"kind": "object", "value": {"status": "FAILED"}}
    status["execution"]["status"] = "FAILED"
    status["raw_ref"] = "stash://space_example/status_failed"
    saved = followup.extract_followup_data({"apify_read_result": [earlier, latest, status]})["apify_read_result"]
    assert saved["runs_count"] == 3 and saved["results_truncated"]
    assert len(saved["results"]) == 1
    result = saved["results"][0]["result"]
    assert result["offset"] == 20 and result["pagination"]["next_offset"] == 40
    assert result["sample_items"][0]["price"] == 420000
    assert result["sample_items"][0]["days_on_zillow"] is None
    assert result["returned_count"] == latest["result"]["returned_count"]
    assert [page["offset"] for page in result["retained_pages"]] == [0, 20]
    assert saved["results"][0]["execution"]["status"] == "FAILED"
    assert saved["results"][0]["execution"]["status_raw_ref"] == status["raw_ref"]


def test_apify_followup_does_not_replace_full_fetched_page_with_overlapping_tail():
    full = _data(rows=[{"address": f"Property {i}", "price": 400000} for i in range(8)])
    full["source"]["provider"] = "apify"
    full["result"]["offset"] = 0
    full["result"]["requested_fields"] = None
    tail = deepcopy(full)
    tail["raw_ref"] = "stash://space_example/tail"
    tail["result"].update(offset=5, returned_count=3, items=deepcopy(full["result"]["items"][5:]))
    saved = followup.extract_followup_data({"apify_read_result": [full, tail]})["apify_read_result"]
    assert saved["results"][0]["result"]["returned_count"] == 8
    assert saved["results"][0]["result"]["offset"] == 0
    assert saved["results"][0]["result"]["retained_pages_count"] == 1


def _apify_page(offset, *, count=20, run_id="run_exact", dataset_id="dataset_exact", mode="cloud"):
    page = _data(rows=[{"record_id": f"row_{offset + index}", "description": "Evidence " * 100}
                       for index in range(min(count, 20))], run_id=run_id, mode=mode)
    page["source"]["provider"] = "apify"
    page["result"].update(dataset_id=dataset_id, offset=offset, returned_count=count,
                          requested_fields=None, pagination={"next_offset": offset + count})
    page["raw_ref"] = f"stash://space_example/{run_id}_{dataset_id}_page_{offset}"
    return page


def test_twenty_disjoint_pages_survive_one_bounded_followup_without_merged_counts():
    pages = [_apify_page(offset, count=100) for offset in range(0, 2000, 100)]
    before = deepcopy(pages)
    saved = followup.extract_followup_data({"apify_read_result": pages})["apify_read_result"]
    result = saved["results"][0]["result"]
    assert len(json.dumps(saved, ensure_ascii=True, separators=(",", ":"))) <= 6000
    assert result["retained_pages_count"] == 20
    assert [page["raw_ref"] for page in result["retained_pages"]] == [page["raw_ref"] for page in pages]
    assert [page["offset"] for page in result["retained_pages"]] == list(range(0, 2000, 100))
    assert result["returned_count"] == 100
    assert result["offset"] == 1900
    assert result["total_items"] is None and result["complete"] is None
    assert not result.get("retained_pages_truncated")
    assert pages == before


@pytest.mark.parametrize("change", [
    "unknown_fields", "different_fields", "partial_overlap", "sampled", "changed_rows",
    "normalized", "compacted", "missing_archive",
])
def test_page_manifest_does_not_deduplicate_unproven_containment(change):
    full = _apify_page(0, count=8)
    tail = deepcopy(full)
    tail["raw_ref"] = "stash://space_example/tail"
    tail["result"].update(offset=5, returned_count=3, items=deepcopy(full["result"]["items"][5:]))
    if change == "unknown_fields":
        full["result"].pop("requested_fields")
        tail["result"].pop("requested_fields")
    elif change == "different_fields":
        tail["result"]["requested_fields"] = "record_id"
    elif change == "partial_overlap":
        tail["result"]["returned_count"] = 8
    elif change == "sampled":
        full["result"]["returned_count"] = 100
    elif change == "normalized":
        full["result"]["presentation"] = {"kind": "properties"}
    elif change == "compacted":
        full["limits"]["truncated"] = True
    elif change == "missing_archive":
        full["raw_ref"] = None
    else:
        tail["result"]["items"][0]["record_id"] = "a_changed_record"
    result = select_external_followup_results([full, tail])[0]["result"]
    assert result["retained_pages_count"] == 2
    assert [page["raw_ref"] for page in result["retained_pages"]] == [full["raw_ref"], tail["raw_ref"]]


def test_broader_later_equivalent_page_replaces_only_contained_reference():
    full = _apify_page(0, count=8)
    tail = deepcopy(full)
    tail["raw_ref"] = "stash://space_example/tail"
    tail["result"].update(offset=5, returned_count=3, items=deepcopy(full["result"]["items"][5:]))
    result = select_external_followup_results([tail, full, deepcopy(full)])[0]["result"]
    assert result["retained_pages"] == [{
        "offset": 0, "returned_count": 8, "requested_fields": None, "raw_ref": full["raw_ref"],
    }]


def test_page_manifests_and_native_status_do_not_cross_mode_run_or_dataset():
    pages = [_apify_page(0), _apify_page(20, mode="local"),
             _apify_page(40, run_id="other_run"), _apify_page(60, dataset_id="other_dataset")]
    status = deepcopy(pages[0])
    status["result"] = {"kind": "object", "value": {"status": "FAILED"}}
    status["execution"]["status"] = "FAILED"
    status["raw_ref"] = "stash://space_example/failed_status"
    selected = select_external_followup_results([*pages, status], limit=10)
    assert len(selected) == 4
    for item in selected:
        identity = (item["source"]["mode"], item["execution"]["run_id"], item["result"]["dataset_id"])
        expected = next(page for page in pages if (
            page["source"]["mode"], page["execution"]["run_id"], page["result"]["dataset_id"],
        ) == identity)
        assert item["result"]["retained_pages"][0]["raw_ref"] == expected["raw_ref"]
        assert item["execution"]["status"] == ("FAILED" if identity[:2] == ("cloud", "run_exact") else "SUCCEEDED")


def test_page_manifest_survives_preview_and_optional_metadata_pressure():
    pages = [_apify_page(offset) for offset in range(0, 100, 20)]
    status = deepcopy(pages[-1])
    status["execution"]["status"] = "FAILED"
    status["raw_ref"] = "stash://space_example/failed_status"
    status["result"] = {"kind": "object", "value": {"status": "FAILED"}}
    selected = select_external_followup_results([*pages, status])[0]
    selected["result"]["optional_details"] = "very large " * 1000
    selected["result"]["pagination"]["next_cursor"] = "opaque" * 2000
    selected["artifacts"] = [{"kind": "raw", "url": "https://example.com/" + "x" * 5000}]
    projected = project_external_result(selected, max_chars=1800)
    assert len(json.dumps(projected, ensure_ascii=True, separators=(",", ":"))) <= 1800
    assert projected["result"]["retained_pages"] == selected["result"]["retained_pages"]
    assert projected["execution"]["run_id"] == "run_exact"
    assert projected["execution"]["status"] == "FAILED"
    assert projected["execution"]["status_raw_ref"] == status["raw_ref"]
    assert projected["source"]["mode"] == "cloud"
    assert projected["result"]["dataset_id"] == "dataset_exact"


def test_pathological_page_manifest_marks_omitted_references_explicitly():
    pages = [_apify_page(offset) for offset in range(0, 100, 20)]
    for index, page in enumerate(pages):
        page["raw_ref"] = f"stash://space_example/{index}_" + "x" * 300
    selected = select_external_followup_results(pages)[0]
    projected = project_external_result(selected, max_chars=1500)
    assert projected["result"]["retained_pages_truncated"] is True
    assert projected["result"]["retained_pages_count"] == 5
    assert len(projected["result"]["retained_pages"]) < 5
    assert all(page in selected["result"]["retained_pages"] for page in projected["result"]["retained_pages"])
    assert projected["execution"]["run_id"] == "run_exact"
    assert projected["result"]["dataset_id"] == "dataset_exact"
    assert len(json.dumps(projected, ensure_ascii=True, separators=(",", ":"))) <= 1500


def _failed_apify_trace(page):
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "orchestrator"))
        from orchestrator_v2 import Orchestrator

        sanitized = Orchestrator._sanitize_tool_trace_value(page)

    return {
        "tool": "apify_read_result", "ok": False,
        "result_data": sanitized,
    }


def _apify_status(page, status):
    observed = deepcopy(page)
    observed["execution"]["status"] = status
    observed["raw_ref"] = f"stash://space_example/status_{status.lower()}"
    observed["result"] = {"kind": "object", "value": {"status": status}}
    return observed


def test_failed_trace_only_status_follows_successful_accumulated_page():
    page = _apify_page(0)
    failed = _apify_status(page, "FAILED")
    saved = followup.extract_followup_data({
        "apify_read_result": page,
        "_tool_trace": [{"tool": "apify_read_result", "ok": True, "result_data": None},
                        _failed_apify_trace(failed)],
    })["apify_read_result"]["results"][0]
    assert saved["execution"]["status"] == "FAILED"
    assert saved["execution"]["status_raw_ref"] == failed["raw_ref"]
    assert saved["result"]["retained_pages"][0]["raw_ref"] == page["raw_ref"]


def test_failed_only_native_trace_keeps_recovery_identity():
    failed = _apify_status(_apify_page(0), "FAILED")
    saved = followup.extract_followup_data({
        "_tool_trace": [_failed_apify_trace(failed)],
    })["apify_read_result"]
    assert saved["source"]["mode"] == "cloud"
    assert saved["execution"]["run_id"] == "run_exact"
    assert saved["execution"]["status"] == "FAILED"
    assert saved["raw_ref"] == failed["raw_ref"]
    assert saved["limits"]["trace_compacted"] is True


@pytest.mark.parametrize("failure_first", [False, True])
def test_later_success_wins_over_earlier_failed_trace_in_native_chronology(failure_first):
    earlier, recovered = _apify_page(0), _apify_page(20)
    failure = _failed_apify_trace(_apify_status(earlier, "FAILED"))
    success = {"tool": "apify_read_result", "ok": True, "result_data": None}
    runs = [recovered] if failure_first else [earlier, recovered]
    trace = [failure, success] if failure_first else [success, failure, success]
    saved = followup.extract_followup_data({
        "apify_read_result": runs, "_tool_trace": trace,
    })["apify_read_result"]["results"][0]
    assert saved["execution"]["status"] == "SUCCEEDED"
    assert saved["execution"]["status_raw_ref"] == recovered["raw_ref"]
    assert saved["result"]["retained_pages_count"] == len(runs)


def test_partial_trace_preserves_failure_without_inventing_its_status_order():
    page = _apify_page(0)
    saved = followup.extract_followup_data({
        "apify_read_result": page,
        "_tool_trace": [_failed_apify_trace(_apify_status(page, "FAILED"))],
    })["apify_read_result"]["results"]
    dataset = next(row for row in saved if row["result"]["kind"] == "dataset")
    failure = next(row for row in saved if row["result"]["kind"] == "object")
    assert dataset["execution"]["status"] == "SUCCEEDED"
    assert failure["execution"]["status"] == "FAILED"
    assert failure["limits"]["status_order_unknown"] is True


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


def test_minimal_apify_failure_projection_preserves_status_and_order_uncertainty():
    data = _data()
    data["source"]["provider"] = "apify"
    data["execution"].update(status="FAILED", irrelevant_id="x" * 12000)
    data["result"] = {"kind": "object"}
    data["limits"].update(status_order_unknown=True, trace_compacted=True)
    projected = project_external_result(data, max_chars=1800)
    assert projected["execution"]["run_id"] == "run_exact"
    assert projected["execution"]["status"] == "FAILED"
    assert projected["limits"]["status_order_unknown"] is True
    assert projected["limits"]["trace_compacted"] is True
    assert len(json.dumps(projected, separators=(",", ":"))) <= 1800
