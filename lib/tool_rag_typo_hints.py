#!/usr/bin/env python3
"""
Optional typo hints for Tool RAG embedding queries only.

Appends canonical tool names to the *retrieval* string when a user token is
1–2 edits (optimal string alignment / Damerau-style transpositions) from:
  - an enabled tool's full name, or
  - a snake_case / kebab segment of that name (e.g. "bookmark" in "bookmark_search"),
so near-misses like "bookmakrs" still surface the right tool.

Ties (multiple tools at the same minimum distance) are skipped.

``hint_source`` (wired from the orchestrator as the sanitized user line) limits which
tokens are candidate-matched; the full Tool-RAG string is still embedded, with hints
appended.

Does not modify the user-visible transcript.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from config_loader import get_bool, get_int

logger = logging.getLogger(__name__)

# Token must be at least this long to consider (avoids "ab" → many hits).
_DEFAULT_MIN_TOKEN_LEN = 4
_DEFAULT_MAX_DISTANCE = 1
_GENERIC_SEGMENTS = frozenset(
    {
        "api",
        "apis",
        "call",
        "calls",
        "check",
        "checks",
        "data",
        "doc",
        "docs",
        "email",
        "emails",
        "fetch",
        "file",
        "files",
        "find",
        "get",
        "image",
        "images",
        "intel",
        "list",
        "lists",
        "log",
        "logs",
        "manage",
        "memory",
        "network",
        "price",
        "prices",
        "query",
        "recent",
        "recall",
        "reminder",
        "reminders",
        "search",
        "service",
        "session",
        "sessions",
        "stock",
        "stocks",
        "system",
        "time",
        "tool",
        "tools",
        "update",
        "url",
        "urls",
        "video",
        "videos",
        "weather",
        "web",
        "webhook",
    }
)


def optimal_string_alignment_distance(a: str, b: str) -> int:
    """
    Optimal string alignment distance (Damerau variant with adjacent transpositions only).
    Classic O(nm) DP; suitable for short tool names.
    """
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    # d[i][j] = distance between first i chars of a and first j chars of b
    d: list[list[int]] = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            best = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, d[i - 2][j - 2] + 1)
            d[i][j] = best
    return d[la][lb]


def _strip_url_like_spans(text: str) -> str:
    """
    Remove URL-like spans before tokenization so host/path pieces are not typo-scanned
    (e.g. https://weathr.com → no separate "weathr" token).
    """
    t = re.sub(r"https?://[^\s]+", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"\bwww\.[^\s]+", " ", t, flags=re.IGNORECASE)
    return t


def _tokenize_for_typo_scan(query: str) -> list[str]:
    """Alphanumeric + underscore tokens (tool names are snake_case)."""
    return re.findall(r"[A-Za-z0-9_]+", query)


def _tool_name_candidates(name: str, min_segment_len: int) -> list[tuple[str, bool]]:
    """Full lower name plus distinctive underscore/hyphen segments long enough to compare."""
    out: list[tuple[str, bool]] = [(name.lower(), False)]
    for seg in re.split(r"[_-]+", name):
        seg = seg.lower()
        if len(seg) < min_segment_len or seg in _GENERIC_SEGMENTS:
            continue
        out.append((seg, True))
    # Preserve order, dedupe
    seen: set[tuple[str, bool]] = set()
    uniq: list[tuple[str, bool]] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _best_typo_distance_for_tool(
    token_lower: str,
    name: str,
    max_distance: int,
    min_segment_len: int,
) -> int | None:
    """
    Minimum edit distance from token to full tool name or a long segment.
    Returns None if no distance in [1, max_distance]; 0 means exact match (caller skips hint).
    """
    best: int | None = None
    for c, is_segment in _tool_name_candidates(name, min_segment_len):
        allowed_distance = min(max_distance, 1) if is_segment else max_distance
        d = optimal_string_alignment_distance(token_lower, c)
        if d == 0:
            return 0
        if 1 <= d <= allowed_distance:
            if best is None or d < best:
                best = d
    return best


def _best_unique_tool_for_token(
    token_lower: str,
    tool_names: list[str],
    max_distance: int,
    min_segment_len: int,
) -> str | None:
    """
    Return the single canonical tool name if exactly one tool achieves the global minimum
    distance in [1, max_distance] (against full name or segments). Ties → None.
    """
    per_tool: list[tuple[str, int]] = []
    for name in tool_names:
        bd = _best_typo_distance_for_tool(token_lower, name, max_distance, min_segment_len)
        if bd is None or bd == 0:
            continue
        per_tool.append((name, bd))

    if not per_tool:
        return None
    min_d = min(d for _, d in per_tool)
    at_min = [n for n, d in per_tool if d == min_d]
    if len(at_min) != 1:
        return None
    return at_min[0]


def expand_tool_rag_query_for_typo_hints(
    query: str,
    enabled_tool_names: Iterable[str],
    *,
    hint_source: str | None = None,
    max_distance: int | None = None,
    min_token_len: int | None = None,
    enabled: bool | None = None,
) -> tuple[str, list[str]]:
    """
    Append rare typo hints to the Tool RAG embedding query only.

    Args:
        query: Full text embedded for vector search (may include intelligence/context).
        enabled_tool_names: Enabled tool names (canonical casing from registry).
        hint_source: If set, only tokens from this string (e.g. current user request)
            are considered for typo/near-segment matching. Hints are still appended
            to ``query``. If unset or empty, all tokens in ``query`` are scanned
            (legacy behavior for tests and single-line debug queries).
        max_distance: Default from TOOL_RAG_TYPO_MAX_DISTANCE or 1.
        min_token_len: Default from TOOL_RAG_TYPO_MIN_TOKEN_LEN or 4.
        enabled: Default from TOOL_RAG_TYPO_ENABLED or True.

    Returns:
        (embedding_query, list of canonical tool names appended for logging)
    """
    if enabled is None:
        enabled = get_bool("TOOL_RAG_TYPO_ENABLED", True)
    if not enabled:
        return query, []

    if max_distance is None:
        max_distance = int(get_int("TOOL_RAG_TYPO_MAX_DISTANCE", _DEFAULT_MAX_DISTANCE))
    max_distance = max(1, min(max_distance, 3))

    if min_token_len is None:
        min_token_len = int(get_int("TOOL_RAG_TYPO_MIN_TOKEN_LEN", _DEFAULT_MIN_TOKEN_LEN))
    min_token_len = max(2, min_token_len)

    max_hints = int(get_int("TOOL_RAG_TYPO_MAX_HINTS", 5))
    max_hints = max(1, min(max_hints, 20))

    names = list(enabled_tool_names)

    # Strip URLs first so host/path tokens are not typo-matched (e.g. weathr inside a URL).
    basis = (hint_source or "").strip()
    if basis:
        scan_text = _strip_url_like_spans(basis)
    else:
        scan_text = _strip_url_like_spans(query)
    tokens = _tokenize_for_typo_scan(scan_text)
    hints_ordered: list[str] = []
    seen_hint: set[str] = set()

    # Skip bare scheme tokens if they appear as words
    _skip_words = frozenset({"http", "https", "ftp"})

    for raw in tokens:
        if len(hints_ordered) >= max_hints:
            break
        if len(raw) < min_token_len:
            continue
        tl = raw.lower()
        if tl in _skip_words:
            continue
        canonical = _best_unique_tool_for_token(tl, names, max_distance, min_token_len)
        if canonical and canonical not in seen_hint:
            seen_hint.add(canonical)
            hints_ordered.append(canonical)

    if not hints_ordered:
        return query, []

    # Small separator so embedding model sees extra signal without huge bloat
    augmented = f"{query} {' '.join(hints_ordered)}".strip()
    logger.debug(
        "[TOOL_RAG] typo_rag_hints=%s",
        hints_ordered,
    )
    return augmented, hints_ordered
