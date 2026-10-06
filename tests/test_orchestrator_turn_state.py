"""Request-state behavior across tool retries and native provider continuation."""

import copy
from types import SimpleNamespace

import pytest
import test_orchestrator_tool_turn_budget as budget_fixture
from router_v2 import ProviderRouteInput


@pytest.fixture(params=["openai", "xai"])
def continuing_request(request, monkeypatch):
    import orchestrator_v2

    provider = request.param
    orch = budget_fixture.ToolTurnBudgetTests()._build_orchestrator(fail_on_calls={2})
    orch.router.provider_type = provider
    orch.router.model_name = "test-model"
    orch._openai_responses_tracking_enabled = lambda: provider == "openai"
    orch._openai_native_continuation_allowed = lambda: provider == "openai"
    orch._xai_native_continuation_allowed = lambda: provider == "xai"
    # Use the real continuation validation/builders, with explicit test config.
    monkeypatch.setattr(orchestrator_v2, "get_config_value", lambda key, default=None: {
        "XAI_STORE_MESSAGES": "true",
        "JARVIS_RESPONSE_STYLE": "detailed",
    }.get(key, default))
    orch._config_bool = lambda key, default=False: False

    calls = []
    events = []
    orch.set_progress_callback(lambda event, **payload: events.append((event, payload)))

    def script(routes):
        decisions = iter(routes)

        def route(payload, **kwargs):
            calls.append((payload, kwargs))
            return next(decisions)

        orch.router.route = route

    def tool(index):
        return {
            "intent": "tool",
            "tool_name": "weather",
            "arguments": {"location": f"city-{index}"},
            "response_id": f"resp-{index}",
            "tool_call_id": f"call-{index}",
            "response_model": orch.router.model_name,
            "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "thinking": "first reasoning" if index == 1 else "later reasoning",
            "available_tools": [{"name": "weather"}],
            "web_search_hint_tools": ["web_search"],
        }

    def reject():
        return {
            "intent": "error", "error": "expired continuation",
            "provider_error_raw": "previous_response expired",
            f"{provider}_continuation_error": True,
        }

    def run(max_turns):
        return budget_fixture.ToolTurnBudgetTests()._run_with_max_turns(orch, max_turns)

    return SimpleNamespace(orch=orch, provider=provider, calls=calls, events=events,
                           script=script, tool=tool, reject=reject, run=run)


def _tool_output(payload):
    if payload.responses_continuation_input:
        item = payload.responses_continuation_input[0]
        return item["call_id"], item["output"]
    item = payload.messages[0]
    return item["tool_call_id"], item["content"]


def test_tool_retry_submits_failed_native_result_and_starts_next_request_fresh(continuing_request):
    case = continuing_request
    qa = {"intent": "qa", "text_response": "done",
          "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    case.script([case.tool(1), case.tool(2), qa])
    first = case.run(3)

    assert first["ok"] is True
    assert first["tools_used"] == ["weather"]
    assert first["data"] == {"weather": {"call": 1}}
    assert [item["ok"] for item in first["tool_trace"]] == [True, False]
    assert first["thinking"] == "first reasoning"
    assert first["available_tools"] == [{"name": "weather"}]
    assert first["web_search_hint_tools"] == ["web_search"]
    assert first["usage"]["model_calls"] == 3
    assert first["usage"]["total_tokens"] == 6
    assert [p["call_index"] for event, p in case.events if event == "tool_start"] == [0, 1]
    assert len(case.calls) == 3
    # The provider receives each executed call's actual result, including the
    # failed call; its error must be in the model payload, not just the RAG query.
    for index, (payload, kwargs) in enumerate(case.calls[1:], start=1):
        assert isinstance(payload, ProviderRouteInput)
        assert payload.previous_response_id == f"resp-{index}"
        assert kwargs["previous_response_id"] == f"resp-{index}"
        call_id, output = _tool_output(payload)
        assert call_id == f"call-{index}"
        assert f"city-{index}" in output
        assert f"Status: {'ok' if index == 1 else 'error'}" in output
    assert "Yelp hasn't returned any results" in _tool_output(case.calls[2][0])[1]

    saved_first = copy.deepcopy(first)
    case.calls.clear()
    case.events.clear()
    case.script([case.tool(1), qa])
    second = case.run(2)

    assert second["ok"] is True
    assert second["data"] == {"weather": {"call": 3}}
    assert second["usage"]["model_calls"] == 2
    assert second["usage"]["total_tokens"] == 4
    assert len(second["tool_trace"]) == 1
    assert second["tools_used"] == ["weather"]
    assert [p["call_index"] for event, p in case.events if event == "tool_start"] == [0]
    assert isinstance(case.calls[0][0], str)
    assert case.calls[0][1]["previous_response_id"] is None
    assert first == saved_first


def test_native_text_fallback_is_used_once_across_tool_failure_retry(continuing_request):
    case = continuing_request
    first_route = case.tool(1)
    first_route["usage_info"]["server_side_tools"] = {"SERVER_SIDE_TOOL_WEB_SEARCH": 2}
    case.script([first_route, case.reject(), case.tool(2), case.tool(3), case.reject()])
    result = case.run(4)

    assert result["ok"] is False
    assert result["error"] == "expired continuation"
    assert result["tools_used"] == ["weather", "weather"]
    assert result["data"] == {"weather": [{"call": 1}, {"call": 3}]}
    assert [item["ok"] for item in result["tool_trace"]] == [True, False, True]
    assert result["thinking"] == "first reasoning"
    assert result["available_tools"] == [{"name": "weather"}]
    assert result["web_search_hint_tools"] == ["web_search"]
    assert result["usage"]["model_calls"] == 3
    assert result["usage"]["total_tokens"] == 6
    assert result["server_side_tools"] == {"SERVER_SIDE_TOOL_WEB_SEARCH": 2}
    assert result["usage"]["server_side_tools"] == result["server_side_tools"]
    # Four budgeted routing turns plus one native-to-text fallback. The second
    # rejection must not get another fallback just because a tool retry occurred.
    assert len(case.calls) == 5
    assert [isinstance(payload, ProviderRouteInput) for payload, _ in case.calls] == [
        False, True, False, True, True,
    ]
    failed_call_id, failed_output = _tool_output(case.calls[3][0])
    assert failed_call_id == "call-2"
    assert case.calls[3][1]["previous_response_id"] == "resp-2"
    assert "Status: error" in failed_output
    assert "Yelp hasn't returned any results" in failed_output
    assert case.calls[-1][1]["previous_response_id"] == "resp-3"
    assert [p["call_index"] for event, p in case.events if event == "tool_start"] == [0, 1, 2]
    assert case.orch.executor.calls == 3


@pytest.mark.parametrize("missing_key", ["response_id", "tool_call_id"])
@pytest.mark.parametrize("tool_ok", [False, True])
def test_call_without_native_metadata_sends_full_text_context(continuing_request, missing_key, tool_ok):
    case = continuing_request
    if tool_ok:
        case.orch.executor.fail_on_calls.clear()
    second_route = case.tool(2)
    second_route.pop(missing_key)
    case.script([case.tool(1), second_route, {"intent": "qa", "text_response": "done"}])
    result = case.run(3)

    assert result["ok"] is True
    assert [item["ok"] for item in result["tool_trace"]] == [True, tool_ok]
    payload, kwargs = case.calls[2]
    assert isinstance(payload, str)
    assert kwargs["previous_response_id"] is None
    if not tool_ok:
        assert "Yelp hasn't returned any results" in payload
    assert "city-2" in payload


@pytest.mark.parametrize("with_prompt_version", [True, False])
def test_initial_routing_error_returns_empty_request_state(continuing_request, with_prompt_version):
    case = continuing_request
    if not with_prompt_version:
        case.orch.router.system_prompt_version = None
    case.script([{"intent": "error", "error": "provider unavailable"}])
    result = case.run(3)

    assert result["ok"] is False
    assert result["error"] == "provider unavailable"
    assert result["tools_used"] == []
    assert result["data"] == {}
    assert result["tool_trace"] == []
    if with_prompt_version:
        assert result["usage"]["router_prompt_version"] == "test"
        assert result["usage"]["total_tokens"] == 0
        assert result["usage"]["model_calls"] == 0
    else:
        assert result["usage"] is None
    assert result["server_side_tools"] == {}
    assert case.orch.executor.calls == 0
