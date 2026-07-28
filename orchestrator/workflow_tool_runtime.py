#!/usr/bin/env python3
"""Compact discovery and foreground execution for the workflow meta-tool."""

from __future__ import annotations

import math
import re
from typing import Any

try:
    from .workflow_availability import (
        check_workflow_registry_availability,
        workflow_tool_names,
        workflow_unavailable_message,
    )
    from .workflow_loader import WorkflowLoader
except ImportError:
    from workflow_availability import (
        check_workflow_registry_availability,
        workflow_tool_names,
        workflow_unavailable_message,
    )
    from workflow_loader import WorkflowLoader


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _coerce_limit(value: Any, default: int = 6) -> int:
    if isinstance(value, bool) or value is None:
        parsed = default
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value) if math.isfinite(value) else default
    else:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            parsed = default
    return max(1, min(parsed, 20))


def _clean_text(value: Any, max_chars: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 15].rstrip() + "... [truncated]"


def _query_variables(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe workflow inputs derived from the single foreground query."""
    inputs: list[dict[str, Any]] = []
    variables = workflow.get("variables") or {}
    if not isinstance(variables, dict):
        return inputs

    for name, definition in variables.items():
        if not isinstance(definition, dict) or definition.get("from", "query") != "query":
            continue
        inputs.append(
            {
                "name": str(name),
                "extract": str(definition.get("extract", "main_subject")),
                "required": definition.get("default") is None,
                **(
                    {"default": definition.get("default")}
                    if definition.get("default") is not None
                    else {}
                ),
            }
        )
    return inputs


def _trigger_summary(workflow: dict[str, Any]) -> dict[str, list[str]]:
    triggers = workflow.get("triggers") or {}
    if not isinstance(triggers, dict):
        return {"explicit": [], "patterns": [], "keywords": []}
    return {
        key: [
            _clean_text(value, 100)
            for value in (triggers.get(key) or [])[:8]
            if str(value or "").strip()
        ]
        for key in ("explicit", "patterns", "keywords")
    }


def _workflow_summary(workflow: dict[str, Any], *, include_steps: bool = False) -> dict[str, Any]:
    query_inputs = _query_variables(workflow)
    summary: dict[str, Any] = {
        "workflow_id": str(workflow.get("id") or ""),
        "name": _clean_text(workflow.get("name") or workflow.get("id"), 120),
        "summary": _clean_text(workflow.get("description"), 280),
        "triggers": _trigger_summary(workflow),
        "query_inputs": query_inputs,
        "query_required": any(item["required"] for item in query_inputs),
        "step_count": len(workflow.get("steps") or []),
        "component_tools": workflow_tool_names(workflow),
        "available_now": True,
        "execution": "foreground",
    }
    if include_steps:
        summary["steps"] = [
            {
                "step": step.get("step", index),
                "tool": str(step.get("tool") or ""),
                **({"action": step.get("action")} if step.get("action") else {}),
                **(
                    {"description": _clean_text(step.get("description"), 180)}
                    if step.get("description")
                    else {}
                ),
            }
            for index, step in enumerate(workflow.get("steps") or [], 1)
        ]
    return summary


def _search_score(query: str, workflow: dict[str, Any]) -> float:
    query_lower = query.lower().strip()
    query_tokens = set(_TOKEN_RE.findall(query_lower))
    if not query_tokens:
        return 0.0

    workflow_id = str(workflow.get("id") or "").lower()
    name = str(workflow.get("name") or "").lower()
    description = str(workflow.get("description") or "").lower()
    triggers = workflow.get("triggers") or {}
    trigger_text = " ".join(
        str(item)
        for key in ("explicit", "patterns", "keywords")
        for item in (triggers.get(key) or [])
    ).lower()
    tool_text = " ".join(workflow_tool_names(workflow)).lower()

    fields = [
        (workflow_id, 7.0),
        (name, 6.0),
        (trigger_text, 5.0),
        (description, 3.0),
        (tool_text, 1.5),
    ]
    score = 0.0
    for text, weight in fields:
        tokens = set(_TOKEN_RE.findall(text))
        score += len(query_tokens & tokens) * weight
        if query_lower and query_lower in text:
            score += weight * 3
    return score


def _resolve_workflow(loader: WorkflowLoader, workflow_id: Any) -> dict[str, Any] | None:
    requested = str(workflow_id or "").strip()
    if not requested:
        return None
    exact = loader.get_workflow(requested)
    if exact:
        return exact
    lowered = requested.lower()
    return next(
        (
            workflow
            for workflow in loader.workflows.values()
            if str(workflow.get("id") or "").lower() == lowered
        ),
        None,
    )


def _allows_workflow_tool(workflow: dict[str, Any]) -> bool:
    """Return False only for an explicit workflow meta-tool opt-out."""
    return workflow.get("allow_workflow_tool", True) is not False


def _available_workflows(loader: WorkflowLoader, registry, excluded_tools) -> list[dict[str, Any]]:
    loader.reload()
    return [
        workflow
        for workflow in loader.workflows.values()
        if _allows_workflow_tool(workflow)
        and check_workflow_registry_availability(
            workflow,
            registry,
            excluded_tools=excluded_tools,
        )["available"]
    ]


def _error(message: str, **data: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "speech": message,
        "error": message,
        "data": data,
    }


def execute_workflow_tool(
    *,
    registry,
    args: dict[str, Any],
    mode: str,
    excluded_tools=None,
    loader: WorkflowLoader | None = None,
    pipeline_executor=None,
    tool_executor=None,
    status_callback=None,
) -> dict[str, Any]:
    """
    Search, describe, or synchronously run a workflow.

    Discovery is rebuilt from shared plus personal workflow files for every
    call. Every returned workflow must allow the workflow meta-tool and pass
    the same effective-registry availability gate used by slash commands and
    scheduled workflows.
    """
    loader = loader or WorkflowLoader(explicit_only=True)
    action = str(args.get("action") or "").strip().lower()
    excluded = {
        str(name).strip()
        for name in (excluded_tools or [])
        if str(name).strip()
    }

    if action == "search":
        query = str(args.get("query") or "").strip()
        limit = _coerce_limit(args.get("limit"))
        workflows = _available_workflows(loader, registry, excluded)
        if query:
            ranked = sorted(
                (
                    (_search_score(query, workflow), workflow)
                    for workflow in workflows
                ),
                key=lambda item: (-item[0], str(item[1].get("name") or item[1].get("id")).lower()),
            )
            matches = [
                _workflow_summary(workflow)
                for score, workflow in ranked
                if score > 0
            ][:limit]
            search_mode = "metadata"
        else:
            matches = [
                _workflow_summary(workflow)
                for workflow in sorted(
                    workflows,
                    key=lambda item: str(item.get("name") or item.get("id")).lower(),
                )[:limit]
            ]
            search_mode = "browse"

        selected = [item["workflow_id"] for item in matches]
        speech = (
            f"I found {len(matches)} runnable workflows: "
            + ", ".join(item["name"] for item in matches)
            + "."
            if matches
            else "I couldn't find a matching workflow that is runnable in the current mode and tool profile."
        )
        return {
            "ok": True,
            "speech": speech,
            "data": {
                "action": "search",
                "query": query,
                "matches": matches,
                "selected_workflow_hints": selected,
                "count": len(matches),
                "search_space": len(workflows),
                "search_mode": search_mode,
            },
        }

    if action not in {"describe", "run"}:
        return _error(
            "Workflow action must be search, describe, or run.",
            action=action,
        )

    workflow = _resolve_workflow(loader, args.get("workflow_id"))
    if not workflow:
        return _error(
            "That workflow was not found.",
            action=action,
            workflow_id=str(args.get("workflow_id") or ""),
        )
    if not _allows_workflow_tool(workflow):
        return _error(
            "That workflow is not available through the workflow tool. "
            "Use its explicit command, API endpoint, or scheduled task instead.",
            action=action,
            workflow_id=workflow.get("id"),
            allow_workflow_tool=False,
        )

    availability = check_workflow_registry_availability(
        workflow,
        registry,
        excluded_tools=excluded,
    )
    if not availability["available"]:
        message = workflow_unavailable_message(workflow, availability)
        return _error(
            message,
            action=action,
            workflow_id=workflow.get("id"),
            availability=availability,
        )

    if action == "describe":
        return {
            "ok": True,
            "speech": (
                f"{workflow.get('name') or workflow.get('id')} is runnable now "
                f"and has {len(workflow.get('steps') or [])} steps."
            ),
            "data": {
                "action": "describe",
                "workflow": _workflow_summary(workflow, include_steps=True),
                "selected_workflow_hints": [workflow.get("id")],
            },
        }

    query = str(args.get("query") or "").strip()
    required_inputs = [item["name"] for item in _query_variables(workflow) if item["required"]]
    if required_inputs and not query:
        return _error(
            "This workflow needs a query before it can run.",
            action="run",
            workflow_id=workflow.get("id"),
            required_query_inputs=required_inputs,
        )

    if pipeline_executor is None:
        if tool_executor is None:
            from executor import ToolExecutor

            tool_executor = ToolExecutor(mode=mode, registry=registry)
            tool_executor.set_excluded_tools(sorted(excluded))
        from pipeline_executor import PipelineExecutor

        pipeline_executor = PipelineExecutor(mode, tool_executor)

    explicit_triggers = (workflow.get("triggers") or {}).get("explicit") or []
    command = str(explicit_triggers[0]).strip() if explicit_triggers else ""
    execution_query = " ".join(part for part in (command, query) if part).strip()
    if not execution_query:
        execution_query = query

    result = pipeline_executor.execute(
        workflow,
        execution_query,
        status_callback=status_callback,
    )
    result_data = dict(result.get("data") or {})
    result_data.update(
        {
            "action": "run",
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name") or workflow.get("id"),
            "workflow_metadata": _workflow_summary(workflow),
            "component_tools_used": list(result.get("tools_used") or []),
            "execution": "foreground",
            "workflow_started": True,
            "workflow_executed": True,
            "workflow_completed": bool(result.get("ok")) and not bool(result.get("cancelled")),
        }
    )
    response = {
        "ok": bool(result.get("ok")),
        "speech": result.get("speech") or "Workflow complete.",
        "data": result_data,
        "tools_used": list(result.get("tools_used") or []),
    }
    for key in ("error", "usage", "server_side_tools", "cancelled"):
        if result.get(key) is not None:
            response[key] = result[key]
    return response
