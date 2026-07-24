"""Shared strict availability checks for deterministic workflows."""

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


def check_workflow_availability(
    workflow: dict[str, Any],
    *,
    available_tools: Iterable[str],
    excluded_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve whether every workflow tool is callable in the current context.

    This is intentionally strict: optional and conditional steps still count.
    A workflow is unavailable when any declared step tool is missing from the
    effective registry or blocked for the originating request surface.
    """
    tools = workflow_tool_names(workflow)
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
    blocked = [name for name in tools if name in excluded]
    unavailable = [
        name for name in tools
        if (name not in available or name in _WORKFLOW_META_TOOLS) and name not in excluded
    ]
    return {
        "available": not blocked and not unavailable,
        "workflow_id": workflow.get("id"),
        "tools": tools,
        "blocked_tools": blocked,
        "unavailable_tools": unavailable,
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
