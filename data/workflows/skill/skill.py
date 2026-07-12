#!/usr/bin/env python3
"""Helpers for authoring Jarvis workflow JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))


ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Workflow root must be a JSON object")
    return data


def _check_workflow(workflow: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    workflow_id = workflow.get("id")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        errors.append("Missing string field: id")
    elif not ID_RE.match(workflow_id):
        errors.append("id should use lowercase letters, digits, and underscores")

    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        steps = []

    triggers = workflow.get("triggers", {})
    explicit = triggers.get("explicit", []) if isinstance(triggers, dict) else []
    if not isinstance(explicit, list) or not explicit:
        warnings.append("Add triggers.explicit so the workflow can be invoked predictably")
    else:
        for trigger in explicit:
            if not isinstance(trigger, str) or not trigger.startswith("/") or " " in trigger:
                errors.append(f"Invalid explicit trigger: {trigger!r}")

    seen_step_numbers: set[int] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"Step {index} must be an object")
            continue

        step_num = step.get("step", index)
        if isinstance(step_num, int):
            if step_num in seen_step_numbers:
                errors.append(f"Duplicate step number: {step_num}")
            seen_step_numbers.add(step_num)
        else:
            errors.append(f"Step {index} has non-integer step value")

        tool = step.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            errors.append(f"Step {step_num}: missing tool")

        action = step.get("action")
        validation = step.get("llm_output_validation")
        if step.get("llm_prompt") and not isinstance(validation, dict):
            warnings.append(f"Step {step_num}: llm_prompt should usually define llm_output_validation")

        if tool == "canvas" and action in {"create", "update"} and step.get("llm_prompt"):
            if not isinstance(validation, dict):
                errors.append(f"Step {step_num}: Canvas {action} with llm_prompt needs validation")
            else:
                rejects = {str(item).lower() for item in validation.get("reject_patterns", [])}
                for pattern in ("```", "<html", "<pre", "https://..."):
                    if pattern not in rejects:
                        warnings.append(f"Step {step_num}: consider rejecting {pattern!r} in Canvas output")

        params = step.get("params", {})
        if (
            tool == "canvas"
            and action == "update"
            and isinstance(params, dict)
            and params.get("allow_content_shrink") is True
        ):
            required = validation.get("required_patterns", []) if isinstance(validation, dict) else []
            if len(required) < 3:
                errors.append(
                    f"Step {step_num}: allow_content_shrink=true requires strong required_patterns"
                )

    if workflow.get("disable_server_side_tools") is True:
        llm_steps = [step for step in steps if isinstance(step, dict) and step.get("llm_prompt")]
        if not llm_steps:
            warnings.append("disable_server_side_tools=true has no llm_prompt steps to protect")

    return errors, warnings


def validate_workflow(path: Path) -> int:
    try:
        workflow = _load_json(path)
    except Exception as exc:
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return 1

    errors, warnings = _check_workflow(workflow)
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
