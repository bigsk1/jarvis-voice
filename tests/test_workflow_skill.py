#!/usr/bin/env python3
"""Repo-tracked workflow skill helper tests."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_HELPER = ROOT / "data" / "workflows" / "skill" / "skill.py"


def test_workflow_skill_template_outputs_valid_workflow_json():
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_HELPER),
            "template",
            "--id",
            "sample_workflow",
            "--trigger",
            "/sample",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = json.loads(result.stdout)
    assert workflow["id"] == "sample_workflow"
    assert workflow["triggers"]["explicit"] == ["/sample"]
    assert workflow["steps"][0]["tool"] == "get_time"


def test_workflow_skill_check_loader_scope():
    result = subprocess.run(
        [sys.executable, str(SKILL_HELPER), "check-loader-scope"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "WorkflowLoader ignores" in result.stdout


def test_workflow_skill_accepts_deterministic_canvas_shrink_update(tmp_path):
    workflow_path = tmp_path / "self_check.json"
    workflow_path.write_text(
        json.dumps(
            {
                "id": "self_check",
                "triggers": {"explicit": ["/self_check"]},
                "steps": [
                    {
                        "step": 1,
                        "tool": "canvas",
                        "action": "update",
                        "params": {
                            "page_id": "page_test",
                            "allow_content_shrink": True,
                            "content": "# Status\n\n## Current Status\nOK\n\n## Run Log\n- now",
                        },
                    }
                ],
            }
        )
    )

    result = subprocess.run(
        [sys.executable, str(SKILL_HELPER), "validate", str(workflow_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "OK:" in result.stdout
