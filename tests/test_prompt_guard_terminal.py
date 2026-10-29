"""Withheld tool content stops retries while retaining neutral incident facts."""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

import orchestrator_v2 as runtime

from lib.prompt_guard_observer import is_prompt_guard_rejection, prompt_guard_notice
from orchestrator.pipeline_executor import PipelineExecutor
from orchestrator.workflow_tool_runtime import execute_workflow_tool

INCIDENT = "pg-" + "a" * 32


def rejection(tool="crawl_url", completion="unknown"):
    result = {
        "ok": False,
        "error_code": "prompt_injection_detected",
        "terminal_failure": True,
        "retry_safe": False,
        "completion": completion,
        "error": "Returned content withheld by Prompt Guard.",
        "data": {
            "prompt_guard": {
                "content_withheld": True, "tool": tool,
                "incident_id": INCIDENT, "evidence_saved": True,
                "score": .99, "threshold": .8,
            },
            "operation": {"tool_executed": True, "original_ok": True},
        },
    }
    result["speech"] = prompt_guard_notice(result)
    return result


class Status:
    def __init__(self):
        self.retry_errors = []

    def reset(self):
        pass

    def set_turn(self, _turn):
        pass

    def update(self, **_kwargs):
        pass

    def update_error(self, **kwargs):
        self.retry_errors.append(kwargs)

    def mark_complete(self):
        pass


def orchestrator_with(result, tool="crawl_url"):
    calls = []
    routes = []

    def execute(name, arguments):
        calls.append((name, arguments))
        return result

    def route(*args, **_kwargs):
        routes.append(args)
        if len(routes) > 1:
            pytest.fail("A terminal content rejection must not reach another model turn")
        return {"intent": "tool", "tool_name": tool, "arguments": {"url": "https://example.org/article"}}

    instance = object.__new__(runtime.Orchestrator)
    instance.executor = SimpleNamespace(
        execute=execute, set_excluded_tools=lambda _tools: None,
        set_allowed_tools=lambda _tools: None,
    )
    instance.router = SimpleNamespace(
        route=route, provider_type="test", model_name="test-model",
        system_prompt_version="test", provider=None,
    )
    instance.status_updater = Status()
    instance.max_retries = 10
    instance.timezone = ZoneInfo("UTC")
    instance.auto_context_enabled = False
    instance._last_experience_id = None
    instance.session_id = "guard-test-session"
    instance.web_conversation_id = "guard-test-conversation"
    instance.progress_callback = None
    instance.cancel_check = None
    instance.learning_enabled = False
    instance._try_workflow = lambda _query: None
    instance._get_relevant_memories_bundle = lambda _query: {"context": "", "meta": {}}
    instance._get_learning_insights = lambda *_args: ("", [])
    instance._log_conversation = lambda *_args, **_kwargs: None
    instance._maybe_collect_feedback = lambda response, _query: response
    return instance, calls, routes


@pytest.mark.parametrize("tool", ["crawl_url", "generate_audio", "workflow"])
@pytest.mark.parametrize("completion", ["unknown", "completed", "rejected"])
def test_content_rejection_ends_tool_turn_without_retry_or_another_model_call(monkeypatch, tool, completion):
    original = rejection(tool, completion)
    before = deepcopy(original)
    instance, calls, routes = orchestrator_with(original, tool)
    monkeypatch.setattr(runtime, "get_int", lambda key, default=0: 20 if key == "MAX_TOOL_TURNS" else default)

    result = instance.process("Read this article")

    assert len(calls) == len(routes) == 1
    assert instance.status_updater.retry_errors == []
    assert is_prompt_guard_rejection(result)
    assert result["retry_safe"] is False and result["completion"] == completion
    assert result["speech"] == prompt_guard_notice(original)
    assert result["data"][tool]["prompt_guard"]["incident_id"] == INCIDENT
    assert result["data"][tool]["operation"] == original["data"]["operation"]
    assert result["tool_trace"][0]["error_code"] == "prompt_injection_detected"
    assert result["tool_trace"][0]["completion"] == completion
    assert original == before


def test_audio_failure_formatter_reports_content_rejection_before_artifact_failure():
    result = rejection("generate_audio", "completed")
    assert runtime._format_terminal_tool_failure(
        "generate_audio", result["error"], result=result,
    ) == prompt_guard_notice(result)


def pipeline_with(result):
    calls = []

    def execute(tool, arguments):
        calls.append((tool, arguments))
        return deepcopy(result) if tool != "canvas" else {"ok": True, "data": {}}

    pipeline = object.__new__(PipelineExecutor)
    pipeline.mode = "cloud"
    pipeline.executor = SimpleNamespace(execute=execute, excluded_tools=set(), registry=None)
    pipeline.provider = None
    pipeline.logger = SimpleNamespace(log_workflow_execution=lambda **_kwargs: None)
    pipeline.llm_logger = SimpleNamespace(log_server_side_tools=lambda **_kwargs: None)
    return pipeline, calls


def workflow(step):
    return {
        "id": "guard_digest", "name": "Guard digest",
        "triggers": {"explicit": ["/guard_digest"]},
        "variables": {"urls": {"from": "static", "value": ["https://example.org/one", "https://example.org/two"]}},
        "validation_policy": {"max_total_retries": 20},
        "abort_speech": "A generic recipe failure message.",
        "steps": [
            {"step": 1, "tool": "crawl_url", "output_var": "article", **step},
            {"step": 2, "tool": "canvas", "params": {"content": "${article}"}},
        ],
    }


@pytest.mark.parametrize("on_fail", [None, "continue"])
@pytest.mark.parametrize("looped", [False, True])
def test_required_workflow_stops_before_later_items_validation_or_transforms(monkeypatch, on_fail, looped):
    original = rejection()
    pipeline, calls = pipeline_with(original)
    step = {"required": True, "validation": {"min_content_length": 10}, "retry": {"max_attempts": 10}}
    if on_fail:
        step["on_fail"] = on_fail
    if looped:
        step.update(for_each="${urls}", process_all=True)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Rejected content must not reach validation or transforms")

    monkeypatch.setattr(pipeline, "_validate_result", unexpected)
    monkeypatch.setattr(pipeline, "_apply_output_transforms", unexpected)
    result = pipeline.execute(workflow(step), "/guard_digest articles")

    assert len(calls) == 1
    assert is_prompt_guard_rejection(result)
    assert result["speech"] == prompt_guard_notice(original)
    assert result["data"]["prompt_guard"]["incident_id"] == INCIDENT
    assert result["data"]["operation"] == original["data"]["operation"]
    failed = result["data"]["results"][-1]
    assert is_prompt_guard_rejection(failed)
    if looped:
        assert failed["items_processed"] == 1 and failed["items_succeeded"] == 0
        assert is_prompt_guard_rejection(failed["outputs"][0])


@pytest.mark.parametrize("looped", [False, True])
def test_optional_content_rejection_also_stops_workflow_before_later_actions(looped):
    pipeline, calls = pipeline_with(rejection())
    step = {"required": False, "on_fail": "continue"}
    if looped:
        step.update(for_each="${urls}", process_all=True)
    result = pipeline.execute(workflow(step), "/guard_digest articles")
    assert result["ok"] is False
    assert [tool for tool, _arguments in calls] == ["crawl_url"]
    assert is_prompt_guard_rejection(result)
    assert is_prompt_guard_rejection(result["data"]["results"][0])


@pytest.mark.parametrize("looped", [False, True])
def test_ordinary_optional_failure_keeps_existing_workflow_continuation(looped):
    pipeline, calls = pipeline_with({"ok": False, "error": "No article found.", "data": {}})
    step = {"required": False, "on_fail": "continue"}
    if looped:
        step.update(for_each="${urls}", process_all=True)
    result = pipeline.execute(workflow(step), "/guard_digest articles")
    assert result["ok"] is True
    assert [tool for tool, _arguments in calls] == ["crawl_url"] * (2 if looped else 1) + ["canvas"]
    assert not is_prompt_guard_rejection(result)


def test_failed_search_transform_cannot_revive_terminal_content_rejection():
    result = rejection("brave_llm_context")
    # A regression retaining URLs must still not turn this policy failure into
    # a successful search or feed any source data into workflow variables.
    result["data"]["results"] = [{"url": "https://example.org/untrusted"}]
    pipeline = object.__new__(PipelineExecutor)
    variables = {}
    pipeline._apply_output_transforms({}, result, variables, "brave_llm_context", "")
    assert result["ok"] is False
    assert variables == {}


def test_workflow_tool_wrapper_preserves_terminal_marker_and_incident():
    original = rejection()
    original["data"]["results"] = []
    recipe = workflow({})
    registry = SimpleNamespace(
        list_tools=lambda: ["workflow", "crawl_url", "canvas"],
        get_tool=lambda name: SimpleNamespace(name=name),
    )
    loader = SimpleNamespace(get_workflow=lambda _identifier: recipe)
    result = execute_workflow_tool(
        registry=registry, args={"action": "run", "workflow_id": "guard_digest", "query": "articles"},
        mode="cloud", loader=loader,
        pipeline_executor=SimpleNamespace(execute=lambda *_args, **_kwargs: original),
    )
    assert is_prompt_guard_rejection(result)
    assert result["retry_safe"] is False
    assert result["completion"] == original["completion"]
    assert result["data"]["prompt_guard"] == original["data"]["prompt_guard"]
    assert result["data"]["workflow_started"] is True


def test_slash_workflow_preserves_terminal_marker_and_incident():
    original = rejection()
    recipe = workflow({})
    instance = object.__new__(runtime.Orchestrator)
    instance.workflow_loader = SimpleNamespace(match=lambda _query: recipe)
    instance.registry = SimpleNamespace(
        list_tools=lambda: ["workflow", "crawl_url", "canvas"],
        get_tool=lambda name: SimpleNamespace(name=name),
    )
    instance.executor = SimpleNamespace(excluded_tools=set())
    instance.pipeline_executor = SimpleNamespace(execute=lambda *_args, **_kwargs: original)
    instance.status_updater = Status()
    result = instance._try_workflow("/guard_digest articles")
    assert is_prompt_guard_rejection(result)
    assert result["retry_safe"] is False
    assert result["completion"] == original["completion"]
    assert result["data"]["prompt_guard"] == original["data"]["prompt_guard"]
