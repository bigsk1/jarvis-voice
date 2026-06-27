"""Tests for canonical Jarvis startup-environment mode resolution."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from jarvis_mode import (
    JarvisModeError,
    cloud_missing_local_hint,
    env_file_for_mode,
    require_local_config,
    resolve_jarvis_mode,
)


def test_defaults_to_cloud(monkeypatch):
    monkeypatch.delenv("JARVIS_MODE", raising=False)
    assert resolve_jarvis_mode() == "cloud"


def test_environment_mode_is_honored(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    assert resolve_jarvis_mode() == "local"


def test_explicit_mode_beats_environment(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")
    assert resolve_jarvis_mode("cloud") == "cloud"


@pytest.mark.parametrize("explicit,environment", [("locla", None), (None, "hybrid")])
def test_invalid_mode_never_falls_back(monkeypatch, explicit, environment):
    if environment is None:
        monkeypatch.delenv("JARVIS_MODE", raising=False)
    else:
        monkeypatch.setenv("JARVIS_MODE", environment)
    with pytest.raises(JarvisModeError, match="expected 'cloud' or 'local'"):
        resolve_jarvis_mode(explicit)


def test_provider_settings_do_not_select_startup_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen:cloud")
    (tmp_path / ".env").write_text("JARVIS_MODE=local\n")
    assert resolve_jarvis_mode() == "cloud"


def test_env_file_and_local_contract(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    assert env_file_for_mode("local", tmp_path) == config / "local.env"
    with pytest.raises(JarvisModeError, match="config/local.env"):
        require_local_config("local", tmp_path)
    (config / "local.env").write_text("WEBUI_PASSWORD=test\n")
    assert require_local_config("local", tmp_path) == config / "local.env"


def test_cloud_remains_non_strict_and_local_only_hint_is_available(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "local.env").write_text("")
    assert require_local_config("cloud", tmp_path) == config / "cloud.env"
    assert "./bin/start --local" in cloud_missing_local_hint(tmp_path)


def test_missing_local_config_points_to_existing_cloud_config(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "cloud.env").write_text("")
    with pytest.raises(JarvisModeError, match="existing config/cloud.env"):
        require_local_config("local", tmp_path)
