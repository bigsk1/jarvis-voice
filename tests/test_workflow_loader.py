#!/usr/bin/env python3
"""Workflow discovery regressions."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from workflow_loader import WorkflowLoader  # noqa: E402


def _write_workflow(path: Path, workflow_id: str, trigger: str, tool: str = "get_time"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": workflow_id,
                "name": workflow_id.replace("_", " ").title(),
                "enabled": True,
                "triggers": {"explicit": [trigger]},
                "steps": [{"step": 1, "tool": tool, "params": {}}],
            }
        )
    )


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
