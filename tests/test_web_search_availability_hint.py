"""Conditional routing policies stay in system instructions, separate from user input."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from config_loader import config_scope  # noqa: E402
from lib.background_tasks.admission import WebTaskContext  # noqa: E402
from router_prompts import get_router_system_prompt  # noqa: E402
from router_v2 import LLMRouter, ProviderRouteInput, _web_search_availability_hint  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


def _tool(name, *, web_search=False, enabled=True):
    return ToolSchema(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        script_path=f"{name}.py",
        permissions={"enabled": enabled},
        web_search=web_search,
    )


class _Registry:
    def __init__(self):
        self.tools = {
            tool.name: tool for tool in [
                _tool("tool_search"),
                _tool("tavily_search", web_search=True),
                _tool("mcp_brave_search_brave_web_search", web_search=True),
                _tool("blocked_search", web_search=True),
                _tool("disabled_search", web_search=True, enabled=False),
                _tool("crawl_url"),
            ]
        }
        self.last_tool_search_meta = {}

    def find_tools(self, *_args, **_kwargs):
        return [self.tools["tool_search"], self.tools["tavily_search"]]

    def get_tool(self, name):
        return self.tools.get(name)


class _Provider:
    def __init__(self):
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return "Answer", None, None, None


def test_manifest_boolean_is_read_and_absence_is_false():
    assert ToolSchema.from_json_file(str(ROOT / "skills/tavily_search.tool.json")).web_search
    assert not ToolSchema.from_json_file(str(ROOT / "skills/crawl_url.tool.json")).web_search


def test_hint_uses_only_callable_unblocked_search_tools():
    registry = _Registry()
    hint = _web_search_availability_hint(registry, {"blocked_search"})

    assert "mcp_brave_search_brave_web_search" in hint
    assert "tavily_search" in hint
    assert "blocked_search" not in hint
    assert "disabled_search" not in hint
    assert "crawl_url" not in hint
    assert "Local web search tools" in hint
    assert "separate from provider-native search" in hint
    assert "Use only if relevant" in hint
    assert _web_search_availability_hint(registry, {"tool_search"}) == ""


def test_router_sends_hint_without_adding_search_schemas_or_chat_only_tools():
    router = LLMRouter.__new__(LLMRouter)
    router.mode = "cloud"
    router.registry = _Registry()
    router.provider = _Provider()
    router.provider_type = "test"
    router.model_name = "test-model"
    router.system_prompt_version = "test"
    route_input = ProviderRouteInput(
        tool_retrieval_query="Research this",
        messages=[{"role": "user", "content": "Research this"}],
        system_prompt="Base policy",
    )

    with config_scope("cloud", overrides={"TOOL_RAG_TRACE_ENABLED": "false"}), \
         patch("router_v2._log_tool_rag_trace"), \
         patch("thinking.should_enable_thinking", return_value=False), \
         patch("llm_logger.get_logger"):
        result = router.route(route_input, excluded_tools=["blocked_search"])
        chat_only = router.route(route_input, tool_policy="none")

    assert result["intent"] == "qa"
    assert result["web_search_hint_tools"] == [
        "mcp_brave_search_brave_web_search", "tavily_search"
    ]
    call = router.provider.calls[0]
    assert "mcp_brave_search_brave_web_search" in call["system_prompt"]
    assert "mcp_brave_search_brave_web_search" not in [tool["function"]["name"] for tool in call["tools"]]
    assert "blocked_search" not in call["system_prompt"]
    assert chat_only["intent"] == "qa"
    assert chat_only["web_search_hint_tools"] == []
    assert "Local web search tools" not in router.provider.calls[1]["system_prompt"]
    assert router.provider.calls[1]["tools"] == []


def _background_policy_call(request, context, *, version="v4", tool_policy="auto", now=None):
    router = LLMRouter.__new__(LLMRouter)
    router.mode = "cloud"
    router.registry = _Registry()
    router.provider = _Provider()
    router.provider_type = "test"
    router._provider_override = "test"
    router.model_name = "test-model"
    router.system_prompt_version, router._system_prompt_base = get_router_system_prompt(version)
    router.timezone = ZoneInfo("UTC")
    router.prompt_override = None
    with config_scope("cloud", overrides={"TOOL_RAG_TRACE_ENABLED": "false",
                                          "JARVIS_DEFAULT_LOCATION": "Fixture City"}), \
         patch("router_v2.append_profile_card_for_router_direct_answer", side_effect=lambda text: text), \
         patch("router_v2._log_tool_rag_trace"), \
         patch("thinking.should_enable_thinking", return_value=False), \
         patch("llm_logger.get_logger"), \
         patch("router_v2.datetime") as clock:
        clock.now.return_value = now or datetime(2026, 10, 15, 12, tzinfo=ZoneInfo("UTC"))
        router.route(request, background_context=context, tool_policy=tool_policy)
    return router.provider.calls[-1]


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4"])
def test_background_receipt_policy_is_system_only_for_every_prompt_version(version):
    query = "Get the current Bitcoin price."
    context = WebTaskContext(object(), "fixture-request", ("fixture",))
    call = _background_policy_call(query, context, version=version)

    assert call["messages"] == [{"role": "user", "content": query}]
    assert call["system_prompt"].count("A background acceptance receipt") == 1
    assert "job_id identifies the Jarvis queue entry, not a provider task" in call["system_prompt"]
    assert "Do not repeat the accepted call" in call["system_prompt"]


@pytest.mark.parametrize("context", [None, object(), WebTaskContext(object(), "fixture-request", ())])
def test_background_receipt_policy_requires_selected_web_context(context):
    call = _background_policy_call("Get the current Bitcoin price.", context)
    assert "background acceptance receipt" not in call["system_prompt"]


def test_chat_only_does_not_receive_background_receipt_policy():
    context = WebTaskContext(object(), "fixture-request", ("fixture",))
    call = _background_policy_call("Explain Bitcoin.", context, tool_policy="none")
    assert "background acceptance receipt" not in call["system_prompt"]
    assert call["tools"] == []


@pytest.mark.parametrize("system_prompt", [None, "Fallback system instructions."])
def test_background_receipt_policy_preserves_structural_continuation_and_text_fallback(system_prompt):
    context = WebTaskContext(object(), "fixture-request", ("fixture",))
    messages = [{"role": "tool", "tool_call_id": "fixture-call", "content": "queued"}]
    request = ProviderRouteInput(
        tool_retrieval_query="Get the current Bitcoin price.",
        messages=messages,
        system_prompt=system_prompt,
        previous_response_id="fixture-response" if system_prompt is None else None,
        continuation_mode="structural" if system_prompt is None else "text_fallback",
    )
    call = _background_policy_call(request, context)
    assert call["messages"] == messages
    if system_prompt is None:
        assert call["system_prompt"] is None
    else:
        assert system_prompt in call["system_prompt"]
        assert call["system_prompt"].count("A background acceptance receipt") == 1


def test_background_receipt_policy_is_not_duplicated_in_a_supplied_system_prompt():
    context = WebTaskContext(object(), "fixture-request", ("fixture",))
    first = _background_policy_call("Get the current Bitcoin price.", context)
    request = ProviderRouteInput(
        tool_retrieval_query="Continue from the prior result.",
        messages=[{"role": "user", "content": "Continue from the prior result."}],
        system_prompt=first["system_prompt"],
    )
    call = _background_policy_call(request, context)
    assert call["system_prompt"].count("A background acceptance receipt") == 1


def test_background_receipt_policy_and_base_stay_in_the_stable_prefix_when_clock_changes():
    context = WebTaskContext(object(), "fixture-request", ("fixture",))
    first = _background_policy_call(
        "Get the current Bitcoin price.", context,
        now=datetime(2026, 10, 15, 12, tzinfo=ZoneInfo("UTC")),
    )["system_prompt"]
    second = _background_policy_call(
        "Get the current Bitcoin price.", context,
        now=datetime(2026, 10, 15, 13, tzinfo=ZoneInfo("UTC")),
    )["system_prompt"]
    _, base = get_router_system_prompt("v4")
    stable_end = first.index(base.strip()) + len(base.strip())
    assert first.startswith("A background acceptance receipt")
    assert first[:stable_end] == second[:stable_end]
    assert first[stable_end:] != second[stable_end:]
