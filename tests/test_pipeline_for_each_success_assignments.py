"""Loop success assignments must reflect the aggregate step outcome."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from config_loader import config_scope
from workflow_validation import validate_workflow_document

from orchestrator import pipeline_executor
from orchestrator.pipeline_executor import PipelineExecutor


@pytest.fixture
def runtime(monkeypatch):
    """Keep real pipeline control flow while replacing external boundaries."""
    logger = Mock()
    monkeypatch.setattr(pipeline_executor, "ToolLogger", lambda: logger)
    monkeypatch.setattr(pipeline_executor, "LLMLogger", lambda: logger)

    def build(mode="cloud"):
        calls = []

        def execute(name, params):
            calls.append((name, deepcopy(params)))
            if params.get("outcome") == "cancelled":
                return {"ok": True, "cancelled": True}
            if params.get("outcome") == "failed":
                return {"ok": False, "error": "Synthetic item failure"}
            return {"ok": True, "data": {
                "value": params.get("value", "published"), "content": params.get("content", ""),
            }}

        tools = SimpleNamespace(execute=execute)
        provider = SimpleNamespace(chat=Mock(side_effect=AssertionError("Unexpected model call")))
        pipeline = PipelineExecutor(mode, tools, provider=provider)
        return pipeline, tools, calls

    with config_scope("cloud", overrides={"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-model"}):
        yield build


def recipe(step, *, variables=None):
    return {
        "id": "loop_assignments",
        "triggers": {"explicit": ["/loop_assignments"]},
        "variables": variables or {},
        "steps": [step, {
            "step": 8,
            "tool": "publish_report",
            "condition": {"op": "truthy", "left": "${ready}"},
            "params": {"first": "${first_value}"},
        }],
        "success_speech": "Published ${first_value}.",
    }


def loop(items, **fields):
    return {
        "step": 7,
        "tool": "collect_item",
        "for_each": items,
        "output_var": "attempts",
        "validated_output_var": "usable",
        "set_variables_on_success": {"ready": True, "first_value": "${usable[0].data.value}"},
        **fields,
    }


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("explicit_output", [True, False])
def test_success_assignments_run_once_after_aggregate_outputs(runtime, mode, explicit_output):
    step = loop([{"value": "first"}, {"value": "second"}], process_all=True)
    output = "attempts"
    if not explicit_output:
        step.pop("output_var")
        output = "step7_results"
    step["set_variables_on_success"].update({
        "attempt_copy": "${" + output + "}",
        "usable_copy": "${usable}",
        "second_value": "${usable[1].data.value}",
    })
    workflow = recipe(step)
    diagnostics = validate_workflow_document(workflow, builder=True)
    assert diagnostics == {"errors": [], "warnings": []}

    with config_scope(mode, overrides={"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-model"}):
        pipeline, _tools, calls = runtime(mode)
        with patch.object(
            pipeline, "_apply_variable_assignments", wraps=pipeline._apply_variable_assignments
        ) as assignments:
            result = pipeline.execute(workflow, "/loop_assignments")

    assert result["ok"] is True
    assert calls[-1] == ("publish_report", {"first": "first"})
    assert len(calls) == 3
    variables = result["data"]["variables"]
    assert variables["second_value"] == "second"
    assert variables["attempt_copy"] == variables[output]
    assert variables["usable_copy"] == variables["usable"]
    assert len(variables[output]) == 2
    assert result["speech"] == "Published first."
    assert assignments.call_count == 1


def test_threshold_success_after_failed_candidate_unlocks_downstream(runtime):
    workflow = recipe(loop([
        {"outcome": "failed"}, {"value": "first"}, {"value": "second"}, {"value": "unused"},
    ], required_success_count=2))
    pipeline, _tools, calls = runtime()

    result = pipeline.execute(workflow, "/loop_assignments")

    assert result["ok"] is True
    assert calls[-1] == ("publish_report", {"first": "first"})
    assert len(calls) == 4
    assert result["data"]["results"][0]["items_succeeded"] == 2
    assert len(result["data"]["variables"]["attempts"]) == 3
    assert len(result["data"]["variables"]["usable"]) == 2


@pytest.mark.parametrize("has_valid_candidate", [True, False])
def test_only_validated_results_can_trigger_success_assignments(runtime, has_valid_candidate):
    items = [{"value": "rejected", "content": "short"}]
    if has_valid_candidate:
        items.append({"value": "accepted", "content": "Long enough to pass validation"})
    workflow = recipe(loop(
        items, required=False, validation={"type": "heuristic", "min_length": 10},
    ), variables={"ready": False})
    pipeline, _tools, calls = runtime()

    result = pipeline.execute(workflow, "/loop_assignments")

    assert result["ok"] is True
    variables = result["data"]["variables"]
    assert variables["ready"] is has_valid_candidate
    assert variables["attempts"][0]["validation_failed"] is True
    if has_valid_candidate:
        assert calls[-1] == ("publish_report", {"first": "accepted"})
        assert len(variables["usable"]) == 1
    else:
        assert [name for name, _params in calls] == ["collect_item"]
        assert variables["usable"] == []


@pytest.mark.parametrize(("items", "policy"), [
    ([{"outcome": "failed"}], {"on_all_fail": "continue"}),
    ([{"value": "only"}], {"required_success_count": 2, "on_fail": "continue"}),
    ([{"value": "only"}, {"outcome": "failed"}], {"process_all": True, "required": False}),
    ([], {"on_all_fail": "continue"}),
])
def test_continued_unsuccessful_loop_preserves_defaults(runtime, items, policy):
    workflow = recipe(loop(items, **policy), variables={"ready": False, "first_value": "unsaved"})
    workflow["steps"][1].pop("condition")
    workflow["steps"][1]["params"]["ready"] = "${ready}"
    pipeline, _tools, calls = runtime()
    with patch.object(
        pipeline, "_apply_variable_assignments", wraps=pipeline._apply_variable_assignments
    ) as assignments:
        result = pipeline.execute(workflow, "/loop_assignments")

    assert result["ok"] is True
    assert calls[-1] == ("publish_report", {"first": "unsaved", "ready": False})
    assert result["data"]["variables"]["ready"] is False
    assert assignments.call_count == 0


def test_empty_process_all_succeeds_and_publishes_empty_aggregate_before_assignments(runtime):
    step = loop([], process_all=True)
    step["set_variables_on_success"] = {"ready": True, "first_value": "nothing to save", "saved": "${usable}"}
    pipeline, _tools, calls = runtime()
    result = pipeline.execute(recipe(step), "/loop_assignments")

    assert result["ok"] is True
    assert calls == [("publish_report", {"first": "nothing to save"})]
    assert result["data"]["variables"]["saved"] == []
    assert result["data"]["results"][0]["items_processed"] == 0


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_terminal_loop_never_applies_success_assignments_or_runs_downstream(runtime, outcome):
    pipeline, _tools, calls = runtime()
    workflow = recipe(loop(
        [{"value": "partial"}, {"outcome": outcome}], required_success_count=2,
    ))
    with patch.object(
        pipeline, "_apply_variable_assignments", wraps=pipeline._apply_variable_assignments
    ) as assignments:
        result = pipeline.execute(workflow, "/loop_assignments")

    assert [name for name, _params in calls] == ["collect_item", "collect_item"]
    assert assignments.call_count == 0
    if outcome == "cancelled":
        assert result["cancelled"] is True
        assert "ready" not in result["data"]["variables"]
    else:
        assert result["ok"] is False
        assert result["data"]["aborted_at_step"] == 7


@pytest.mark.parametrize("skip", ["condition", "unavailable"])
def test_skipped_loop_applies_only_skip_assignments(runtime, skip):
    step = loop([{"value": "must not run"}])
    step["set_variables_on_skip"] = {"ready": False, "first_value": "skipped"}
    if skip == "condition":
        step["condition"] = {"op": "eq", "left": "one", "right": "two"}
    else:
        step["required"] = False
    workflow = recipe(step)
    workflow["steps"][1].pop("condition")
    pipeline, tools, calls = runtime()
    if skip == "unavailable":
        tools.registry = SimpleNamespace(list_tools=lambda: ["publish_report"])

    with patch.object(
        pipeline, "_apply_variable_assignments", wraps=pipeline._apply_variable_assignments
    ) as assignments:
        result = pipeline.execute(workflow, "/loop_assignments")

    assert result["ok"] is True
    assert calls == [("publish_report", {"first": "skipped"})]
    assert result["data"]["variables"]["ready"] is False
    assert assignments.call_count == 1
    assert assignments.call_args.args[0] == step["set_variables_on_skip"]


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_single_step_success_assignments_keep_existing_behavior(runtime, outcome):
    step = {
        "step": 7, "tool": "collect_item", "params": {"outcome": outcome, "value": "single"},
        "output_var": "receipt", "required": False, "on_fail": "continue",
        "set_variables_on_success": {"ready": True, "first_value": "${receipt.value}"},
    }
    pipeline, _tools, calls = runtime()
    result = pipeline.execute(recipe(step, variables={"ready": False}), "/loop_assignments")

    assert result["ok"] is True
    if outcome == "succeeded":
        assert calls[-1] == ("publish_report", {"first": "single"})
        assert result["data"]["variables"]["ready"] is True
    else:
        assert len(calls) == 1
        assert result["data"]["variables"]["ready"] is False
