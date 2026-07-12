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
