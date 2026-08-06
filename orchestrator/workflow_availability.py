"""Shared availability checks for deterministic workflows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


_WORKFLOW_META_TOOLS = frozenset({"workflow"})


def workflow_tool_names(workflow: dict[str, Any]) -> list[str]:
    """Return unique workflow step tools in declaration order."""
    names: list[str] = []
    for step in workflow.get("steps", []):
        name = str(step.get("tool") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def workflow_tool_requirements(
    workflow: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Return required and explicitly optional tools in declaration order.

    A tool used by any required step remains required even when another step
    marks the same tool optional. Recursive ``workflow`` steps are always
    treated as required so the existing recursion guard cannot be bypassed.
    """
    required: list[str] = []
    optional: list[str] = []
    for step in workflow.get("steps", []):
        name = str(step.get("tool") or "").strip()
        if not name:
            continue
        is_required = (
            name in _WORKFLOW_META_TOOLS
            or step.get("required", True) is not False
        )
        if is_required:
            if name not in required:
                required.append(name)
            if name in optional:
                optional.remove(name)
        elif name not in required and name not in optional:
            optional.append(name)
    return required, optional


def check_workflow_availability(
    workflow: dict[str, Any],
    *,
    available_tools: Iterable[str],
    excluded_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve whether every required workflow tool is callable in this context.

    Required and conditional-required steps remain strict. A step explicitly
    marked ``required: false`` may be unavailable or blocked without making the
    whole workflow unavailable; the pipeline records and skips it at runtime.
    """
    tools = workflow_tool_names(workflow)
    required_tools, optional_tools = workflow_tool_requirements(workflow)
    available = {
        str(name).strip()
        for name in available_tools
        if str(name).strip()
    }
    excluded = {
        str(name).strip()
        for name in (excluded_tools or [])
        if str(name).strip()
    }
    blocked = [name for name in required_tools if name in excluded]
    unavailable = [
        name for name in required_tools
        if (name not in available or name in _WORKFLOW_META_TOOLS)
        and name not in excluded
    ]
    optional_blocked = [name for name in optional_tools if name in excluded]
    optional_unavailable = [
        name for name in optional_tools
        if name not in available and name not in excluded
    ]
    skipped_optional_set = set(optional_blocked + optional_unavailable)
    skipped_optional = [
        name
        for name in tools
        if name in skipped_optional_set
    ]
    return {
        "available": not blocked and not unavailable,
        "degraded": bool(skipped_optional),
        "workflow_id": workflow.get("id"),
        "tools": tools,
        "required_tools": required_tools,
        "optional_tools": optional_tools,
        "blocked_tools": blocked,
        "unavailable_tools": unavailable,
        "optional_blocked_tools": optional_blocked,
        "optional_unavailable_tools": optional_unavailable,
        "optional_tools_skipped": skipped_optional,
    }


def check_workflow_registry_availability(
    workflow: dict[str, Any],
    registry,
    *,
    excluded_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Check a workflow against one effective ToolRegistry."""
    return check_workflow_availability(
        workflow,
        available_tools=registry.list_tools(),
        excluded_tools=excluded_tools,
    )


def workflow_unavailable_message(
    workflow: dict[str, Any],
    availability: dict[str, Any],
) -> str:
    """Build a concise user-facing explanation for a blocked workflow."""
    name = workflow.get("name") or workflow.get("id") or "Workflow"
    reasons: list[str] = []
    blocked = availability.get("blocked_tools") or []
    unavailable = availability.get("unavailable_tools") or []
    if blocked:
        reasons.append(f"blocked for this request: {', '.join(blocked)}")
    if unavailable:
        reasons.append(f"disabled or unavailable: {', '.join(unavailable)}")
    reason = "; ".join(reasons) or "one or more workflow tools are unavailable"
    return f"{name} is unavailable because its tool set is not fully enabled ({reason})."
