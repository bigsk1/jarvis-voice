"""Reviewed tool failures that may continue the current research loop.

An empty search is still a failed tool result. Only recognized read-only
provider responses qualify; neither arbitrary error prose nor a tool-supplied
classification can opt a mutation or a genuine service failure into recovery.
"""

from __future__ import annotations

import re
from typing import Any

EMPTY_SEARCH_RECOVERY_HINT = (
    "That query returned no results. Broaden the query, use another search source, "
    "or answer from evidence already gathered. Do not repeat the identical call "
    "or treat this failed lookup as successful evidence."
)

# Keep this allowlist tied to reviewed, read-only producer contracts. Yelp
# already returns successful empty searches and needs no failure exception.
_EMPTY_SEARCH_ERRORS = {
    "serpapi_google_events": re.compile(
        r"(?:serpapi google events error:\s*)?(?:serpapi error:\s*)?"
        r"google hasn't returned any results for this query\.?",
        re.IGNORECASE,
    ),
}


def is_recoverable_empty_search(tool_name: str, result: object) -> bool:
    """Recognize a known empty lookup without reclassifying other failures.

    Incident enrichment runs in the executor first. Nonempty data or explicit
    failure/lifecycle flags take precedence over a matching legacy error text.
    Additional tools require an explicit reviewed allowlist entry here.
    """
    pattern = _EMPTY_SEARCH_ERRORS.get(tool_name)
    if pattern is None or not isinstance(result, dict) or result.get("ok") is not False:
        return False
    if any(result.get(key) for key in (
        "error_code", "failure_reason", "terminal_failure", "cancelled", "completion",
    )):
        return False
    if result.get("retry_safe", True) is not True:
        return False
    if result.get("result_kind", "tool_result") != "tool_result":
        return False
    data = result.get("data")
    if data is not None and data != {}:
        return False
    error = result.get("error")
    return isinstance(error, str) and pattern.fullmatch(error.strip()) is not None


def has_only_empty_search_results(conversation_context: list[dict[str, Any]]) -> bool:
    """Identify misses plus their own blocked repeats, without hiding other work."""
    empty_calls = []
    for item in conversation_context:
        if not isinstance(item, dict):
            return False
        tool_name = item.get("tool")
        result = item.get("result")
        if isinstance(tool_name, str) and is_recoverable_empty_search(tool_name, result):
            empty_calls.append((tool_name, item.get("arguments", {})))
            continue

        arguments = item.get("arguments")
        meta = item.get("meta")
        if not (
            tool_name == "duplicate_guard"
            and isinstance(result, dict) and result.get("ok") is False
            and isinstance(arguments, dict)
            and arguments.get("reason") == "exact duplicate"
            and isinstance(arguments.get("blocked_arguments"), dict)
            and isinstance(meta, dict)
            and meta.get("source") == "duplicate_guard"
            and meta.get("freshness") == "duplicate_guard"
        ):
            return False
        data = result.get("data")
        if not isinstance(data, dict) or any(
            data.get(key) != arguments.get(key)
            for key in ("blocked_tool", "blocked_arguments", "reason")
        ):
            return False
        if not any(
            arguments.get("blocked_tool") == name and arguments["blocked_arguments"] == args
            for name, args in empty_calls
        ):
            return False
    return bool(empty_calls)
