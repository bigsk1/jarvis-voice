#!/usr/bin/env python3
"""Tests for Ollama-cloud-primary model and embedding resolution."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import config_loader
from config_loader import config_scope
from ollama_utils import (
    OllamaModelError,
    get_effective_ollama_model,
    is_ollama_cloud_model,
)
from embeddings import get_effective_embedding_provider


@pytest.fixture
def fake_configs(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                "OLLAMA_CLOUD_MODEL=qwen3.5:cloud",
                "OLLAMA_MODEL=gemma4",
                "EMBEDDING_PROVIDER=openai",
            ]
        )
    )
    (config_dir / "local.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                "OLLAMA_MODEL=gemma4-local",
                "EMBEDDING_PROVIDER=ollama",
            ]
        )
    )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    return tmp_path


# --- is_ollama_cloud_model -------------------------------------------------

@pytest.mark.parametrize(
    "model",
    ["qwen3.5:cloud", "gpt-oss:120b-cloud", "minimax-m2.7:cloud", "model-cloud"],
)
def test_recognizes_cloud_models(model):
    assert is_ollama_cloud_model(model) is True


@pytest.mark.parametrize(
    "model",
    ["gemma4", "cloud-helper:latest", "qwen3:8b", "", None, "llama3:cloudy"],
)
def test_rejects_non_cloud_models(model):
    assert is_ollama_cloud_model(model) is False


# --- get_effective_ollama_model -------------------------------------------

def test_local_mode_uses_ollama_model(fake_configs):
    with config_scope("local"):
        assert get_effective_ollama_model() == "gemma4-local"


def test_cloud_mode_uses_cloud_model(fake_configs):
    with config_scope("cloud"):
        assert get_effective_ollama_model() == "qwen3.5:cloud"


def test_explicit_override_wins(fake_configs):
    with config_scope("cloud"):
        assert get_effective_ollama_model(model_override="minimax-m3:cloud") == "minimax-m3:cloud"


def test_cloud_fallback_accepts_cloud_tagged_legacy_model(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("OLLAMA_MODEL=kimi-k2.6:cloud\n")
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    with config_scope("cloud"):
        assert get_effective_ollama_model() == "kimi-k2.6:cloud"


def test_cloud_mode_without_valid_model_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("OLLAMA_MODEL=gemma4\n")
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    with config_scope("cloud"):
        with pytest.raises(OllamaModelError):
            get_effective_ollama_model()


def test_cloud_mode_rejects_non_cloud_cloud_model(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("OLLAMA_CLOUD_MODEL=gemma4\n")
    (config_dir / "local.env").write_text("OLLAMA_MODEL=gemma4\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    with config_scope("cloud"):
        with pytest.raises(OllamaModelError, match="must be a cloud-tagged"):
            get_effective_ollama_model()


# --- get_effective_embedding_provider -------------------------------------

def test_cloud_embedding_defaults_to_openai(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("LLM_PROVIDER=ollama\n")
    (config_dir / "local.env").write_text("LLM_PROVIDER=ollama\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    with config_scope("cloud"):
        assert get_effective_embedding_provider() == "openai"


def test_local_embedding_defaults_to_ollama(tmp_path, monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("LLM_PROVIDER=ollama\n")
    (config_dir / "local.env").write_text("LLM_PROVIDER=ollama\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    with config_scope("local"):
        assert get_effective_embedding_provider() == "ollama"


def test_explicit_embedding_provider_wins(fake_configs):
    # cloud.env sets EMBEDDING_PROVIDER=openai explicitly.
    with config_scope("cloud"):
        assert get_effective_embedding_provider() == "openai"
    # local.env sets EMBEDDING_PROVIDER=ollama explicitly.
    with config_scope("local"):
        assert get_effective_embedding_provider() == "ollama"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
