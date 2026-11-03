#!/usr/bin/env python3
"""Workflow discovery regressions."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from workflow_loader import WorkflowLoader  # noqa: E402


def _write_workflow(path: Path, workflow_id: str, trigger, tool: str = "get_time"):
    explicit = trigger if isinstance(trigger, list) else [trigger]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": workflow_id,
                "name": workflow_id.replace("_", " ").title(),
                "enabled": True,
                "triggers": {"explicit": explicit},
                "steps": [{"step": 1, "tool": tool, "params": {}}],
            }
        )
    )


def test_serpapi_amazon_workflow_uses_canonical_trigger():
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)
    workflow = loader.get_workflow("serpapi_amazon_search")

    assert workflow is not None
    assert loader.get_workflow("serpapi_search") is None
    assert workflow["steps"][0]["tool"] == "serpapi_amazon_search"
    assert loader.match("/serpapi_amazon usb c charger")["id"] == "serpapi_amazon_search"


def test_shared_workflows_each_have_one_canonical_trigger():
    for path in sorted((ROOT / "data" / "workflows").glob("*.json")):
        workflow = json.loads(path.read_text())
        explicit = workflow.get("triggers", {}).get("explicit", [])
        assert len(explicit) == 1, f"{path.name} has non-canonical triggers: {explicit}"


@pytest.mark.parametrize(
    "query",
    [
        "/dive https://example.com",
        "/daily",
        "/garden_watch",
        "/serpapi headphones",
        "/what_to_watch funny and short",
    ],
)
def test_retired_shared_aliases_no_longer_match(query):
    loader = WorkflowLoader(str(ROOT / "data" / "workflows"), explicit_only=True)

    assert loader.match(query) is None


def test_loader_supports_deliberate_temporary_compatibility_aliases(tmp_path):
    _write_workflow(
        tmp_path / "renamed.json",
        "renamed_workflow",
        ["/canonical", "/legacy_compat"],
    )
    loader = WorkflowLoader(str(tmp_path), explicit_only=True)

    assert loader.match("/canonical run it")["id"] == "renamed_workflow"
    assert loader.match("/legacy_compat run it")["id"] == "renamed_workflow"


def test_workflow_loader_includes_gitignored_personal_workflows(tmp_path):
    _write_workflow(tmp_path / "shared.json", "shared_workflow", "/shared")
    _write_workflow(
        tmp_path / "personal" / "private.json",
        "private_workflow",
        "/private",
    )

    loader = WorkflowLoader(str(tmp_path), explicit_only=True)

    assert set(loader.workflows) == {"shared_workflow", "private_workflow"}
    assert loader.get_workflow("private_workflow")["triggers"]["explicit"] == ["/private"]
    assert loader.match("/private run it")["id"] == "private_workflow"


def test_personal_workflow_overrides_shared_workflow_id(tmp_path):
    _write_workflow(
        tmp_path / "radar.json",
        "github_ai_radar_daily",
        "/github_ai_radar",
        tool="get_time",
    )
    _write_workflow(
        tmp_path / "personal" / "radar.json",
        "github_ai_radar_daily",
        "/my_private_radar",
        tool="canvas",
    )

    loader = WorkflowLoader(str(tmp_path), explicit_only=True)
    workflow = loader.get_workflow("github_ai_radar_daily")

    assert workflow["triggers"]["explicit"] == ["/my_private_radar"]
    assert workflow["steps"][0]["tool"] == "canvas"
    assert loader.match("/my_private_radar")["id"] == "github_ai_radar_daily"


def test_workflow_loader_ignores_skill_folder(tmp_path):
    _write_workflow(tmp_path / "shared.json", "shared_workflow", "/shared")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: workflow-builder\ndescription: Workflow helper\n---\n"
    )
    _write_workflow(skill_dir / "sneaky.json", "should_not_load", "/sneaky")

    loader = WorkflowLoader(str(tmp_path), explicit_only=True)

    assert set(loader.workflows) == {"shared_workflow"}
    assert loader.get_workflow("should_not_load") is None
    assert loader.match("/sneaky") is None


def test_disabled_personal_definition_preserves_shared_runtime_behavior(tmp_path):
    import json

    _write_workflow(tmp_path / "shared.json", "same", "/shared")
    personal = tmp_path / "personal" / "arbitrary_filename.json"
    _write_workflow(personal, "same", "/personal")
    disabled = json.loads(personal.read_text())
    disabled["enabled"] = False
    personal.write_text(json.dumps(disabled))
    loader = WorkflowLoader(str(tmp_path))
    assert loader.get_workflow("same")["triggers"]["explicit"] == ["/shared"]
    assert loader.match("/shared") is not None
    personal.unlink()
    assert WorkflowLoader(str(tmp_path)).get_workflow("same")["triggers"]["explicit"] == ["/shared"]


def test_new_loader_sees_published_edits_and_removed_recipes(tmp_path):
    target = tmp_path / "not_the_workflow_id.json"
    _write_workflow(target, "fresh", "/before")
    loader = WorkflowLoader(str(tmp_path))
    original = loader.get_workflow("fresh")
    _write_workflow(target, "fresh", "/after")
    fresh = WorkflowLoader(str(tmp_path))
    assert fresh.match("/after") is not None
    assert fresh.match("/before") is None
    assert original["triggers"]["explicit"] == ["/before"]
    target.unlink()
    assert WorkflowLoader(str(tmp_path)).list_workflows() == []
