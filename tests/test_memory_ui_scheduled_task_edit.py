"""Exercise the real scheduled-task edit handlers with delayed API responses."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "scenario",
    [
        "missing",
        "false",
        "true",
        "zero",
        "new",
        "slow-workflows",
        "new-slow-workflows",
        "workflow-error",
        "legacy-workflow-error",
        "changed-workflow-error",
        "new-workflow-error",
        "empty-workflows",
        "cancel-workflows",
        "stale-workflows",
        "slow-task",
        "slow-edit-catalog",
        "task-error",
        "cancel-task",
    ],
)
def test_scheduled_task_edit_behavior(scenario):
    subprocess.run(
        [
            "node",
            str(ROOT / "tests/fixtures/memory/scheduled-task-edit.cjs"),
            str(ROOT / "jarvis-memory/client/js/app.js"),
            scenario,
        ],
        cwd=ROOT,
        check=True,
        timeout=10,
    )
