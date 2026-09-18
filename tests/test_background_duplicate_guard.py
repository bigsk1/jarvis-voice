"""Real routing/admission with inert tools and disposable task storage."""

import sys
from types import SimpleNamespace

import pytest
import test_orchestrator_tool_turn_budget as orchestrator_fixture
from test_background_tasks import store as store

from lib.background_tasks.admission import BackgroundAdmissionService


@pytest.fixture
def routing(store, monkeypatch):
    import executor
    from tool_schema import ToolSchema

    names = ("convert_file", "generate_image", "generate_video", "generate_music")
    store.configure(background_tools=list(names))
    schemas = {
        name: ToolSchema(name, "Inert test tool", {"type": "object"}, "never-run.py",
                         execution={"background": {"supported": True, "adapter": "local_fixture"}})
        for name in names
    }
    registry = SimpleNamespace(list_tools=lambda: list(schemas), get_tool=schemas.get)
    store.touch_worker("worker", {"local_fixture"})
    service = BackgroundAdmissionService(
        store, adapters=dict.fromkeys(names, "local_fixture"),
        ready=lambda: True, validate_source=lambda payload: True,
    )
    orchestrator = orchestrator_fixture.ToolTurnBudgetTests()._build_orchestrator(fail_on_calls=set())
    orchestrator.registry = registry
    orchestrator.executor = executor.ToolExecutor.__new__(executor.ToolExecutor)
    orchestrator.executor.registry = registry
    orchestrator.executor.excluded_tools = set()
    monkeypatch.setattr(orchestrator.executor, "_execute_foreground",
                        lambda *a, **kw: pytest.fail("Background tools must only be admitted"))
    orchestrator._format_multi_turn_summary = lambda transcript, tools, data, text: text
    orchestrator._format_auto_mode = lambda transcript, tools, data, text, turn: text
    dispatches = []
    admit = service.admit

    def counted_admit(*args, **kwargs):
        dispatches.append(args[3])
        return admit(*args, **kwargs)

    monkeypatch.setattr(service, "admit", counted_admit)

    def run(calls, request_id="request", **options):
        orchestrator.background_context = service.authorize({
            "source": "web", "selected": list(names), "tool_policy": "auto",
            "conversation_id": "chat", "generation": 0, "request_id": request_id,
            "mode": "cloud", **options,
        }, registry)
        decisions = iter([
            {"intent": "tool", "tool_name": name, "arguments": args,
             "tool_call_id": f"call-{index}"}
            for index, (name, args) in enumerate(calls)
        ] + [{"intent": "qa", "text_response": "Accepted work is still pending."}])

        def route(*args, **kwargs):
            return next(decisions)

        orchestrator.router.route = route
        return orchestrator.process("Run the requested background tasks")

    return SimpleNamespace(run=run, store=store, orchestrator=orchestrator,
                           dispatches=dispatches)


def test_accepted_exact_duplicate_is_blocked_before_admission(routing, monkeypatch):
    recorded = []
    monkeypatch.setitem(sys.modules, "intelligence_hooks", SimpleNamespace(
        record_interaction=lambda **kwargs: recorded.append(kwargs) or 99,
        track_insight_outcomes=lambda *a, **kw: None,
    ))
    routing.orchestrator.learning_enabled = True
    first = {"source": "input.wav", "target_format": "flac"}
    reordered = {"target_format": "flac", "source": "input.wav"}
    result = routing.run([("convert_file", first), ("convert_file", reordered)],
                         allow_repeated_background=True)  # An old client cannot override the guard.
    assert len(routing.dispatches) == 1
    assert len(routing.store.conversation_jobs()) == 1
    assert len(result["pending_jobs"]) == 1
    assert result["tools_used"] == []
    assert result["tool_trace"][0]["ok"] is None
    assert result["tool_trace"][0]["result_kind"] == "background_admission"
    assert "experience_id" not in result
    assert recorded == []


def test_exhausted_duplicate_recovery_returns_the_existing_pending_receipt(routing):
    args = {"source": "input.wav", "target_format": "flac"}
    result = routing.run([("convert_file", args)] * 5)
    assert result["duplicate_prevented"] is True
    assert len(routing.dispatches) == 1
    assert len(result["pending_jobs"]) == 1
    assert result["tools_used"] == []
    assert "queued" in result["speech"]


def test_changed_conversion_arguments_and_new_message_can_admit(routing):
    first = {"source": "input.wav", "target_format": "flac"}
    result = routing.run([
        ("convert_file", first),
        ("convert_file", {**first, "target_format": "ogg"}),
        ("convert_file", {**first, "source": "second.wav"}),
    ])
    assert len(result["pending_jobs"]) == 3
    assert result["tools_used"] == []
    next_result = routing.run([("convert_file", first)], request_id="next-message")
    assert len(next_result["pending_jobs"]) == 1
    assert len(routing.store.conversation_jobs()) == 4


@pytest.mark.parametrize("tool", ["generate_image", "generate_video", "generate_music"])
def test_single_attempt_cap_still_blocks_changed_background_arguments(routing, tool):
    result = routing.run([(tool, {"prompt": "first"}), (tool, {"prompt": "second"})],
                         allow_repeated_background=True)
    assert len(routing.dispatches) == 1
    assert len(result["pending_jobs"]) == 1
    assert result["tools_used"] == []


def test_accepted_duplicate_stays_blocked_after_other_tool_failure_retry(routing, monkeypatch):
    execute = routing.orchestrator.executor.execute

    def fail_other_tool(tool, *args, **kwargs):
        if tool == "get_time":
            return {"ok": False, "error": "Temporary clock failure"}
        return execute(tool, *args, **kwargs)

    monkeypatch.setattr(routing.orchestrator.executor, "execute", fail_other_tool)
    args = {"source": "input.wav", "target_format": "flac"}
    result = routing.run([("convert_file", args), ("get_time", {}), ("convert_file", args)],
                         allow_repeated_background=True)
    assert len(routing.dispatches) == 1
    assert len(result["pending_jobs"]) == 1
    assert result["tools_used"] == []


def test_denied_admission_does_not_prevent_retry(routing, monkeypatch):
    execute = routing.orchestrator.executor.execute
    attempts = []

    def deny_once(*args, **kwargs):
        attempts.append(args)
        if len(attempts) == 1:
            return {"ok": False, "error": "Worker temporarily unavailable"}
        return execute(*args, **kwargs)

    monkeypatch.setattr(routing.orchestrator.executor, "execute", deny_once)
    args = {"source": "input.wav", "target_format": "flac"}
    result = routing.run([("convert_file", args), ("convert_file", args)])
    assert len(attempts) == 2
    assert len(result["pending_jobs"]) == 1
    assert result["tools_used"] == []
