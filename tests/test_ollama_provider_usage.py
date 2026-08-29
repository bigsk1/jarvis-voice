#!/usr/bin/env python3
"""Tests for Ollama provider cloud-vs-local request tuning and usage labels."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from llm_provider import OllamaProvider


GLM_ORPHAN_THINK_RESPONSE = (
    "The user asked for the current Solana price, and I already have it from "
    "the crypto_price tool. The result is fresh and authoritative. No need to "
    "call another tool.\n\nLet me respond directly with the information."
    "</think>**Solana (SOL) is currently at $77.89**, down 4.51%."
)


class _ChatResponse:
    status_code = 200

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "message": {"content": self.content},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }


class _ThinkingChatResponse(_ChatResponse):
    def json(self):
        payload = super().json()
        payload["message"]["thinking"] = "private reasoning trace"
        return payload


class _ThinkingOnlyChatResponse(_ChatResponse):
    def __init__(self, thinking):
        super().__init__("")
        self.thinking = thinking

    def json(self):
        payload = super().json()
        payload["message"]["thinking"] = self.thinking
        return payload


class _PaymentRequiredResponse:
    status_code = 402
    reason = "Payment Required"

    def __init__(self):
        self.raise_for_status_calls = 0

    def raise_for_status(self):
        self.raise_for_status_calls += 1
        raise AssertionError("detailed Ollama errors must be handled before raise_for_status")

    def json(self):
        return {
            "error": (
                "this model uses extra usage only (not included plan usage) and "
                "your extra usage balance is empty, add extra usage or turn on "
                "auto reload at https://ollama.com/settings "
                "(ref: test-ref-402)"
            )
        }


def _provider(model, monkeypatch=None, mode="local"):
    if monkeypatch is not None:
        monkeypatch.setenv("JARVIS_MODE", mode)
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    return OllamaProvider(base_url="http://localhost:11434", model=model)


def test_local_usage_is_free_and_known(monkeypatch):
    p = _provider("gemma4", monkeypatch)
    usage = p._build_usage(100, 50)
    assert usage["cost_usd"] == 0.0
    assert usage["cost_known"] is True
    assert usage["billing_mode"] == "local"
    assert usage["total_tokens"] == 150


def test_cloud_usage_cost_unknown_with_tokens(monkeypatch):
    p = _provider("qwen3.5:cloud", monkeypatch)
    usage = p._build_usage(100, 50)
    assert usage["cost_usd"] is None
    assert usage["cost_known"] is False
    assert usage["billing_mode"] == "ollama_cloud_subscription"
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 50
    assert usage["total_tokens"] == 150


def test_cloud_dash_tag_usage_detected(monkeypatch):
    p = _provider("gpt-oss:120b-cloud", monkeypatch)
    usage = p._build_usage(10, 10)
    assert usage["cost_known"] is False


def test_local_request_includes_num_ctx(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_WINDOW", "32000")
    p = _provider("gemma4", monkeypatch)
    opts = p._get_context_options()
    assert opts.get("num_ctx") == 32000


def test_cloud_request_omits_num_ctx(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_WINDOW", "32000")
    p = _provider("qwen3.5:cloud", monkeypatch)
    opts = p._get_context_options()
    assert "num_ctx" not in opts


def test_structured_fallback_note_suffix():
    p = _provider("qwen3.5:cloud")
    usage = p._build_usage(1, 1, note_suffix=" (structured prompting fallback)")
    assert "structured prompting fallback" in usage["note"]


def test_cloud_provider_does_not_append_localhost(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    p = OllamaProvider(
        base_url="http://gpu-one:11434,http://gpu-two:11434",
        model="qwen3.5:cloud",
    )
    assert p.base_urls == ["http://gpu-one:11434", "http://gpu-two:11434"]


def test_local_provider_keeps_localhost_fallback(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    p = OllamaProvider(base_url="http://gpu-one:11434", model="gemma4")
    assert p.base_urls == ["http://gpu-one:11434", "http://localhost:11434"]


def test_explicit_no_localhost_fallback_is_passed_to_request_ollama(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    provider = OllamaProvider(
        base_url="http://gpu-one:11434",
        model="gemma4",
        include_localhost_fallback=False,
        force_local_daemon=True,
    )
    assert provider.base_urls == ["http://gpu-one:11434"]
    response = _ChatResponse("ok")
    with patch("llm_provider.request_ollama", return_value=(response, "http://gpu-one:11434")) as mocked:
        provider.chat_with_tools(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[],
        )
    assert mocked.call_args.kwargs["include_localhost_fallback"] is False
    assert mocked.call_args.kwargs["base_urls"] == ["http://gpu-one:11434"]


def test_optional_seed_is_sent_only_when_configured(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    seeded = OllamaProvider(
        base_url="http://gpu-one:11434",
        model="gemma4",
        include_localhost_fallback=False,
        force_local_daemon=True,
        seed=73,
    )
    unseeded = OllamaProvider(
        base_url="http://gpu-one:11434",
        model="gemma4",
        include_localhost_fallback=False,
        force_local_daemon=True,
    )
    response = _ChatResponse("ok")
    with patch("llm_provider.request_ollama", return_value=(response, "http://gpu-one:11434")) as mocked:
        seeded.chat_with_tools(messages=[{"role": "user", "content": "Hi"}], tools=[])
        unseeded.chat_with_tools(messages=[{"role": "user", "content": "Hi"}], tools=[])

    assert mocked.call_args_list[0].kwargs["json"]["options"]["seed"] == 73
    assert "seed" not in mocked.call_args_list[1].kwargs["json"]["options"]


def test_timeout_error_text_uses_configured_request_timeout(monkeypatch):
    import requests as req

    monkeypatch.setenv("JARVIS_MODE", "local")
    provider = OllamaProvider(
        base_url="http://gpu-one:11434",
        model="gemma4",
        include_localhost_fallback=False,
        request_timeout=300,
        force_local_daemon=True,
    )
    with patch("llm_provider.request_ollama", side_effect=req.exceptions.Timeout()):
        text, tool_call, usage, thinking = provider.chat_with_tools(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[],
        )
    assert text.startswith("Error: Request timed out after 300s")
    assert tool_call is None
    assert usage is None
    assert thinking is None


def test_cloud_tool_calls_skip_local_rewrites(monkeypatch):
    raw = {"name": "Some-Tool", "arguments": {"url": "example.com"}}
    assert _provider("qwen3.5:cloud", monkeypatch)._correct_tool_call_for_execution_class(raw) == raw


def test_local_tool_calls_keep_compatibility_rewrites(monkeypatch):
    raw = {"name": "Some-Tool", "arguments": {"url": "example.com"}}
    corrected = _provider("gemma4", monkeypatch)._correct_tool_call_for_execution_class(raw)
    assert corrected == {
        "name": "some_tool",
        "arguments": {"url": "https://example.com"},
    }


def test_direct_cloud_canonical_model_omits_num_ctx_and_reports_cloud(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "configured")
    monkeypatch.setenv("OLLAMA_CONTEXT_WINDOW", "32000")
    p = OllamaProvider(base_url="http://ignored:11434", model="qwen3.5:397b")

    assert p.base_urls == ["https://ollama.com"]
    assert "num_ctx" not in p._get_context_options()
    assert p._build_usage(10, 5)["billing_mode"] == "ollama_cloud_subscription"
    assert p._build_usage(10, 5)["ollama_execution"] == "direct_cloud_api"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>internal plan</think>Final answer", "Final answer"),
        ("<reasoning>internal plan</reasoning>Final answer", "Final answer"),
        ("internal plan</think>Final answer", "Final answer"),
        ("internal plan</reasoning>Final answer", "Final answer"),
        (GLM_ORPHAN_THINK_RESPONSE, "**Solana (SOL) is currently at $77.89**, down 4.51%."),
        ("Ordinary answer", "Ordinary answer"),
    ],
)
def test_strip_reasoning_content_handles_closed_and_orphan_wrappers(raw, expected):
    assert OllamaProvider._strip_reasoning_content(raw) == expected


def test_native_tool_q_and_a_path_strips_glm_orphan_reasoning(monkeypatch):
    provider = _provider("glm-5.2", monkeypatch, mode="cloud")
    response = _ChatResponse(GLM_ORPHAN_THINK_RESPONSE)

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text, tool_call, usage, thinking = provider.chat_with_tools(
            messages=[{"role": "user", "content": "What is Solana worth?"}],
            tools=[],
            system_prompt="Answer directly.",
        )

    assert text == "**Solana (SOL) is currently at $77.89**, down 4.51%."
    assert tool_call is None
    assert usage["total_tokens"] == 15
    assert thinking is None


@pytest.mark.parametrize("model", ["glm-5.3:cloud", "glm-5.3-flash:cloud"])
def test_required_glm_thinking_uses_low_and_hides_trace_by_default(monkeypatch, model):
    provider = _provider(model, monkeypatch, mode="cloud")
    response = _ThinkingChatResponse("Hello!")

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")) as mocked:
        text, tool_call, usage, thinking = provider.chat_with_tools(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )

    assert mocked.call_args.kwargs["json"]["think"] == "low"
    assert text == "Hello!"
    assert tool_call is None
    assert usage["total_tokens"] == 15
    assert thinking is None


def test_required_glm_thinking_uses_default_and_returns_trace_when_enabled(monkeypatch):
    provider = _provider("glm-5.3:cloud", monkeypatch, mode="cloud")
    response = _ThinkingChatResponse("Hello!")

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")) as mocked:
        text, _, _, thinking = provider.chat_with_tools(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
            enable_thinking=True,
        )

    assert mocked.call_args.kwargs["json"]["think"] == "max"
    assert text == "Hello!"
    assert thinking == "private reasoning trace"


def test_required_glm_simple_chat_and_structured_fallback_use_low(monkeypatch):
    provider = _provider("glm-5.3-flash:cloud", monkeypatch, mode="cloud")
    response = _ThinkingChatResponse("Hello!")

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")) as mocked:
        assert provider.chat("Hello") == "Hello!"
        simple_request = mocked.call_args.kwargs["json"]
        _, _, _, thinking = provider._chat_with_tools_structured(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
        )
        structured_request = mocked.call_args.kwargs["json"]

    assert simple_request["think"] == "low"
    assert structured_request["think"] == "low"
    assert thinking is None


def test_json_mode_never_promotes_or_logs_reasoning_only_fallback(
    monkeypatch,
    capsys,
):
    provider = _provider("glm-5.3:cloud", monkeypatch, mode="cloud")
    monkeypatch.setenv("JARVIS_DEBUG", "false")
    private_trace = (
        "SENSITIVE_PRIVATE_TRACE: I should inspect the task and decide which "
        "fields belong in the result."
    )
    response = _ThinkingOnlyChatResponse(private_trace)
    capsys.readouterr()

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text = provider.chat(
            "Evaluate this result.",
            system_prompt="Return JSON only.",
        )

    assert text == ""
    captured = capsys.readouterr()
    assert private_trace not in captured.err
    assert "JSON recovery failed" not in captured.err
    assert "result=" not in captured.err


def test_json_mode_failed_recovery_debug_log_contains_metadata_only(
    monkeypatch,
    capsys,
):
    provider = _provider("glm-5.3:cloud", monkeypatch, mode="cloud")
    monkeypatch.setenv("JARVIS_DEBUG", "true")
    private_trace = "SENSITIVE_PRIVATE_TRACE: internal analysis without JSON"
    response = _ThinkingOnlyChatResponse(private_trace)
    capsys.readouterr()

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text = provider.chat(
            "Evaluate this result.",
            system_prompt="Return JSON only.",
        )

    assert text == ""
    captured = capsys.readouterr()
    assert "JSON recovery failed" in captured.err
    assert f"thinking_chars={len(private_trace)}" in captured.err
    assert "prompt_tokens=10" in captured.err
    assert "completion_tokens=5" in captured.err
    assert private_trace not in captured.err
    assert "result=" not in captured.err


def test_json_mode_recovers_only_parseable_object_from_thinking(monkeypatch):
    provider = _provider("glm-5.3:cloud", monkeypatch, mode="cloud")
    response = _ThinkingOnlyChatResponse(
        'I should return the requested shape.\n```json\n{"ok": true, "score": 4}\n```'
    )

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text = provider.chat(
            "Evaluate this result.",
            system_prompt="Return valid JSON only.",
        )

    assert text == '{"ok": true, "score": 4}'


def test_native_tool_path_preserves_ollama_cloud_payment_error_body(monkeypatch):
    provider = _provider("kimi-k3", monkeypatch, mode="cloud")
    response = _PaymentRequiredResponse()

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text, tool_call, usage, thinking = provider.chat_with_tools(
            messages=[{"role": "user", "content": "Hey, how are you?"}],
            tools=[],
            system_prompt="Answer directly.",
        )

    assert text == (
        "Error: 402 Payment Required: this model uses extra usage only "
        "(not included plan usage) and your extra usage balance is empty, "
        "add extra usage or turn on auto reload at https://ollama.com/settings "
        "(ref: test-ref-402)"
    )
    assert tool_call is None
    assert usage is None
    assert thinking is None
    assert response.raise_for_status_calls == 0


def test_simple_chat_path_preserves_ollama_cloud_payment_error_body(monkeypatch):
    provider = _provider("kimi-k3", monkeypatch, mode="cloud")
    response = _PaymentRequiredResponse()

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text = provider.chat("Hey, how are you?", system_prompt="Answer directly.")

    assert text.startswith("Error: 402 Payment Required: this model uses extra usage only")
    assert "https://ollama.com/settings" in text
    assert response.raise_for_status_calls == 0


def test_structured_path_preserves_ollama_cloud_payment_error_body(monkeypatch):
    provider = _provider("kimi-k3", monkeypatch, mode="cloud")
    response = _PaymentRequiredResponse()

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text, tool_call, usage, thinking = provider._chat_with_tools_structured(
            messages=[{"role": "user", "content": "Hey, how are you?"}],
            tools=[],
            system_prompt="Answer directly.",
        )

    assert text.startswith("Error: 402 Payment Required: this model uses extra usage only")
    assert "https://ollama.com/settings" in text
    assert tool_call is None
    assert usage is None
    assert thinking is None
    assert response.raise_for_status_calls == 0


def test_simple_chat_path_strips_glm_orphan_reasoning(monkeypatch):
    provider = _provider("glm-5.2", monkeypatch, mode="cloud")
    response = _ChatResponse(GLM_ORPHAN_THINK_RESPONSE)

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text = provider.chat("What is Solana worth?", system_prompt="Answer directly.")

    assert text == "**Solana (SOL) is currently at $77.89**, down 4.51%."


def test_structured_fallback_q_and_a_path_returns_cleaned_content(monkeypatch):
    provider = _provider("glm-5.2", monkeypatch, mode="cloud")
    response = _ChatResponse(GLM_ORPHAN_THINK_RESPONSE)

    with patch("llm_provider.request_ollama", return_value=(response, "https://ollama.com")):
        text, tool_call, usage, thinking = provider._chat_with_tools_structured(
            messages=[{"role": "user", "content": "What is Solana worth?"}],
            tools=[],
            system_prompt="Answer directly.",
        )

    assert text == "**Solana (SOL) is currently at $77.89**, down 4.51%."
    assert tool_call is None
    assert usage["total_tokens"] == 15
    assert thinking is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
