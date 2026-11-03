#!/usr/bin/env python3
"""Helpers for authoring Jarvis workflow JSON."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Workflow root must be a JSON object")
    return data


def _check_workflow(
    workflow: dict[str, Any], *, is_personal: bool = False
) -> tuple[list[str], list[str]]:
    from workflow_validation import validate_workflow_document

    diagnostics = validate_workflow_document(workflow)
    errors = [item["message"] for item in diagnostics["errors"]]
    warnings = [item["message"] for item in diagnostics["warnings"]]
    if is_personal:
        warnings = [message for message in warnings if not message.startswith("Shared workflows should define")]
    return errors, warnings


def validate_workflow(path: Path) -> int:
    try:
        workflow = _load_json(path)
    except Exception as exc:
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return 1

    errors, warnings = _check_workflow(
        workflow,
        is_personal=path.parent.name == "personal",
    )
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        return 1
    print(f"OK: {path}")
    return 0


def print_template(args: argparse.Namespace) -> int:
    workflow_id = args.id.strip()
    trigger = args.trigger.strip()
    workflow = {
        "id": workflow_id,
        "name": args.name or workflow_id.replace("_", " ").title(),
        "description": args.description or "TODO: describe what this workflow does.",
        "enabled": True,
        "version": "1.0",
        "triggers": {"explicit": [trigger]},
        "variables": {},
        "steps": [
            {
                "step": 1,
                "tool": "get_time",
                "params": {},
                "output_var": "time_info",
                "required": True,
                "description": "Capture current date and time",
            }
        ],
        "success_speech": "Workflow complete.",
        "abort_speech": "I couldn't complete the workflow.",
    }
    print(json.dumps(workflow, indent=2))
    return 0


def check_loader_scope() -> int:
    from workflow_loader import WorkflowLoader

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared.json").write_text(
            json.dumps(
                {
                    "id": "shared_workflow",
                    "triggers": {"explicit": ["/shared"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                }
            )
        )
        personal = root / "personal"
        personal.mkdir()
        (personal / "private.json").write_text(
            json.dumps(
                {
                    "id": "private_workflow",
                    "triggers": {"explicit": ["/private"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                }
            )
        )
        skill_dir = root / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n")
        (skill_dir / "sneaky.json").write_text(
            json.dumps(
                {
                    "id": "should_not_load",
                    "triggers": {"explicit": ["/sneaky"]},
                    "steps": [{"step": 1, "tool": "get_time"}],
                }
            )
        )

        loader = WorkflowLoader(str(root), explicit_only=True)
        loaded = set(loader.workflows)
        expected = {"shared_workflow", "private_workflow"}
        if loaded != expected:
            print(f"ERROR: loader scope mismatch: loaded={sorted(loaded)}", file=sys.stderr)
            return 1

    print("OK: WorkflowLoader ignores data/workflows/skill and loads only shared/personal JSON")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jarvis workflow authoring helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one workflow JSON file")
    validate_parser.add_argument("workflow", type=Path)

    template_parser = subparsers.add_parser("template", help="Print a minimal workflow template")
    template_parser.add_argument("--id", required=True)
    template_parser.add_argument("--trigger", required=True)
    template_parser.add_argument("--name")
    template_parser.add_argument("--description")

    subparsers.add_parser("check-loader-scope", help="Verify skill files are not workflow-loaded")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate_workflow(args.workflow)
    if args.command == "template":
        return print_template(args)
    if args.command == "check-loader-scope":
        return check_loader_scope()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
