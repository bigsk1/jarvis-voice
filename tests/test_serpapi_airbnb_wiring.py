"""Airbnb search honors selected-mode credentials and shipped travel profile boundaries."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from config_loader import config_scope
from tool_schema import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
TOOL = "serpapi_airbnb_search"


def copy_manifest(destination):
    (destination / f"{TOOL}.tool.json").write_text(
        (ROOT / "skills" / f"{TOOL}.tool.json").read_text()
    )


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("configured", [False, True])
def test_airbnb_registry_requires_selected_mode_key_and_keeps_location_out_of_child_env(
    tmp_path, mode, configured,
):
    copy_manifest(tmp_path)
    with (
        config_scope(mode, overrides={
            "JARVIS_TOOL_PROFILE": "default",
            "SERP_API_KEY": "test-only-key" if configured else "",
            "JARVIS_DEFAULT_POSTAL_CODE": "00000",
            "JARVIS_DEFAULT_LOCATION": "Unrelated home location",
        }),
        patch("tool_profiles.load_active_profile_overrides", return_value={}),
        patch("tool_profiles.warn_missing_profile_file"),
    ):
        registry = ToolRegistry(str(tmp_path))
    assert set(registry.list_tools()) == ({TOOL} if configured else set())
    if configured:
        schema = registry.get_tool(TOOL)
        assert schema is not None
        assert schema.child_environment_names == frozenset({"SERP_API_KEY"})
        assert schema.proxy_policy == "off"


@pytest.mark.parametrize("profile,enabled", [
    ("default.json", True),
    ("docker.json", True),
    ("docker-mcp.json", True),
    ("openai_only.json", False),
    *[(str(path.relative_to(ROOT / "skills" / "profiles")), False)
      for path in sorted((ROOT / "skills" / "profiles" / "examples").glob("*.json"))
      if json.loads(path.read_text())["overrides"].get("serpapi_trader_joes_search") is False],
])
def test_airbnb_registry_preserves_shipped_profile_policy(tmp_path, profile, enabled):
    copy_manifest(tmp_path)
    overrides = json.loads((ROOT / "skills" / "profiles" / profile).read_text())["overrides"]
    with (
        config_scope("cloud", overrides={"SERP_API_KEY": "test-only-key"}),
        patch("tool_profiles.load_active_profile_overrides", return_value=overrides),
        patch("tool_profiles.warn_missing_profile_file"),
    ):
        registry = ToolRegistry(str(tmp_path))
    assert set(registry.list_tools()) == ({TOOL} if enabled else set())


@pytest.mark.parametrize("title", ["Airbnb Search API degraded", "Airbnb API outage"])
def test_airbnb_failure_diagnostics_select_its_provider_engine(title):
    from serpapi_client import (
        SERPAPI_ENGINE_LABELS,
        find_serpapi_incident,
        serpapi_engines_for_tool,
    )

    engines = serpapi_engines_for_tool(TOOL)
    assert engines == ("airbnb",)
    assert SERPAPI_ENGINE_LABELS["airbnb"] == "Airbnb Search"
    incident = {"name": title, "status": "investigating"}
    assert find_serpapi_incident(engines, [incident]) == ("airbnb", incident)


def test_airbnb_executor_allows_provider_deadline_and_cleanup():
    from orchestrator.executor import ToolExecutor

    executor = ToolExecutor.__new__(ToolExecutor)
    assert executor._get_subprocess_timeout(TOOL, {}) == 90
