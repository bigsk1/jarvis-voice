"""Walmart tools honor selected-mode credentials and shipped profile boundaries."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from config_loader import config_scope
from tool_schema import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"serpapi_walmart_search", "serpapi_walmart_product"}


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("configured", [False, True])
def test_walmart_registry_requires_selected_mode_key_and_limits_child_settings(
    tmp_path, mode, configured,
):
    for name in TOOLS:
        (tmp_path / f"{name}.tool.json").write_text(
            (ROOT / "skills" / f"{name}.tool.json").read_text()
        )
    with (
        config_scope(mode, overrides={
            "JARVIS_TOOL_PROFILE": "default",
            "SERP_API_KEY": "test-only-key" if configured else "",
            "JARVIS_DEFAULT_POSTAL_CODE": "00000",
            "JARVIS_WALMART_STORE_ID": "1234",
        }),
        patch("tool_profiles.load_active_profile_overrides", return_value={}),
        patch("tool_profiles.warn_missing_profile_file"),
    ):
        registry = ToolRegistry(str(tmp_path))
    assert set(registry.list_tools()) == (TOOLS if configured else set())
    for name in registry.list_tools():
        schema = registry.get_tool(name)
        assert schema is not None
        assert schema.child_environment_names == frozenset({
            "SERP_API_KEY", "JARVIS_DEFAULT_POSTAL_CODE", "JARVIS_WALMART_STORE_ID",
        })
        assert schema.proxy_policy == "off"


@pytest.mark.parametrize("profile,enabled", [
    ("default.json", True),
    ("docker.json", True),
    ("docker-mcp.json", True),
    ("openai_only.json", False),
    ("examples/offline.json", False),
    ("examples/offline_lan_first.json", False),
    ("examples/research_pipeline.json", False),
])
def test_walmart_registry_keeps_shipped_shopping_profile_policy(tmp_path, profile, enabled):
    for name in TOOLS:
        (tmp_path / f"{name}.tool.json").write_text(
            (ROOT / "skills" / f"{name}.tool.json").read_text()
        )
    overrides = json.loads((ROOT / "skills" / "profiles" / profile).read_text())["overrides"]
    with (
        config_scope("cloud", overrides={"SERP_API_KEY": "test-only-key"}),
        patch("tool_profiles.load_active_profile_overrides", return_value=overrides),
        patch("tool_profiles.warn_missing_profile_file"),
    ):
        registry = ToolRegistry(str(tmp_path))
    assert set(registry.list_tools()) == (TOOLS if enabled else set())


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_walmart_store_override_is_optional_in_each_public_mode_template(mode):
    template = (ROOT / "config" / f"{mode}.env.example").read_text()
    assert template.splitlines().count('JARVIS_WALMART_STORE_ID=""') == 1


@pytest.mark.parametrize("tool,engine,label", [
    ("serpapi_walmart_search", "walmart", "Walmart Search"),
    ("serpapi_walmart_product", "walmart_product", "Walmart Product"),
])
def test_walmart_failure_diagnostics_select_the_correct_provider_engine(tool, engine, label):
    from serpapi_client import (
        SERPAPI_ENGINE_LABELS,
        find_serpapi_incident,
        serpapi_engines_for_tool,
    )

    engines = serpapi_engines_for_tool(tool)
    assert engines == (engine,)
    assert SERPAPI_ENGINE_LABELS[engine] == label
    incident = {"name": f"{label} API degraded", "status": "investigating"}
    assert find_serpapi_incident(engines, [incident]) == (engine, incident)
