"""Empty research outcomes keep their failed provenance without restarting the loop."""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from config_loader import config_scope  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402

EMPTY_EVENTS_ERROR = (
    "SerpApi Google Events error: SerpApi error: "
    "Google hasn't returned any results for this query."
)


def _tool_route(name="serpapi_google_events", query="local events"):
    return {
        "intent": "tool",
        "tool_name": name,
        "arguments": {"query": query},
        "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _qa_route():
    return {
        "intent": "qa",
        "text_response": "Here are the results supported by the successful searches.",
        "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _empty_result():
    return {
        "ok": False,
        "error": EMPTY_EVENTS_ERROR,
        "speech": EMPTY_EVENTS_ERROR,
        "data": {},
    }


def _success_result(label):
    return {"ok": True, "speech": label, "data": {"verified_result": label}}


def _build_orchestrator(routes, results):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.executor = SimpleNamespace(
        execute=Mock(side_effect=deepcopy(results)),
        set_excluded_tools=Mock(),
        set_allowed_tools=Mock(),
    )
    orchestrator.router = SimpleNamespace(
        provider_type="test",
        model_name="fake-model",
        system_prompt_version="test",
        provider=None,
        route=Mock(side_effect=deepcopy(routes)),
    )
    orchestrator.status_updater = SimpleNamespace(
        reset=Mock(),
        set_turn=Mock(),
        update=Mock(),
        update_error=Mock(),
        mark_complete=Mock(),
    )
    orchestrator.max_retries = 1
    orchestrator.timezone = ZoneInfo("UTC")
    orchestrator.auto_context_enabled = False
    orchestrator._last_experience_id = None
    orchestrator.session_id = "empty-results-test"
    orchestrator.web_conversation_id = "empty-results-conversation"
    orchestrator.progress_callback = None
    orchestrator.cancel_check = None
    orchestrator.learning_enabled = False
    orchestrator._try_workflow = Mock(return_value=None)
    orchestrator._get_relevant_memories_bundle = Mock(return_value={"context": "", "meta": {}})
    orchestrator._get_learning_insights = Mock(return_value=("", []))
    orchestrator._format_max_turns_summary = Mock(return_value="Reached the turn budget.")
    orchestrator._log_conversation = Mock()
    orchestrator._maybe_collect_feedback = lambda result, _transcript: result
    orchestrator._record_learning_experience = Mock(return_value=-1)
    orchestrator.process = Mock(wraps=orchestrator.process)
    progress = []
    orchestrator.set_progress_callback(lambda event, **fields: progress.append((event, fields)))
    contexts = []
    build_turn_context = orchestrator._build_turn_context

    def capture_context(query, context):
        contexts.append(deepcopy(context))
        return build_turn_context(query, context)

    orchestrator._build_turn_context = capture_context
    return orchestrator, progress, contexts


def _run(orchestrator, max_turns, *, response_style="detailed"):
    with config_scope("cloud", overrides={"JARVIS_RESPONSE_STYLE": response_style}):
        with patch(
            "orchestrator_v2.get_int",
            side_effect=lambda key, default=0: max_turns if key == "MAX_TOOL_TURNS" else default,
        ):
            return orchestrator.process("Find local events and compare available sources.")


def test_two_empty_searches_continue_without_recursion_and_keep_earlier_success():
    routes = [
        _tool_route("serpapi_maps_search", "nearby venues"),
        _tool_route(query="narrow event query"),
        _tool_route(query="broader event query"),
        _tool_route("tavily_search", "local event calendars"),
        _qa_route(),
    ]
    successes = [_success_result("Venue found"), _success_result("Calendar found")]
    orchestrator, progress, contexts = _build_orchestrator(
        routes, [successes[0], _empty_result(), _empty_result(), successes[1]],
    )

    result = _run(orchestrator, 5)

    assert result["ok"] is True
    assert orchestrator.process.call_count == 1
    assert orchestrator.router.route.call_count == 5
    assert orchestrator.executor.execute.call_count == 4
    assert result["tools_used"] == ["serpapi_maps_search", "tavily_search"]
    assert result["data"] == {
        "serpapi_maps_search": successes[0]["data"],
        "tavily_search": successes[1]["data"],
    }
    assert [entry["tool"] for entry in result["tool_trace"]] == [
        route["tool_name"] for route in routes[:-1]
    ]
    assert [entry["ok"] for entry in result["tool_trace"]] == [True, False, False, True]
    assert all(entry["error"] == EMPTY_EVENTS_ERROR for entry in result["tool_trace"][1:3])
    completed = [fields for event, fields in progress if event == "tool_complete"]
    assert [(entry["tool"], entry["call_index"], entry["success"]) for entry in completed] == [
        ("serpapi_maps_search", 0, True),
        ("serpapi_google_events", 0, False),
        ("serpapi_google_events", 1, False),
        ("tavily_search", 0, True),
    ]
    orchestrator.status_updater.update_error.assert_not_called()
    assert not any("retry" in fields.get("message", "").lower() for _, fields in progress)
    failed_contexts = [item for item in contexts[-1] if not item["result"]["ok"]]
    assert len(failed_contexts) == 2
    assert all(item["meta"]["freshness"] == "failed_tool_call" for item in failed_contexts)
    assert all(item["meta"]["authoritative_live"] is False for item in failed_contexts)
    learning_call = orchestrator._record_learning_experience.call_args
    assert learning_call.args[1] == result["tools_used"]
    assert [item["result"]["ok"] for item in learning_call.args[3]] == [True, False, False, True]
    assert result["usage"]["model_calls"] == 5
    assert result["usage"]["total_tokens"] == 10
    final_input = orchestrator.router.route.call_args.args[0].lower()
    assert "google hasn't returned any results" in final_input
    assert any(hint in final_input for hint in ("broaden", "different source", "alternate"))


@pytest.mark.parametrize("max_turns", [1, 2, 3])
def test_empty_searches_consume_the_existing_turn_budget(max_turns):
    orchestrator, progress, _contexts = _build_orchestrator(
        [_tool_route(query=f"event query {index}") for index in range(max_turns)],
        [_empty_result() for _index in range(max_turns)],
    )

    result = _run(orchestrator, max_turns)

    assert result["max_turns_reached"] is True
    assert result["ok"] is False
    assert result["error"] == result["speech"]
    assert result["error_code"] == "empty_results"
    assert orchestrator._log_conversation.call_args.kwargs["success"] is False
    assert orchestrator.process.call_count == 1
    assert orchestrator.router.route.call_count == max_turns
    assert orchestrator.executor.execute.call_count == max_turns
    assert result["tools_used"] == []
    assert result["data"] == {}
    assert [entry["ok"] for entry in result["tool_trace"]] == [False] * max_turns
    assert result["usage"]["model_calls"] == max_turns
    assert len([event for event, _fields in progress if event == "tool_complete"]) == max_turns
    assert "no matches" in result["speech"]
    assert "couldn't complete the research" in result["speech"]
    orchestrator._format_max_turns_summary.assert_not_called()


@pytest.mark.parametrize(
    "error,data",
    [
        ("SerpApi Google Events error: Invalid API key.", {}),
        ("SerpApi Google Events error: HTTP 429 rate limit exceeded.", {}),
        ("Missing required query argument.", {}),
        (EMPTY_EVENTS_ERROR, {"failure_reason": "active_provider_incident"}),
        (EMPTY_EVENTS_ERROR, {"results": [], "results_count": 0}),
        (f"HTTP 401 Unauthorized: {EMPTY_EVENTS_ERROR}", {}),
        (f"HTTP 429: {EMPTY_EVENTS_ERROR}", {}),
        (f"Schema error: {EMPTY_EVENTS_ERROR}", {}),
    ],
)
def test_hard_failures_still_use_the_guarded_retry_path(error, data):
    failure = {"ok": False, "error": error, "speech": error, "data": data}
    orchestrator, progress, _contexts = _build_orchestrator(
        [_tool_route(), _tool_route("tavily_search", "event calendar"), _qa_route()],
        [failure, _success_result("Calendar found")],
    )

    result = _run(orchestrator, 3)

    assert result["ok"] is True
    assert orchestrator.process.call_count == 2
    assert orchestrator.router.route.call_count == 3
    assert orchestrator.executor.execute.call_count == 2
    assert [entry["ok"] for entry in result["tool_trace"]] == [False, True]
    assert result["tools_used"] == ["tavily_search"]
    assert any("retry 1/1" in fields.get("message", "") for _, fields in progress)
    orchestrator.status_updater.update_error.assert_called_once()


def test_unreviewed_tool_cannot_claim_a_soft_miss_with_the_same_error_text():
    orchestrator, _progress, _contexts = _build_orchestrator(
        [_tool_route("custom_lookup"), _qa_route()], [_empty_result()],
    )

    result = _run(orchestrator, 2)

    assert result["ok"] is True
    assert orchestrator.process.call_count == 2
    assert result["tools_used"] == []
    assert result["tool_trace"][0]["ok"] is False


def test_single_call_tool_failure_remains_terminal_even_with_empty_search_text():
    orchestrator, _progress, _contexts = _build_orchestrator(
        [_tool_route("generate_image")], [_empty_result()],
    )

    result = _run(orchestrator, 4)

    assert result["ok"] is False
    assert result["terminal_failure"] is True
    assert orchestrator.process.call_count == 1
    assert orchestrator.router.route.call_count == 1
    assert orchestrator.executor.execute.call_count == 1
    assert result["tool_trace"][0]["ok"] is False


def test_empty_search_then_qa_has_no_successful_tool_grounding():
    orchestrator, _progress, contexts = _build_orchestrator(
        [_tool_route(), {**_qa_route(), "text_response": "No matching events were returned."}],
        [_empty_result()],
    )

    result = _run(orchestrator, 2)

    assert result["ok"] is True
    assert "error" not in result
    assert "error_code" not in result
    assert orchestrator._log_conversation.call_args.kwargs["success"] is True
    assert orchestrator.process.call_count == 1
    assert result["tools_used"] == []
    assert result["data"] == {}
    assert result["tool_trace"][0]["ok"] is False
    assert contexts[-1][0]["result"]["ok"] is False
    assert contexts[-1][0]["meta"]["authoritative_live"] is False


def test_soft_misses_can_recover_after_the_hard_failure_retry_is_already_spent():
    hard_failure = {"ok": False, "error": "HTTP 429 rate limit exceeded.", "data": {}}
    orchestrator, progress, _contexts = _build_orchestrator(
        [
            _tool_route("serpapi_maps_search", "local venues"),
            _tool_route(query="narrow event query"),
            _tool_route(query="broader event query"),
            _tool_route("tavily_search", "community calendars"),
            _qa_route(),
        ],
        [hard_failure, _empty_result(), _empty_result(), _success_result("Calendar found")],
    )

    result = _run(orchestrator, 5)

    assert result["ok"] is True
    assert orchestrator.process.call_count == 2
    assert orchestrator.router.route.call_count == 5
    assert orchestrator.executor.execute.call_count == 4
    assert result["tools_used"] == ["tavily_search"]
    assert [entry["ok"] for entry in result["tool_trace"]] == [False, False, False, True]
    assert result["usage"]["model_calls"] == 5
    assert len([
        fields for _event, fields in progress if "retry 1/1" in fields.get("message", "")
    ]) == 1
    orchestrator.status_updater.update_error.assert_called_once()


def test_identical_empty_lookup_is_not_executed_again_but_broader_query_can_run():
    orchestrator, _progress, contexts = _build_orchestrator(
        [
            _tool_route(query="narrow event query"),
            _tool_route(query="narrow event query"),
            _tool_route(query="broader event query"),
            _tool_route("tavily_search", "community calendars"),
            _qa_route(),
        ],
        [_empty_result(), _empty_result(), _success_result("Calendar found")],
    )

    result = _run(orchestrator, 5)

    assert result["ok"] is True
    assert orchestrator.process.call_count == 1
    assert orchestrator.router.route.call_count == 5
    assert orchestrator.executor.execute.call_count == 3
    executed_queries = [call.args[1]["query"] for call in orchestrator.executor.execute.call_args_list]
    assert executed_queries == ["narrow event query", "broader event query", "community calendars"]
    assert result["tools_used"] == ["tavily_search"]
    assert [entry["ok"] for entry in result["tool_trace"]] == [False, False, True]
    duplicate_context = next(item for item in contexts[-1] if item["tool"] == "duplicate_guard")
    assert duplicate_context["result"]["ok"] is False
    assert duplicate_context["meta"]["authoritative_live"] is False


@pytest.mark.parametrize("max_turns", [2, 4])
def test_empty_lookup_duplicate_exhaustion_keeps_failure_trace_without_synthesis(max_turns):
    orchestrator, _progress, _contexts = _build_orchestrator(
        [_tool_route(query="same event query") for _index in range(max_turns)],
        [_empty_result()],
    )
    orchestrator._synthesize_duplicate_prevented_response = Mock(return_value="No evidence supplied.")

    result = _run(orchestrator, max_turns)

    assert result["ok"] is False
    assert result["duplicate_prevented"] is True
    assert result["error"] == result["speech"]
    assert result["error_code"] == "empty_results"
    assert orchestrator._log_conversation.call_args.kwargs["success"] is False
    assert orchestrator.executor.execute.call_count == 1
    assert orchestrator.router.route.call_count == max_turns
    assert orchestrator.process.call_count == 1
    assert result["tools_used"] == []
    assert result["data"] == {}
    assert len(result["tool_trace"]) == 1
    assert result["tool_trace"][0]["ok"] is False
    assert result["tool_trace"][0]["error"] == EMPTY_EVENTS_ERROR
    assert "no matches" in result["speech"].lower()
    assert "couldn't complete" in result["speech"].lower()
    orchestrator._synthesize_duplicate_prevented_response.assert_not_called()


def test_empty_lookup_budget_exhaustion_with_duplicate_guard_still_avoids_empty_summary():
    orchestrator, _progress, _contexts = _build_orchestrator(
        [
            _tool_route(query="narrow event query"),
            _tool_route(query="narrow event query"),
            _tool_route(query="broader event query"),
        ],
        [_empty_result(), _empty_result()],
    )

    result = _run(orchestrator, 3, response_style="casual")

    assert result["max_turns_reached"] is True
    assert result["ok"] is False
    assert result["error"] == result["speech"]
    assert result["error_code"] == "empty_results"
    assert orchestrator._log_conversation.call_args.kwargs["success"] is False
    assert orchestrator.executor.execute.call_count == 2
    assert orchestrator.router.route.call_count == 3
    assert result["tools_used"] == []
    assert result["data"] == {}
    assert [entry["ok"] for entry in result["tool_trace"]] == [False, False]
    assert "no matches" in result["speech"].lower()
    assert "couldn't complete" in result["speech"].lower()
    orchestrator._format_max_turns_summary.assert_not_called()


def test_empty_miss_does_not_reclassify_partial_success_at_the_turn_limit():
    orchestrator, _progress, _contexts = _build_orchestrator(
        [_tool_route("tavily_search", "event calendars"), _tool_route()],
        [_success_result("Calendar found"), _empty_result()],
    )

    result = _run(orchestrator, 2, response_style="casual")

    assert result["max_turns_reached"] is True
    assert result["ok"] is True
    assert "error" not in result
    assert "error_code" not in result
    assert result["tools_used"] == ["tavily_search"]
    assert orchestrator._log_conversation.call_args.kwargs["success"] is True
    orchestrator._format_max_turns_summary.assert_called_once()
