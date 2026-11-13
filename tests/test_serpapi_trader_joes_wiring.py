"""Trader Joe's tools honor selected-mode credentials and shipped profile boundaries."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from config_loader import config_scope
from tool_schema import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"serpapi_trader_joes_search", "serpapi_trader_joes_product"}


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("configured", [False, True])
def test_trader_joes_registry_requires_selected_mode_key_and_limits_child_settings(
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
            "JARVIS_TRADER_JOES_STORE_ID": "1234",
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
            "SERP_API_KEY", "JARVIS_DEFAULT_POSTAL_CODE", "JARVIS_TRADER_JOES_STORE_ID",
        })
        assert schema.proxy_policy == "off"


@pytest.mark.parametrize("profile,enabled", [
    ("default.json", True),
    ("docker.json", True),
    ("docker-mcp.json", True),
    ("openai_only.json", False),
    *[(str(path.relative_to(ROOT / "skills" / "profiles")), False)
      for path in sorted((ROOT / "skills" / "profiles" / "examples").glob("*.json"))
      if json.loads(path.read_text())["overrides"].get("serpapi_walmart_search") is False],
])
def test_trader_joes_registry_keeps_shipped_shopping_profile_policy(tmp_path, profile, enabled):
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
def test_trader_joes_store_override_is_optional_in_each_public_mode_template(mode):
    template = (ROOT / "config" / f"{mode}.env.example").read_text()
    assert template.splitlines().count('JARVIS_TRADER_JOES_STORE_ID=""') == 1


@pytest.mark.parametrize("tool,engine,label", [
    ("serpapi_trader_joes_search", "trader_joes", "Trader Joe's Search"),
    ("serpapi_trader_joes_product", "trader_joes_product", "Trader Joe's Product"),
])
@pytest.mark.parametrize("apostrophe", ["'", "’", ""])
def test_trader_joes_failure_diagnostics_select_the_correct_provider_engine(
    tool, engine, label, apostrophe,
):
    from serpapi_client import (
        SERPAPI_ENGINE_LABELS,
        find_serpapi_incident,
        serpapi_engines_for_tool,
    )

    engines = serpapi_engines_for_tool(tool)
    assert engines == (engine,)
    assert SERPAPI_ENGINE_LABELS[engine] == label
    incident = {"name": f"{label.replace(chr(39), apostrophe)} API degraded",
                "status": "investigating"}
    assert find_serpapi_incident(engines, [incident]) == (engine, incident)


def test_trader_joes_executor_and_workflow_keep_search_and_detail_boundaries():
    from orchestrator.executor import ToolExecutor
    from orchestrator.pipeline_executor import PipelineExecutor

    executor = ToolExecutor.__new__(ToolExecutor)
    pipeline = PipelineExecutor.__new__(PipelineExecutor)
    for name in TOOLS:
        assert executor._get_subprocess_timeout(name, {}) == 90
    assert pipeline._is_search_tool("serpapi_trader_joes_search") is True
    assert pipeline._is_search_tool("serpapi_trader_joes_product") is False
