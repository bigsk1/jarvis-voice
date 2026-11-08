"""Only reviewed empty searches may continue without weakening failure evidence."""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lib.tool_failure_policy import (
    EMPTY_SEARCH_RECOVERY_HINT,
    has_only_empty_search_results,
    is_recoverable_empty_search,
)
from orchestrator.context_assembler import ContextAssembler

TOOL = "serpapi_google_events"
EMPTY_MESSAGE = "Google hasn't returned any results for this query"
NOW = datetime(2026, 11, 7, 18, 0, tzinfo=ZoneInfo("UTC"))


def _empty_result(**overrides):
    return {"ok": False, "error": EMPTY_MESSAGE, "speech": EMPTY_MESSAGE, **overrides}


def _assembler():
    def no_database():
        raise AssertionError("empty-search projection must not access live memory")

    return ContextAssembler(
        timezone_obj=ZoneInfo("UTC"),
        auto_context_window=3,
        auto_context_minutes=10,
        safe_iso_to_local_datetime=lambda value: datetime.fromisoformat(value) if value else None,
        format_age_seconds=lambda value: str(value),
        format_gap_for_prompt=lambda value: str(value),
        conversation_has_text_summary_for_ref=lambda *_args: False,
        stash_ref_from_result=lambda *_args: "",
        get_memory_db_fn=no_database,
        now_utc_fn=lambda: NOW,
        parse_utc_timestamp_fn=datetime.fromisoformat,
    )


@pytest.mark.parametrize(
    "message",
    [
        EMPTY_MESSAGE,
        EMPTY_MESSAGE + ".",
        "  " + EMPTY_MESSAGE.upper() + ".  ",
        "SerpApi Google Events error: " + EMPTY_MESSAGE,
        "SerpApi error: " + EMPTY_MESSAGE + ".",
        "SerpApi Google Events error: SerpApi error: " + EMPTY_MESSAGE,
    ],
)
def test_reviewed_google_events_response_is_recoverable(message):
    result = _empty_result(error=message)
    before = deepcopy(result)

    assert is_recoverable_empty_search(TOOL, result) is True
    assert result == before


@pytest.mark.parametrize("data", [None, {}])
def test_absent_or_empty_structured_payload_has_no_conflicting_evidence(data):
    assert is_recoverable_empty_search(TOOL, _empty_result(data=data)) is True


@pytest.mark.parametrize(
    "tool",
    ["weather", "serpapi_yelp_search", "serpapi_web_search", "send_email", "", None],
)
def test_same_provider_words_do_not_enable_unreviewed_tools(tool):
    assert is_recoverable_empty_search(tool, _empty_result()) is False


@pytest.mark.parametrize(
    "message",
    [
        "No results",
        "Google Events returned no events for this query",
        "No events_results key in response",
        "Invalid API key",
        "Rate limit exceeded",
        "SerpApi Google Events request timed out.",
        "Missing required query",
        "Error: " + EMPTY_MESSAGE,
        "HTTP 500: " + EMPTY_MESSAGE,
        EMPTY_MESSAGE + "; invalid API key",
        EMPTY_MESSAGE + ". Please retry after 429.",
        "The documentation says: " + EMPTY_MESSAGE,
        "Google hasn't returned any results for this query or another query",
    ],
)
def test_unrecognized_or_mixed_failure_messages_keep_normal_error_recovery(message):
    assert is_recoverable_empty_search(TOOL, _empty_result(error=message)) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"ok": True},
        {"ok": None},
        {"ok": 0},
        {"ok": "false"},
        {"error": None},
        {"error": ""},
        {"error": [EMPTY_MESSAGE]},
        {"error_code": "prompt_injection_detected"},
        {"error_code": "auth_error"},
        {"failure_reason": "active_provider_incident"},
        {"terminal_failure": True},
        {"retry_safe": False},
        {"retry_safe": None},
        {"cancelled": True},
        {"completion": "pending"},
        {"completion": "unknown"},
        {"completion": "completed"},
        {"result_kind": "background_admission"},
        {"result_kind": "background_attention"},
        {"data": {"failure_reason": "active_provider_incident"}},
        {"data": {"status_code": 429}},
        {"data": {"results": [{"title": "An actual event"}]}},
        {"data": {"results": []}},
        {"data": []},
        {"data": ""},
        {"data": False},
    ],
)
def test_conflicting_or_malformed_envelopes_are_not_soft_misses(overrides):
    assert is_recoverable_empty_search(TOOL, _empty_result(**overrides)) is False


@pytest.mark.parametrize("result", [None, [], EMPTY_MESSAGE, {}, {"error": EMPTY_MESSAGE}])
def test_malformed_result_shapes_fail_closed(result):
    assert is_recoverable_empty_search(TOOL, result) is False


def test_text_turn_context_preserves_failed_evidence_and_recovery_guidance():
    result = _empty_result()
    before = deepcopy(result)
    context = _assembler().build_turn_context(
        "Find live music near Portland",
        [{
            "tool": TOOL,
            "arguments": {"query": "live music", "location": "Portland, Oregon"},
            "result": result,
            "meta": {
                "freshness": "failed_tool_call",
                "source": "tool_failure",
                "executed_at_iso": NOW.isoformat(),
                "authoritative_live": False,
            },
        }],
        now=NOW,
    )

    assert "Status: FAILED" in context
    assert "ok=False" in context
    assert "kind=failed_tool_call" in context
    assert EMPTY_MESSAGE in context
    assert EMPTY_SEARCH_RECOVERY_HINT in context
    assert result == before


@pytest.mark.parametrize("budget", [800, 1400, 6000])
def test_native_continuation_reserves_hint_and_error_status_with_huge_arguments(budget):
    result = _empty_result()
    arguments = {"query": "ARGUMENT_SENTINEL " * 10000, "location": "Portland, Oregon"}
    before = deepcopy(result)
    arguments_before = deepcopy(arguments)

    text, metadata = _assembler().build_provider_tool_result_message(
        tool_name=TOOL,
        arguments=arguments,
        result=result,
        tool_call_id="call_empty_1",
        duration_ms=120,
        max_chars=budget,
    )

    assert len(text) <= budget
    assert EMPTY_SEARCH_RECOVERY_HINT in text
    assert "Status: error" in text
    assert metadata["ok"] is False
    assert metadata["arguments_truncated"] is True
    assert result == before
    assert arguments == arguments_before


@pytest.mark.parametrize(
    "result",
    [
        _empty_result(error="Invalid API key"),
        _empty_result(data={"failure_reason": "active_provider_incident"}),
        {"ok": True, "data": {"results": []}},
    ],
)
def test_context_paths_do_not_suggest_empty_search_recovery_for_other_outcomes(result):
    assembler = _assembler()
    context = assembler.build_turn_context(
        "Find events",
        [{"tool": TOOL, "arguments": {"query": "music"}, "result": result}],
        now=NOW,
    )
    text, _metadata = assembler.build_provider_tool_result_message(
        tool_name=TOOL,
        arguments={"query": "music"},
        result=result,
        max_chars=800,
    )

    assert EMPTY_SEARCH_RECOVERY_HINT not in context
    assert EMPTY_SEARCH_RECOVERY_HINT not in text


def _miss_context(arguments=None):
    return {
        "tool": TOOL,
        "arguments": arguments if arguments is not None else {"query": "live music"},
        "result": _empty_result(),
        "meta": {"freshness": "failed_tool_call", "source": "tool_failure"},
    }


def _duplicate_context(arguments=None):
    blocked = {
        "blocked_tool": TOOL,
        "blocked_arguments": arguments if arguments is not None else {"query": "live music"},
        "reason": "exact duplicate",
    }
    return {
        "tool": "duplicate_guard",
        "arguments": deepcopy(blocked),
        "result": {"ok": False, "error": "Duplicate guard blocked this exact call.", "data": blocked},
        "meta": {"freshness": "duplicate_guard", "source": "duplicate_guard"},
    }


@pytest.mark.parametrize(
    "contexts",
    [
        [_miss_context()],
        [_miss_context(), _miss_context({"query": "concerts"})],
        [_miss_context(), _duplicate_context()],
        [_miss_context(), _duplicate_context(), _duplicate_context()],
        [
            _miss_context({"query": "live music", "location": "Portland"}),
            _duplicate_context({"location": "Portland", "query": "live music"}),
            _miss_context({"query": "concerts"}),
            _duplicate_context({"query": "concerts"}),
        ],
    ],
)
def test_only_empty_search_summary_accepts_matching_server_duplicate_guards(contexts):
    before = deepcopy(contexts)

    assert has_only_empty_search_results(contexts) is True
    assert contexts == before


@pytest.mark.parametrize(
    "contexts",
    [
        [],
        [_duplicate_context()],
        [_duplicate_context(), _miss_context()],
        [_miss_context(), _duplicate_context({"query": "a different search"})],
        [_miss_context(), {"tool": "weather", "result": {"ok": True, "data": {}}}],
        [_miss_context(), {"tool": TOOL, "result": _empty_result(error="Invalid API key")}],
        [_miss_context(), {"tool": TOOL, "result": _empty_result(
            data={"failure_reason": "active_provider_incident"},
        )}],
        [_miss_context(), {"tool": "send_email", "result": _empty_result()}],
        [_miss_context(), {"tool": "serpapi_google_events", "result": None}],
        [_miss_context(), {}],
        [_miss_context(), None],
    ],
)
def test_only_empty_search_summary_rejects_missing_misses_and_other_outcomes(contexts):
    assert has_only_empty_search_results(contexts) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool", "send_email"),
        ("tool", "unregistered_tool"),
        ("meta", {}),
        ("meta", None),
        ("meta", {"source": "duplicate_guard"}),
        ("meta", {"freshness": "duplicate_guard"}),
        ("meta", {"source": "tool_failure", "freshness": "duplicate_guard"}),
        ("meta", {"source": "duplicate_guard", "freshness": "failed_tool_call"}),
        ("arguments", {}),
        ("arguments", None),
        ("result", None),
        ("result", {"ok": True}),
        ("result", {"ok": False, "data": {}}),
    ],
)
def test_only_empty_search_summary_rejects_forged_or_malformed_guard_envelopes(field, value):
    guard = _duplicate_context()
    guard[field] = value

    assert has_only_empty_search_results([_miss_context(), guard]) is False


@pytest.mark.parametrize("location", ["arguments", "data", "both"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("blocked_tool", "weather"),
        ("blocked_tool", "send_email"),
        ("blocked_arguments", {"query": "changed query"}),
        ("blocked_arguments", None),
        ("reason", "single-call cap"),
        ("reason", "same target"),
        ("reason", None),
    ],
)
def test_only_empty_search_summary_requires_matching_guard_identity_and_reason(location, field, value):
    guard = _duplicate_context()
    if location in {"arguments", "both"}:
        guard["arguments"][field] = value
    if location in {"data", "both"}:
        guard["result"]["data"][field] = value

    assert has_only_empty_search_results([_miss_context(), guard]) is False
