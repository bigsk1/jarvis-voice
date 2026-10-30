"""Anthropic generation budgets, completion states, and safe tool admission."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib.llm_provider import AnthropicProvider, has_usage_accounting_data
from lib.provider_errors import classify_provider_error, is_provider_error_text


def provider_for(model, response):
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = model
    provider.enable_search = False
    provider.client = SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))
    return provider


def response_with(blocks, *, stop="end_turn", usage=None):
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


@pytest.mark.parametrize("model,thinking,budget", [
    ("claude-opus-5-5", {"type": "adaptive", "display": "omitted"}, 16_384),
    ("claude-sonnet-5-5", {"type": "between_tools"}, 4096),
])
def test_ui_auto_has_model_supported_budget_with_hidden_trace(monkeypatch, model, thinking, budget):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "auto")
    response = response_with([
        SimpleNamespace(type="thinking", thinking="Hidden summary"),
        SimpleNamespace(type="text", text="Completed answer"),
    ])
    provider = provider_for(model, response)

    text, tool, usage, trace = provider.chat_with_tools(
        [{"role": "user", "content": "Explain the result"}], [], enable_thinking=False,
    )

    sent = provider.client.messages.create.call_args.kwargs
    assert sent["thinking"] == thinking
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == budget
    assert text == "Completed answer"
    assert tool is None
    assert trace is None
    assert usage["anthropic_stop_reason"] == "end_turn"
    assert usage["reasoning_effort_sent"] == "low"
    assert not has_usage_accounting_data(usage)


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
@pytest.mark.parametrize("effort", ["low", "high", "max", "xhigh"])
def test_explicit_effort_preserved_without_enabling_trace(monkeypatch, model, effort):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", effort)
    provider = provider_for(model, response_with([SimpleNamespace(type="text", text="Done")]))

    _, _, usage, trace = provider.chat_with_tools([{"role": "user", "content": "Hello"}], [])

    sent = provider.client.messages.create.call_args.kwargs
    assert sent["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert sent["output_config"] == {"effort": effort}
    assert sent["max_tokens"] == 16_384
    assert usage["reasoning_effort_sent"] == effort
    assert trace is None


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_simple_chat_uses_same_model_aware_auto_settings(monkeypatch, model):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "auto")
    provider = provider_for(model, response_with([SimpleNamespace(type="text", text="Hello")]))

    assert provider.chat("Hello") == "Hello"
    sent = provider.client.messages.create.call_args.kwargs
    assert sent["max_tokens"] > 1024
    assert sent["output_config"] == {"effort": "low"}

    assert provider.chat("Hello", max_tokens=512) == "Hello"
    assert provider.client.messages.create.call_args.kwargs["max_tokens"] == 512


@pytest.mark.parametrize("block", [
    SimpleNamespace(type="thinking", thinking="", signature="never log this signature"),
    SimpleNamespace(type="text", text="A truncated answer"),
    SimpleNamespace(type="tool_use", name="send_email", input={"body": "partial"}),
])
def test_max_tokens_never_becomes_success_or_executable_tool(block):
    usage = SimpleNamespace(
        input_tokens=20, output_tokens=1024, output_tokens_details={"thinking_tokens": 1024},
    )
    provider = provider_for("claude-opus-5-5", response_with([block], stop="max_tokens", usage=usage))

    text, tool, accounting, trace = provider.chat_with_tools(
        [{"role": "user", "content": "Do the task"}], [],
    )

    assert is_provider_error_text(text)
    assert "stop_reason=max_tokens" in text
    assert tool is None
    assert accounting["output_tokens"] == 1024
    assert accounting["reasoning_tokens"] == 1024
    assert accounting["anthropic_content_blocks_by_type"] == {block.type: 1}
    assert "signature" not in str(accounting)
    assert trace is None
    provider.client.messages.create.assert_called_once()


@pytest.mark.parametrize("blocks", [
    [],
    [SimpleNamespace(type="text", text="Searching...")],
    [SimpleNamespace(type="server_tool_use", name="web_search")],
])
def test_pause_turn_is_incomplete_even_with_preamble(blocks):
    provider = provider_for("claude-sonnet-5-5", response_with(blocks, stop="pause_turn"))

    text, tool, usage, _ = provider.chat_with_tools([{"role": "user", "content": "Find an answer"}], [])

    assert is_provider_error_text(text)
    assert "stop_reason=pause_turn" in text
    assert tool is None
    assert usage["anthropic_stop_reason"] == "pause_turn"
    provider.client.messages.create.assert_called_once()


@pytest.mark.parametrize("blocks", [[], [SimpleNamespace(type="text", text=" \n ")]])
def test_empty_completion_is_a_provider_error(blocks):
    provider = provider_for("claude-sonnet-5-5", response_with(blocks))

    text, tool, _, _ = provider.chat_with_tools([{"role": "user", "content": "Hello"}], [])

    assert is_provider_error_text(text)
    assert "no usable text or tool call" in text
    assert tool is None
    assert is_provider_error_text(provider.chat("Hello"))


def test_simple_chat_reports_budget_exhaustion():
    provider = provider_for(
        "claude-opus-5-5",
        response_with([SimpleNamespace(type="thinking", thinking="")], stop="max_tokens"),
    )
    text = provider.chat("Complex question", max_tokens=1024)
    assert is_provider_error_text(text)
    assert "max_tokens=1024" in text


@pytest.mark.parametrize("limit,thinking", [
    (512, {"type": "disabled"}),
    (1024, {"type": "disabled"}),
    (1500, {"type": "enabled", "budget_tokens": 1499}),
    (4096, {"type": "enabled", "budget_tokens": 2000}),
])
def test_legacy_manual_thinking_respects_valid_simple_chat_caps(monkeypatch, limit, thinking):
    monkeypatch.setenv("JARVIS_THINKING_EFFORT", "high")
    provider = provider_for(
        "claude-opus-4-5-20251101", response_with([SimpleNamespace(type="text", text="Done")]),
    )

    assert provider.chat("Summarize", max_tokens=limit) == "Done"

    sent = provider.client.messages.create.call_args.kwargs
    assert sent["max_tokens"] == limit
    assert sent["thinking"] == thinking


def test_context_limit_preserves_its_user_facing_classification():
    provider = provider_for(
        "claude-opus-5-5", response_with([], stop="model_context_window_exceeded"),
    )

    text, tool, _, _ = provider.chat_with_tools([{"role": "user", "content": "Hello"}], [])

    assert classify_provider_error(text).kind == "context"
    assert tool is None


def test_refusal_is_specific_and_never_admits_a_client_tool():
    block = SimpleNamespace(type="tool_use", name="lookup", input={"query": "example"})
    provider = provider_for("claude-opus-5-5", response_with([block], stop="refusal"))

    text, tool, usage, trace = provider.chat_with_tools(
        [{"role": "user", "content": "Look it up"}], [],
    )

    assert is_provider_error_text(text)
    assert classify_provider_error(text).kind == "refusal"
    assert tool is None
    assert trace is None
    assert usage["anthropic_stop_reason"] == "refusal"
    provider.client.messages.create.assert_called_once()
    assert classify_provider_error(provider.chat("Look it up")).kind == "refusal"


def test_completed_client_tool_still_routes_normally():
    block = SimpleNamespace(type="tool_use", name="lookup", input={"query": "example"})
    provider = provider_for("claude-opus-5-5", response_with([block], stop="tool_use"))

    text, tool, usage, _ = provider.chat_with_tools([{"role": "user", "content": "Look it up"}], [])

    assert text is None
    assert tool == {"name": "lookup", "arguments": {"query": "example"}}
    assert usage["anthropic_stop_reason"] == "tool_use"
