#!/usr/bin/env python3
"""
OpenAI Responses API helpers for Jarvis (adapter-local).

Converts Chat Completions-style tool payloads to Responses-native shapes,
extracts typed output items, usage, and normalized server_side_tools counts.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from provider_tool_policy import server_side_tools_disabled
from typing_extensions import TypedDict


class OpenAIResponsesDiag(TypedDict, total=False):
    """Safe diagnostics surfaced to router / llm_logger (no raw payloads)."""

    openai_api_mode: str
    openai_responses_tools_enabled: bool
    openai_responses_previous_id_present: bool
    openai_responses_previous_id_used: bool
    openai_responses_continuation_input_items: int
    openai_responses_output_items_by_type: dict[str, int]
    openai_responses_fallback_reason: str


def openai_env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        try:
            from config_loader import get_bool

            return bool(get_bool(name, default))
        except Exception:
            return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def openai_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        try:
            from config_loader import get_int

            return int(get_int(name, default))
        except Exception:
            return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def openai_should_use_responses_for_tools(*, tools: list[dict[str, Any]]) -> bool:
    """Gate the Responses routing path when tools may be invoked."""
    if not tools:
        return False
    try:
        from config_loader import get_config_value

        mode = (get_config_value("OPENAI_API_MODE", "chat") or "chat").strip().lower()
    except Exception:
        mode = (os.environ.get("OPENAI_API_MODE", "chat") or "chat").strip().lower()
    if mode != "responses":
        return False
    return openai_env_bool("OPENAI_RESPONSES_TOOLS", False)


def openai_responses_router_enabled() -> bool:
    """True when Responses tool routing knobs are armed (does not imply non-empty tools)."""
    try:
        from config_loader import get_config_value

        mode = (get_config_value("OPENAI_API_MODE", "chat") or "chat").strip().lower()
    except Exception:
        mode = (os.environ.get("OPENAI_API_MODE", "chat") or "chat").strip().lower()
    if mode != "responses":
        return False
    return openai_env_bool("OPENAI_RESPONSES_TOOLS", False)


def openai_responses_inflight_continuation_enabled() -> bool:
    """Continuation via previous_response_id + structured function outputs."""
    return openai_responses_router_enabled() and openai_env_bool(
        "OPENAI_RESPONSES_INFLIGHT_CONTINUATION", False
    )


def openai_responses_storage_flag(*, inflight_continuation_enabled: bool) -> bool:
    """
    Responses store= policy: Jarvis favors statelessness unless continuation needs it.

    When in-flight continuation is enabled, upstream requires chainable Responses.
    Otherwise default store=false unless explicitly overridden.
    """
    if inflight_continuation_enabled:
        return openai_env_bool("OPENAI_RESPONSES_STORE_CONTINUE", True)
    if "OPENAI_RESPONSES_STORE" in os.environ:
        return openai_env_bool("OPENAI_RESPONSES_STORE", False)
    try:
        from config_loader import get_bool

        return bool(get_bool("OPENAI_RESPONSES_STORE", False))
    except Exception:
        return False


def chat_tools_to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Chat Completions: {type,function:{name,description,parameters}}
    Responses:       {type:function,name,description,parameters,strict}

    Mirrors migration guide; default strict=false to approximate Chat semantics.
    """
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            out.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description"),
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                "strict": False,
            })
        elif tool.get("name"):
            # Already Responses-native or anthropic-ish fallthrough
            out.append({
                "type": "function",
                "name": tool.get("name", ""),
                "description": tool.get("description"),
                "parameters": tool.get("parameters")
                or tool.get("input_schema")
                or {"type": "object", "properties": {}},
                "strict": False,
            })
    return out


def build_openai_builtin_responses_tools() -> list[dict[str, Any]]:
    """Optional hosted tools (behind discrete env knobs)."""
    if server_side_tools_disabled():
        return []
    if openai_env_bool("OPENAI_RESPONSES_DISABLE_SERVER_SIDE_TOOLS", False):
        return []
    if not openai_env_bool("OPENAI_RESPONSES_SERVER_SIDE_TOOLS", False):
        return []
    tools: list[dict[str, Any]] = []

    def _comma_list(raw: str) -> list[str]:
        return [p.strip() for p in (raw or "").split(",") if p.strip()]

    try:
        from config_loader import get_config_value
    except Exception:
        def get_config_value(key: str, default: Any = "") -> Any:
            return os.environ.get(key, default)

    if openai_env_bool("OPENAI_RESPONSES_WEB_SEARCH", False):
        spec: dict[str, Any] = {"type": "web_search"}
        allowed = (
            _comma_list(str(get_config_value("OPENAI_RESPONSES_WEB_SEARCH_ALLOWED_DOMAINS", "") or ""))
            or None
        )
        blocked = (
            _comma_list(str(get_config_value("OPENAI_RESPONSES_WEB_SEARCH_BLOCKED_DOMAINS", "") or ""))
            or None
        )
        if allowed or blocked:
            filt: dict[str, Any] = {}
            if allowed:
                filt["allowed_domains"] = allowed
            if blocked:
                filt["blocked_domains"] = blocked
            spec["filters"] = filt
        tools.append(spec)

    if openai_env_bool("OPENAI_RESPONSES_FILE_SEARCH", False):
        vs_raw = str(get_config_value("OPENAI_RESPONSES_FILE_SEARCH_VECTOR_STORE_IDS", "") or "")
        vs_ids = _comma_list(vs_raw)
        if vs_ids:
            tools.append({"type": "file_search", "vector_store_ids": vs_ids})

    if openai_env_bool("OPENAI_RESPONSES_CODE_INTERPRETER", False):
        mem = str(get_config_value("OPENAI_RESPONSES_CODE_INTERPRETER_MEMORY_LIMIT", "1g") or "1g").strip()
        tools.append({"type": "code_interpreter", "container": {"type": "auto", "memory_limit": mem}})

    max_calls = openai_env_int("OPENAI_RESPONSES_SERVER_SIDE_MAX_TOOL_CALLS", 0)
    if tools and max_calls > 0:
        # SDK passes max_tool_calls at top level; annotate first tool payload is wrong.
        # Caller merges max_tool_calls into responses.create kwargs.
        pass

    return tools


def responses_output_type_counts(items: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not items:
        return counts
    for item in items:
        t = getattr(item, "type", None)
        if t is None and isinstance(item, dict):
            t = item.get("type")
        if not t:
            t = type(item).__name__
        counts[str(t)] = counts.get(str(t), 0) + 1
    return counts


def accumulate_server_side_from_output(items: Any) -> dict[str, int]:
    """Normalize hosted tool calls into SERVER_SIDE_TOOL_* counters."""
    out: dict[str, int] = {}
    if not items:
        return out
    for item in items:
        t = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
        if t == "web_search_call":
            out["SERVER_SIDE_TOOL_WEB_SEARCH"] = out.get("SERVER_SIDE_TOOL_WEB_SEARCH", 0) + 1
        elif t == "file_search_call":
            out["SERVER_SIDE_TOOL_FILE_SEARCH"] = out.get("SERVER_SIDE_TOOL_FILE_SEARCH", 0) + 1
        elif t == "code_interpreter_call":
            out["SERVER_SIDE_TOOL_CODE_INTERPRETER"] = out.get(
                "SERVER_SIDE_TOOL_CODE_INTERPRETER", 0
            ) + 1
    return out


def _response_output_text_fallback(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text

    chunks: list[str] = []
    for item in getattr(response, "output", None) or []:
        typ = getattr(item, "type", None)
        if typ == "message":
            for block in getattr(item, "content", []) or []:
                btyp = getattr(block, "type", None)
                if btyp == "output_text":
                    tex = getattr(block, "text", None)
                    if tex:
                        chunks.append(tex)
        elif isinstance(item, dict):
            if item.get("type") == "message":
                for block in item.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        tex = block.get("text")
                        if tex:
                            chunks.append(str(tex))
    return "".join(chunks)


def extract_function_calls_from_response(response: Any) -> list[Any]:
    items = getattr(response, "output", None) or []
    return [it for it in items if getattr(it, "type", None) == "function_call"]


def parse_responses_result(
    response: Any,
    *,
    model: str,
    parallel_tool_calls_allowed: bool,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any], dict[str, int]]:
    """
    Build (text, tool_call, usage_info, server_side_counts) from a Response object.

    When multiple client function_call items arrive and parallel is disallowed, the
    first item wins (deterministic ordering of output array).
    """
    from cost_estimator import estimate_cost, estimate_cache_cost

    fc_items = extract_function_calls_from_response(response)
    srv = accumulate_server_side_from_output(getattr(response, "output", None))

    text_out: str | None = None
    tool_payload: dict[str, Any] | None = None

    if fc_items:
        picked = fc_items[0]
        if not parallel_tool_calls_allowed and len(fc_items) > 1:
            print(
                "INFO: OpenAI Responses returned multiple function_call items; "
                f"picking first of {len(fc_items)} (OPENAI_RESPONSES_PARALLEL_TOOL_CALLS=false)",
                file=sys.stderr,
            )

        raw_args = getattr(picked, "arguments", None) if picked is not None else None
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                args = {}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        call_id = getattr(picked, "call_id", None) or getattr(picked, "id", "") or ""
        name = getattr(picked, "name", "") or ""
        rid = getattr(response, "id", None)

        tool_payload = {
            "name": name,
            "arguments": args or {},
        }
        if call_id:
            tool_payload["tool_call_id"] = call_id
            tool_payload["id"] = call_id
        if rid:
            tool_payload["response_id"] = rid
    else:
        joined = _response_output_text_fallback(response)
        text_out = joined if joined else None

    usage_info: dict[str, Any] = {}
    usage_obj = getattr(response, "usage", None)
    if usage_obj:
        in_tok = (
            getattr(usage_obj, "input_tokens", None)
            or getattr(usage_obj, "prompt_tokens", None)
            or 0
        )
        out_tok = (
            getattr(usage_obj, "output_tokens", None)
            or getattr(usage_obj, "completion_tokens", None)
            or 0
        )
        reasoning_tok = getattr(usage_obj, "reasoning_tokens", None)
        if reasoning_tok is None:
            output_details = getattr(usage_obj, "output_tokens_details", None)
            reasoning_tok = (
                getattr(output_details, "reasoning_tokens", None)
                if output_details
                else None
            )

        cached_details = getattr(usage_obj, "input_tokens_details", None)
        cached_in = getattr(cached_details, "cached_tokens", None) if cached_details else None
        if cached_in is None:
            cached_in = getattr(usage_obj, "prompt_tokens_cached", None) or 0

        base = estimate_cost(
            provider="openai",
            model=model,
            input_tokens=int(in_tok or 0),
            output_tokens=int(out_tok or 0),
        )
        usage_info.update(base)
        usage_info["total_tokens"] = int(in_tok or 0) + int(out_tok or 0)

        cached_count = int(cached_in or 0)
        usage_info["cached_input_tokens"] = cached_count
        # Keep the shared cache-read field populated so existing log/UI code can
        # show OpenAI cache hits alongside xAI/Anthropic without inspecting
        # provider-specific usage objects.
        usage_info["cached_prompt_text_tokens"] = cached_count
        usage_info["cache_read_tokens"] = cached_count

        if cached_count:
            cache_bits = estimate_cache_cost(
                provider="openai",
                model=model,
                cache_creation_tokens=0,
                cache_read_tokens=cached_count,
            )
            usage_info.update(cache_bits)

        if reasoning_tok:
            usage_info["reasoning_tokens"] = int(reasoning_tok)

    if srv:
        usage_info["server_side_tools"] = srv

    return text_out, tool_payload, usage_info, srv


def build_responses_input_from_chat(
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Simple migration-compatible input from chat-shaped messages.

    OpenAI Responses accepts the same `{role, content}` rows as Chat Completions
    for straightforward migrations.
    """
    rows: list[dict[str, Any]] = []
    if system_prompt:
        rows.append({"role": "system", "content": system_prompt})
    for msg in messages or []:
        role = msg.get("role") or "user"
        content = msg.get("content")
        rows.append({"role": role, "content": content if content is not None else ""})
    return rows


def is_openai_previous_response_error(exc: Exception) -> bool:
    """Heuristic match for stale/missing continuation ids (tune over time)."""
    text = str(exc).lower()
    markers = (
        "previous_response",
        "response_id",
        "not found",
        "invalid_previous_response_id",
        "no such response",
        "unknown response",
        "conversation not found",
    )
    return any(m in text for m in markers)
