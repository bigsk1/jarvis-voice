#!/usr/bin/env python3
"""Canonical text builders for fingerprinted Jarvis embedding namespaces."""

from __future__ import annotations

import json
from typing import Any, Sequence


def build_outcome_embedding_text(
    query: str,
    tools_used: Sequence[Any],
    outcome: dict[str, Any],
    user_signals: dict[str, Any],
) -> str:
    """Build the v1 Intelligence outcome document from structured values."""
    parts = [f"User asked: {str(query or '')[:100]}"]
    tools = [str(tool) for tool in tools_used]
    if len(tools) == 1:
        parts.append(f"Answered in one turn using {tools[0]}")
    elif len(tools) > 1:
        parts.append(f"Took {len(tools)} turns: {' → '.join(tools)}")

    if outcome.get("success"):
        parts.append("Task completed successfully")
    else:
        parts.append(f"Task failed: {outcome.get('error', 'unknown error')}")
    if user_signals.get("thanked"):
        parts.append("User expressed satisfaction")
    if user_signals.get("clarified"):
        parts.append("User had to clarify their request")
    if user_signals.get("retried"):
        parts.append("User had to retry")
    return ". ".join(parts)


def build_stored_outcome_embedding_text(
    *,
    query: str,
    tools_used_json: str | None,
    raw_data_json: str | None,
    outcome_success: Any,
    error_occurred: Any,
) -> str:
    """Reconstruct the canonical outcome document from an experience row."""
    try:
        tools_used = json.loads(tools_used_json or "[]")
        if not isinstance(tools_used, list):
            tools_used = []
    except (TypeError, json.JSONDecodeError):
        tools_used = []

    try:
        raw_data = json.loads(raw_data_json or "{}")
        if not isinstance(raw_data, dict):
            raw_data = {}
    except (TypeError, json.JSONDecodeError):
        raw_data = {}

    raw_outcome = raw_data.get("outcome")
    outcome = dict(raw_outcome) if isinstance(raw_outcome, dict) else {}
    raw_signals = raw_data.get("user_signals")
    user_signals = dict(raw_signals) if isinstance(raw_signals, dict) else {}
    if "success" not in outcome:
        outcome["success"] = bool(outcome_success)
    if error_occurred and not outcome.get("error"):
        outcome["error"] = True

    return build_outcome_embedding_text(query, tools_used, outcome, user_signals)
