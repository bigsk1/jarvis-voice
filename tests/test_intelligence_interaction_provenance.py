"""Queue provenance keeps only the bounded original request and explicit source."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

import intelligence_hooks  # noqa: E402
from intelligence import IntelligenceLayer  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_intelligence_log():
    with patch("intelligence.get_intel_logger"):
        yield


def make_orchestrator(routes=None, results=None):
    orch = Orchestrator.__new__(Orchestrator)
    orch.executor = Mock(allowed_tools=None)
    orch.executor.execute.side_effect = results or []
    orch.router = SimpleNamespace(
        provider_type="test", model_name="test", system_prompt_version="test", provider=None,
        route=Mock(side_effect=routes or [{"intent": "qa", "text_response": "The blue one."}]),
    )
    orch.status_updater = Mock()
    orch.max_retries = 1
    orch.timezone = ZoneInfo("UTC")
    orch.auto_context_enabled = False
    orch._last_experience_id = None
    orch.session_id = "session-test"
    orch.web_conversation_id = None
    orch.progress_callback = None
    orch.cancel_check = None
    orch.learning_enabled = True
    orch.reflection_queue_enabled = True
    orch._try_workflow = lambda _query: None
    orch._get_relevant_memories_bundle = lambda _query: {"context": "", "meta": {}}
    orch._get_learning_insights = lambda *_args: ("", [])
    orch._log_conversation = Mock()
    orch._maybe_collect_feedback = lambda response, _query: response
    return orch


@pytest.mark.parametrize("source", ["web", "voice", "cli", "api", "scheduled", "unknown", "internal"])
def test_minimal_queue_metadata_redacts_original_and_classifies_only_explicit_source(source):
    secret = "sk-" + "a" * 30
    value = intelligence_hooks.build_interaction_context("request " + secret, source=source)
    assert value == {
        "version": 1,
        "source": source if source != "internal" else "unknown",
        "user_query": "request sk-[redacted]",
    }
    assert secret not in json.dumps(value)


@pytest.mark.parametrize("queue_enabled", [True, False])
def test_clean_query_and_source_saved_without_new_routing_or_prior_context_capture(tmp_path, queue_enabled):
    intel = IntelligenceLayer(str(tmp_path / "intel.db"), load_runtime_config=False)
    intel._get_persistable_embedding = lambda *_args, **_kwargs: np.array([1.0, 0.5])
    orch = make_orchestrator()
    orch.reflection_queue_enabled = queue_enabled
    history = [{"role": "user", "content": "PRIVATE_HISTORY_SENTINEL"},
               {"role": "assistant", "content": "Done.", "tools_used": ["stock_price"],
                "tool_results": {"stock_price": {"detail": "PRIOR_RESULT_SENTINEL"}}}]
    augmented = "ROUTING_GUIDANCE_SENTINEL.\n\nUser's request: Which one?"
    try:
        with patch.object(intelligence_hooks, "_get_intel", return_value=intel):
            result = orch.process(augmented, original_query="Which one?", request_source="web",
                                  conversation_history=history, tool_policy="none")
        row = intel.conn.execute("SELECT query, raw_data FROM experiences").fetchone()
        assert row["query"] == "Which one?"
        context = json.loads(row["raw_data"])["context"]
        assert context["interaction"] == {"version": 1, "source": "web", "user_query": "Which one?"}
        assert context["tool_policy"] == "none"
        for marker in ("PRIVATE_HISTORY_SENTINEL", "PRIOR_RESULT_SENTINEL", "ROUTING_GUIDANCE_SENTINEL"):
            assert marker not in row["raw_data"]
        assert intel.conn.execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0] == int(queue_enabled)
        routed = orch.router.route.call_args.args[0]
        assert augmented in routed and "PRIVATE_HISTORY_SENTINEL" in routed and "PRIOR_RESULT_SENTINEL" in routed
        orch._log_conversation.assert_called_once()
        assert orch._log_conversation.call_args.args[0] == "Which one?"
        assert result["experience_id"] > 0
    finally:
        intel.conn.close()


def test_original_query_keeps_existing_length_boundary_in_storage(tmp_path):
    intel = IntelligenceLayer(str(tmp_path / "intel.db"), load_runtime_config=False)
    intel._get_persistable_embedding = lambda *_args, **_kwargs: np.array([1.0, 0.5])
    orch = make_orchestrator()
    query = "q" * 10000 + " OMITTED_QUERY_SUFFIX"
    try:
        with patch.object(intelligence_hooks, "_get_intel", return_value=intel):
            orch.process(query, original_query=query, request_source="cli", tool_policy="none")
        row = intel.conn.execute("SELECT query, raw_data FROM experiences").fetchone()
        assert row["query"] == "q" * 10000
        assert "OMITTED_QUERY_SUFFIX" not in row["raw_data"]
        interaction = json.loads(row["raw_data"])["context"]["interaction"]
        assert interaction == {"version": 1, "source": "cli", "user_query": "q" * 10000,
                               "user_query_truncated": True}
        routed = orch.router.route.call_args.args[0]
        assert routed.endswith("q" * 10000)
        assert "OMITTED_QUERY_SUFFIX" not in routed
        assert orch._log_conversation.call_args.args[0] == "q" * 10000
    finally:
        intel.conn.close()


def test_legacy_snapshot_metadata_stays_stored_but_outside_reflection_input(tmp_path):
    intel = IntelligenceLayer(str(tmp_path / "intel.db"), load_runtime_config=False)
    raw = {"context": {
        "interaction": {
            "version": 1, "source": "web", "user_query": "Legacy original request",
            "routing_query": "LEGACY_ROUTING_SNAPSHOT_SENTINEL",
            "previous_turns": [{"role": "assistant", "content": "LEGACY_HISTORY_SNAPSHOT_SENTINEL",
                                "tool_results_excerpt": "LEGACY_EVIDENCE_SNAPSHOT_SENTINEL"}],
        },
        "raw_llm_response": "CURRENT_RESPONSE_SENTINEL",
        "final_speech": "CURRENT_SPEECH_SENTINEL",
        "tool_results": json.dumps({"get_time": {"time": "CURRENT_TOOL_RESULT_SENTINEL"}}),
        "tool_trace": json.dumps([{"tool": "get_time", "ok": True, "detail": "CURRENT_TOOL_TRACE_SENTINEL"}]),
        "available_tools": ["get_time"],
    }}
    stored_raw = json.dumps(raw)
    try:
        cursor = intel.conn.execute(
            "INSERT INTO experiences (query, tools_used, outcome_success, raw_data) VALUES (?, ?, ?, ?)",
            ("Canonical original query", '["get_time"]', 1, stored_raw),
        )
        with patch.object(intel, "_think_deeply", new=AsyncMock(return_value=None)) as reflect:
            asyncio.run(intel.reflect_on_experience(cursor.lastrowid))
        prompt = reflect.call_args.args[0]
        assert "**User Query**: Canonical original query" in prompt
        for marker in ("LEGACY_ROUTING_SNAPSHOT_SENTINEL", "LEGACY_HISTORY_SNAPSHOT_SENTINEL",
                       "LEGACY_EVIDENCE_SNAPSHOT_SENTINEL", "Legacy original request"):
            assert marker not in prompt
        for marker in ("CURRENT_RESPONSE_SENTINEL", "CURRENT_SPEECH_SENTINEL",
                       "CURRENT_TOOL_RESULT_SENTINEL", "CURRENT_TOOL_TRACE_SENTINEL"):
            assert marker in prompt
        assert intel.conn.execute("SELECT raw_data FROM experiences").fetchone()[0] == stored_raw
    finally:
        intel.conn.close()


@pytest.mark.parametrize("long_original", [False, True])
def test_retry_preserves_original_source_and_request_boundary(long_original):
    orch = make_orchestrator(
        routes=[{"intent": "tool", "tool_name": "get_time", "arguments": {}},
                {"intent": "qa", "text_response": "Could not get the time."}],
        results=[{"ok": False, "error": "temporary failure"}],
    )
    captured = {}
    original = "q" * 10000 + " OMITTED_QUERY_SUFFIX" if long_original else "again"
    with patch.object(intelligence_hooks, "record_interaction", side_effect=lambda **kw: captured.update(kw) or 8):
        orch.process("wrapper\nUser's request: " + original, original_query=original, request_source="api")
    assert orch.router.route.call_count == 2
    expected = {"version": 1, "source": "api", "user_query": original[:10000]}
    if long_original:
        expected["user_query_truncated"] = True
    assert captured["query"] == original[:10000]
    assert captured["interaction"] == expected
    orch._log_conversation.assert_called_once()
    assert orch._log_conversation.call_args.args[0] == original[:10000]
    for call in orch.router.route.call_args_list:
        assert "wrapper\nUser's request: " in call.args[0]
    assert "temporary failure" in orch.router.route.call_args.args[0]


def test_default_query_keeps_existing_memory_logging_length_boundary():
    orch = make_orchestrator()
    orch.learning_enabled = False
    query = "q" * 10000 + " OMITTED_QUERY_SUFFIX"
    orch.process(query, tool_policy="none")
    orch._log_conversation.assert_called_once()
    assert orch._log_conversation.call_args.args[0] == "q" * 10000
    assert "OMITTED_QUERY_SUFFIX" not in orch.router.route.call_args.args[0]


@pytest.mark.parametrize(
    "ending", ["single_call_failure", "retry_exhausted", "duplicate_guard", "routing_error", "max_turns"]
)
def test_terminal_paths_log_original_request_and_retain_routing_guidance(ending):
    original = "Get the requested result."
    augmented = "ROUTING_GUIDANCE_SENTINEL.\n\nUser's request: " + original
    tool = {"intent": "tool", "tool_name": "get_time", "arguments": {}}
    success = {"ok": True, "speech": "It is noon.", "data": {"time": "12:00"}}
    failure = {"ok": False, "speech": "Could not finish.", "error": "temporary failure"}
    routes = [tool]
    results = [failure]
    max_turns = 5
    if ending == "single_call_failure":
        routes = [{"intent": "tool", "tool_name": "generate_image", "arguments": {"prompt": "test"}}]
    elif ending == "duplicate_guard":
        routes = [tool] * 4
        results = [success]
    elif ending == "routing_error":
        routes = [{"intent": "error", "error": "router unavailable", "text_response": "Try later."}]
        results = []
    elif ending == "max_turns":
        results = [success]
        max_turns = 1

    orch = make_orchestrator(routes=routes, results=results)
    orch.learning_enabled = False
    orch.max_retries = 0
    orch._synthesize_duplicate_prevented_response = Mock(return_value="Already completed.")
    with patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
               "detailed" if key == "JARVIS_RESPONSE_STYLE" else default), patch(
        "orchestrator_v2.get_int", side_effect=lambda key, default=0:
        max_turns if key == "MAX_TOOL_TURNS" else default,
    ):
        result = orch.process(augmented, original_query=original, request_source="web")

    orch._log_conversation.assert_called_once()
    logged = orch._log_conversation.call_args
    assert logged.args[0] == original
    assert logged.args[1] == result["speech"]
    assert logged.kwargs["success"] is result["ok"]
    for call in orch.router.route.call_args_list:
        assert augmented in call.args[0]
    if ending == "single_call_failure":
        assert result["terminal_failure"] is True
    elif ending == "duplicate_guard":
        assert result["duplicate_prevented"] is True
        assert orch.executor.execute.call_count == 1
    elif ending == "max_turns":
        assert result["max_turns_reached"] is True
    elif ending == "retry_exhausted":
        assert result["retries"] == 0
    else:
        assert result["error"] == "router unavailable"


@pytest.mark.parametrize("guard", ["disabled", "background"])
def test_learning_guards_still_skip_metadata_recording(guard):
    orch = make_orchestrator()
    orch.learning_enabled = guard != "disabled"
    orch.background_context = SimpleNamespace(receipts=[{"job_id": "pending"}]) if guard == "background" else None
    with patch.object(intelligence_hooks, "record_interaction") as record:
        assert orch._record_learning_experience("question", [], {"ok": True}, [], request_source="web") == -1
    record.assert_not_called()
