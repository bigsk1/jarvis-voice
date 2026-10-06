"""Request-local bookkeeping shared by the tool loop and its failure retries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _initial_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        # Peak logical context does not double-count repeated prompt history.
        "model_calls": 0,
        "peak_context_tokens": 0,
        "cost_usd": 0.0,
        # Subscription/compute-metered usage can have an unknown dollar cost.
        "has_unknown_cost": False,
        "cost_known": True,
        "billing_mode": None,
        "input_estimated": False,
        "cache_creation_tokens": 0,
        "cache_creation_5m_tokens": 0,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_cost_usd": 0.0,
        "cache_read_cost_usd": 0.0,
        "cache_cost_usd": 0.0,
        "cache_savings_usd": 0.0,
        "server_side_tools": {},
    }


@dataclass
class TurnState:
    """Own one in-flight request's state, including recursive tool-failure retries.

    A fresh process() call creates a fresh instance; this is never stored on the
    orchestrator or persisted. Routing, execution, and response-shaping policy
    remain in the orchestrator, including whether a result counts as completed.
    """

    vision_pre_analyzed: bool = False
    conversation_context: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    accumulated_data: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    # Accepted background calls block redispatch but are not completed tool work.
    seen_tool_calls: set[tuple[str, str]] = field(default_factory=set)
    blocked_duplicate_calls: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    duplicate_recovery_attempts: int = 0
    max_duplicate_recovery_attempts: int = 2
    total_usage: dict[str, Any] = field(default_factory=_initial_usage)
    first_thinking: str | None = None
    available_tools: list[dict[str, Any]] = field(default_factory=list)
    web_search_hint_tools: set[str] = field(default_factory=set)
    xai_previous_response_id: str | None = None
    xai_provider_continuation: dict[str, Any] | None = None
    xai_text_fallback_retry_used: bool = False
    openai_previous_response_id: str | None = None
    openai_provider_continuation: dict[str, Any] | None = None
    openai_text_fallback_retry_used: bool = False
    start_turn_num: int = 0

    def next_call_index(self, tool_name: str) -> int:
        """Allocate before approval/execution, preserving per-tool event numbering."""
        call_index = self.tool_call_counts.get(tool_name, 0)
        self.tool_call_counts[tool_name] = call_index + 1
        return call_index

    def for_retry(self, completed_turn_num: int) -> TurnState:
        """Continue this request after a failed turn without resetting its budget."""
        self.start_turn_num = completed_turn_num + 1
        return self
