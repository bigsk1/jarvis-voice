#!/usr/bin/env python3
"""Workflow attribution regressions for reflection and feedback."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from workflow_learning import (  # noqa: E402
    completed_workflow_id,
    extract_workflow_learning_context,
)


def _autonomous_result(*, completed: bool = True) -> dict:
    return {
        "ok": completed,
        "tools_used": ["workflow", "workflow"],
        "data": {
            "workflow": [
                {
                    "action": "search",
                    "selected_workflow_hints": ["research_report"],
                    "matches": [
                        {
                            "workflow_id": "research_report",
                            "name": "Research Report",
                            "summary": "Research a topic and create a sourced Canvas report",
                            "triggers": {
                                "explicit": ["/research"],
                                "patterns": ["research *"],
                                "keywords": ["research", "report"],
                            },
                            "query_inputs": [
                                {
                                    "name": "topic",
                                    "extract": "main_subject",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "action": "run",
                    "workflow_id": "research_report",
                    "workflow_name": "Research Report",
                    "workflow_started": True,
                    "workflow_completed": completed,
                    "component_tools_used": ["search_docs", "text_summarizer", "canvas"],
                    "results": [
                        {"step": 1, "tool": "search_docs", "ok": True},
                        {"step": 2, "tool": "text_summarizer", "ok": completed},
                    ],
                },
            ]
        },
        "tool_trace": [
            {
                "tool": "workflow",
                "ok": True,
                "arguments": {"action": "search", "query": "AI"},
                "workflow_run_started": False,
            },
            {
                "tool": "workflow",
                "ok": completed,
                "arguments": {
                    "action": "run",
                    "workflow_id": "research_report",
                    "query": "AI",
                },
                "workflow_run_started": True,
            },
        ],
    }


def test_autonomous_summary_separates_discovery_from_recipe_components():
    context = extract_workflow_learning_context(_autonomous_result())

    assert context == {
        "is_workflow_interaction": True,
        "invocation": "autonomous_meta_tool",
        "actions": ["search", "run"],
        "selected_workflow_id": "research_report",
        "selected_workflow_name": "Research Report",
        "selected_workflow_summary": "Research a topic and create a sourced Canvas report",
        "selected_workflow_triggers": {
            "explicit": ["/research"],
            "patterns": ["research *"],
            "keywords": ["research", "report"],
        },
        "selected_workflow_query_inputs": [
            {
                "name": "topic",
                "extract": "main_subject",
                "required": True,
            }
        ],
        "run_started": True,
        "run_completed": True,
        "cancelled": False,
        "outcome_success": True,
        "component_tools_used": ["search_docs", "text_summarizer", "canvas"],
        "component_order_owner": "deterministic_workflow_recipe",
        "step_outcomes": [
            {"step": 1, "tool": "search_docs", "ok": True},
            {"step": 2, "tool": "text_summarizer", "ok": True},
        ],
    }


def test_completed_workflow_id_requires_successful_completed_run():
    assert completed_workflow_id(_autonomous_result()) == "research_report"
    assert completed_workflow_id(_autonomous_result(completed=False)) is None


def test_explicit_slash_workflow_is_identified_separately():
    context = extract_workflow_learning_context(
        {
            "ok": True,
            "workflow_executed": "research_report",
            "tools_used": ["search_docs", "canvas"],
            "data": {"results": []},
        }
    )

    assert context["invocation"] == "explicit_slash"
    assert context["selected_workflow_id"] == "research_report"
    assert context["selected_workflow_summary"] is None
    assert context["selected_workflow_triggers"] == {
        "explicit": [],
        "patterns": [],
        "keywords": [],
    }
    assert context["selected_workflow_query_inputs"] == []
    assert context["component_tools_used"] == ["search_docs", "canvas"]
