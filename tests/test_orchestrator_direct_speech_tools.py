#!/usr/bin/env python3
"""
Regression tests for authoritative tool speech passthrough.

Run:
    python3 tests/test_orchestrator_direct_speech_tools.py
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import Orchestrator


class OrchestratorDirectSpeechToolTests(unittest.TestCase):
    def test_create_reminder_uses_direct_speech(self):
        self.assertIn("create_reminder", Orchestrator.DIRECT_SPEECH_TOOLS)

    def _build_orchestrator(self, routes, results):
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.executor = Mock(allowed_tools=None)
        orchestrator.executor.execute.side_effect = results
        orchestrator.router = SimpleNamespace(
            provider_type="test",
            model_name="fake-model",
            system_prompt_version="test",
            provider=None,
            route=Mock(side_effect=routes),
        )
        orchestrator.status_updater = Mock()
        orchestrator.max_retries = 1
        orchestrator.timezone = ZoneInfo("America/Los_Angeles")
        orchestrator.auto_context_enabled = False
        orchestrator._last_experience_id = None
        orchestrator.session_id = "test-session"
        orchestrator.web_conversation_id = "test-conversation"
        orchestrator.progress_callback = None
        orchestrator.cancel_check = None
        orchestrator.learning_enabled = False
        orchestrator._try_workflow = lambda _query: None
        orchestrator._get_relevant_memories_bundle = lambda _query: {"context": "", "meta": {}}
        orchestrator._get_learning_insights = lambda *_args: ("", [])
        orchestrator._log_conversation = Mock()
        orchestrator._maybe_collect_feedback = lambda response, _query: response
        return orchestrator

    def test_duplicate_recovery_keeps_successful_reminder_confirmation(self):
        arguments = {"title": "Order party food", "when": "October 23rd at 1pm"}
        confirmation = "Reminder set for Friday, October 23 at 01:00 PM PDT: Order party food"
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder", "arguments": dict(arguments)},
                {"intent": "tool", "tool_name": "create_reminder", "arguments": dict(arguments)},
                {"intent": "qa", "text_response": "Your reminder is set."},
            ],
            results=[{
                "ok": True,
                "speech": confirmation,
                "data": {"reminder_id": 1, "formatted_time": "Friday, October 23 at 01:00 PM PDT"},
            }],
        )

        with patch(
            "orchestrator_v2.get_int",
            side_effect=lambda key, default=0: 4 if key == "MAX_TOOL_TURNS" else default,
        ):
            result = orchestrator.process("Set a reminder to order party food October 23rd at 1pm")

        orchestrator.executor.execute.assert_called_once_with("create_reminder", arguments)
        expected = confirmation + "."
        self.assertEqual(result["speech"], expected)
        self.assertEqual(result["raw_llm_response"], expected)
        self.assertEqual(result["tools_used"], ["create_reminder"])
        self.assertEqual(result["data"]["create_reminder"]["reminder_id"], 1)
        recovery_context = orchestrator.router.route.call_args.args[0]
        self.assertIn("Do not retry this reminder with a different title or time", recovery_context)
        self.assertNotIn("choose a clearly different tool call", recovery_context)

    def test_distinct_explicit_reminders_remain_separate_calls(self):
        first = {"title": "Call the plumber", "when": "tomorrow at noon"}
        second = {"title": "Pick up a package", "when": "tomorrow at 3pm"}
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder", "arguments": first},
                {"intent": "tool", "tool_name": "create_reminder", "arguments": second},
                {"intent": "qa", "text_response": "Both reminders are set."},
            ],
            results=[
                {"ok": True, "speech": "Reminder set for noon: Call the plumber", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Reminder set for 3pm: Pick up a package", "data": {"reminder_id": 2}},
            ],
        )
        with patch(
            "orchestrator_v2.get_int",
            side_effect=lambda key, default=0: 4 if key == "MAX_TOOL_TURNS" else default,
        ):
            result = orchestrator.process(
                "Remind me tomorrow at noon to call the plumber and at 3pm to pick up a package"
            )

        self.assertTrue(result["ok"])
        self.assertEqual(orchestrator.executor.execute.call_count, 2)
        self.assertEqual(result["tools_used"], ["create_reminder", "create_reminder"])
        self.assertEqual(
            [row["reminder_id"] for row in result["data"]["create_reminder"]], [1, 2]
        )
        self.assertEqual(
            result["speech"],
            "Reminder set for noon: Call the plumber. Reminder set for 3pm: Pick up a package.",
        )

    def test_reminder_success_then_failure_reports_both_receipts(self):
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "First reminder", "when": "tomorrow at noon"}},
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Second reminder", "when": "unparseable time"}},
                {"intent": "qa", "text_response": "One reminder succeeded and one failed."},
            ],
            results=[
                {"ok": True, "speech": "First reminder saved.", "data": {"reminder_id": 1}},
                {"ok": False, "speech": "Second reminder failed: unrecognized time.",
                 "error": "Unrecognized time"},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Create two reminders.")

        self.assertEqual(orchestrator.executor.execute.call_count, 2)
        self.assertEqual(
            result["speech"],
            "First reminder saved. Second reminder failed: unrecognized time.",
        )

    def test_corrected_schedule_retry_speaks_only_the_saved_receipt(self):
        title = "Call the plumber"
        invalid = {"title": title, "when": "tomorrow at noon about an appointment at 2pm"}
        corrected = {"title": title, "when": "tomorrow at noon"}
        receipt = "Reminder set for noon: Call the plumber."
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder", "arguments": invalid},
                {"intent": "tool", "tool_name": "create_reminder", "arguments": corrected},
                {"intent": "qa", "text_response": "The reminder is set."},
            ],
            results=[
                {"ok": False, "speech": "No reminder was created. Use only the notification time.",
                 "error": "Multiple notification times", "error_code": "invalid_reminder_schedule"},
                {"ok": True, "speech": receipt, "data": {"reminder_id": 1}},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Remind me at noon about my 2pm appointment.")

        self.assertEqual(result["speech"], receipt)
        self.assertEqual(result["raw_llm_response"], receipt)
        self.assertEqual(len(result["tool_trace"]), 2)
        self.assertFalse(result["tool_trace"][0]["ok"])
        self.assertEqual(orchestrator.executor.execute.call_count, 2)

    def test_correcting_one_reminder_does_not_hide_another_reminders_failure(self):
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Call the plumber", "when": "invalid"}},
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Pick up a package", "when": "tomorrow at 3pm"}},
                {"intent": "qa", "text_response": "Both reminders are set."},
            ],
            results=[
                {"ok": False, "speech": "Plumber reminder could not be created.",
                 "error": "Invalid schedule", "error_code": "invalid_reminder_schedule"},
                {"ok": True, "speech": "Package reminder set for 3pm.", "data": {"reminder_id": 2}},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Create these two reminders.")

        self.assertEqual(
            result["speech"],
            "Plumber reminder could not be created. Package reminder set for 3pm.",
        )

    def test_later_success_does_not_hide_an_uncertain_earlier_write_failure(self):
        arguments = {"title": "Call the plumber", "when": "tomorrow at noon"}
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder", "arguments": arguments},
                {"intent": "tool", "tool_name": "create_reminder", "arguments": arguments},
                {"intent": "qa", "text_response": "The reminder is set."},
            ],
            results=[
                {"ok": False, "speech": "The first save could not be confirmed.",
                 "error": "Database connection lost"},
                {"ok": True, "speech": "Reminder set for noon.", "data": {"reminder_id": 1}},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Remind me to call the plumber tomorrow at noon.")

        self.assertEqual(
            result["speech"],
            "The first save could not be confirmed. Reminder set for noon.",
        )

    def test_reminder_preparation_lookups_do_not_replace_saved_receipts(self):
        receipt = "Reminder set for noon: Call the plumber."
        for helper in ("tool_search", "get_time", "list_reminders"):
            for helper_first in (True, False):
                with self.subTest(helper=helper, helper_first=helper_first):
                    reminder = {"intent": "tool", "tool_name": "create_reminder",
                                "arguments": {"title": "Call the plumber", "when": "tomorrow at noon"}}
                    lookup = {"intent": "tool", "tool_name": helper, "arguments": {}}
                    lookup_result = {"ok": True, "speech": "Lookup completed.", "data": {}}
                    saved = {"ok": True, "speech": receipt, "data": {"reminder_id": 1}}
                    routes = [lookup, reminder] if helper_first else [reminder, lookup]
                    results = [lookup_result, saved] if helper_first else [saved, lookup_result]
                    orchestrator = self._build_orchestrator(
                        routes=[*routes, {"intent": "qa", "text_response": "The appointment starts at 2pm."}],
                        results=results,
                    )
                    orchestrator._format_auto_mode = Mock(side_effect=AssertionError("Unexpected rewrite"))
                    orchestrator._format_multi_turn_summary = Mock(side_effect=AssertionError("Unexpected rewrite"))
                    with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                               4 if key == "MAX_TOOL_TURNS" else default):
                        result = orchestrator.process("Remind me at noon about my 2pm appointment.")

                    self.assertEqual(result["speech"], receipt)
                    self.assertEqual(result["raw_llm_response"], receipt)
                    self.assertEqual(len(result["tool_trace"]), 2)
                    orchestrator._format_auto_mode.assert_not_called()
                    orchestrator._format_multi_turn_summary.assert_not_called()

    def test_duplicate_limit_preserves_all_reminder_receipts_and_trace(self):
        first = {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Call the plumber", "when": "tomorrow at noon"}}
        second = {"intent": "tool", "tool_name": "create_reminder",
                  "arguments": {"title": "Pick up a package", "when": "tomorrow at 3pm"}}
        orchestrator = self._build_orchestrator(
            routes=[first, second, second, second, second],
            results=[
                {"ok": True, "speech": "Plumber reminder set for noon.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Package reminder set for 3pm.", "data": {"reminder_id": 2}},
            ],
        )
        orchestrator._synthesize_duplicate_prevented_response = Mock(
            side_effect=AssertionError("Reminder receipts must not be rewritten")
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   7 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Create these two reminders.")

        self.assertTrue(result["duplicate_prevented"])
        self.assertEqual(orchestrator.executor.execute.call_count, 2)
        self.assertEqual(orchestrator.router.route.call_count, 5)
        expected = "Plumber reminder set for noon. Package reminder set for 3pm."
        self.assertEqual(result["speech"], expected)
        self.assertEqual(result["raw_llm_response"], expected)
        self.assertEqual(len(result["tool_trace"]), 2)

    def test_turn_limit_preserves_reminder_receipts_without_a_summary_pass(self):
        arguments = {"title": "Call the plumber", "when": "tomorrow at noon"}
        receipt = "Reminder set for noon: Call the plumber."
        orchestrator = self._build_orchestrator(
            routes=[{"intent": "tool", "tool_name": "create_reminder", "arguments": arguments}],
            results=[{"ok": True, "speech": receipt, "data": {"reminder_id": 1}}],
        )
        orchestrator._format_max_turns_summary = Mock(side_effect=AssertionError("Unexpected rewrite"))
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   1 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Remind me to call the plumber tomorrow at noon.")

        self.assertTrue(result["max_turns_reached"])
        self.assertEqual(result["speech"], receipt)
        self.assertEqual(result["raw_llm_response"], receipt)
        self.assertEqual(len(result["tool_trace"]), 1)

    def test_other_direct_speech_tools_keep_the_latest_failure(self):
        for tool_name in ("phone_call", "status_recap"):
            with self.subTest(tool_name=tool_name):
                orchestrator = self._build_orchestrator(
                    routes=[
                        {"intent": "tool", "tool_name": tool_name, "arguments": {"target": "first"}},
                        {"intent": "tool", "tool_name": tool_name, "arguments": {"target": "second"}},
                        {"intent": "qa", "text_response": "The second attempt failed."},
                    ],
                    results=[
                        {"ok": True, "speech": "First attempt succeeded.", "data": {}},
                        {"ok": False, "speech": "Second attempt failed.", "error": "Unavailable"},
                    ],
                )
                with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                           4 if key == "MAX_TOOL_TURNS" else default):
                    result = orchestrator.process("Use both targets.")

                self.assertEqual(result["speech"], "Second attempt failed.")

    def test_reminder_router_commentary_is_audit_context_not_spoken_prose(self):
        receipt = "Reminder set for 9:00 AM: Order party food."
        for style in ("auto", "casual", "detailed"):
            for warning in (
                "The saved 9am time differs from your requested 1pm. No replacement was created.",
                receipt + " You requested 1pm, so this schedule is wrong.",
                "The party starts at 1pm, so you should order food early.",
            ):
                with self.subTest(style=style, warning=warning):
                    arguments = {"title": "Order party food", "when": "October 23rd at 9am"}
                    orchestrator = self._build_orchestrator(
                        routes=[
                            {"intent": "tool", "tool_name": "create_reminder", "arguments": arguments},
                            {"intent": "qa", "text_response": warning},
                        ],
                        results=[{"ok": True, "speech": receipt, "data": {"reminder_id": 1}}],
                    )
                    orchestrator._format_auto_mode = Mock(side_effect=AssertionError("Unexpected rewrite"))
                    orchestrator._format_multi_turn_summary = Mock(side_effect=AssertionError("Unexpected rewrite"))
                    with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                               3 if key == "MAX_TOOL_TURNS" else default), \
                         patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
                               style if key == "JARVIS_RESPONSE_STYLE" else default):
                        result = orchestrator.process("Remind me October 23rd at 1pm to order party food")

                    self.assertEqual(result["speech"], receipt)
                    self.assertEqual(result["raw_llm_response"], result["speech"])
                    self.assertEqual(result["tool_trace"][-1]["reminder_router_commentary"], warning)
                    orchestrator.executor.execute.assert_called_once_with("create_reminder", arguments)
                    orchestrator._format_auto_mode.assert_not_called()
                    orchestrator._format_multi_turn_summary.assert_not_called()

    def test_exact_receipt_repeated_in_qa_is_spoken_once(self):
        receipt = "Reminder set for noon: Call the plumber."
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Call the plumber", "when": "tomorrow at noon"}},
                {"intent": "qa", "text_response": receipt},
            ],
            results=[{"ok": True, "speech": receipt, "data": {"reminder_id": 1}}],
        )
        result = orchestrator.process("Remind me tomorrow at noon to call the plumber")
        self.assertEqual(result["speech"], receipt)

    def test_reminders_preserve_other_direct_speech_receipts_in_both_orders(self):
        reminder = {"intent": "tool", "tool_name": "create_reminder",
                    "arguments": {"title": "Order food", "when": "tomorrow at noon"}}
        reminder_result = {"ok": True, "speech": "Reminder set for noon: Order food", "data": {"reminder_id": 1}}
        for tool_name, speech in (
            ("status_recap", "Memory use is 42 percent. Disk free space is 87 gigabytes."),
            ("phone_call", "Call connected at 1:23 PM for 42 seconds."),
            ("generate_music", "Created 2 tracks lasting 87 seconds."),
        ):
            for reminder_first in (True, False):
                for style in ("auto", "casual", "detailed"):
                    with self.subTest(tool=tool_name, reminder_first=reminder_first, style=style):
                        direct = {"intent": "tool", "tool_name": tool_name, "arguments": {}}
                        direct_result = {"ok": True, "speech": speech, "data": {"value": 42}}
                        routes = [reminder, direct] if reminder_first else [direct, reminder]
                        results = [reminder_result, direct_result] if reminder_first else [direct_result, reminder_result]
                        orchestrator = self._build_orchestrator(
                            routes=[*routes, {"intent": "qa", "text_response": "The party starts at 1pm. Everything looks fine."}],
                            results=results,
                        )
                        orchestrator._format_auto_mode = Mock(side_effect=AssertionError("Unexpected rewrite"))
                        orchestrator._format_multi_turn_summary = Mock(side_effect=AssertionError("Unexpected rewrite"))
                        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                                   4 if key == "MAX_TOOL_TURNS" else default), \
                             patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
                                   style if key == "JARVIS_RESPONSE_STYLE" else default):
                            result = orchestrator.process("Set my reminder and run the other requested tool")

                        expected = (
                            "Reminder set for noon: Order food. " + speech if reminder_first
                            else speech + " Reminder set for noon: Order food."
                        )
                        self.assertEqual(result["speech"], expected)
                        self.assertEqual(result["raw_llm_response"], expected)
                        self.assertNotIn("party starts", result["speech"])
                        self.assertEqual(len(result["tool_trace"]), 2)
                        orchestrator._format_auto_mode.assert_not_called()
                        orchestrator._format_multi_turn_summary.assert_not_called()

    def test_reminder_and_direct_speech_failure_keep_all_actual_receipts(self):
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Order food", "when": "tomorrow at noon"}},
                {"intent": "tool", "tool_name": "status_recap", "arguments": {"target": "first"}},
                {"intent": "tool", "tool_name": "status_recap", "arguments": {"target": "second"}},
                {"intent": "qa", "text_response": "Everything looks fine."},
            ],
            results=[
                {"ok": True, "speech": "Reminder set for noon.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Memory use is 42 percent.", "data": {"memory_percent": 42}},
                {"ok": False, "speech": "Second status check failed.", "error": "Unavailable"},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   5 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Set my reminder and check both systems")

        self.assertEqual(
            result["speech"], "Reminder set for noon. Memory use is 42 percent. Second status check failed."
        )

    def test_mixed_cancellation_keeps_direct_speech_and_whole_task_summary(self):
        status = "Memory use is 42 percent. Disk free space is 87 gigabytes."
        answer = "The reminder was created and then canceled; the system check completed."
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Order food", "when": "tomorrow at noon"}},
                {"intent": "tool", "tool_name": "acknowledge_reminders", "arguments": {"reminder_ids": [1]}},
                {"intent": "tool", "tool_name": "status_recap", "arguments": {}},
                {"intent": "qa", "text_response": answer},
            ],
            results=[
                {"ok": True, "speech": "Reminder set for noon.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Reminder canceled.", "data": {}},
                {"ok": True, "speech": status, "data": {"memory_percent": 42}},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   5 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Create then cancel the reminder and check system status")

        self.assertEqual(result["speech"], status + " " + answer)
        self.assertNotIn("Reminder set for noon.", result["speech"])

    def test_other_tools_keep_generic_duplicate_recovery(self):
        arguments = {"symbol": "SAMPLE"}
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "stock_price", "arguments": dict(arguments)},
                {"intent": "tool", "tool_name": "stock_price", "arguments": dict(arguments)},
                {"intent": "qa", "text_response": "The price is 10 dollars."},
            ],
            results=[{"ok": True, "speech": "The price is 10 dollars.", "data": {"price": 10}}],
        )
        orchestrator._format_auto_mode = Mock(return_value="The price is 10 dollars.")
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default), \
             patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
                   "auto" if key == "JARVIS_RESPONSE_STYLE" else default):
            result = orchestrator.process("What is the SAMPLE stock price?")

        context = orchestrator.router.route.call_args.args[0]
        self.assertIn(
            "- You must either answer directly from the existing results or choose a clearly different tool call.",
            context,
        )
        self.assertNotIn("For create_reminder", context)
        self.assertEqual(result["speech"], "The price is 10 dollars.")
        orchestrator.executor.execute.assert_called_once_with("stock_price", arguments)
        orchestrator._format_auto_mode.assert_called_once()

    def test_audio_generation_failure_does_not_trigger_another_paid_attempt(self):
        arguments = {"text": "Hello, Andrew.", "provider": "elevenlabs"}
        recovery = {
            "file_path": "/tmp/generated_audio/voiceover.mp3", "provider": "elevenlabs",
            "audio_url": "/api/generated-audio/speech_voiceover.mp3",
            "recovery_available": True, "saved": {"saved": True, "stash": False},
        }
        actual_error = (
            "The audio was generated and saved locally, but saving all artifacts failed. "
            "Reuse the existing recording; do not regenerate it."
        )
        self.assertEqual(len(actual_error), 127)
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "generate_audio", "arguments": arguments},
                {"intent": "tool", "tool_name": "generate_audio",
                 "arguments": {**arguments, "provider": "openai"}},
            ],
            results=[{
                "ok": False, "speech": actual_error,
                "error": actual_error,
                "completion": "completed", "data": recovery,
            }],
        )
        result = orchestrator.process("Create a voiceover with ElevenLabs.")
        self.assertFalse(result["ok"])
        self.assertTrue(result["terminal_failure"])
        orchestrator.executor.execute.assert_called_once_with("generate_audio", arguments)
        self.assertEqual(orchestrator.router.route.call_count, 1)
        self.assertEqual(result["speech"], actual_error)
        self.assertEqual(result["completion"], "completed")
        self.assertEqual(result["tool_trace"][0]["result_data"], recovery)
        self.assertEqual(result["tool_trace"][0]["completion"], "completed")
        self.assertFalse(result["tool_trace"][0]["ok"])
        self.assertEqual(result["data"]["generate_audio"]["audio_url"], recovery["audio_url"])
        self.assertFalse(result["data"]["generate_audio"]["ok"])
        self.assertEqual(result["data"]["generate_audio"]["completion"], "completed")
        orchestrator.status_updater.update_error.assert_not_called()

    def test_audio_unknown_outcome_preserves_billing_warning_without_retrying(self):
        arguments = {"text": "Hello.", "provider": "elevenlabs"}
        orchestrator = self._build_orchestrator(
            routes=[{"intent": "tool", "tool_name": "generate_audio", "arguments": arguments}],
            results=[{
                "ok": False, "completion": "unknown", "error": "Timeout",
                "speech": "Tool generate_audio timed out",
            }],
        )
        result = orchestrator.process("Create an ElevenLabs recording.")
        self.assertFalse(result["ok"])
        self.assertTrue(result["terminal_failure"])
        self.assertEqual(result["completion"], "unknown")
        self.assertIn("may have been billed", result["speech"])
        self.assertIn("do not retry it automatically", result["speech"])
        self.assertIn("Check existing recordings", result["speech"])
        self.assertEqual(result["tool_trace"][0]["completion"], "unknown")
        orchestrator.executor.execute.assert_called_once_with("generate_audio", arguments)
        self.assertEqual(orchestrator.router.route.call_count, 1)
        orchestrator.status_updater.update_error.assert_not_called()

    def test_audio_terminal_speech_uses_completion_evidence_without_raw_error(self):
        from orchestrator_v2 import _format_terminal_tool_failure

        unsafe = "secret-header http://user:password@private-host/internal " * 8
        for completion in ("completed", "unknown"):
            with self.subTest(completion=completion):
                speech = _format_terminal_tool_failure(
                    "generate_audio", unsafe, result={"ok": False, "completion": completion},
                )
                self.assertIn("may have been billed", speech)
                self.assertNotIn("technical error", speech)
                self.assertNotIn("secret", speech)
                self.assertNotIn("password", speech)

    def test_rejected_audio_request_keeps_existing_preflight_failure_behavior(self):
        from orchestrator_v2 import _format_terminal_tool_failure

        self.assertEqual(
            _format_terminal_tool_failure(
                "generate_audio", "A nonempty text script is required",
                result={"ok": False, "completion": "rejected"},
            ),
            "Generate audio failed because A nonempty text script is required.",
        )

    def test_mixed_duplicate_recovery_scopes_the_reminder_exception(self):
        reminder = {"intent": "tool", "tool_name": "create_reminder",
                    "arguments": {"title": "Call the plumber", "when": "tomorrow at noon"}}
        quote = {"intent": "tool", "tool_name": "stock_price", "arguments": {"symbol": "SAMPLE"}}
        answer = "Reminder set for noon. The stock price is 10 dollars."
        orchestrator = self._build_orchestrator(
            routes=[reminder, reminder, quote, quote, {"intent": "qa", "text_response": answer}],
            results=[
                {"ok": True, "speech": "Reminder set for noon.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "The price is 10 dollars.", "data": {"price": 10}},
            ],
        )
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   6 if key == "MAX_TOOL_TURNS" else default):
            result = orchestrator.process("Remind me to call the plumber tomorrow at noon and check SAMPLE stock")

        context = orchestrator.router.route.call_args.args[0]
        self.assertIn("For create_reminder, answer from the saved result", context)
        self.assertIn("For tools other than create_reminder", context)
        self.assertIn("choose a clearly different tool call", context)
        self.assertEqual(orchestrator.executor.execute.call_count, 2)
        self.assertEqual(result["speech"], answer)

    def test_duplicate_loops_still_stop_for_reminders_and_other_tools(self):
        for tool_name in ("create_reminder", "stock_price"):
            with self.subTest(tool_name=tool_name):
                arguments = (
                    {"title": "Call the plumber", "when": "tomorrow at noon"}
                    if tool_name == "create_reminder" else {"symbol": "SAMPLE"}
                )
                route = {"intent": "tool", "tool_name": tool_name, "arguments": arguments}
                orchestrator = self._build_orchestrator(
                    routes=[route] * 5,
                    results=[{"ok": True, "speech": "Completed.", "data": {"id": 1}}],
                )
                orchestrator._synthesize_duplicate_prevented_response = Mock(return_value="Already completed.")
                with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                           6 if key == "MAX_TOOL_TURNS" else default):
                    result = orchestrator.process("Complete this request")

                self.assertTrue(result["duplicate_prevented"])
                self.assertTrue(result["ok"])
                self.assertEqual(orchestrator.executor.execute.call_count, 1)
                self.assertEqual(orchestrator.router.route.call_count, 4)

    def test_create_then_cancel_uses_whole_task_answer_in_auto_mode(self):
        answer = "Created the reminder and then canceled it. No notification remains scheduled."
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Call the plumber", "when": "tomorrow at noon"}},
                {"intent": "tool", "tool_name": "acknowledge_reminders", "arguments": {"reminder_ids": [1]}},
                {"intent": "qa", "text_response": answer},
            ],
            results=[
                {"ok": True, "speech": "Reminder set for noon.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Reminder canceled.", "data": {}},
            ],
        )
        orchestrator._format_auto_mode = Mock(side_effect=AssertionError("Unexpected rewrite"))
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   4 if key == "MAX_TOOL_TURNS" else default), \
             patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
                   "auto" if key == "JARVIS_RESPONSE_STYLE" else default):
            result = orchestrator.process("Create a reminder to call the plumber tomorrow, then cancel it")

        self.assertEqual(result["speech"], answer)
        self.assertEqual(result["raw_llm_response"], answer)
        orchestrator._format_auto_mode.assert_not_called()

    def test_create_cancel_create_keeps_whole_task_confirmation_in_all_styles(self):
        for style in ("auto", "casual", "detailed"):
            with self.subTest(style=style):
                self._check_mixed_confirmation(style)

    def _check_mixed_confirmation(self, style):
        answer = "Canceled the first reminder and saved its replacement for noon."
        orchestrator = self._build_orchestrator(
            routes=[
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Old reminder", "when": "tomorrow at 2pm"}},
                {"intent": "tool", "tool_name": "acknowledge_reminders",
                 "arguments": {"reminder_ids": [1]}},
                {"intent": "tool", "tool_name": "create_reminder",
                 "arguments": {"title": "Replacement", "when": "tomorrow at noon"}},
                {"intent": "qa", "text_response": answer},
            ],
            results=[
                {"ok": True, "speech": "Old reminder saved.", "data": {"reminder_id": 1}},
                {"ok": True, "speech": "Old reminder canceled.", "data": {}},
                {"ok": True, "speech": "Replacement saved.", "data": {"reminder_id": 2}},
            ],
        )
        orchestrator._format_auto_mode = Mock(side_effect=AssertionError("Unexpected auto rewrite"))
        orchestrator._format_multi_turn_summary = Mock(side_effect=AssertionError("Unexpected summary rewrite"))
        with patch("orchestrator_v2.get_int", side_effect=lambda key, default=0:
                   5 if key == "MAX_TOOL_TURNS" else default), \
             patch("orchestrator_v2.get_config_value", side_effect=lambda key, default=None:
                   style if key == "JARVIS_RESPONSE_STYLE" else default):
            result = orchestrator.process("Create, cancel, then replace a reminder.")

        self.assertEqual(orchestrator.executor.execute.call_count, 3)
        self.assertEqual(result["speech"], answer)
        self.assertEqual(result["raw_llm_response"], answer)
        orchestrator._format_auto_mode.assert_not_called()
        orchestrator._format_multi_turn_summary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
