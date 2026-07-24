#!/usr/bin/env python3
"""Compact workflow execution context for reflection and feedback grading."""

from __future__ import annotations

import json
from typing import Any


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _stable_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def extract_workflow_learning_context(
    result: dict[str, Any] | None,
    tools_used: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Return a bounded, deterministic summary of a workflow interaction.

    Autonomous orchestration records the outer ``workflow`` tool while the
    recipe's component tools live inside ``data.workflow``. Keeping this
    summary separate prevents reflection and feedback LLMs from confusing
    discovery calls or recipe-owned steps with normal router-selected tools.
    """
    if not isinstance(result, dict):
        return None

    used = _stable_strings(list(tools_used or result.get("tools_used") or []))
    data = result.get("data")
    data = data if isinstance(data, dict) else {}
    workflow_entries = _dict_items(data.get("workflow"))
    tool_trace = [
        item
        for item in (result.get("tool_trace") or [])
        if isinstance(item, dict) and item.get("tool") == "workflow"
    ]

    explicit_workflow_id = str(result.get("workflow_executed") or "").strip()
    is_autonomous = "workflow" in used or bool(workflow_entries) or bool(tool_trace)
    is_explicit = bool(explicit_workflow_id) and not is_autonomous
    if not is_autonomous and not is_explicit:
        return None

    actions: list[str] = []
    workflow_ids: list[str] = []
    workflow_names: list[str] = []
    workflow_metadata: list[dict[str, Any]] = []
    component_tools: list[str] = []
    step_outcomes: list[dict[str, Any]] = []
    started = False
    completed = False
    cancelled = bool(result.get("cancelled"))

    for entry in workflow_entries:
        action = str(entry.get("action") or "").strip().lower()
        if action:
            actions.append(action)
        workflow_ids.append(entry.get("workflow_id"))
        workflow_names.append(entry.get("workflow_name"))
        workflow_metadata.extend(_dict_items(entry.get("matches")))
        workflow_metadata.extend(_dict_items(entry.get("workflow")))
        workflow_metadata.extend(_dict_items(entry.get("workflow_metadata")))
        component_tools.extend(entry.get("component_tools_used") or [])
        started = started or bool(entry.get("workflow_started"))
        completed = completed or bool(entry.get("workflow_completed"))
        cancelled = cancelled or bool(entry.get("cancelled"))

        for step in _dict_items(entry.get("results"))[:20]:
            step_outcomes.append(
                {
                    "step": step.get("step"),
                    "tool": step.get("tool"),
                    "ok": bool(step.get("ok")),
                    **(
                        {"error": str(step.get("error"))[:240]}
                        if step.get("error")
                        else {}
                    ),
                }
            )

    for trace in tool_trace:
        arguments = trace.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        action = str(arguments.get("action") or "").strip().lower()
        if action:
            actions.append(action)
        workflow_ids.append(arguments.get("workflow_id"))
        started = started or bool(trace.get("workflow_run_started"))

    if is_explicit:
        workflow_ids.append(explicit_workflow_id)
        actions.append("run")
        component_tools.extend(used)
        started = True
        completed = bool(result.get("ok")) and not cancelled

    action_sequence = _stable_strings(actions)
    ids = _stable_strings(workflow_ids)
    names = _stable_strings(workflow_names)
    components = _stable_strings(component_tools)
    selected_workflow_id = ids[-1] if ids else None
    selected_metadata = next(
        (
            item
            for item in reversed(workflow_metadata)
            if str(item.get("workflow_id") or "").strip() == selected_workflow_id
        ),
        {},
    )
    selected_name = str(selected_metadata.get("name") or "").strip()
    selected_summary = str(selected_metadata.get("summary") or "").strip()
    selected_triggers = selected_metadata.get("triggers")
    if not isinstance(selected_triggers, dict):
        selected_triggers = {}
    selected_query_inputs = _dict_items(selected_metadata.get("query_inputs"))

    return {
        "is_workflow_interaction": True,
        "invocation": "autonomous_meta_tool" if is_autonomous else "explicit_slash",
        "actions": action_sequence,
        "selected_workflow_id": selected_workflow_id,
        "selected_workflow_name": selected_name or (names[-1] if names else None),
        "selected_workflow_summary": selected_summary or None,
        "selected_workflow_triggers": {
            key: _stable_strings(list(selected_triggers.get(key) or []))[:8]
            for key in ("explicit", "patterns", "keywords")
        },
        "selected_workflow_query_inputs": selected_query_inputs[:12],
        "run_started": started,
        "run_completed": completed,
        "cancelled": cancelled,
        "outcome_success": bool(result.get("ok")),
        "component_tools_used": components,
        "component_order_owner": "deterministic_workflow_recipe",
        "step_outcomes": step_outcomes,
    }


def format_workflow_learning_context(context: dict[str, Any] | None) -> str:
    """Format a workflow summary for bounded prompt injection."""
    if not context:
        return "(not a workflow interaction)"
    return json.dumps(context, ensure_ascii=False, default=str)[:5000]


def completed_workflow_id(
    result: dict[str, Any] | None,
    tools_used: list[str] | None = None,
) -> str | None:
    """Return the selected workflow ID only for a completed successful run."""
    context = extract_workflow_learning_context(result, tools_used)
    if not context:
        return None
    if not context.get("run_started") or not context.get("run_completed"):
        return None
    if context.get("cancelled") or not context.get("outcome_success"):
        return None
    return str(context.get("selected_workflow_id") or "").strip() or None
