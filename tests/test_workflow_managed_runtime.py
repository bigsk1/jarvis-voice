"""Managed workflows retain policy and approve the exact prepared invocation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import workflow_policy
from config_loader import config_scope
from tool_logger import ToolLogger, workflow_execution_scope

from orchestrator.pipeline_executor import PipelineExecutor


class Registry:
    def __init__(self, confirmations=()):
        self.schemas = {
            name: SimpleNamespace(
                requires_confirmation=lambda name=name: name in confirmations,
                permissions={"auto_approve": name not in confirmations},
                background_required=False,
            ) for name in ("get_time", "send_email", "stash", "canvas")
        }

    def list_tools(self):
        return list(self.schemas)

    def get_tool(self, name):
        return self.schemas.get(name)


class Executor:
    def __init__(self, confirmations=()):
        self.registry = Registry(confirmations)
        self.excluded_tools = set()
        self.cancel_check = None
        self.calls = []

    def execute(self, name, params):
        self.calls.append((name, params))
        return {"ok": True, "data": {"value": params.get("text", "done")}}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_policy, "WEB_CONFIG_PATH", tmp_path / "web_config.json")
    with config_scope("cloud", overrides={"BLOCKED_TOOLS": "", "WORKFLOW_BUILDER_ALLOWED_ENV_KEYS": ""}):
        executor = Executor()
        pipeline = PipelineExecutor("cloud", executor, provider=SimpleNamespace())
        pipeline.logger = ToolLogger(str(tmp_path / "logs" / "tools"))
        yield pipeline, executor


def recipe(steps=None, **fields):
    return {"id": "managed_test", "builder_policy_version": 1,
            "triggers": {"explicit": ["/managed_test"]},
            "steps": steps or [{"step": 1, "tool": "get_time", "params": {}}], **fields}


@pytest.mark.parametrize("condition", [None, False, {"op": "eq", "left": "one", "right": "two"}])
def test_managed_unattended_rejects_confirmation_before_any_prior_effect(runtime, condition):
    pipeline, executor = runtime
    executor.registry = Registry({"send_email"})
    result = pipeline.execute(recipe([
        {"step": 1, "tool": "get_time", "params": {}},
        {"step": 2, "tool": "send_email", "params": {"to": "user@example.test"}, "required": False, "condition": condition},
    ]), "/managed_test")
    assert result["error_code"] == "workflow_policy_rejected"
    assert executor.calls == []


def test_approval_uses_final_once_filled_args_and_ignores_callback_mutation(runtime, monkeypatch):
    pipeline, executor = runtime
    executor.registry = Registry({"send_email"})
    filled = []
    def fill(step, variables):
        filled.append(step)
        return {"subject": "Generated once", "body": "Prepared content"}
    monkeypatch.setattr(pipeline, "_llm_fill_params", fill)
    approvals = []
    def approve(payload):
        approvals.append(json.loads(json.dumps(payload)))
        payload["arguments"]["to"] = "mutated@example.test"
        return True
    result = pipeline.execute(recipe([{
        "step": 7, "tool": "send_email", "params": {"to": "${recipient}"},
        "llm_prompt": "Create a message", "llm_output_validation": {},
    }], variables={"recipient": "intended@example.test"}), "/managed_test",
        approval_callback=approve, execution_context={"surface": "builder", "run_id": "run_a"})
    assert result["ok"]
    assert len(filled) == len(approvals) == len(executor.calls) == 1
    assert executor.calls[0][1] == {"to": "intended@example.test", "subject": "Generated once", "body": "Prepared content"}
    assert approvals[0]["index"] == 0 and approvals[0]["step"] == 7
    assert len(approvals[0]["call_hash"]) == 64


def test_denied_optional_loop_is_terminal_and_keeps_prior_item_results(runtime):
    pipeline, executor = runtime
    executor.registry = Registry({"send_email"})
    approvals = []
    def approve(payload):
        approvals.append(payload)
        return len(approvals) == 1
    result = pipeline.execute(recipe([
        {"step": 1, "tool": "send_email", "for_each": "${items}", "params": {},
         "required": False, "on_fail": "continue", "on_all_fail": "continue", "process_all": True},
        {"step": 2, "tool": "get_time", "params": {}},
    ], variables={"items": {"from": "static", "value": [{"to": "first@example.test"}, {"to": "second@example.test"}]}}),
        "/managed_test", approval_callback=approve, execution_context={"surface": "builder", "run_id": "loop_run"})
    assert result["error_code"] == "approval_denied"
    assert len(executor.calls) == 1
    assert [call["item_index"] for call in approvals] == [0, 1]
    assert approvals[0]["call_hash"] != approvals[1]["call_hash"]
    assert len(result["data"]["results"][0]["outputs"]) == 1


def test_partial_count_uses_array_positions_including_skips_and_never_success_prompt(runtime, monkeypatch):
    pipeline, executor = runtime
    monkeypatch.setattr(pipeline, "_chat_with_usage", lambda *a, **k: pytest.fail("Whole-workflow success prompt ran"))
    events = []
    result = pipeline.execute(recipe([
        {"step": 15, "tool": "get_time", "condition": False, "params": {}},
        {"step": 2, "tool": "get_time", "params": {}},
        {"step": 8, "tool": "get_time", "params": {}},
    ], success_speech_llm_prompt="Say whole recipe done"), "/managed_test", stop_after=2,
        execution_context={"surface": "builder", "run_id": "partial"}, event_callback=events.append)
    assert result["partial"] is True
    assert len(executor.calls) == 1
    assert [step["step"] for step in result["data"]["results"]] == [15, 2]
    assert events[-1]["type"] == "run_finished"
    assert any(event["type"] == "step_skipped" for event in events)


def test_event_failure_never_replays_and_pipeline_scope_restores(runtime):
    pipeline, executor = runtime
    def broken(event):
        raise RuntimeError("Disconnected observer")
    assert pipeline.execute(recipe(), "/managed_test", event_callback=broken)["ok"]
    assert len(executor.calls) == 1
    assert pipeline._event_callback is None


def test_loop_cancel_between_items_stops_future_effects(runtime):
    pipeline, executor = runtime
    executor.cancel_check = lambda: bool(executor.calls)
    result = pipeline.execute(recipe([{
        "step": 1, "tool": "get_time", "params": {}, "for_each": "${items}", "process_all": True,
    }], variables={"items": {"from": "static", "value": [{"text": "first"}, {"text": "second"}]}}), "/managed_test")
    assert result["cancelled"]
    assert len(executor.calls) == 1


def test_fresh_saved_blocks_skip_optional_and_malformed_policy_fails_closed(runtime):
    pipeline, executor = runtime
    path = workflow_policy.WEB_CONFIG_PATH
    path.write_text(json.dumps({"tools": {"blocked": ["get_time"]}}))
    result = pipeline.execute(recipe([{"step": 1, "tool": "get_time", "params": {}, "required": False}]), "/managed_test")
    assert result["ok"] and result["data"]["degraded"]
    assert executor.calls == []
    path.write_text("{")
    result = pipeline.execute(recipe(), "/managed_test")
    assert result["error_code"] == "workflow_policy_rejected"
    assert executor.calls == []


def test_invalid_marker_and_secret_source_reject_before_tools(runtime):
    pipeline, executor = runtime
    result = pipeline.execute(recipe(builder_policy_version=True), "/managed_test", execution_context={"managed": False})
    assert not result["ok"]
    result = pipeline.execute(recipe(variables={"harmless": {"from": "env", "key": "OPENAI_API_KEY"}}), "/managed_test")
    assert not result["ok"] and executor.calls == []


def test_builder_log_context_is_bounded_and_does_not_leak_to_normal_calls(tmp_path):
    logger = ToolLogger(str(tmp_path / "tools"))
    payload = dict(workflow_id="test", workflow_name="Test", user_query="", result={"ok": True}, duration_ms=1, steps_completed=1, tools_used=[])
    with workflow_execution_scope({"surface": "builder", "run_id": "run_1", "recipe_hash": "a" * 64, "secret": "hidden"}):
        logger.log_workflow_execution(**payload)
    logger.log_workflow_execution(**payload)
    rows = [json.loads(line) for line in next(tmp_path.glob("workflows-*.jsonl")).read_text().splitlines()]
    assert rows[0]["origin"] == "builder" and rows[0]["run_id"] == "run_1"
    assert "secret" not in rows[0] and "origin" not in rows[1]


def test_not_autoapproved_tool_without_effect_flags_still_requires_builder_approval(runtime):
    pipeline, executor = runtime
    schema = executor.registry.schemas["get_time"]
    schema.permissions = {"auto_approve": False}
    assert schema.requires_confirmation() is False
    result = pipeline.execute(recipe(), "/managed_test")
    assert result["error_code"] == "workflow_policy_rejected" and executor.calls == []
    result = pipeline.execute(recipe(), "/managed_test", approval_callback=lambda payload: True,
                              execution_context={"surface": "builder"})
    assert result["ok"] and len(executor.calls) == 1


def test_builder_history_is_opt_in_for_existing_history_readers(tmp_path, monkeypatch):
    from datetime import datetime

    from api.routes import workflows

    monkeypatch.setattr(workflows, "__file__", str(tmp_path / "api" / "routes" / "workflows.py"))
    folder = tmp_path / "logs"
    folder.mkdir()
    rows = [{"timestamp": "same", "workflow_id": "regular"},
            {"timestamp": "same", "workflow_id": "managed", "origin": "builder", "run_id": "run_1"}]
    (folder / f"workflows-{datetime.now():%Y-%m-%d}.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    assert [row["workflow_id"] for row in workflows.get_workflow_logs()] == ["regular"]
    assert len(workflows.get_workflow_logs(include_builder=True)) == 2


def test_unicode_recipe_hash_matches_server_canonical_json(runtime):
    import hashlib

    pipeline, executor = runtime
    executor.registry = Registry({"send_email"})
    value = recipe([{"step": 1, "tool": "send_email", "params": {"subject": "Café 日本語"}}])
    approvals = []
    def approve(payload):
        approvals.append(payload)
        return True
    result = pipeline.execute(value, "/managed_test", approval_callback=approve,
                              execution_context={"surface": "builder", "run_id": "unicode_run"})
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert result["ok"]
    assert approvals[0]["recipe_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_stop_after_full_array_is_complete_and_allows_completion_speech(runtime, monkeypatch):
    pipeline, executor = runtime
    prompts = []
    def complete(message, **kwargs):
        prompts.append(message)
        return "The whole recipe completed."
    monkeypatch.setattr(pipeline, "_chat_with_usage", complete)
    result = pipeline.execute(recipe(success_speech_llm_prompt="Describe the completed recipe"),
                              "/managed_test", stop_after=1)
    assert result["ok"] and not result.get("partial")
    assert result["speech"] == "The whole recipe completed."
    assert len(prompts) == len(executor.calls) == 1


@pytest.mark.parametrize("tail_tool,blocked", [("unavailable_tool", False), ("send_email", True)])
def test_partial_availability_checks_only_selected_prefix_without_changing_snapshot(runtime, tail_tool, blocked):
    import hashlib

    pipeline, executor = runtime
    if blocked:
        workflow_policy.WEB_CONFIG_PATH.write_text(json.dumps({"tools": {"blocked": [tail_tool]}}))
    value = recipe([
        {"step": 12, "tool": "get_time", "params": {}},
        {"step": 2, "tool": tail_tool, "params": {}},
    ])
    events = []
    result = pipeline.execute(value, "/managed_test", stop_after=1,
                              execution_context={"surface": "builder"}, event_callback=events.append)
    assert result["ok"] and result["partial"]
    assert [name for name, _ in executor.calls] == ["get_time"]
    assert [step["step"] for step in result["data"]["results"]] == [12]
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert events[0]["recipe_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    executor.calls.clear()
    full = pipeline.execute(value, "/managed_test", execution_context={"surface": "builder"})
    assert not full["ok"] and executor.calls == []


def test_partial_run_keeps_full_document_policy_validation(runtime):
    pipeline, executor = runtime
    value = recipe([
        {"step": 1, "tool": "get_time", "params": {}},
        {"step": 2, "tool": "opencode", "params": {}},
    ])
    result = pipeline.execute(value, "/managed_test", stop_after=1,
                              execution_context={"surface": "builder"})
    assert result["error_code"] == "workflow_policy_rejected"
    assert executor.calls == []


def grant_for(value, tools):
    from copy import deepcopy

    from workflow_policy import workflow_approval_hash

    trusted = deepcopy(value)
    trusted['builder_unattended_approval'] = {'version': 1, 'recipe_hash': workflow_approval_hash(value), 'tools': tools}
    return trusted


def test_exact_recipe_grant_allows_unattended_dynamic_arguments_without_call_prompts(runtime):
    pipeline, executor = runtime
    executor.registry = Registry({'send_email'})
    value = grant_for(recipe([{'step': 1, 'tool': 'send_email', 'params': {'to': '${topic}'}}]), ['send_email'])
    for recipient in ('first@example.test', 'second@example.test'):
        result = pipeline.execute(value, f'/managed_test {recipient}')
        assert result['ok']
    assert [arguments['to'] for _, arguments in executor.calls] == ['first@example.test', 'second@example.test']
    result = pipeline.execute(value, '/managed_test builder@example.test',
                              execution_context={'surface': 'builder'},
                              approval_callback=lambda payload: pytest.fail('Recipe-approved call prompted again'))
    assert result['ok']


def test_grants_cover_only_listed_tools_and_never_bypass_saved_blocks(runtime):
    pipeline, executor = runtime
    executor.registry = Registry({'send_email', 'stash'})
    value = grant_for(recipe([
        {'step': 1, 'tool': 'get_time', 'params': {}},
        {'step': 2, 'tool': 'send_email', 'params': {}},
        {'step': 3, 'tool': 'stash', 'params': {}},
    ]), ['send_email'])
    assert pipeline.execute(value, '/managed_test')['error_code'] == 'workflow_policy_rejected'
    assert executor.calls == []
    value = grant_for(recipe([{'step': 1, 'tool': 'send_email', 'params': {}}]), ['send_email'])
    workflow_policy.WEB_CONFIG_PATH.write_text(json.dumps({'tools': {'blocked': ['send_email']}}))
    assert not pipeline.execute(value, '/managed_test')['ok']
    assert executor.calls == []


@pytest.mark.parametrize('mutation', ['hash', 'version', 'duplicate', 'undeclared'])
def test_malformed_or_stale_recipe_approval_rejects_before_earlier_effects(runtime, mutation):
    pipeline, executor = runtime
    executor.registry = Registry({'send_email'})
    value = grant_for(recipe([
        {'step': 1, 'tool': 'get_time', 'params': {}},
        {'step': 2, 'tool': 'send_email', 'params': {}},
    ]), ['send_email'])
    if mutation == 'hash':
        value['steps'][1]['params']['to'] = 'changed@example.test'
    elif mutation == 'version':
        value['builder_unattended_approval']['version'] = True
    elif mutation == 'duplicate':
        value['builder_unattended_approval']['tools'] = ['send_email', 'send_email']
    else:
        value['builder_unattended_approval']['tools'] = ['undeclared_tool']
    result = pipeline.execute(value, '/managed_test')
    assert result['error_code'] == 'workflow_policy_rejected' and executor.calls == []
