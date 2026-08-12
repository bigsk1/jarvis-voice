#!/usr/bin/env python3
"""
Jarvis Voice Assistant - LLM-Based Router (v2)
Uses native tool calling from OpenAI/Anthropic/Ollama to intelligently route requests.
"""
import os
import sys
import re
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import (
    load_config,
    get_config_value,
    get_float,
    get_int,
    get_bool,
    DEFAULT_JARVIS_QA_WORD_LIMIT,
    DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
)
from model_prompt_overrides import load_model_prompt_override, apply_prompt_override_sections
from router_prompts import DEFAULT_ROUTER_PROMPT_VERSION, get_router_system_prompt
from tool_schema import ToolRegistry, _merged_ghost_tool_names
from llm_provider import create_configured_provider
from provider_errors import classify_provider_error, friendly_provider_error, is_provider_error_text
from user_profile import append_profile_card_for_router_direct_answer


@dataclass
class ToolRetrievalSignals:
    """Compact Tool RAG query plus structured tool-name signals."""

    query: str
    source: str
    positive_tools: set[str] = field(default_factory=set)
    negative_tools: set[str] = field(default_factory=set)
    conflicted_tools: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


@dataclass
class ProviderRouteInput:
    """Provider-facing route payload decoupled from Tool RAG retrieval text."""

    tool_retrieval_query: str
    messages: list[dict[str, Any]]
    system_prompt: str | None
    previous_response_id: str | None = None
    continuation_mode: str = "text_fallback"
    continuation_fallback_reason: str | None = None
    responses_continuation_input: list[dict[str, Any]] | None = None


_REQUEST_BOUNDARY_MARKERS = (
    "\n\nTools executed so far:",
    "\nTools executed so far:",
    "\n\n===PREVIOUS ATTEMPT FAILED",
    "\n===PREVIOUS ATTEMPT FAILED",
    "\n\nUse ONLY one of these exact tool names",
    "\nUse ONLY one of these exact tool names",
    "\n\nBased on the above results",
    "\nBased on the above results",
    "\n\nFRESHNESS RULES",
    "\nFRESHNESS RULES",
    "\n\nDUPLICATE TOOL GUARD:",
    "\nDUPLICATE TOOL GUARD:",
)

_FULL_PROMPT_MARKERS = (
    "=== LEARNED STRATEGIES",
    "=== TOOL PREFERENCES",
    "=== RELEVANT STORED KNOWLEDGE",
    "=== RECENT CONVERSATION CONTEXT",
    "=== RECENT CONVERSATION HISTORY",
    "[CONTEXT - Tool preference",
    "Original user request:",
    "Tools executed so far:",
    "[Turn ",
)
_MANDATORY_DISCOVERY_TOOLS = ("tool_search", "workflow")
_REQUEST_TOOL_RAG_LIMIT_MAX = 50
_CHAT_ONLY_SYSTEM_POLICY = (
    "CHAT ONLY MODE:\n"
    "- No client-side or provider-hosted tools are available for this request.\n"
    "- Answer directly from the conversation context and your existing knowledge.\n"
    "- Do not emit a tool call. If current or external information is required, say that it cannot be fetched in Chat only mode."
)


@contextmanager
def _provider_runtime_tool_scope(
    *,
    disable_server_side_tools: bool,
    server_side_max_tool_turns: int | None,
):
    """Apply provider tool policy without leaking Web request state globally."""
    overrides: dict[str, str] = {}
    if disable_server_side_tools:
        overrides["DISABLE_SERVER_SIDE_TOOLS"] = "true"
    if server_side_max_tool_turns is not None:
        overrides["XAI_SERVER_SIDE_MAX_TOOL_TURNS"] = str(
            max(1, int(server_side_max_tool_turns))
        )
    if not overrides:
        yield
        return

    from config_loader import config_override_scope, get_scoped_config

    if get_scoped_config() is not None:
        with config_override_scope(overrides):
            yield
        return

    # Legacy CLI callers may not install a config scope. Preserve their existing
    # process-env behavior while Web requests use the isolated ContextVar path.
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _resolve_tool_rag_limit(mode: str, override: int | str | None = None) -> int:
    """Resolve final tool schema cap for Tool RAG."""
    default = 6 if mode == "local" else 15
    if override not in (None, ""):
        try:
            return min(max(1, int(override)), _REQUEST_TOOL_RAG_LIMIT_MAX)
        except (TypeError, ValueError):
            return default

    if mode == "local":
        return max(1, get_int("LOCAL_TOOL_RAG_LIMIT", default))
    return max(1, get_int("CLOUD_TOOL_RAG_LIMIT", default))


def _cap_tool_names_for_schema(
    names: list[str],
    limit: int,
    positive_tools: set[str] | list[str] | None = None,
    ghost_tools: list[str] | set[str] | None = None,
) -> list[str]:
    """
    Apply a final Tool RAG schema cap after ghost/signal merging.

    Priority:
    1. explicit positive signals such as UI-selected tool hints
    2. mandatory discovery escape hatches like tool_search and workflow
    3. retrieved non-ghost tools in current rank order
    4. remaining ghost tools, only if room remains
    """
    limit = max(1, int(limit or 1))
    if len(names) <= limit:
        return list(names)

    positive_set = set(positive_tools or [])
    ghost_set = set(ghost_tools or [])
    name_set = set(names)
    selected: list[str] = []
    selected_set: set[str] = set()

    def add(name: str) -> None:
        if len(selected) >= limit or name in selected_set or name not in name_set:
            return
        selected.append(name)
        selected_set.add(name)

    for name in names:
        if name in positive_set:
            add(name)
    for name in _MANDATORY_DISCOVERY_TOOLS:
        add(name)
    for name in names:
        if name not in ghost_set:
            add(name)
    for name in names:
        add(name)

    return selected


def _log_tool_rag_signal_meta(logger: logging.Logger, signal_meta: dict[str, Any]) -> None:
    """Log signal metadata, including pure final-cap drops."""
    if signal_meta:
        logger.info(f"[TOOL_RAG] signal_meta={signal_meta}")

_MEMORY_TOOL_SIGNAL_POSITIVE_MARKERS = (
    "always use",
    "prefer",
    "preferred",
    "should use",
    "use ",
    "route to",
    "optimal",
    "start with",
)

_MEMORY_TOOL_SIGNAL_NEGATIVE_MARKERS = (
    "do not use",
    "don't use",
    "never use",
    "avoid",
    "failed",
    "failure",
    "wrong",
    "bad path",
)


def _cap_tool_rag_text(text: str, max_chars: int | None = None) -> str:
    """Keep fallback Tool RAG embedding text small and stable."""
    limit = max_chars if max_chars is not None else get_int("TOOL_RAG_CONTEXT_QUERY_MAX_CHARS", 500)
    limit = max(80, int(limit or 500))
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 16].rstrip() + " ... [truncated]"


def _truncate_at_first_marker(text: str, markers: tuple[str, ...] = _REQUEST_BOUNDARY_MARKERS) -> str:
    """Trim a captured request before subsequent tool/result instruction blocks."""
    if not text:
        return ""
    stops = [idx for marker in markers if (idx := text.find(marker)) >= 0]
    if stops:
        text = text[: min(stops)]
    return text.strip()


def _extract_trailing_request_after_context(text: str) -> str | None:
    """
    Pull the final plain request paragraph after prepended intelligence/memory blocks.

    In normal cloud/web routing, learned insights and auto-memory are prepended
    directly before the raw request without a "Current request:" label. Embedding
    the whole thing is noisy; the trailing user paragraph is usually the best
    retrieval query.
    """
    if not text or not any(marker in text for marker in _FULL_PROMPT_MARKERS):
        return None

    candidate = _truncate_at_first_marker(text)
    lines = candidate.splitlines()
    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    if end <= 0:
        return None

    start = end
    while start > 0:
        line = lines[start - 1].strip()
        if not line:
            break
        if line.startswith("==="):
            break
        start -= 1

    tail = "\n".join(lines[start:end]).strip()
    if not tail:
        return None

    first = tail.lstrip()
    context_prefixes = (
        "✅", "❌", "→", "- ", "(", "Freshness note:", "Higher rank =",
        "Lines tagged ", "Other lines are ", "Context timing:",
    )
    if first.startswith(context_prefixes):
        return None
    return tail


def _extract_current_tool_request(transcript: str) -> tuple[str | None, str]:
    """
    Extract the current user request from Jarvis routing prompts.

    The LLM still receives the full prompt. This is only for Tool RAG embeddings,
    where long learned-strategy, memory, and prior-result prose can drown the
    current task in vector space.
    """
    text = transcript or ""

    # Web UI prompt wrapper: [CONTEXT - Tool preference] ... User's request: ...
    marker = "User's request:"
    idx = text.rfind(marker)
    if idx >= 0:
        request = _truncate_at_first_marker(text[idx + len(marker):])
        if request:
            return request, "user_request"

    # Web conversation context wrapper: ... Current request: ...
    marker = "Current request:"
    idx = text.rfind(marker)
    if idx >= 0:
        request = _truncate_at_first_marker(text[idx + len(marker):])
        if request:
            return request, "current_request"

    # Legacy auto-context wrapper used by CLI/wake-word mode.
    if "=== RECENT CONVERSATION HISTORY ===" in text and "Instructions:" in text:
        before_instructions = text.split("Instructions:", 1)[0]
        lines = before_instructions.split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line and not line.startswith("[") and not line.startswith("User:") and \
               not line.startswith("Assistant:") and not line.startswith("Tools used:") and \
               not line.startswith("Status:") and not line.startswith("===") and \
               not line.startswith("Last ") and not line.startswith("Model:") and \
               not line.startswith("Cost:") and "conversation(s)" not in line:
                return line, "legacy_history_strip"

    # Multi-turn tool context can wrap the original request without the Web UI
    # Current request marker. Use it only if no richer marker was available.
    marker = "Original user request:"
    idx = text.rfind(marker)
    if idx >= 0:
        request = _truncate_at_first_marker(text[idx + len(marker):])
        if request:
            trailing = _extract_trailing_request_after_context(request)
            if trailing:
                return trailing, "original_user_request_tail"
            return request, "original_user_request"

    trailing = _extract_trailing_request_after_context(text)
    if trailing:
        return trailing, "trailing_request"

    return None, "unparsed"


def extract_current_user_request(transcript: str) -> str:
    """Return the clean current request used by semantic retrieval layers.

    Jarvis prepends tool hints, learned strategies, memory, and prior-result
    context to the router transcript. Those blocks remain available to the LLM,
    but embedding them as if they were user text can make their tool names or
    prohibitions look relevant to an unrelated request.
    """
    request, _source = _extract_current_tool_request(transcript)
    return request or (transcript or "")


def _parse_enabled_tool_names(raw: str, enabled_tool_names: set[str]) -> set[str]:
    """Extract exact registered tool names from a line of text."""
    if not raw or not enabled_tool_names:
        return set()
    names: set[str] = set()
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9_]{1,120}\b", raw):
        name = match.group(0)
        if name in enabled_tool_names:
            names.add(name)
    return names


def _extract_memory_tool_signals(transcript: str, enabled_tool_names: set[str]) -> tuple[set[str], set[str]]:
    """
    Optionally classify exact tool names in auto-memory/intel context.

    This is intentionally gated by TOOL_RAG_MEMORY_TOOL_SIGNALS_ENABLED because
    memory prose can be noisy. When enabled, only exact enabled tool names with a
    nearby positive/negative cue become structured signals.
    """
    positives: set[str] = set()
    negatives: set[str] = set()
    if not enabled_tool_names or not get_bool("TOOL_RAG_MEMORY_TOOL_SIGNALS_ENABLED", False):
        return positives, negatives

    sections = re.findall(
        r"=== RELEVANT STORED KNOWLEDGE.*?(?:\n===|$)",
        transcript or "",
        flags=re.DOTALL,
    )
    if not sections:
        return positives, negatives

    for section in sections:
        lowered = section.lower()
        for name in enabled_tool_names:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])"
            for match in re.finditer(pattern, section):
                start = max(0, match.start() - 120)
                end = min(len(section), match.end() + 120)
                window = lowered[start:end]
                if any(marker in window for marker in _MEMORY_TOOL_SIGNAL_POSITIVE_MARKERS):
                    positives.add(name)
                if any(marker in window for marker in _MEMORY_TOOL_SIGNAL_NEGATIVE_MARKERS):
                    negatives.add(name)

    return positives, negatives


def _current_request_needs_image_analysis(request: str) -> bool:
    """Detect follow-up requests that need Jarvis vision over stash/local images."""
    if not request:
        return False
    lowered = request.lower()
    if not any(term in lowered for term in ("image", "photo", "picture", "upload", "uploaded")):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "look at",
            "take a look",
            "analyze",
            "compare",
            "review",
            "let me know how",
            "how it went",
            "original uploaded",
            "new image",
            "generated image",
        )
    )


def build_tool_retrieval_signals(
    transcript: str,
    enabled_tool_names: list[str] | set[str] | None = None,
) -> ToolRetrievalSignals:
    """
    Build a compact Tool RAG query and structured exact tool-name signals.

    Learned strategies, auto-memory, and recent context still go to the routing
    LLM in full. Tool RAG gets a smaller task-shaped query plus explicit
    positive/negative tool names so long context cannot distort top-K ranking.
    """
    enabled_set = set(enabled_tool_names or [])
    positive_tools: set[str] = set()
    negative_tools: set[str] = set()
    explicit_tool_hints: set[str] = set()
    notes: list[str] = []
    text = transcript or ""

    for block in re.findall(
        r"\[CONTEXT - Tool preference for this request\](.*?)\[END CONTEXT\]",
        text,
        flags=re.DOTALL,
    ):
        for line in block.splitlines():
            if "Selected tool hints:" in line:
                explicit_tool_hints.update(
                    _parse_enabled_tool_names(
                        line.split("Selected tool hints:", 1)[1],
                        enabled_set,
                    )
                )

    for line in text.splitlines():
        if "Selected tool hints:" in line:
            positive_tools.update(_parse_enabled_tool_names(line.split("Selected tool hints:", 1)[1], enabled_set))
            continue

        prefer_match = re.search(
            r"\bPREFER:\s*([A-Za-z][A-Za-z0-9_]{1,120})(?:\s*\(\+?([0-9]+(?:\.[0-9]+)?)\))?",
            line,
        )
        if prefer_match:
            min_bias = get_float("TOOL_RAG_MIN_LEARNED_PREFER_BIAS", 0.50)
            bias_raw = prefer_match.group(2)
            bias_ok = True
            if bias_raw is not None:
                try:
                    bias_ok = float(bias_raw) >= min_bias
                except ValueError:
                    bias_ok = True
            if bias_ok:
                positive_tools.update(_parse_enabled_tool_names(prefer_match.group(1), enabled_set))
            else:
                notes.append(f"skipped_low_bias_prefer={prefer_match.group(1)}:{bias_raw}")

        avoid_match = re.search(
            r"\bAVOID:\s*([A-Za-z][A-Za-z0-9_]{1,120})(?:\s*\(-?([0-9]+(?:\.[0-9]+)?)\))?",
            line,
        )
        if avoid_match:
            min_bias = get_float("TOOL_RAG_MIN_LEARNED_AVOID_BIAS", 0.50)
            bias_raw = avoid_match.group(2)
            bias_ok = True
            if bias_raw is not None:
                try:
                    bias_ok = float(bias_raw) >= min_bias
                except ValueError:
                    bias_ok = True
            if bias_ok:
                negative_tools.update(_parse_enabled_tool_names(avoid_match.group(1), enabled_set))
            else:
                notes.append(f"skipped_low_bias_avoid={avoid_match.group(1)}:{bias_raw}")

        do_not_match = re.search(r"\bDO NOT use:\s*(.+)$", line, flags=re.IGNORECASE)
        if do_not_match:
            negative_tools.update(_parse_enabled_tool_names(do_not_match.group(1), enabled_set))

    mem_positive, mem_negative = _extract_memory_tool_signals(text, enabled_set)
    positive_tools.update(mem_positive)
    negative_tools.update(mem_negative)

    conflicted = positive_tools & negative_tools
    if conflicted:
        # A direct UI selection is current-turn user intent and outranks learned
        # negative preferences. Conflicts entirely within learned intelligence
        # remain neutral so stale or contradictory lessons do not force routing.
        explicit_overrides = conflicted & explicit_tool_hints
        neutralized = conflicted - explicit_overrides
        positive_tools -= neutralized
        negative_tools -= conflicted
        if explicit_overrides:
            notes.append(
                "explicit_tool_hints_overrode_negative="
                + ",".join(sorted(explicit_overrides))
            )
        if neutralized:
            notes.append(f"conflicted_tools={','.join(sorted(neutralized))}")
        conflicted = neutralized

    if not get_bool("TOOL_RAG_COMPACT_QUERY_ENABLED", True):
        return ToolRetrievalSignals(
            query=text,
            source="full_prompt_disabled",
            positive_tools=positive_tools,
            negative_tools=negative_tools,
            conflicted_tools=conflicted,
            notes=notes,
        )

    request, source = _extract_current_tool_request(text)
    if request:
        if "analyze_image" in enabled_set and _current_request_needs_image_analysis(request):
            positive_tools.add("analyze_image")
        query = _cap_tool_rag_text(request, get_int("TOOL_RAG_CURRENT_QUERY_MAX_CHARS", 1200))
        return ToolRetrievalSignals(
            query=query,
            source=source,
            positive_tools=positive_tools,
            negative_tools=negative_tools,
            conflicted_tools=conflicted,
            notes=notes,
        )

    if not any(marker in text for marker in _FULL_PROMPT_MARKERS):
        return ToolRetrievalSignals(
            query=_cap_tool_rag_text(text, get_int("TOOL_RAG_CURRENT_QUERY_MAX_CHARS", 1200)),
            source="raw_request",
            positive_tools=positive_tools,
            negative_tools=negative_tools,
            conflicted_tools=conflicted,
            notes=notes,
        )

    return ToolRetrievalSignals(
        query=_cap_tool_rag_text(text, get_int("TOOL_RAG_CONTEXT_QUERY_MAX_CHARS", 500)),
        source="full_fallback",
        positive_tools=positive_tools,
        negative_tools=negative_tools,
        conflicted_tools=conflicted,
        notes=notes,
    )


def merge_tool_signal_names(
    initial_names: list[str],
    signals: ToolRetrievalSignals,
    enabled_tool_names: list[str] | set[str],
    ghost_tools: list[str] | set[str] | None = None,
    excluded_tools: list[str] | set[str] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Apply structured positive/negative tool signals to a retrieved name list."""
    enabled_set = set(enabled_tool_names or [])
    ghost_set = set(ghost_tools or [])
    excluded_set = set(excluded_tools or [])
    append_positive = get_bool("TOOL_RAG_APPEND_POSITIVE_SIGNALS", True)
    exclude_negative = get_bool("TOOL_RAG_EXCLUDE_NEGATIVE_SIGNALS", True)

    positive = {
        name for name in signals.positive_tools
        if name in enabled_set and name not in excluded_set
    }
    negative = {
        name for name in signals.negative_tools
        if name in enabled_set and name not in excluded_set
    }
    conflicted = positive & negative
    positive -= conflicted
    negative -= conflicted

    names: list[str] = []
    for name in initial_names:
        if name in excluded_set:
            continue
        if exclude_negative and name in negative and name not in ghost_set:
            continue
        if name not in names:
            names.append(name)

    appended: list[str] = []
    if append_positive:
        for name in sorted(positive):
            if name not in names:
                names.append(name)
                appended.append(name)

    return names, {
        "positive": sorted(positive),
        "negative": sorted(negative),
        "conflicted": sorted(set(signals.conflicted_tools) | conflicted),
        "appended": appended,
    }


def _log_tool_rag_trace(
    *,
    mode: str,
    provider: str,
    model: str,
    transcript: str,
    query: str,
    threshold: float,
    retrieval_limit: int,
    signal_source: str,
    signal_meta: dict[str, list[str]],
    signal_notes: list[str],
    ranked_tools: list[dict[str, Any]],
    final_tools: list[str],
    ghost_tools: list[str],
    excluded_tools: list[str],
    router_prompt_version: str | None = None,
    system_prompt_chars: int | None = None,
    system_prompt_est_tokens: int | None = None,
    system_prompt_sent: bool | None = None,
    tool_schema_chars: int | None = None,
    tool_schema_est_tokens: int | None = None,
    tool_schema_top: list[dict[str, Any]] | None = None,
    tool_rag_skipped: bool = False,
) -> None:
    """Write optional Tool RAG retrieval traces for live routing debugging."""
    if not get_bool("TOOL_RAG_TRACE_ENABLED", True):
        return
    try:
        project_root = Path(__file__).parent.parent.resolve()
        log_dir = project_root / "logs" / "tool-rag"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"tool-rag-{today}.jsonl"
        max_ranked = max(5, get_int("TOOL_RAG_TRACE_TOP_N", 25))
        max_query_chars = max(80, get_int("TOOL_RAG_TRACE_QUERY_CHARS", 1200))
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "provider": provider,
            "model": model,
            "router_prompt_version": router_prompt_version,
            "system_prompt_chars": system_prompt_chars,
            "system_prompt_est_tokens": system_prompt_est_tokens,
            "system_prompt_sent": system_prompt_sent,
            "signal_source": signal_source,
            "similarity_threshold": threshold,
            "retrieval_limit": retrieval_limit,
            "final_schema_limit": retrieval_limit,
            "query": _cap_tool_rag_text(query, max_query_chars),
            "query_chars": len(query or ""),
            "full_transcript_chars": len(transcript or ""),
            "full_transcript_embedding": query == transcript,
            "signal_meta": signal_meta,
            "signal_notes": signal_notes,
            "ghost_tools": ghost_tools,
            "excluded_tools": excluded_tools,
            "ranked_tools": [
                {
                    "rank": idx + 1,
                    "name": tool.get("name"),
                    "similarity": round(float(tool.get("similarity") or 0.0), 6),
                    "in_final_tools": tool.get("name") in final_tools,
                }
                for idx, tool in enumerate(ranked_tools[:max_ranked])
            ],
            "final_tools": final_tools,
            "final_tool_count": len(final_tools),
            "tool_rag_skipped": bool(tool_rag_skipped),
            "tool_schema_chars": tool_schema_chars,
            "tool_schema_est_tokens": tool_schema_est_tokens,
            "tool_schema_top": tool_schema_top or [],
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        if os.environ.get("JARVIS_DEBUG"):
            print(f"DEBUG: Failed to log Tool RAG trace: {exc}", file=sys.stderr)


def _estimate_tool_schema_payload(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimate chars/tokens for the exact tool schemas sent to the provider."""
    try:
        serialized = json.dumps(tools, default=str, separators=(",", ":"))
    except Exception:
        serialized = str(tools)
    per_tool: list[dict[str, Any]] = []
    for tool in tools:
        name = None
        if isinstance(tool, dict):
            if "function" in tool and isinstance(tool.get("function"), dict):
                name = tool["function"].get("name")
            else:
                name = tool.get("name")
        try:
            tool_serialized = json.dumps(tool, default=str, separators=(",", ":"))
        except Exception:
            tool_serialized = str(tool)
        chars = len(tool_serialized)
        per_tool.append({
            "name": name or "unknown",
            "chars": chars,
            "est_tokens": max(1, round(chars / 4)),
        })
    per_tool.sort(key=lambda item: item["chars"], reverse=True)
    chars = len(serialized)
    return {
        "chars": chars,
        "est_tokens": max(1, round(chars / 4)) if chars else 0,
        "top": per_tool[: max(1, get_int("TOOL_RAG_TRACE_SCHEMA_TOP_N", 10))],
    }


def _tool_rag_similarity_threshold(
    transcript: str,
    tool_search_query: str,
    signal_source: str | None = None,
) -> float:
    """
    When the full routing string is embedded for Tool RAG (no strip to a short user line),
    optionally use TOOL_SIMILARITY_THRESHOLD_FULL; if unset or empty, use TOOL_SIMILARITY_THRESHOLD
    for both paths.
    """
    base = get_float('TOOL_SIMILARITY_THRESHOLD', 0.0)
    if signal_source:
        if not signal_source.startswith("full"):
            return base
        raw = get_config_value('TOOL_SIMILARITY_THRESHOLD_FULL', None)
        if raw is None or str(raw).strip() == '':
            return base
        try:
            return float(raw)
        except (ValueError, TypeError):
            return base
    if tool_search_query != transcript:
        return base
    raw = get_config_value('TOOL_SIMILARITY_THRESHOLD_FULL', None)
    if raw is None or str(raw).strip() == '':
        return base
    try:
        return float(raw)
    except (ValueError, TypeError):
        return base


def _provider_message_shape(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize provider messages without logging content."""
    by_role: dict[str, int] = {}
    for msg in messages or []:
        role = str(msg.get("role", "unknown"))
        by_role[role] = by_role.get(role, 0) + 1
    return {
        "count": len(messages or []),
        "roles": by_role,
        "has_tool_result": bool(by_role.get("tool")),
        "has_assistant_tool_calls": any(
            msg.get("role") == "assistant" and bool(msg.get("tool_calls"))
            for msg in messages or []
        ),
    }


def _provider_continuation_meta(
    *,
    provider_type: str,
    continuation_mode: str,
    continuation_fallback_reason: str | None,
    previous_response_id: str | None,
    provider_shape: dict[str, Any],
    responses_continuation_payload_items: int = 0,
) -> dict[str, Any]:
    """Build provider-scoped continuation log metadata without cross-provider aliases."""
    previous_present = bool(previous_response_id)
    meta: dict[str, Any] = {
        "provider_continuation_mode": continuation_mode,
        "provider_continuation_fallback_reason": continuation_fallback_reason,
        "provider_previous_response_id_present": previous_present,
        "provider_previous_response_id_used": previous_present,
        "provider_messages_shape": provider_shape,
    }

    if provider_type == "xai":
        meta.update({
            "xai_continuation_mode": continuation_mode,
            "xai_continuation_fallback_reason": continuation_fallback_reason,
            "xai_previous_response_id_present": previous_present,
            "xai_previous_response_id_used": previous_present,
        })
    elif provider_type == "openai":
        meta.update({
            "openai_responses_continuation_payload_items": responses_continuation_payload_items,
            "openai_responses_continuation_mode": continuation_mode,
            "openai_responses_continuation_fallback_reason": continuation_fallback_reason,
        })

    return meta


class LLMRouter:
    """Intelligent router using LLM tool calling."""
    
    def __init__(self, mode='cloud', registry=None, provider_override=None, model_override=None):
        """
        Initialize router with LLM provider.
        
        Args:
            mode: 'cloud' or 'local'
            registry: Optional shared ToolRegistry (prevents duplicate MCP servers)
            provider_override: Optional provider override (for web UI)
            model_override: Optional model override (for web UI)
        """
        self.mode = mode
        self._provider_override = provider_override
        self._model_override = model_override
        load_config(mode)
        
        # Use provided registry or create new one
        if registry:
            self.registry = registry
        else:
            # Backward compatibility: create own registry
            project_root = Path(__file__).parent.parent.resolve()
            mcp_config = str(project_root / "config" / "mcp-servers.json")
            self.registry = ToolRegistry(str(project_root / "skills"), mcp_config)
        
        # Initialize LLM provider
        self.provider = self._create_provider()

        # ``_create_provider`` records the centrally resolved identity. Keep
        # defensive fallbacks for tests and callers that inject/patch a provider.
        if not hasattr(self, "provider_type"):
            self.provider_type = self._provider_override or get_config_value(
                "LLM_PROVIDER",
                "openai" if self.mode == "cloud" else "ollama",
            )
        if not hasattr(self, "model_name"):
            self.model_name = getattr(self.provider, "model", "unknown")

        # Store provider info for metadata tracking
        self.prompt_override = load_model_prompt_override(
            provider=self.provider_type,
            model=self.model_name,
            mode=self.mode,
        )
        
        # Timezone for timestamps (configurable via env)
        self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # Select the stable prompt baseline independently from runtime context,
        # model-specific overlays, and tool schemas.
        self.system_prompt_version, self._system_prompt_base = get_router_system_prompt(
            get_config_value("JARVIS_ROUTER_PROMPT_VERSION", DEFAULT_ROUTER_PROMPT_VERSION)
        )
    
    @property
    def system_prompt(self) -> str:
        """
        Dynamic system prompt with stable instructions first and per-turn
        runtime context appended.
        
        This ensures the LLM knows the CURRENT date/time for:
        - Web searches (use correct year, not training cutoff)
        - Temporal context ("recent", "latest", "this week")
        - Time-sensitive queries ("tomorrow", "next Friday")
        """
        now = datetime.now(self.timezone)
        
        # Get response style - this affects output formatting rules
        response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual').lower()
        qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT)))
        multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
        tool_confirmation_limit = 35
        
        # Build style-aware prefix
        if response_style == 'detailed':
            style_note = """
RESPONSE STYLE: DETAILED (for display/reading - NOT voice synthesis)
- Output will be DISPLAYED, not spoken through TTS
- Markdown formatting IS allowed (links, bold, lists)
- Full URLs with markdown links ARE allowed: [Title](https://...)
- No word limit - provide comprehensive information
- The VOICE OUTPUT RULES section does NOT apply in detailed mode
- For code, commands, config, or multi-line examples: keep headings/explanations OUTSIDE the fence and put only executable/code content inside fenced blocks
- Use fenced code blocks with a language tag when possible: ```bash, ```python, ```json, ```yaml, ```text
- Leave a blank line before and after each fenced block, and always close the fence correctly
- Prefer `##` or `###` section headings in chat responses; reserve top-level `#` for full document-style outputs
- Do not escape backticks unless you are literally explaining markdown syntax
- STRUCTURED TOOL OUTPUT (any tool): If the tool returned JSON with multiple items (arrays such as `results`, `items`, `candidates`, or similar), expand them in the chat: one section per element, same order, using the fields present in each object (markdown links where URLs exist). The chat message is the deliverable—do not substitute a teaser plus "see the tool result", "full output", or the provider name. Do not collapse tail items into ranges like "2–5" or "additional results" unless the user asked for a short summary only. If a field is missing in the payload, say so briefly or omit it—do not invent placeholder text.

"""
        else:
            xai_tts_style_tags_enabled = (
                get_config_value('TTS_PROVIDER', '').strip().lower() == 'xai'
                and get_config_value('XAI_TTS_STYLE_TAGS_ENABLED', 'true').strip().lower()
                in {'1', 'true', 'yes', 'on'}
            )
            xai_tts_style_note = ""
            if xai_tts_style_tags_enabled:
                xai_tts_style_note = """
- xAI TTS is active: you may use supported speech tags sparingly in the final spoken answer when they improve delivery
- Inline sounds: [pause], [long-pause], [hum-tune], [laugh], [chuckle], [giggle], [cry], [tsk], [tongue-click], [lip-smack], [breath], [inhale], [exhale], [sigh]
- Wrapping styles: <soft>...</soft>, <whisper>...</whisper>, <loud>...</loud>, <build-intensity>...</build-intensity>, <decrease-intensity>...</decrease-intensity>, <higher-pitch>...</higher-pitch>, <lower-pitch>...</lower-pitch>, <slow>...</slow>, <fast>...</fast>, <sing-song>...</sing-song>, <singing>...</singing>, <laugh-speak>...</laugh-speak>, <emphasis>...</emphasis>
- Use exact tag syntax: inline tags use square brackets like [pause]; wrapping tags use angle brackets like <slow>text</slow>
- Speech tags are final-answer-only. Never put them in tool arguments, code, URLs, filenames, IDs, prices, data tables, or factual lists. Do not tag every sentence.
"""
            style_note = f"""
RESPONSE STYLE: {response_style.upper()}
- Keep voice output concise using the CURRENT configured runtime limits
- Tool confirmations: brief ({tool_confirmation_limit} words max)
- Q&A/informational: up to {qa_word_limit} words max
- Multi-turn summaries: up to {multi_turn_word_limit} words max
- No URLs for speech unless critical
{xai_tts_style_note}

"""
        
        # Check for native search/tool capabilities
        native_search_note = ""
        xai_search = get_config_value("XAI_SEARCH", "false").lower() == "true"
        xai_code_exec = get_config_value("XAI_CODE_EXECUTION", "true").lower() == "true"
        xai_image_understanding = get_config_value("XAI_IMAGE_UNDERSTANDING", "true").lower() == "true"
        xai_video_understanding = get_config_value("XAI_VIDEO_UNDERSTANDING", "true").lower() == "true"
        anthropic_search = get_config_value("ANTHROPIC_SEARCH", "false").lower() == "true"
        provider_type = str(
            self._provider_override or get_config_value("LLM_PROVIDER", "")
        ).strip().lower()
        
        active_provider = getattr(self, "provider", None)
        xai_native_search_available = (
            provider_type == "xai"
            and bool(getattr(active_provider, "enable_search", False))
            and getattr(active_provider, "xai_client", None) is not None
        )

        if xai_search and xai_native_search_available:
            # Build xAI capabilities note
            capabilities = []
            capabilities.append("- NATIVE WEB/X SEARCH: Use for current info, news, prices - DO NOT use brave_search or mcp_fetch_fetch (crawl_url is OK for specific URL extraction)")

            if xai_image_understanding:
                capabilities.append(
                    "- NATIVE IMAGE UNDERSTANDING: Search can inspect images encountered during web/X browsing via xAI's native view_image capability. For local Jarvis stash:// images, use analyze_image instead."
                )

            if xai_video_understanding:
                capabilities.append(
                    "- NATIVE VIDEO UNDERSTANDING: X search can inspect videos in posts when needed"
                )
            
            if xai_code_exec:
                capabilities.append("""- NATIVE CODE EXECUTION: You have a Python REPL (numpy, pandas, sympy, scipy, matplotlib).
  For complex math, data analysis, or verification: write and run Python code directly.
  Can chain with search: "search for data, then analyze programmatically"
  Use code execution for any math beyond trivial""")
            
            native_search_note = f"""
NATIVE SERVER-SIDE TOOLS ENABLED:
{chr(10).join(capabilities)}
- Results are grounded and cited automatically
- Only use external tools when native capabilities are insufficient
"""
        elif xai_search and provider_type == "xai":
            native_search_note = """
XAI NATIVE SERVER-SIDE TOOLS DISABLED:
- The current xAI authentication/transport does not provide native web/X search or code execution.
- For current information, use the available Jarvis search/fetch tools; do not answer from stale knowledge.
"""
        elif anthropic_search and provider_type == "anthropic":
            native_search_note = """
WEB SEARCH TOOL ENABLED:
You have a special 'web_search' tool for real-time web queries. Use it for current info, news, prices, events.
- Prefer web_search over mcp_fetch_fetch, brave_search, or other external search tools
- crawl_url is OK for extracting content from specific URLs (that's URL extraction, not search)
- web_search is server-side and fast - use it freely for web queries
"""
        else:
            # OpenAI, Ollama, or native search disabled - need external tools for web search
            native_search_note = """
NO NATIVE WEB SEARCH:
For current info, news, prices, events - use external search tools from your available tools:
- brave_search tools (if available) for web queries
- mcp_fetch_fetch (if available) for fetching specific URLs
- crawl_url (if available) for extracting content from URLs
"""
        
        now_utc = datetime.now(ZoneInfo("UTC"))
        runtime_context = f"""RUNTIME CONTEXT FOR THIS TURN:

CURRENT DATE AND TIME:
Local: {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p %Z')}
UTC:   {now_utc.strftime('%A, %B %d, %Y')} at {now_utc.strftime('%H:%M UTC')}
Database times are stored in UTC. Convert to local time when presenting to the user.
Use this for any time-sensitive queries, web searches, or temporal references.
When searching the web, if needed use the CURRENT YEAR ({now.year}) not past years.
{native_search_note}
LIVE FLIGHT STATUS:
For a specific flight's current status, delay, gate, cancellation, arrival, or location, use the generic web-search path available in this mode and profile. Search with the airline name, flight number, and current local date; prefer official airline or airport status pages and cross-check a live flight tracker. Do not use flight_search, if enabled which is only for future fare and itinerary options. If no web-search path is available, say so rather than guessing.
{style_note}"""
        # Default location for weather/location queries only - never override user-specified locations
        location_block = ""
        default_loc = get_config_value("JARVIS_DEFAULT_LOCATION", "").strip()
        default_postal_code = get_config_value("JARVIS_DEFAULT_POSTAL_CODE", "").strip()
        if default_loc:
            postal_line = (
                f'\nConfigured default postal/ZIP code for tools that require one: "{default_postal_code}"'
                if default_postal_code else ""
            )
            location_block = f"""

DEFAULT LOCATION (weather and location-based queries):
When the user asks for weather or location-based info WITHOUT specifying a place, use: "{default_loc}"
{postal_line}
Do NOT use this when the user specifies a different location (e.g. "weather in Seattle" → use Seattle).
Use the postal/ZIP code only for tools or APIs that explicitly need a structured postal code; do not replace the readable location with it.
Time and timezone use JARVIS_TIMEZONE - this is separate."""
        # Light personal touch for fresh conversations using the runtime context.
        greeting_hint = """

PERSONAL TOUCH (new conversations only):
If this appears to be the start of a genuinely fresh conversation, you may add one short natural opener before the main response when it adds warmth/humor/facts. You may lightly draw from the current time, date, season, holiday, observance, or general vibe if it comes naturally from what you already know. Keep it original and brief, and skip it for urgent, transactional, or continuing conversations."""
        base_prompt = "\n\n".join(
            part.strip()
            for part in (
                self._system_prompt_base,
                runtime_context,
                location_block,
                greeting_hint,
            )
            if part and part.strip()
        )
        prompt = apply_prompt_override_sections(
            base_prompt,
            self.prompt_override,
            prepend_sections=("routing_prepend", "tool_calling_prepend"),
            append_sections=("routing_append",),
        )
        return append_profile_card_for_router_direct_answer(prompt)
    
    def _create_provider(self):
        """Create appropriate LLM provider based on config or overrides."""
        self.provider_type, self.model_name, provider = create_configured_provider(
            provider_override=self._provider_override,
            model_override=self._model_override,
            default_provider="openai" if self.mode == "cloud" else "ollama",
            mode=self.mode,
        )
        return provider
    
    def route(
        self,
        transcript: str | ProviderRouteInput,
        excluded_tools: list = None,
        typo_hint_source: str | None = None,
        disable_server_side_tools: bool = False,
        routing_provenance: dict[str, Any] | None = None,
        server_side_max_tool_turns: int | None = None,
        previous_response_id: str | None = None,
        tool_rag_limit: int | None = None,
        tool_policy: str = "auto",
    ) -> dict[str, Any]:
        """
        Use LLM to determine intent and route appropriately.
        
        Args:
            transcript: Full routing prompt (intelligence, multi-turn context, etc.)
            excluded_tools: Optional list of tool names to exclude from selection
            typo_hint_source: Raw user request text for typo-RAG token scan only (embedding still uses full tool search string).
            
        Returns:
            dict: Routing decision
            {
                "intent": "tool" | "qa",
                "tool_name": str (if tool),
                "arguments": dict (if tool),
                "text_response": str (if qa),
                "confidence": float
            }
        """
        self._excluded_tools = excluded_tools or []
        chat_only = tool_policy == "none"
        disable_server_side_tools = disable_server_side_tools or chat_only
        if isinstance(transcript, ProviderRouteInput):
            route_input = transcript
            transcript_text = route_input.tool_retrieval_query
            provider_messages = route_input.messages
            provider_system_prompt = route_input.system_prompt
            route_previous_response_id = route_input.previous_response_id
            responses_continuation_input = route_input.responses_continuation_input
            provider_shape = _provider_message_shape(provider_messages)
            continuation_meta = _provider_continuation_meta(
                provider_type=getattr(self, "provider_type", ""),
                continuation_mode=route_input.continuation_mode,
                continuation_fallback_reason=route_input.continuation_fallback_reason,
                previous_response_id=route_input.previous_response_id,
                provider_shape=provider_shape,
                responses_continuation_payload_items=len(responses_continuation_input or [])
                if responses_continuation_input
                else 0,
            )
        else:
            transcript_text = transcript
            provider_messages = [{"role": "user", "content": transcript_text}]
            provider_system_prompt = self.system_prompt
            route_previous_response_id = previous_response_id
            responses_continuation_input = None
            provider_shape = _provider_message_shape(provider_messages)
            continuation_meta = _provider_continuation_meta(
                provider_type=getattr(self, "provider_type", ""),
                continuation_mode="text_fallback",
                continuation_fallback_reason=None,
                previous_response_id=previous_response_id,
                provider_shape=provider_shape,
                responses_continuation_payload_items=0,
            )
        if chat_only:
            provider_system_prompt = "\n\n".join(
                part for part in (provider_system_prompt, _CHAT_ONLY_SYSTEM_POLICY) if part
            )
        
        # Only print if in interactive mode
        if sys.stdout.isatty():
            print(f"🧠 Routing with LLM: '{transcript_text}'")
        
        # DYNAMIC TOOL RETRIEVAL (The "Tool RAG" System)
        # Instead of loading all tools, we find only the relevant ones
        
        # 1. Determine final Tool RAG schema cap based on mode/request.
        # This cap is applied again after ghost/signal merging.
        if chat_only:
            retrieval_limit = 0
            enabled_tool_names = []
            tool_signals = ToolRetrievalSignals(
                query="",
                source="disabled_by_policy",
                notes=["tool_policy=none; Tool RAG retrieval skipped"],
            )
            tool_search_query = ""
            tool_sim_threshold = 0.0
            relevant_tools = []
        else:
            retrieval_limit = _resolve_tool_rag_limit(self.mode, tool_rag_limit)

            # 2. Build a Tool RAG retrieval view. The routing LLM still receives the
            # full transcript, but embeddings use a compact task-shaped query plus
            # structured exact tool signals from hints/intelligence.
            enabled_tool_names = list(self.registry.tools.keys())
            tool_signals = build_tool_retrieval_signals(transcript_text, enabled_tool_names)
            tool_search_query = tool_signals.query
            tool_sim_threshold = _tool_rag_similarity_threshold(
                transcript_text,
                tool_search_query,
                tool_signals.source,
            )

            # 3. Find relevant tools using vector search
            # This returns ToolSchema objects for the top matches + ghost tools
            relevant_tools = self.registry.find_tools(
                tool_search_query,
                limit=retrieval_limit,
                similarity_threshold=tool_sim_threshold,
                typo_hint_source=typo_hint_source,
            )
        ranked_tool_trace: list[dict[str, Any]] = []
        if not chat_only and get_bool("TOOL_RAG_TRACE_ENABLED", True):
            try:
                from memory_db import get_memory_db
                from tool_rag_typo_hints import expand_tool_rag_query_for_typo_hints

                db = get_memory_db()
                try:
                    rag_trace_query, _ = expand_tool_rag_query_for_typo_hints(
                        tool_search_query,
                        enabled_tool_names,
                        hint_source=typo_hint_source,
                    )
                    ranked_tool_trace = db.search_tools(rag_trace_query, limit=100, threshold=0.0)
                finally:
                    db.close()
            except Exception as trace_error:
                if os.environ.get("JARVIS_DEBUG"):
                    print(f"DEBUG: Tool RAG rank trace unavailable: {trace_error}", file=sys.stderr)
        
        # Filter out excluded tools (e.g., tools blocked for web mode)
        if self._excluded_tools:
            original_count = len(relevant_tools)
            relevant_tools = [t for t in relevant_tools if t.name not in self._excluded_tools]
            if len(relevant_tools) < original_count:
                excluded = set(self._excluded_tools) & set(
                    t.name
                    for t in self.registry.find_tools(
                        tool_search_query,
                        limit=retrieval_limit,
                        similarity_threshold=tool_sim_threshold,
                        typo_hint_source=typo_hint_source,
                    )
                )
                if sys.stdout.isatty():
                    print(f"   🚫 Excluded tools: {', '.join(excluded)}")
        
        # Separate ghost tools from retrieved tools for visibility
        from config_loader import get_config_value
        ghost_tools_str = get_config_value('GHOST_TOOLS', 'search_memory,update_memory,semantic_recall,remember,canvas')
        ghost_list = (
            []
            if chat_only
            else _merged_ghost_tool_names(ghost_tools_str, set(enabled_tool_names))
        )

        initial_tool_names = [t.name for t in relevant_tools]
        merged_tool_names, signal_meta = merge_tool_signal_names(
            initial_tool_names,
            tool_signals,
            enabled_tool_names,
            ghost_tools=ghost_list,
            excluded_tools=self._excluded_tools,
        )
        if merged_tool_names != initial_tool_names:
            by_name = {t.name: t for t in relevant_tools}
            merged_tools = []
            for name in merged_tool_names:
                tool = by_name.get(name) or self.registry.get_tool(name)
                if tool:
                    merged_tools.append(tool)
            relevant_tools = merged_tools

        uncapped_tool_names = [t.name for t in relevant_tools]
        capped_tool_names = _cap_tool_names_for_schema(
            uncapped_tool_names,
            retrieval_limit,
            positive_tools=tool_signals.positive_tools,
            ghost_tools=ghost_list,
        )
        if capped_tool_names != uncapped_tool_names:
            by_name = {t.name: t for t in relevant_tools}
            relevant_tools = [
                by_name[name]
                for name in capped_tool_names
                if name in by_name
            ]
            signal_meta["capped_to"] = [str(retrieval_limit)]
            signal_meta["dropped_by_cap"] = [
                name for name in uncapped_tool_names if name not in capped_tool_names
            ]
        
        tool_names = [t.name for t in relevant_tools]
        retrieved = [name for name in tool_names if name not in ghost_list]
        ghosts = [name for name in tool_names if name in ghost_list]
        
        if sys.stdout.isatty():
            print(f"📚 Loaded {len(tool_names)} tools ({len(retrieved)} retrieved + {len(ghosts)} ghost)")
            if retrieved:
                print(f"   Retrieved: {', '.join(retrieved)}")
            if ghosts:
                print(f"   👻 Ghost: {', '.join(ghosts)}")
        
        # ALWAYS log tool retrieval details for debugging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info(f"[TOOL_RAG] Tool search query: {tool_search_query}")
        logger.info(
            f"[TOOL_RAG] similarity_threshold={tool_sim_threshold:.4f} "
            f"(source={tool_signals.source}, full_transcript_embedding={tool_search_query == transcript_text})"
        )
        _log_tool_rag_signal_meta(logger, signal_meta)
        if tool_signals.notes:
            logger.info(f"[TOOL_RAG] signal_notes={tool_signals.notes}")
        logger.info(f"[TOOL_RAG] Retrieved {len(retrieved)} tools: {retrieved}")
        logger.info(f"[TOOL_RAG] Ghost tools: {ghosts}")
        logger.info(f"[TOOL_RAG] Total tools sent to LLM: {len(tool_names)}")
        
        # 3. Convert to provider-specific format
        if hasattr(self.provider, '__class__') and 'Anthropic' in self.provider.__class__.__name__:
            tools = [t.to_anthropic_format() for t in relevant_tools]
        else:
            tools = [t.to_openai_format() for t in relevant_tools]
        
        # For Ollama, convert to Anthropic-like format (simpler)
        if hasattr(self.provider, '__class__') and 'Ollama' in self.provider.__class__.__name__:
            tools = [t.to_anthropic_format() for t in relevant_tools]
        schema_payload = (
            {"chars": 0, "est_tokens": 0, "top": []}
            if chat_only
            else _estimate_tool_schema_payload(tools)
        )
        _log_tool_rag_trace(
            mode=self.mode,
            provider=getattr(self, "provider_type", "unknown"),
            model=getattr(self, "model_name", "unknown"),
            transcript=transcript_text,
            query=tool_search_query,
            threshold=tool_sim_threshold,
            retrieval_limit=retrieval_limit,
            signal_source=tool_signals.source,
            signal_meta=signal_meta,
            signal_notes=tool_signals.notes,
            ranked_tools=ranked_tool_trace,
            final_tools=tool_names,
            ghost_tools=ghost_list,
            excluded_tools=self._excluded_tools,
            router_prompt_version=getattr(self, "system_prompt_version", DEFAULT_ROUTER_PROMPT_VERSION),
            system_prompt_chars=len(provider_system_prompt or ""),
            system_prompt_est_tokens=(
                max(1, round(len(provider_system_prompt) / 4))
                if provider_system_prompt else 0
            ),
            system_prompt_sent=provider_system_prompt is not None,
            tool_schema_chars=schema_payload["chars"],
            tool_schema_est_tokens=schema_payload["est_tokens"],
            tool_schema_top=schema_payload["top"],
            tool_rag_skipped=chat_only,
        )
        
        try:
            # Check if thinking mode is enabled
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
            from thinking import should_enable_thinking
            enable_thinking = should_enable_thinking()
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Router calling provider.chat_with_tools (thinking={enable_thinking})", file=sys.stderr)
            
            # Track LLM call timing
            import time
            llm_start_time = time.time()
            
            with _provider_runtime_tool_scope(
                disable_server_side_tools=disable_server_side_tools,
                server_side_max_tool_turns=server_side_max_tool_turns,
            ):
                text_response, tool_call, usage_info, thinking = self.provider.chat_with_tools(
                    messages=provider_messages,
                    tools=tools,
                    system_prompt=provider_system_prompt,
                    enable_thinking=enable_thinking,
                    previous_response_id=route_previous_response_id,
                    responses_continuation_input=responses_continuation_input,
                )

            dh = getattr(self.provider, "_openai_responses_diag_holder", None)
            if isinstance(dh, dict) and dh:
                continuation_meta.update(
                    {
                        key: dh[key]
                        for key in dh
                        if str(key).startswith("openai_")
                    }
                )
            
            llm_duration_ms = (time.time() - llm_start_time) * 1000
            provider_error = text_response if is_provider_error_text(text_response) else None
            provider_error_info = classify_provider_error(provider_error) if provider_error else None
            logged_response_text = provider_error_info.raw_preview if provider_error_info else text_response
            
            # Log LLM call for monitoring
            try:
                from llm_logger import get_logger
                llm_logger = get_logger(self.mode)
                llm_logger.log_llm_call(
                    provider=self.provider_type,
                    model=self.model_name,
                    prompt_type="routing",
                    messages=provider_messages,
                    response_text=logged_response_text,
                    tool_call=tool_call,
                    usage_info=usage_info,
                    thinking=thinking,
                    duration_ms=llm_duration_ms,
                    mode=self.mode,
                    user_query=transcript_text,
                    routing_provenance={
                        **(routing_provenance or {}),
                        "router_prompt": {
                            "version": getattr(
                                self,
                                "system_prompt_version",
                                DEFAULT_ROUTER_PROMPT_VERSION,
                            ),
                            "chars": len(provider_system_prompt or ""),
                            "sent": provider_system_prompt is not None,
                        },
                        "provider_route": continuation_meta,
                    },
                    error=provider_error_info.raw_preview if provider_error_info else None
                )
            except Exception as e:
                if os.environ.get('JARVIS_DEBUG'):
                    print(f"DEBUG: Failed to log LLM call: {e}", file=sys.stderr)
            
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Provider returned: tool_call={tool_call is not None}, usage={usage_info is not None}, thinking={thinking is not None}", file=sys.stderr)

            if provider_error:
                openai_structural = bool(responses_continuation_input) and bool(route_previous_response_id)
                if openai_structural:
                    return {
                        "intent": "error",
                        "error": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                        "text_response": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                        "confidence": 0.0,
                        "usage_info": usage_info,
                        "available_tools": tool_names,
                        "provider_error_raw": provider_error_info.raw_preview if provider_error_info else provider_error,
                        "openai_continuation_error": True,
                        "xai_continuation_error": False,
                        **continuation_meta,
                    }
                xai_continuation_error = bool(route_previous_response_id)
                if xai_continuation_error:
                    return {
                        "intent": "error",
                        "error": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                        "text_response": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                        "confidence": 0.0,
                        "usage_info": usage_info,
                        "available_tools": tool_names,
                        "provider_error_raw": provider_error_info.raw_preview if provider_error_info else provider_error,
                        "xai_continuation_error": True,
                        **continuation_meta,
                    }
                fallback = self._provider_error_fallback_route(
                    transcript=transcript_text,
                    error_text=provider_error,
                    tool_names=tool_names,
                    usage_info=usage_info,
                )
                if fallback:
                    return fallback
                return {
                    "intent": "error",
                    "error": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                    "text_response": provider_error_info.friendly_message if provider_error_info else friendly_provider_error(provider_error),
                    "confidence": 0.0,
                    "usage_info": usage_info,
                    "available_tools": tool_names,
                    "provider_error_raw": provider_error_info.raw_preview if provider_error_info else provider_error,
                    "xai_continuation_error": False,
                    **continuation_meta,
                }
            
            # Log provider-native/server-side tool usage.
            if usage_info and usage_info.get('server_side_tools'):
                server_tools = usage_info['server_side_tools']
                tool_list = [f"{k.replace('SERVER_SIDE_TOOL_', '').lower()}({v}x)" for k, v in server_tools.items() if v > 0]
                if tool_list:
                    provider_label = {
                        "xai": "xAI",
                        "openai": "OpenAI",
                        "anthropic": "Anthropic",
                    }.get(str(self.provider_type).lower(), str(self.provider_type or "Provider"))
                    logger.info(
                        f"[{provider_label} SERVER-SIDE TOOLS] "
                        f"Native/hosted tools used: {', '.join(tool_list)}"
                    )
            
            # Tool was called
            if tool_call:
                response = {
                    "intent": "tool",
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "confidence": 1.0,
                    "usage_info": usage_info,  # Include token/cost data
                    "available_tools": tool_names,  # Tools shown to LLM for reflection
                    **continuation_meta,
                }
                for metadata_key in ("id", "tool_call_id", "response_id"):
                    if tool_call.get(metadata_key):
                        response[metadata_key] = tool_call[metadata_key]
                if response.get("response_id"):
                    response["response_created_at_iso"] = datetime.now().isoformat()
                    response["response_model"] = self.model_name
                    response["response_provider"] = self.provider_type
                
                # Add thinking if present
                if thinking:
                    response["thinking"] = thinking
                    
                    # Log thinking for analysis
                    try:
                        from thinking import log_thinking
                        log_thinking(
                            query=transcript_text,
                            thinking=thinking,
                            decision={
                                "tool": tool_call["name"],
                                "arguments": tool_call["arguments"],
                                "saved": tool_call["name"] == "remember"
                            },
                            provider=getattr(self, 'provider_type', 'unknown'),
                            model=getattr(self, 'model_name', 'unknown')
                        )
                    except Exception as e:
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Failed to log thinking: {e}", file=sys.stderr)
                
                # Detect OpenCode agent mode if using opencode tool
                if response.get("tool_name") == "opencode":
                    response = self._detect_opencode_mode(transcript_text, response)
                
                return response
            
            # Direct text response (Q&A)
            else:
                response = {
                    "intent": "qa",
                    "text_response": text_response or "I'm not sure how to respond to that.",
                    "confidence": 1.0,
                    "usage_info": usage_info,  # Include token/cost data
                    "available_tools": tool_names,  # Tools shown to LLM for reflection
                    **continuation_meta,
                }
                
                # Add thinking if present
                if thinking:
                    response["thinking"] = thinking
                    
                    # Log thinking for analysis
                    try:
                        from thinking import log_thinking
                        log_thinking(
                            query=transcript_text,
                            thinking=thinking,
                            decision={
                                "tool": "none",
                                "response_type": "qa",
                                "saved": False
                            },
                            provider=getattr(self, 'provider_type', 'unknown'),
                            model=getattr(self, 'model_name', 'unknown')
                        )
                    except Exception as e:
                        if os.environ.get('JARVIS_DEBUG'):
                            print(f"DEBUG: Failed to log thinking: {e}", file=sys.stderr)
                
                return response
        
        except Exception as e:
            print(f"❌ Router error: {e}")
            return {
                "intent": "error",
                "error": str(e),
                "text_response": "Sorry, I had trouble processing your request.",
                "confidence": 0.0
            }

    def _provider_error_fallback_route(
        self,
        transcript: str,
        error_text: str,
        tool_names: list[str],
        usage_info: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """
        Deterministic fallback for provider/API failures before routing completes.

        This keeps obvious tool requests from surfacing raw provider errors when
        the model refuses the routing prompt itself.
        """
        error_info = classify_provider_error(error_text)
        for tool in self._deterministic_fallback_tools(tool_names):
            routing = getattr(tool, "deterministic_routing", {}) or {}
            fallbacks = routing.get("provider_error_fallbacks") or []
            if not isinstance(fallbacks, list):
                continue

            for fallback in fallbacks:
                if not self._provider_error_fallback_applies(fallback, error_info.kind):
                    continue
                arguments = self._arguments_from_deterministic_fallback(transcript, fallback)
                if arguments is None:
                    continue
                return {
                    "intent": "tool",
                    "tool_name": tool.name,
                    "arguments": arguments,
                    "confidence": 0.7,
                    "usage_info": usage_info,
                    "available_tools": tool_names,
                    "provider_error_recovered": True,
                    "provider_error_kind": error_info.kind,
                    "provider_error": error_info.friendly_message,
                }
        return None

    def _deterministic_fallback_tools(self, tool_names: list[str]) -> list[Any]:
        """Return tools with deterministic fallback metadata, preferring RAG order."""
        tools_by_name = getattr(self.registry, "tools", {}) or {}
        get_tool = getattr(self.registry, "get_tool", None)
        seen = set()
        ordered = []

        def add_tool(tool):
            if not tool or getattr(tool, "name", None) in seen:
                return
            if not (getattr(tool, "deterministic_routing", {}) or {}).get("provider_error_fallbacks"):
                return
            seen.add(tool.name)
            ordered.append(tool)

        for name in tool_names or []:
            tool = tools_by_name.get(name)
            if not tool and callable(get_tool):
                try:
                    tool = get_tool(name)
                except Exception:
                    tool = None
            add_tool(tool)

        for tool in tools_by_name.values():
            add_tool(tool)

        return ordered

    @staticmethod
    def _provider_error_fallback_applies(fallback: dict[str, Any], error_kind: str) -> bool:
        """Return True when a deterministic fallback rule applies to this provider error kind."""
        if not isinstance(fallback, dict):
            return False
        allowed = fallback.get("error_kinds")
        if allowed is None:
            return True
        if isinstance(allowed, str):
            allowed = [allowed]
        if not isinstance(allowed, list):
            return False
        return error_kind in {str(kind).strip().lower() for kind in allowed}

    @staticmethod
    def _arguments_from_deterministic_fallback(transcript: str, fallback: dict[str, Any]) -> dict[str, Any] | None:
        """Build tool arguments from a deterministic fallback rule."""
        if not isinstance(fallback, dict):
            return None
        fallback_type = fallback.get("type", "regex")
        if fallback_type != "regex":
            return None

        pattern = fallback.get("pattern")
        if not pattern:
            return None
        try:
            match = re.search(pattern, transcript or "")
        except re.error:
            return None
        if not match:
            return None

        matched = match.group(1) if match.groups() else match.group(0)
        strip_trailing = fallback.get("strip_trailing")
        if isinstance(strip_trailing, str):
            matched = matched.rstrip(strip_trailing)

        arguments_template = fallback.get("arguments") or {}
        if not isinstance(arguments_template, dict):
            return None

        arguments = {}
        for key, value in arguments_template.items():
            if value == "$match":
                arguments[key] = matched
            elif isinstance(value, str) and value.startswith("$group:"):
                try:
                    arguments[key] = match.group(int(value.split(":", 1)[1]))
                except Exception:
                    return None
            else:
                arguments[key] = value
        return arguments or None
    
    def _detect_opencode_mode(self, query: str, response: dict) -> dict:
        """
        Detect if OpenCode should use 'plan' or 'build' mode based on query intent.
        
        Plan mode: Analysis, suggestions, review (read-only)
        Build mode: Create, modify, build, deploy (default)
        """
        query_lower = query.lower()
        
        # Keywords that indicate analysis/planning (plan mode)
        plan_keywords = [
            "analyze", "review", "suggest", "recommend", 
            "what should", "how should", "advice", "best practice",
            "explain", "show me", "tell me about", "plan for",
            "describe", "list reasons", "compare", "evaluate"
        ]
        
        # Keywords that indicate building (build mode - default)
        # Note: "check", "code", "fix" removed - can be analysis or building
        build_keywords = [
            "create", "build", "make", "write", "implement",
            "deploy", "setup", "configure", "generate", "add",
            "modify", "change", "update", "install"
        ]
        
        # Check if it's clearly a plan/analysis task
        if any(keyword in query_lower for keyword in plan_keywords):
            # But only if NOT also asking to build something
            if not any(keyword in query_lower for keyword in build_keywords):
                if "arguments" not in response:
                    response["arguments"] = {}
                response["arguments"]["agent_mode"] = "plan"
                return response
        
        # Default to build mode (most OpenCode tasks involve creating/modifying)
        if "arguments" not in response:
            response["arguments"] = {}
        response["arguments"]["agent_mode"] = "build"
        
        return response


def main():
    """CLI interface for testing."""
    import json
    
    if len(sys.argv) < 2:
        print("Usage: router_v2.py <mode> <transcript>", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    transcript = " ".join(sys.argv[2:])
    
    router = LLMRouter(mode)
    result = router.route(transcript, typo_hint_source=transcript)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
