#!/usr/bin/env python3
"""Tests for Ollama provider cloud-vs-local request tuning and usage labels."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from llm_provider import OllamaProvider


def _provider(model):
    return OllamaProvider(base_url="http://localhost:11434", model=model)


def test_local_usage_is_free_and_known():
    p = _provider("gemma4")
    usage = p._build_usage(100, 50)
    assert usage["cost_usd"] == 0.0
    assert usage["cost_known"] is True
    assert usage["billing_mode"] == "local"
    assert usage["total_tokens"] == 150


def test_cloud_usage_cost_unknown_with_tokens():
    p = _provider("qwen3.5:cloud")
    usage = p._build_usage(100, 50)
    assert usage["cost_usd"] is None
    assert usage["cost_known"] is False
    assert usage["billing_mode"] == "ollama_cloud_subscription"
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 50
    assert usage["total_tokens"] == 150


def test_cloud_dash_tag_usage_detected():
    p = _provider("gpt-oss:120b-cloud")
    usage = p._build_usage(10, 10)
    assert usage["cost_known"] is False


def test_local_request_includes_num_ctx(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_WINDOW", "32000")
    p = _provider("gemma4")
    opts = p._get_context_options()
    assert opts.get("num_ctx") == 32000


def test_cloud_request_omits_num_ctx(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_WINDOW", "32000")
    p = _provider("qwen3.5:cloud")
    opts = p._get_context_options()
    assert "num_ctx" not in opts


def test_structured_fallback_note_suffix():
    p = _provider("qwen3.5:cloud")
    usage = p._build_usage(1, 1, note_suffix=" (structured prompting fallback)")
    assert "structured prompting fallback" in usage["note"]


def test_cloud_provider_does_not_append_localhost(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    p = OllamaProvider(
        base_url="http://gpu-one:11434,http://gpu-two:11434",
        model="qwen3.5:cloud",
    )
    assert p.base_urls == ["http://gpu-one:11434", "http://gpu-two:11434"]


def test_local_provider_keeps_localhost_fallback(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    p = OllamaProvider(base_url="http://gpu-one:11434", model="gemma4")
    assert p.base_urls == ["http://gpu-one:11434", "http://localhost:11434"]


def test_cloud_tool_calls_skip_local_rewrites():
    raw = {"name": "Some-Tool", "arguments": {"url": "example.com"}}
    assert _provider("qwen3.5:cloud")._correct_tool_call_for_execution_class(raw) == raw


def test_local_tool_calls_keep_compatibility_rewrites():
    raw = {"name": "Some-Tool", "arguments": {"url": "example.com"}}
    corrected = _provider("gemma4")._correct_tool_call_for_execution_class(raw)
    assert corrected == {
        "name": "some_tool",
        "arguments": {"url": "https://example.com"},
    }


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
