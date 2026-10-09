"""Concurrent first requests share a registry; mode changes clean its clients."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import tool_schema  # noqa: E402


@pytest.fixture
def registries(monkeypatch):
    created = []
    def create(*_):
        registry = Mock()
        created.append(registry)
        return registry
    monkeypatch.setattr(tool_schema, "ToolRegistry", create)
    monkeypatch.setattr(tool_schema, "_tool_registry_instance", None)
    monkeypatch.setattr(tool_schema, "_tool_registry_mode", None)
    return created


def test_mode_change_cleans_only_previous_registry(registries):
    cloud = tool_schema.get_tool_registry("skills", "config", mode="cloud")
    assert tool_schema.get_tool_registry("skills", "config", mode="cloud") is cloud
    local = tool_schema.get_tool_registry("skills", "config", mode="local")
    cloud.cleanup.assert_called_once()
    local.cleanup.assert_not_called()
    assert len(registries) == 2
    tool_schema.reset_tool_registry()
    local.cleanup.assert_called_once()
    assert tool_schema._tool_registry_instance is None


def test_concurrent_first_requests_do_not_create_duplicate_registries(registries, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    entered, release, second_entered = Event(), Event(), Event()
    original = tool_schema.ToolRegistry
    def create(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)
    monkeypatch.setattr(tool_schema, "ToolRegistry", create)
    def get_second():
        second_entered.set()
        return tool_schema.get_tool_registry("skills", "config", mode="cloud")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(tool_schema.get_tool_registry, "skills", "config", mode="cloud")
        assert entered.wait(1)
        second = pool.submit(get_second)
        try:
            assert second_entered.wait(1)
            with pytest.raises(TimeoutError):
                second.result(timeout=.05)
        finally:
            release.set()
        assert first.result(timeout=1) is second.result(timeout=1)
    assert len(registries) == 1
