#!/usr/bin/env python3
"""Tests for Ollama provider cloud-vs-local request tuning and usage labels."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from llm_provider import OllamaProvider


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
