#!/usr/bin/env python3
"""Tests for request-scoped config-mode and config-value authority.

These prove that:
- mode is resolved independently of LLM_PROVIDER,
- a request scope overlays config values without mutating os.environ,
- concurrent cloud/local scopes never leak modes or values,
- nested load_config() inside a scope returns scoped values,
- export_config_environment() materializes a child env without side effects.
"""

import os
import sys
import contextvars
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import config_loader
from config_loader import (
    config_scope,
    config_override_scope,
    export_config_environment,
    get_active_config_mode,
    get_config_value,
    get_scoped_config,
    load_config,
)
from jarvis_mode import JarvisModeError


@pytest.fixture
def fake_configs(tmp_path, monkeypatch):
    """Point the loader at temp cloud/local env files with distinct values."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                "OLLAMA_CLOUD_MODEL=qwen3.5:cloud",
                "OLLAMA_MODEL=gemma4",
                "EMBEDDING_PROVIDER=openai",
                "OLLAMA_BASE_URL=http://cloud-host:11434",
            ]
        )
    )
    (config_dir / "local.env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=ollama",
                "OLLAMA_MODEL=gemma4-local",
                "EMBEDDING_PROVIDER=ollama",
                "OLLAMA_BASE_URL=http://localhost:11434",
            ]
        )
    )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    return tmp_path


def test_mode_does_not_follow_provider(monkeypatch):
    monkeypatch.delenv("JARVIS_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    # No scope, no JARVIS_MODE -> cloud, even though provider is ollama.
    assert get_active_config_mode() == "cloud"


def test_explicit_mode_beats_scope_and_env(fake_configs, monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    with config_scope("local"):
        assert get_active_config_mode("cloud") == "cloud"


def test_scope_resolves_mode_over_env(fake_configs, monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    with config_scope("local"):
        assert get_active_config_mode() == "local"
    # After the scope the env default returns.
    assert get_active_config_mode() == "cloud"


def test_invalid_mode_raises(fake_configs):
    with pytest.raises(JarvisModeError):
        with config_scope("hybrid"):
            pass


def test_scope_overlays_values_without_mutating_environ(fake_configs, monkeypatch):
    monkeypatch.delenv("OLLAMA_CLOUD_MODEL", raising=False)
    with config_scope("cloud"):
        assert get_config_value("OLLAMA_CLOUD_MODEL") == "qwen3.5:cloud"
        assert get_config_value("EMBEDDING_PROVIDER") == "openai"
    # os.environ untouched by the scope.
    assert "OLLAMA_CLOUD_MODEL" not in os.environ


def test_get_config_value_priority(fake_configs, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "from-startup-environ")
    monkeypatch.setenv("JARVIS_OVERRIDE_OLLAMA_MODEL", "from-web-override")
    # Scoped request override wins over everything.
    with config_scope("local", overrides={"OLLAMA_MODEL": "from-request"}):
        assert get_config_value("OLLAMA_MODEL") == "from-request"
    # Without a scoped override, JARVIS_OVERRIDE wins over scoped config overlay.
    with config_scope("local"):
        assert get_config_value("OLLAMA_MODEL") == "from-web-override"
    monkeypatch.delenv("JARVIS_OVERRIDE_OLLAMA_MODEL", raising=False)
    # Then scoped config overlay wins over startup environ.
    with config_scope("local"):
        assert get_config_value("OLLAMA_MODEL") == "gemma4-local"
    # Outside any scope, startup environ is used.
    assert get_config_value("OLLAMA_MODEL") == "from-startup-environ"


def test_nested_load_config_in_scope_returns_scoped_values(fake_configs):
    before = dict(os.environ)
    with config_scope("cloud", overrides={"LLM_PROVIDER": "ollama"}):
        cfg = load_config()
        assert cfg["OLLAMA_CLOUD_MODEL"] == "qwen3.5:cloud"
        assert cfg["LLM_PROVIDER"] == "ollama"
        # load_config inside a scope must not rehydrate or alter globals.
    assert dict(os.environ) == before


def test_get_scoped_config_none_outside_scope(fake_configs):
    assert get_scoped_config() is None
    with config_scope("cloud"):
        merged = get_scoped_config()
        assert merged is not None
        assert merged["OLLAMA_CLOUD_MODEL"] == "qwen3.5:cloud"


def test_export_config_environment(fake_configs):
    before = dict(os.environ)
    child = export_config_environment("cloud", overrides={"LLM_PROVIDER": "ollama"})
    assert child["JARVIS_MODE"] == "cloud"
    assert child["OLLAMA_CLOUD_MODEL"] == "qwen3.5:cloud"
    assert child["LLM_PROVIDER"] == "ollama"
    # Parent environment is never mutated.
    assert dict(os.environ) == before


def test_export_includes_active_scoped_overrides(fake_configs):
    before = dict(os.environ)
    with config_scope("cloud", overrides={"IMAGE_TOOL_PROVIDER": "openai"}):
        child = export_config_environment("cloud")
        assert child["IMAGE_TOOL_PROVIDER"] == "openai"
        assert child["JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER"] == "openai"
    assert dict(os.environ) == before


def test_export_masks_values_owned_only_by_other_mode(fake_configs, monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "stale-cloud-model:cloud")
    child = export_config_environment("local")
    assert "OLLAMA_CLOUD_MODEL" not in child


def test_nested_override_scope_restores_outer_values(fake_configs):
    with config_scope("cloud", overrides={"FEEDBACK_RANDOM_ENABLED": "true"}):
        assert get_config_value("FEEDBACK_RANDOM_ENABLED") == "true"
        with config_override_scope({"FEEDBACK_RANDOM_ENABLED": "false"}):
            assert get_config_value("FEEDBACK_RANDOM_ENABLED") == "false"
        assert get_config_value("FEEDBACK_RANDOM_ENABLED") == "true"


def test_concurrent_scopes_do_not_leak(fake_configs):
    """Two contexts running concurrently must read distinct scoped values."""
    results = {}
    barrier = threading.Barrier(2)

    def run(mode, key):
        def worker():
            with config_scope(mode):
                barrier.wait()
                # Both threads read while the other's scope is also active.
                results[key] = {
                    "mode": get_active_config_mode(),
                    "model": get_config_value("OLLAMA_MODEL"),
                    "embedding": get_config_value("EMBEDDING_PROVIDER"),
                    "url": get_config_value("OLLAMA_BASE_URL"),
                }
                barrier.wait()

        # Each thread runs in its own copied context so the ContextVar is isolated.
        ctx = contextvars.copy_context()
        return threading.Thread(target=lambda: ctx.run(worker))

    t_cloud = run("cloud", "cloud")
    t_local = run("local", "local")
    t_cloud.start()
    t_local.start()
    t_cloud.join()
    t_local.join()

    assert results["cloud"]["mode"] == "cloud"
    assert results["cloud"]["model"] == "gemma4"
    assert results["cloud"]["embedding"] == "openai"
    assert results["cloud"]["url"] == "http://cloud-host:11434"

    assert results["local"]["mode"] == "local"
    assert results["local"]["model"] == "gemma4-local"
    assert results["local"]["embedding"] == "ollama"
    assert results["local"]["url"] == "http://localhost:11434"


def test_concurrent_request_overrides_isolated(fake_configs):
    results = {}
    barrier = threading.Barrier(2)

    def run(key, override):
        def worker():
            with config_scope("cloud", overrides={"JARVIS_OVERRIDE_X": override}):
                barrier.wait()
                results[key] = get_config_value("JARVIS_OVERRIDE_X")
                barrier.wait()

        ctx = contextvars.copy_context()
        return threading.Thread(target=lambda: ctx.run(worker))

    a = run("a", "image-a")
    b = run("b", "image-b")
    a.start()
    b.start()
    a.join()
    b.join()

    assert results["a"] == "image-a"
    assert results["b"] == "image-b"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
