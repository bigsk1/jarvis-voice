#!/usr/bin/env python3
"""Regression coverage for direct Ollama calls outside OllamaProvider."""

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills"))

import config_loader
from config_loader import config_scope
import status_llm
import stash


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "response": "working now",
            "message": {"content": "summary"},
        }


class _StatusResponse(_Response):
    def json(self):
        return {
            "response": "working now",
            "message": {"content": "working summary"},
        }


def _write_configs(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                "OLLAMA_API_KEY=configured",
                "OLLAMA_CLOUD_MODEL=minimax-m3",
                "STATUS_LLM_PROVIDER=ollama",
                "STATUS_LLM_ENABLED=true",
                "STASH_SUMMARIZE_LLM_PROVIDER=ollama",
                "STASH_SUMMARIZE_MODEL=minimax-m3",
            ]
        )
    )
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")


def _write_signed_daemon_configs(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                'OLLAMA_API_KEY=""',
                "OLLAMA_BASE_URL=http://ollama-daemon:11434",
                "OLLAMA_CLOUD_MODEL=minimax-m3:cloud",
                "STASH_SUMMARIZE_LLM_PROVIDER=ollama",
            ]
        )
    )
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")


def _write_helper_configs(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=xai",
                "OLLAMA_BASE_URL=http://remote-primary:11434",
                "STATUS_LLM_PROVIDER=helper",
                "STATUS_LLM_ENABLED=true",
                "STASH_SUMMARIZE_LLM_PROVIDER=helper",
                "JARVIS_HELPER_LLM_BASE_URL=http://127.0.0.1:11434",
                "JARVIS_HELPER_LLM_MODEL=jarvis-minicpm5-1b",
                "JARVIS_HELPER_LLM_DEVICE=cpu",
                "JARVIS_HELPER_LLM_KEEP_ALIVE=30m",
            ]
        )
    )
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")


def test_status_llm_uses_cloud_routing_for_direct_canonical_model(tmp_path, monkeypatch):
    _write_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)

    with config_scope("cloud"), patch.object(
        status_llm,
        "request_ollama",
        return_value=(_Response(), "https://ollama.com"),
    ) as request_ollama:
        summarizer = status_llm.StatusSummarizer()
        assert summarizer._call_ollama("Still working?") == "working now"

    assert request_ollama.call_args.kwargs["cloud_access"] is True
    assert "base_urls" not in request_ollama.call_args.kwargs


def test_stash_summary_uses_configured_provider_for_ollama_cloud(tmp_path, monkeypatch):
    _write_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)

    with config_scope("cloud"), patch(
        "llm_provider.request_ollama",
        return_value=(_Response(), "https://ollama.com"),
    ) as request_ollama:
        assert stash.summarize_content_with_llm("facts", "facts.txt") == "summary"

    assert request_ollama.call_args.kwargs["base_urls"] == ["https://ollama.com"]


def test_stash_summary_uses_signed_in_ollama_daemon(tmp_path, monkeypatch):
    _write_signed_daemon_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)

    with config_scope("cloud"), patch(
        "llm_provider.request_ollama",
        return_value=(_Response(), "http://ollama-daemon:11434"),
    ) as request_ollama:
        assert stash.summarize_content_with_llm("facts", "facts.txt") == "summary"

    request = request_ollama.call_args
    assert request.kwargs["base_urls"] == ["http://ollama-daemon:11434"]
    assert request.kwargs["json"]["model"] == "minimax-m3:cloud"


def test_status_helper_stays_on_loopback_and_applies_cpu_controls(tmp_path, monkeypatch):
    _write_helper_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    overrides = {
        "STATUS_LLM_PROVIDER": "helper",
        "STATUS_LLM_ENABLED": "true",
        "JARVIS_HELPER_LLM_BASE_URL": "http://127.0.0.1:11434",
        "JARVIS_HELPER_LLM_MODEL": "jarvis-minicpm5-1b",
        "JARVIS_HELPER_LLM_DEVICE": "cpu",
        "JARVIS_HELPER_LLM_KEEP_ALIVE": "30m",
        "STATUS_LLM_MAX_TOKENS": "30",
    }

    with config_scope("cloud", overrides=overrides), patch(
        "llm_provider.request_ollama",
        return_value=(_StatusResponse(), "http://127.0.0.1:11434"),
    ) as request_ollama:
        summarizer = status_llm.StatusSummarizer()
        assert summarizer._call_helper("Still working?") == "working summary"

    request = request_ollama.call_args
    assert request.kwargs["base_urls"] == ["http://127.0.0.1:11434"]
    assert request.kwargs["json"]["model"] == "jarvis-minicpm5-1b"
    assert request.kwargs["json"]["think"] is False
    assert request.kwargs["json"]["keep_alive"] == "30m"
    assert request.kwargs["json"]["options"]["num_gpu"] == 0
    assert request.kwargs["json"]["options"]["num_predict"] == 30


def test_status_helper_rejects_false_completion_claim(tmp_path, monkeypatch):
    _write_helper_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    overrides = {
        "STATUS_LLM_PROVIDER": "helper",
        "STATUS_LLM_ENABLED": "true",
        "JARVIS_HELPER_LLM_MODEL": "jarvis-minicpm5-1b",
    }
    response = _StatusResponse()
    response.json = lambda: {"message": {"content": "Weather lookup completed"}}

    with config_scope("cloud", overrides=overrides), patch(
        "llm_provider.request_ollama",
        return_value=(response, "http://127.0.0.1:11434"),
    ):
        summarizer = status_llm.StatusSummarizer()
        assert summarizer._call_helper("Still working?", event_type="progress") is None


def test_stash_helper_stays_on_loopback_in_cloud_mode(tmp_path, monkeypatch):
    _write_helper_configs(tmp_path)
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    overrides = {
        "STASH_SUMMARIZE_LLM_PROVIDER": "helper",
        "JARVIS_HELPER_LLM_BASE_URL": "http://127.0.0.1:11434",
        "JARVIS_HELPER_LLM_MODEL": "jarvis-minicpm5-1b",
        "JARVIS_HELPER_LLM_DEVICE": "cpu",
        "JARVIS_HELPER_LLM_KEEP_ALIVE": "30m",
    }

    with config_scope("cloud", overrides=overrides), patch(
        "llm_provider.request_ollama",
        return_value=(_Response(), "http://127.0.0.1:11434"),
    ) as request_ollama:
        assert stash.summarize_content_with_llm("facts", "facts.txt") == "summary"

    request = request_ollama.call_args
    assert request.kwargs["base_urls"] == ["http://127.0.0.1:11434"]
    assert request.kwargs["json"]["model"] == "jarvis-minicpm5-1b"
    assert request.kwargs["json"]["think"] is False
    assert request.kwargs["json"]["keep_alive"] == "30m"
