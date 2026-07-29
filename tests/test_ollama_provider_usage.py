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
