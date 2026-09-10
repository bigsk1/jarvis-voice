"""Resolved workflow inputs survive source flattening and saved history replay."""

import copy
from types import SimpleNamespace

import pytest
from test_mixed_source_followup import ROOT, _history_assembler, _load_module, followup


@pytest.fixture
def pipeline():
    # No constructor: provider/config/logger initialization is outside this test.
    from orchestrator.pipeline_executor import PipelineExecutor

    instance = PipelineExecutor.__new__(PipelineExecutor)
    instance.mode = "cloud"
    instance.provider = None
    instance.logger = SimpleNamespace(log_workflow_execution=lambda **kwargs: None)
    return instance


@pytest.mark.parametrize("for_each", [False, True])
def test_workflow_source_results_keep_resolved_input_output_pairs_through_save_reload(
    tmp_path, pipeline, for_each
):
    tools = ("pdf_read", "document_ocr", "stash")
    requests = {
        "pdf_read": [{"stash_ref": f"stash://original/pdf_{n}"} for n in (2, 1)],
        "document_ocr": [{"space_id": "original", "file_id": f"scan_{n}"} for n in (2, 1)],
        "stash": [{"space_id": "original", "file_id": f"note_{n}"} for n in (2, 1)],
    }
    actual_calls = {tool: [] for tool in tools}

    def execute(tool, arguments):
        actual_calls[tool].append(copy.deepcopy(arguments))
        number = len(actual_calls[tool])
        output_ref = f"stash://generated/{tool}_{number}"
        if tool == "pdf_read":
            payload = {"stash_ref": output_ref, "text": f"PDF evidence {number}"}
        elif tool == "document_ocr":
            payload = {"stash_ref": output_ref, "markdown_stash_ref": output_ref,
                       "markdown_excerpt": f"OCR evidence {number}"}
        else:
            payload = {"ref": f"stash://{arguments['space_id']}/{arguments['file_id']}",
                       "content": f"Note evidence {number}"}
        return {"ok": True, "data": payload}

    pipeline.executor = SimpleNamespace(execute=execute)
    steps = []
    variables = {}
    actions = {"pdf_read": "extract_text", "document_ocr": "ocr", "stash": "read"}
    for tool in tools:
        if for_each:
            variables[tool] = {"from": "static", "value": requests[tool]}
            steps.append({"tool": tool, "action": actions[tool], "for_each": f"${{{tool}}}",
                          "process_all": True})
        else:
            for number, request in enumerate(requests[tool]):
                variables[f"{tool}_{number}"] = {"from": "static", "value": request}
                steps.append({"tool": tool, "action": actions[tool], "params": {
                    key: f"${{{tool}_{number}.{key}}}" for key in request
                }})
    response = pipeline.execute({"id": "compare_sources", "steps": steps, "variables": variables},
                                "Compare the second source with the first.")
    assert response["ok"] is True

    # This is the real Web save shape: original workflow plus flattened tools.
    workflow = {**response["data"], "action": "run"}
    saved_data = {"workflow": workflow, **followup.workflow_step_tool_results(workflow),
                  "_tool_trace": [{"tool": "workflow", "ok": True,
                                   "arguments": {"action": "run", "workflow_id": "compare_sources"}}]}
    store_module = _load_module("workflow_source_store", ROOT / "jarvis-web/server/services/conversation_store.py")
    store = store_module.ConversationStore(tmp_path / "conversations")
    conversation = store.create_conversation("Source comparison")
    store.add_message(conversation["id"], "assistant", "Compared the sources.",
                      data=saved_data, tools_used=list(tools))
    reloaded = store_module.ConversationStore(tmp_path / "conversations").get_conversation(conversation["id"])
    restored_data = reloaded["messages"][0]["data"]
    compact = followup.extract_followup_data(restored_data)
    nested_only = followup.extract_followup_data({"workflow": restored_data["workflow"]})
    for tool in tools:
        rows = compact[tool]["results"]
        assert rows == nested_only[tool]["results"]
        assert len(rows) == 2
        for index, row in enumerate(rows):
            expected_request = {key: value for key, value in actual_calls[tool][index].items()
                                if key != "_capture_usage"}
            assert row["request"] == expected_request
            expected_source = expected_request.get("stash_ref") or (
                f"stash://{expected_request['space_id']}/{expected_request['file_id']}"
            )
            assert row["source_stash_ref"] == expected_source
            assert row["run_ordinal"] == index + 1
            if tool != "stash":
                assert row["stash_ref"] == f"stash://generated/{tool}_{index + 1}"
                assert row["stash_ref"] != row["source_stash_ref"]
    rendered = _history_assembler().format_conversation_context(
        "Re-read the second original PDF.",
        [{"role": "assistant", "content": "Compared the sources.", "tools_used": list(tools),
          "tool_results": compact}],
    )
    assert "stash://original/pdf_2" in rendered
    assert "stash://original/scan_2" in rendered
    assert "stash://generated/document_ocr_1" in rendered


@pytest.mark.parametrize("validation_failure", [False, True])
def test_workflow_failed_iteration_cannot_assign_its_source_to_the_next_output(pipeline, validation_failure):
    calls = []

    def execute(tool, arguments):
        calls.append(arguments.copy())
        if len(calls) == 1:
            if validation_failure:
                return {"ok": True, "data": {"stash_ref": "stash://generated/invalid", "text": "Invalid PDF"}}
            return {"ok": False, "error": "Unreadable PDF", "data": {}}
        return {"ok": True, "data": {"stash_ref": "stash://generated/second", "text": "Second PDF"}}

    pipeline.executor = SimpleNamespace(execute=execute)
    pipeline._validate_result = lambda result, *_args: result["data"]["stash_ref"] != "stash://generated/invalid"
    result = pipeline.execute({
        "id": "partial_sources", "variables": {"sources": {"from": "static", "value": [
            {"stash_ref": "stash://original/first"}, {"stash_ref": "stash://original/second"},
        ]}},
        "steps": [{"tool": "pdf_read", "for_each": "${sources}", "required_success_count": 1,
                   "validation": {"enabled": validation_failure}}],
    }, "Read available PDFs")
    flattened = followup.workflow_step_tool_results(result["data"])
    compact = followup.extract_followup_data(flattened)["pdf_read"]
    rows = compact["results"]
    assert rows[-1]["source_stash_ref"] == "stash://original/second"
    assert rows[-1]["stash_ref"] == "stash://generated/second"
    assert all(row.get("source_stash_ref") != "stash://original/first" for row in rows)


def test_single_workflow_source_stays_a_dict_and_records_arguments_before_executor_mutation(pipeline):
    def execute(tool, arguments):
        assert arguments["stash_ref"] == "stash://original/actual"
        arguments["stash_ref"] = "stash://wrong/mutated"
        return {"ok": True, "data": {"stash_ref": "stash://generated/text", "text": "PDF contents"}}

    pipeline.executor = SimpleNamespace(execute=execute)
    response = pipeline.execute({"id": "single", "steps": [{
        "tool": "pdf_read", "action": "extract_text",
        "params": {"stash_ref": "stash://original/actual", "text": "Body must not be copied into provenance",
                   "api_key": "SECRET_MUST_NOT_BE_COPIED"},
    }]}, "Read this PDF")
    flattened = followup.workflow_step_tool_results(response["data"])
    assert isinstance(flattened["pdf_read"], dict)
    compact = followup.extract_followup_data(flattened)["pdf_read"]
    assert compact["request"] == {"action": "extract_text", "stash_ref": "stash://original/actual"}
    assert compact["source_stash_ref"] == "stash://original/actual"
    assert compact["stash_ref"] == "stash://generated/text"
    assert "results" not in compact and "run_ordinal" not in compact
    assert "SECRET_MUST_NOT_BE_COPIED" not in str(flattened)


def test_workflow_legacy_results_never_guess_sources_from_unrelated_parent_trace():
    workflow = {"action": "run", "workflow_id": "legacy", "results": [
        {"tool": "pdf_read", "ok": True, "data": {"stash_ref": "stash://generated/first"}},
        {"tool": "pdf_read", "ok": True, "data": {"stash_ref": "stash://generated/second"}},
    ]}
    compact = followup.extract_followup_data({"workflow": workflow, "_tool_trace": [
        {"tool": "pdf_read", "ok": True, "arguments": {"stash_ref": "stash://unrelated/one"}},
        {"tool": "pdf_read", "ok": True, "arguments": {"stash_ref": "stash://unrelated/two"}},
    ]})["pdf_read"]
    assert all("source_stash_ref" not in row and "request" not in row for row in compact["results"])


@pytest.mark.parametrize("source_length", [400, 2200])
def test_workflow_input_identity_is_preserved_whole_or_omitted_never_shortened(pipeline, source_length):
    source = "stash://original/" + "a" * source_length
    pipeline.executor = SimpleNamespace(execute=lambda tool, arguments: {
        "ok": True, "data": {"stash_ref": "stash://generated/text", "text": "PDF evidence"},
    })
    response = pipeline.execute({"id": "long_source", "steps": [{
        "tool": "pdf_read", "action": "extract_text", "params": {"stash_ref": source},
    }]}, "Read the PDF")
    compact = followup.extract_followup_data(followup.workflow_step_tool_results(response["data"]))["pdf_read"]
    if source_length == 400:
        assert compact["source_stash_ref"] == source
        assert compact["request"]["stash_ref"] == source
    else:
        assert "source_stash_ref" not in compact
        assert "stash_ref" not in compact["request"]
    assert compact["stash_ref"] == "stash://generated/text"
