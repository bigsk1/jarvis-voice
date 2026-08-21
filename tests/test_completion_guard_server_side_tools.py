#!/usr/bin/env python3
"""
Regression tests for Completion Guard handling of provider-native server-side tools.

Run:
    python3 tests/test_completion_guard_server_side_tools.py
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server_package_utils import load_server_package

load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.sockets.chat import ChatHandler


class _FakeSocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload, **kwargs):
        self.emitted.append((event, payload, kwargs))


class CompletionGuardServerSideToolsTests(unittest.TestCase):
    def test_workflow_is_excluded_from_manual_and_auto_completion_guard(self):
        handler = ChatHandler.__new__(ChatHandler)
        policy = handler._get_completion_guard_policy()
        manual = {
            "enabled": True,
            "mode": "manual",
            "show_ui_prompt": True,
            "include_tool_tasks": True,
            "excluded_tools": sorted(ChatHandler.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS),
        }
        auto = {**manual, "mode": "auto"}

        self.assertIn("workflow", ChatHandler.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS)
        self.assertFalse(policy.should_prompt(manual, ["workflow"]))
        self.assertFalse(policy.should_auto_evaluate(auto, ["workflow"]))

    def test_chat_only_repair_strategy_does_not_suggest_tools(self):
        handler = ChatHandler.__new__(ChatHandler)

        strategy = handler._classify_completion_guard_strategy(
            {
                "tool_policy": "none",
                "query": "Search the web and update Canvas",
                "raw_llm_response": "I could not verify this.",
            },
            "Please inspect the source file",
        )

        self.assertEqual(strategy["family"], "chat_only_repair")
        self.assertEqual(strategy["preferred_tools"], [])
        self.assertEqual(strategy["avoid_tools"], ["all tools"])
        self.assertIn("Do not call", strategy["completion_hint"])

    def test_completion_guard_location_context_uses_default_location(self):
        def fake_config(key, default=""):
            return {
                "JARVIS_DEFAULT_LOCATION": "Portland, Oregon",
                "JARVIS_DEFAULT_POSTAL_CODE": "97201",
            }.get(key, default)

        with patch("jarvis_web_test_server.services.completion_guard.load_config"), patch(
            "jarvis_web_test_server.services.completion_guard.get_config_value", side_effect=fake_config
        ):
            context = ChatHandler._get_completion_guard_location_context("cloud")

        self.assertIn("Configured default location:\nPortland, Oregon", context)
        self.assertIn("Configured default postal/ZIP code:\n97201", context)
        self.assertIn('location-relative question like "near me"', context)
        self.assertIn("allowed fallback", context)

    def test_normalize_server_side_tool_names(self):
        tools = ChatHandler._normalize_server_side_tool_names({
            "SERVER_SIDE_TOOL_X_SEARCH": 2,
            "SERVER_SIDE_TOOL_VIEW_IMAGE": 1,
            "SERVER_SIDE_TOOL_WEB_SEARCH": 1,
        })

        self.assertEqual(
            tools,
            ["native:x_search", "native:x_search", "native:view_image", "native:web_search"]
        )

    def test_feedback_context_counts_native_tools_as_real_usage(self):
        record = {
            "tools_used": [],
            "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 1},
            "repair_result": {"tools_used": [], "server_side_tools": {}},
            "speech": "Found results.",
            "raw_llm_response": "Found results with native search."
        }

        context = ChatHandler._build_completion_guard_feedback_context(record, "cancelled")

        self.assertEqual(context["combined_tools_used"], ["native:x_search"])
        self.assertEqual(context["original_response"]["tools_used"], ["native:x_search"])

    def test_compute_effective_evidence_rebuilds_for_native_server_side_tools(self):
        handler = ChatHandler.__new__(ChatHandler)

        ev = handler._compute_effective_evidence(
            "conv1",
            {"raw_llm_response": "Found results with native search."},
            [],
            {"SERVER_SIDE_TOOL_WEB_SEARCH": 1, "SERVER_SIDE_TOOL_VIEW_IMAGE": 1},
            "msg-web-1",
            "find restaurants near me",
        )

        self.assertEqual(
            ev["supporting_tools_used"],
            ["native:web_search", "native:view_image"],
        )
        native = ev["supporting_tool_results"]["native_tools"]
        self.assertEqual(native["server_side_tools"]["SERVER_SIDE_TOOL_WEB_SEARCH"], 1)
        self.assertEqual(
            native["normalized_tools"],
            ["native:web_search", "native:view_image"],
        )
        self.assertFalse(ev["derived_from_prior"])

    def test_completion_guard_eval_prompt_includes_default_location_context(self):
        handler = ChatHandler.__new__(ChatHandler)
        captured = {}

        def fake_config(key, default=""):
            return {
                "JARVIS_DEFAULT_LOCATION": "Portland, Oregon",
                "JARVIS_DEFAULT_POSTAL_CODE": "97201",
            }.get(key, default)

        class _FakeProvider:
            def chat(self, prompt, system_prompt=None, max_tokens=None):
                captured["prompt"] = prompt
                captured["system_prompt"] = system_prompt
                return """{
  "recommended_action": "accept",
  "task_status": "complete",
  "risk_level": "low",
  "repair_worthwhile": false,
  "failure_types": [],
  "missing_requirements": [],
  "unsupported_claims": [],
  "contradictions": [],
  "evidence_gaps": [],
  "reason": "supported",
  "suggested_note": ""
}"""

        handler._create_completion_guard_eval_provider = lambda **kwargs: ("openai", "test-model", _FakeProvider())

        record = {
            "mode": "cloud",
            "tool_policy": "none",
            "query": "what are some of the best places to eat near me?",
            "raw_llm_response": "Top-rated restaurants in Portland, OR (default location).",
            "speech": "Top-rated restaurants in Portland, OR.",
            "tools_used": [],
            "server_side_tools": {},
            "available_tools": [],
            "data": {"sample": "value"},
            "completion_guard": {},
        }

        with patch("jarvis_web_test_server.services.completion_guard.load_config"), patch(
            "jarvis_web_test_server.services.completion_guard.get_config_value", side_effect=fake_config
        ):
            parsed = handler._evaluate_completion_guard_auto(record)

        self.assertEqual(parsed["recommended_action"], "accept")
        self.assertIn("Configured default location:\nPortland, Oregon", captured["prompt"])
        self.assertIn("Configured default postal/ZIP code:\n97201", captured["prompt"])
        self.assertIn('location-relative question like "near me"', captured["prompt"])
        self.assertIn("allowed fallback", captured["prompt"])
        self.assertIn("Tool policy: Chat only", captured["prompt"])
        self.assertIn("Do not penalize the response for using no tools", captured["prompt"])
        self.assertIn("Available tools:\n(disabled by Chat only policy)", captured["prompt"])
        self.assertIn("CHAT ONLY EVALUATION OVERRIDE", captured["system_prompt"])
        self.assertIn("Ignore any model-specific guidance", captured["system_prompt"])
        self.assertNotIn(
            "follow-up pass should materially improve the evidence or tool path",
            captured["prompt"],
        )

    def test_tighten_instead_of_substantive_repair_when_same_tools_and_similar_answer(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": False,
            "evidence_delta": True,
            "answer_similarity": 0.91,
        }
        self.assertTrue(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))

    def test_substantive_repair_when_tool_path_changes(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": True,
            "answer_similarity": 0.95,
        }
        self.assertFalse(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))

    def test_substantive_repair_when_answer_diverges(self):
        delta = {
            "operational_correction": True,
            "tool_path_delta": False,
            "answer_similarity": 0.5,
        }
        self.assertFalse(ChatHandler._completion_guard_tighten_instead_of_substantive_repair(delta))

    def test_chat_only_delta_distinguishes_material_answer_from_tightening(self):
        handler = ChatHandler.__new__(ChatHandler)
        record = {
            "tool_policy": "none",
            "raw_llm_response": "The feature is enabled.",
            "tools_used": [],
            "data": {},
        }

        material = handler._analyze_completion_guard_delta(
            record,
            {
                "raw_llm_response": (
                    "The feature is enabled only for manual QA responses. "
                    "Automatic mode evaluates responses in the background instead."
                ),
                "tools_used": [],
                "data": {},
            },
        )
        similar = handler._analyze_completion_guard_delta(
            record,
            {
                "raw_llm_response": "The feature is enabled.",
                "tools_used": [],
                "data": {},
            },
        )

        self.assertTrue(material["material_answer_delta"])
        self.assertFalse(similar["material_answer_delta"])

    def test_manual_prompt_records_get_expiry(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler.sessions = {"sid": {"completion_guard_records": {}}}

        handler._remember_completion_guard_record("sid", "msg1", {
            "timestamp": 100.0,
            "message_id": "msg1",
            "conversation_id": "conv1",
            "completion_guard_prompt": True,
            "completion_guard": {"manual_prompt_ttl_seconds": 30},
        })

        record = handler.sessions["sid"]["completion_guard_records"]["msg1"]
        self.assertEqual(record["expires_at"], 130.0)

        with patch("jarvis_web_test_server.sockets.chat.time.time", return_value=129.0):
            self.assertFalse(ChatHandler._completion_guard_record_expired(record))
        with patch("jarvis_web_test_server.sockets.chat.time.time", return_value=130.0):
            self.assertTrue(ChatHandler._completion_guard_record_expired(record))

    def test_supersede_pending_manual_prompt_when_conversation_continues(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler.socketio = _FakeSocketIO()
        handler.sessions = {
            "sid": {
                "completion_guard_records": {
                    "msg1": {
                        "status": "pending",
                        "message_id": "msg1",
                        "conversation_id": "conv1",
                        "completion_guard_prompt": True,
                        "feedback_requested": False,
                    }
                }
            }
        }

        handler._supersede_pending_completion_guards("sid", "conv1")

        record = handler.sessions["sid"]["completion_guard_records"]["msg1"]
        self.assertEqual(record["status"], "superseded")
        self.assertEqual(record["settled_reason"], "conversation_continued")
        self.assertEqual(handler.socketio.emitted[0][0], "completion_guard:updated")
        self.assertEqual(handler.socketio.emitted[0][1]["status"], "superseded")
        self.assertEqual(handler.socketio.emitted[0][2].get("room"), "conversation:conv1")

    def test_repair_flow_emits_to_conversation_room_not_session_room(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler.socketio = _FakeSocketIO()
        handler.pending_cancellations = {}
        handler.sessions = {}

        record = {
            "conversation_id": "conv-repair-room",
            "message_id": "msg-parent",
            "mode": "cloud",
            "tool_policy": "none",
            "query": "What is X?",
            "speech": "Answer",
            "raw_llm_response": "Answer",
            "tools_used": [],
            "data": {},
            "completion_guard": {"ticket_on_fail": False},
        }

        fake_result = {
            "ok": True,
            "speech": (
                "REPAIR_STATUS: repaired\n"
                "A substantially better answer that fully explains X and corrects the missing details."
            ),
            "raw_llm_response": (
                "REPAIR_STATUS: repaired\n"
                "A substantially better answer that fully explains X and corrects the missing details."
            ),
            "tools_used": [],
            "data": {},
        }

        fake_orchestrator = unittest.mock.MagicMock()
        fake_orchestrator.process.return_value = fake_result

        with patch("orchestrator_v2.Orchestrator", return_value=fake_orchestrator), patch(
            "jarvis_web_test_server.services.conversation_store.get_conversation_store"
        ), patch.object(
            handler, "_classify_completion_guard_strategy", return_value={"family": "verify"}
        ), patch.object(
            handler, "_format_completion_guard_strategy", return_value="verify source"
        ), patch.object(
            handler, "_prepare_web_response_text", return_value=("Better text", "Better speech")
        ), patch.object(handler, "_compute_effective_evidence", return_value=None), patch.object(
            handler, "_update_completion_guard_experience"
        ), patch.object(handler, "_start_feedback_async"), patch.object(
            handler, "_generate_tts", return_value=None
        ):
            handler._run_completion_guard_repair("ephemeral-session-99", record, note="wrong")

        repair_prompt = fake_orchestrator.process.call_args.args[0]
        self.assertEqual(fake_orchestrator.process.call_args.kwargs["tool_policy"], "none")
        self.assertIn("This repair inherits Chat only mode", repair_prompt)
        self.assertNotIn("You may use tools if needed", repair_prompt)
        self.assertEqual(record["status"], "repaired")
        self.assertTrue(record["repair_result"]["delta"]["chat_only_answer_correction"])
        self.assertTrue(any(event == "chat:response" for event, _payload, _kwargs in handler.socketio.emitted))

        expected_room = "conversation:conv-repair-room"
        self.assertTrue(handler.socketio.emitted)
        for event, _payload, kwargs in handler.socketio.emitted:
            with self.subTest(event=event):
                self.assertEqual(kwargs.get("room"), expected_room)
                self.assertNotEqual(kwargs.get("room"), "ephemeral-session-99")

    def test_repair_status_marker_is_machine_like_completion_text(self):
        self.assertTrue(
            ChatHandler._is_machine_like_completion_text("REPAIR_STATUS: repaired")
        )

    def test_marker_only_repair_never_reaches_chat_or_history(self):
        cases = [
            {
                "name": "tool_data_can_be_synthesized",
                "data": {"verified_value": "present"},
                "synthesized_answer": "The verified value is present.",
                "expected_status": "repaired",
                "expected_answer": "The verified value is present.",
            },
            {
                "name": "no_answer_can_be_synthesized",
                "data": {},
                "synthesized_answer": None,
                "expected_status": "unresolved",
                "expected_answer": (
                    "I couldn't produce a complete repaired answer. "
                    "The original issue remains unresolved."
                ),
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                handler = ChatHandler.__new__(ChatHandler)
                handler.socketio = _FakeSocketIO()
                handler.pending_cancellations = {}
                handler.sessions = {}

                record = {
                    "conversation_id": f"conv-{case['name']}",
                    "message_id": f"msg-{case['name']}",
                    "mode": "cloud",
                    "tool_policy": "auto",
                    "query": "Verify the current value",
                    "speech": "Old answer",
                    "raw_llm_response": "Old answer",
                    "tools_used": [],
                    "data": {},
                    "completion_guard": {"ticket_on_fail": False},
                }
                fake_result = {
                    "ok": True,
                    "speech": "REPAIR_STATUS: repaired",
                    "raw_llm_response": "REPAIR_STATUS: repaired",
                    "tools_used": ["read_file"],
                    "data": case["data"],
                }
                fake_orchestrator = unittest.mock.MagicMock()
                fake_orchestrator.process.return_value = fake_result
                store = unittest.mock.MagicMock()

                with patch(
                    "orchestrator_v2.Orchestrator",
                    return_value=fake_orchestrator,
                ), patch(
                    "jarvis_web_test_server.services.conversation_store.get_conversation_store",
                    return_value=store,
                ), patch.object(
                    handler,
                    "_classify_completion_guard_strategy",
                    return_value={"family": "verify"},
                ), patch.object(
                    handler,
                    "_format_completion_guard_strategy",
                    return_value="verify source",
                ), patch.object(
                    handler,
                    "_synthesize_from_existing_tool_result",
                    return_value=case["synthesized_answer"],
                ) as synthesize, patch.object(
                    handler,
                    "_compute_effective_evidence",
                    return_value=None,
                ), patch.object(
                    handler,
                    "_update_completion_guard_experience",
                ), patch.object(
                    handler,
                    "_start_feedback_async",
                ), patch.object(
                    handler,
                    "_generate_tts",
                    return_value=None,
                ), patch(
                    "jarvis_web_test_server.config.get_web_setting",
                    return_value=False,
                ):
                    ChatHandler._run_completion_guard_repair.__wrapped__(
                        handler,
                        "session-marker-only",
                        record,
                        note="The answer is incomplete",
                    )

                if case["data"]:
                    synthesize.assert_called_once()
                else:
                    synthesize.assert_not_called()

                saved_text = store.add_message.call_args.args[2]
                responses = [
                    payload
                    for event, payload, _kwargs in handler.socketio.emitted
                    if event == "chat:response"
                ]
                self.assertEqual(record["status"], case["expected_status"])
                self.assertEqual(saved_text, case["expected_answer"])
                self.assertEqual(responses[0]["text"], case["expected_answer"])
                self.assertEqual(responses[0]["speech"], case["expected_answer"])
                self.assertNotIn("REPAIR_STATUS", saved_text)
                self.assertNotIn("REPAIR_STATUS", responses[0]["text"])
                self.assertNotIn("REPAIR_STATUS", responses[0]["speech"])

    def test_auto_repair_passes_the_chat_only_record_to_shared_repair(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler._evaluate_completion_guard_auto = unittest.mock.MagicMock(
            return_value={
                "repair_score": 0.95,
                "recommended_action": "repair_required",
                "suggested_note": "The answer missed a requirement.",
            }
        )
        handler._run_completion_guard_repair = unittest.mock.MagicMock()
        handler._update_completion_guard_experience = unittest.mock.MagicMock()
        handler._start_feedback_async = unittest.mock.MagicMock()
        record = {
            "conversation_id": "conv-auto-chat-only",
            "message_id": "msg-auto-chat-only",
            "mode": "cloud",
            "tool_policy": "none",
            "status": "pending",
            "repair_attempts": 0,
            "tools_used": [],
            "completion_guard": {"auto_threshold": 0.70},
        }

        with patch(
            "jarvis_web_test_server.services.conversation_store.get_conversation_store"
        ):
            ChatHandler._run_completion_guard_auto_eval.__wrapped__(
                handler,
                "session-auto-chat-only",
                record,
            )

        self.assertEqual(record["status"], "repairing")
        self.assertEqual(record["repair_attempts"], 1)
        handler._run_completion_guard_repair.assert_called_once_with(
            "session-auto-chat-only",
            record,
            "The answer missed a requirement.",
        )

    def test_latest_pending_message_reaction_updates_intelligence_and_conversation(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler.socketio = _FakeSocketIO()
        handler.sessions = {
            "sid": {
                "completion_guard_records": {
                    "msg-live": {
                        "message_id": "msg-live",
                        "conversation_id": "conv-live",
                        "feedback_requested": False,
                    }
                }
            }
        }
        store = unittest.mock.MagicMock()
        store.get_conversation.return_value = {
            "messages": [{
                "role": "assistant",
                "tools_used": ["crypto_price"],
                "data": {
                    "_web_message_id": "msg-live",
                    "_human_reaction_eligible": True,
                    "_intelligence_mode": "cloud",
                    "experience_id": 42,
                    "usage": {"provider": "xai", "model": "grok-test"},
                },
            }]
        }
        store.update_message_data_by_web_message_id.return_value = True

        with patch(
            "jarvis_web_test_server.services.conversation_store.get_conversation_store",
            return_value=store,
        ), patch(
            "intelligence_hooks.update_experience_from_user_reaction",
            return_value={
                "updated": True,
                "reason": "recorded",
                "priority": 0.8,
            },
        ) as update:
            result = handler._apply_message_reaction("sid", {
                "message_id": "msg-live",
                "conversation_id": "conv-live",
                "reaction": "up",
            })

        self.assertTrue(result["ok"])
        update.assert_called_once_with(
            42,
            "up",
            mode="cloud",
            metadata={
                "message_id": "msg-live",
                "conversation_id": "conv-live",
                "mode": "cloud",
                "provider": "xai",
                "model": "grok-test",
                "tools_used": ["crypto_price"],
                "completion_guard_status": "none",
            },
        )
        store.update_message_data_by_web_message_id.assert_called_once()
        event, payload, kwargs = handler.socketio.emitted[-1]
        self.assertEqual(event, "message_reaction:updated")
        self.assertEqual(payload["reaction"], "up")
        self.assertEqual(kwargs["room"], "conversation:conv-live")

    def test_message_reaction_rejects_response_after_user_continues(self):
        handler = ChatHandler.__new__(ChatHandler)
        handler.socketio = _FakeSocketIO()
        handler.sessions = {
            "sid": {
                "completion_guard_records": {
                    "msg-old": {
                        "message_id": "msg-old",
                        "conversation_id": "conv-live",
                        "feedback_requested": False,
                    }
                }
            }
        }
        store = unittest.mock.MagicMock()
        store.get_conversation.return_value = {
            "messages": [
                {
                    "role": "assistant",
                    "data": {
                        "_web_message_id": "msg-old",
                        "_human_reaction_eligible": True,
                        "_intelligence_mode": "cloud",
                        "experience_id": 42,
                    },
                },
                {"role": "user", "content": "new question", "data": {}},
            ]
        }

        with patch(
            "jarvis_web_test_server.services.conversation_store.get_conversation_store",
            return_value=store,
        ), patch(
            "intelligence_hooks.update_experience_from_user_reaction",
        ) as update:
            result = handler._apply_message_reaction("sid", {
                "message_id": "msg-old",
                "conversation_id": "conv-live",
                "reaction": "down",
            })

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_latest_live_response")
        update.assert_not_called()
        store.update_message_data_by_web_message_id.assert_not_called()


if __name__ == "__main__":
    unittest.main()
