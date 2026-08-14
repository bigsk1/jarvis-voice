#!/usr/bin/env python3
"""
Runtime helpers for the tool_search discovery tool.

This module intentionally builds discovery results from the live registry state
instead of a parallel metadata system. It respects the active profile, enabled
tool set, and per-request exclusions supplied by the orchestrator/executor.
"""

from __future__ import annotations

import math
from typing import Any

from config_loader import get_config_value
from memory_db import get_memory_db
from tool_schema import _merged_ghost_tool_names


def _short_description(text: str, max_chars: int = 220) -> str:
    """Return the first compact paragraph/line of a tool description."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 15].rstrip() + "... [truncated]"


def _tool_source(tool) -> str:
    """Infer whether a tool is local or MCP-backed from its schema."""
    script_path = str(getattr(tool, "script_path", "") or "")
    name = str(getattr(tool, "name", "") or "")
    if script_path.startswith("__mcp__") or name.startswith("mcp_"):
        return "mcp"
    return "local"


def _parameter_preview(parameters: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Build lightweight required/optional parameter previews."""
    if not isinstance(parameters, dict):
        return [], []
    props = parameters.get("properties", {})
    required = parameters.get("required", [])
    if not isinstance(props, dict):
        return [], []
    required_names = [str(name) for name in required if name in props][:5]
    optional_names = [str(name) for name in props.keys() if name not in set(required_names) and name not in set(required)][:5]
    return required_names, optional_names


def _parameter_details(parameters: dict[str, Any], max_items: int = 6) -> list[dict[str, Any]]:
    """Return a compact parameter summary for discovery UI/LLM use."""
    if not isinstance(parameters, dict):
        return []
    props = parameters.get("properties", {})
    required = set(parameters.get("required", []) or [])
    if not isinstance(props, dict):
        return []

    details: list[dict[str, Any]] = []
    for index, (name, info) in enumerate(props.items()):
        if index >= max_items:
            break
        info = info if isinstance(info, dict) else {}
        details.append(
            {
                "name": str(name),
                "type": info.get("type", "string"),
                "required": name in required,
                "description": _short_description(str(info.get("description", "") or ""), max_chars=140),
            }
        )
    return details


def _tool_summary(tool, *, similarity: float | None = None, include_schema: bool = False) -> dict[str, Any]:
    """Convert a ToolSchema into a discovery summary."""
    required_params, optional_params = _parameter_preview(getattr(tool, "parameters", {}) or {})
    summary = {
        "name": tool.name,
        "summary": _short_description(getattr(tool, "description", "") or ""),
        "source": _tool_source(tool),
        "available_now": True,
        "required_parameters": required_params,
        "optional_parameters": optional_params,
        "parameter_details": _parameter_details(getattr(tool, "parameters", {}) or {}),
    }
    if similarity is not None:
        summary["similarity"] = round(float(similarity), 6)
    if include_schema:
        summary["parameters_schema"] = getattr(tool, "parameters", {}) or {"type": "object", "properties": {}}
    return summary


def _coerce_limit(limit: Any, default: int = 6, minimum: int = 1, maximum: int = 20) -> int:
    """Parse loose tool-call input safely and clamp it to the supported range."""
    raw_value = default

    if isinstance(limit, bool) or limit is None:
        raw_value = default
    elif isinstance(limit, int):
        raw_value = limit
    elif isinstance(limit, float):
        raw_value = int(limit) if math.isfinite(limit) else default
    else:
        text = str(limit).strip()
        if text:
            try:
                raw_value = int(text)
            except (TypeError, ValueError):
                try:
                    numeric_value = float(text)
                except (TypeError, ValueError):
                    raw_value = default
                else:
                    raw_value = int(numeric_value) if math.isfinite(numeric_value) else default

    return max(minimum, min(raw_value, maximum))


def _ghost_tool_names(registry) -> set[str]:
    """Return the currently active ghost tool names, including mandatory ones."""
    available_names = set(getattr(registry, "tools", {}).keys())
    raw_value = get_config_value(
        "GHOST_TOOLS",
        "search_memory,update_memory,semantic_recall,remember,canvas",
    )
    return set(_merged_ghost_tool_names(raw_value, available_names))


def search_tools_runtime(
    *,
    registry,
    query: str = "",
    limit: int = 8,
    excluded_tools: list[str] | set[str] | None = None,
    tool_names: list[str] | None = None,
    include_schema: bool = False,
) -> dict[str, Any]:
    """
    Search live available tools without inventing a parallel metadata layer.

    Args:
        registry: Active ToolRegistry instance.
        query: Semantic search text.
        limit: Max number of summaries to return.
        excluded_tools: Request-specific tools that must remain hidden.
        tool_names: Optional exact names to inspect directly.
        include_schema: Include full parameter schema for exact/detail lookups.
    """
    excluded = {str(name).strip() for name in (excluded_tools or []) if str(name).strip()}
    excluded.add("tool_search")
    limit = _coerce_limit(limit)
    ghost_tools = _ghost_tool_names(registry)

    available_names = [
        name
        for name in sorted(getattr(registry, "tools", {}).keys())
        if name not in excluded
    ]
    available_set = set(available_names)
    discoverable_names = [name for name in available_names if name not in ghost_tools]
    discoverable_set = set(discoverable_names)

    summaries: list[dict[str, Any]] = []
    selected_tool_hints: list[str] = []
    search_mode = "semantic"
    fallback_embeddings = None

    if tool_names:
        search_mode = "exact"
        for raw_name in tool_names:
            name = str(raw_name or "").strip()
            if not name or name not in available_set:
                continue
            tool = registry.get_tool(name)
            if not tool:
                continue
            summaries.append(_tool_summary(tool, include_schema=include_schema))
            selected_tool_hints.append(name)
            if len(summaries) >= limit:
                break
    elif str(query or "").strip():
        db = get_memory_db()
        try:
            ranked = db.search_tools(str(query).strip(), limit=max(limit * 4, 24), threshold=0.0)
            search_meta = getattr(db, "last_tool_search_meta", {})
            if isinstance(search_meta, dict):
                fallback_embeddings = search_meta.get("fallback_embeddings")
        finally:
            db.close()
        for row in ranked:
            name = str(row.get("name", "") or "").strip()
            if not name or name not in discoverable_set:
                continue
            tool = registry.get_tool(name)
            if not tool:
                continue
            summaries.append(_tool_summary(tool, similarity=row.get("similarity"), include_schema=include_schema))
            selected_tool_hints.append(name)
            if len(summaries) >= limit:
                break
    else:
        search_mode = "browse"
        for name in discoverable_names[:limit]:
            tool = registry.get_tool(name)
            if not tool:
                continue
            summaries.append(_tool_summary(tool, include_schema=include_schema))
            selected_tool_hints.append(name)

    if summaries:
        names_preview = ", ".join(item["name"] for item in summaries[:6])
        speech = f"I found {len(summaries)} matching tools: {names_preview}."
    else:
        speech = "I couldn't find any matching enabled tools right now."

    return {
        "ok": True,
        "speech": speech,
        "fallback_embeddings": fallback_embeddings,
        "data": {
            "query": str(query or ""),
            "matches": summaries,
            "selected_tool_hints": selected_tool_hints,
            "count": len(summaries),
            "search_space": len(available_names if search_mode == "exact" else discoverable_names),
            "search_mode": search_mode,
            "include_schema": bool(include_schema),
        },
    }
