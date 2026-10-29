"""Optional observations preserve execution outcomes and workflow boundaries."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from config_loader import config_scope

from lib import prompt_guard_observer as observer
from lib.prompt_guard import PromptGuardResult
from orchestrator.executor import ToolExecutor
from orchestrator.pipeline_executor import PipelineExecutor


def executor_for(result):
    executor = object.__new__(ToolExecutor)
    executor.mode = "cloud"
    executor.excluded_tools = set()
    executor.registry = SimpleNamespace()
    calls = []

    def foreground(name, args, permission, *, log_callback=None):
        calls.append((name, args, permission))
        return result

    executor._execute_foreground = foreground
    return executor, calls


@pytest.mark.parametrize("observation", [
    PromptGuardResult("scanned", flagged=False, injection_score=.01),
    PromptGuardResult("unknown", "timeout"),
    PromptGuardResult("skipped", "busy"),
])
@pytest.mark.parametrize("ok", [True, False])
def test_observation_preserves_exact_result_and_never_replays(monkeypatch, observation, ok):
    result = {"ok": ok, "completion": "completed", "speech": "External result.",
              "data": {"content": "Article text.", "receipt": "existing-artifact"}}
    before = deepcopy(result)
    executor, calls = executor_for(result)
    observations = []

    def scan(text, **source):
        observations.append((text, source))
        return observation

    monkeypatch.setattr(observer, "scan_text", scan)
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true"}):
        returned = executor.execute("crawl_url", {"url": "https://example.invalid"})
    assert returned is result and result == before
    assert len(calls) == len(observations) == 1
    assert observations[0][1] == {"source_type": "tool_result", "source_name": "crawl_url"}


def test_observer_bug_cannot_invalidate_completed_tool(monkeypatch):
    result = {"ok": True, "data": {"content": "Saved evidence."}}
    executor, calls = executor_for(result)

    def broken(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_ERROR")

    monkeypatch.setattr(observer, "scan_text", broken)
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true"}):
        assert executor.execute("rss_feed", {}) is result
    assert len(calls) == 1


def test_existing_request_restrictions_run_before_observation(monkeypatch):
    executor, calls = executor_for({"ok": True})
    executor.excluded_tools = {"crawl_url"}

    def unexpected(*_args, **_kwargs):
        pytest.fail("Blocked tools must not reach the optional scanner")

    monkeypatch.setattr(observer, "scan_text", unexpected)
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true"}):
        assert executor.execute("crawl_url", {})["ok"] is False
    assert calls == []


def test_workflow_component_is_observed_once_without_scanning_wrapper(monkeypatch):
    result = {"ok": True, "speech": "Feed loaded.", "data": {"items": ["A news item."]}}
    executor, _ = executor_for(result)
    pipeline = object.__new__(PipelineExecutor)
    pipeline.executor = executor
    observations = []
    executions = []

    def foreground(name, args, _permission, *, log_callback=None):
        executions.append(name)
        if name == "workflow":
            child = pipeline._execute_workflow_tool({"params": {}}, "rss_feed", args)
            return {"ok": True, "data": {"outputs": child}}
        return result

    executor._execute_foreground = foreground
    monkeypatch.setattr(observer, "scan_text", lambda text, **source: observations.append(source))
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true"}):
        returned = executor.execute("workflow", {"profile": "daily"})
    assert returned["data"]["outputs"] is result
    assert executions == ["workflow", "rss_feed"]
    assert observations == [{"source_type": "tool_result", "source_name": "rss_feed"}]
