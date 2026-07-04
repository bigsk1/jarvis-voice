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
