#!/usr/bin/env python3
"""
Regression tests for OpenCode client session handling.

Run:
    python3 tests/test_opencode_client.py
"""

import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from opencode_client import OpenCodeClient, resolve_opencode_defaults  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class OpenCodeClientTests(unittest.TestCase):
    def _make_client(self, config=None):
        config = config or {}

        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_MODEL": "grok-build-0.1",
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_SERVER_PASSWORD": "",
                "OPENCODE_SERVER_USERNAME": "opencode",
            }
            values.update(config)
            return values.get(key, default)

        with patch("opencode_client.requests.get", return_value=FakeResponse({"ok": True})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            return OpenCodeClient(base_url="http://opencode.test")

    def test_create_session_includes_agent_mode_string(self):
        client = self._make_client()

        with patch("opencode_client.requests.post", return_value=FakeResponse({"sessionId": "ses_123"})) as mock_post:
            response = client.create_session(title="Jarvis: demo", agent_mode="build")

        self.assertEqual(response["sessionId"], "ses_123")
        mock_post.assert_called_once_with(
            "http://opencode.test/session",
            json={"title": "Jarvis: demo", "agent": "build"},
            timeout=client.timeout,
        )

    def test_no_reply_context_messages_use_a_short_http_timeout(self):
        client = self._make_client()

        with patch(
            "opencode_client.requests.post",
            return_value=FakeResponse({"ok": True}),
        ) as mock_post:
            client.send_message("ses_123", "context", no_reply=True)

        self.assertEqual(
            mock_post.call_args.kwargs["timeout"],
            client.NO_REPLY_TIMEOUT_SECONDS,
        )
        self.assertTrue(mock_post.call_args.kwargs["json"]["noReply"])

    def test_final_task_message_uses_configured_task_timeout(self):
        client = self._make_client({"OPENCODE_TASK_TIMEOUT_SECONDS": "900"})

        with patch(
            "opencode_client.requests.post",
            return_value=FakeResponse({"parts": [{"type": "text", "text": "done"}]}),
        ) as mock_post:
            client.send_message("ses_123", "build it")

        self.assertEqual(client.task_timeout, 900)
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 900)

    def test_invalid_task_timeout_uses_safe_default(self):
        client = self._make_client({"OPENCODE_TASK_TIMEOUT_SECONDS": "invalid"})

        self.assertEqual(client.task_timeout, client.DEFAULT_TASK_TIMEOUT_SECONDS)

    def test_uses_basic_auth_when_server_password_is_configured(self):
        client = self._make_client({
            "OPENCODE_SERVER_USERNAME": "jarvis",
            "OPENCODE_SERVER_PASSWORD": "secret",
        })

        with patch("opencode_client.requests.post", return_value=FakeResponse({"sessionId": "ses_123"})) as mock_post:
            client.create_session(title="Jarvis: demo", agent_mode="build")

        mock_post.assert_called_once_with(
            "http://opencode.test/session",
            json={"title": "Jarvis: demo", "agent": "build"},
            timeout=client.timeout,
            auth=("jarvis", "secret"),
        )

    def test_resolve_opencode_defaults_uses_catalog_when_model_unset(self):
        def fake_get_config(key, default=""):
            values = {
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_MODEL": "",
            }
            return values.get(key, default)

        with patch("config_loader.get_config_value", side_effect=fake_get_config):
            defaults = resolve_opencode_defaults("cloud")

        self.assertEqual(defaults["providerID"], "xai")
        self.assertEqual(defaults["modelID"], "grok-4.6")

    def test_client_uses_catalog_fallback_when_opencode_model_unset(self):
        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_PROVIDER": "anthropic",
                "OPENCODE_MODEL": "",
                "OPENCODE_SERVER_PASSWORD": "",
                "OPENCODE_SERVER_USERNAME": "opencode",
            }
            return values.get(key, default)

        with patch("opencode_client.requests.get", return_value=FakeResponse({"ok": True})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            client = OpenCodeClient(base_url="http://opencode.test")

        self.assertEqual(client.default_provider_id, "anthropic")
        self.assertEqual(client.default_model_id, "claude-sonnet-5")

    def test_execute_task_accepts_session_id_response_key(self):
        client = self._make_client()
        client.logger = MagicMock()

        with patch.object(client, "create_session", return_value={"sessionId": "ses_from_server"}) as mock_create_session, \
             patch.object(client, "send_message", side_effect=[
                 {"ok": True},
                 {"ok": True},
                 {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
             ]) as mock_send_message:
            result = client.execute_task(
                task="Build a demo app",
                agent_mode="build",
                context={"task_type": "coding"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["session_id"], "ses_from_server")
        mock_create_session.assert_called_once_with(
            title="Jarvis: Build a demo app",
            agent_mode="build",
        )
        self.assertEqual(mock_send_message.call_count, 3)

    def test_parses_multiline_sse_payloads(self):
        payloads = list(OpenCodeClient._iter_sse_payloads([
            'event: message.part.updated',
            'data: {"type":"session.status",',
            'data: "properties":{"sessionID":"ses_123","status":{"type":"busy"}}}',
            '',
        ]))

        self.assertEqual(payloads[0]["type"], "session.status")
        self.assertEqual(payloads[0]["properties"]["sessionID"], "ses_123")

    def test_sse_read_timeout_exceeds_legacy_keepalive_interval(self):
        client = self._make_client()
        stop_event = threading.Event()
        ready_event = threading.Event()
        event_queue = queue.Queue()

        class EventResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=False):
                self.decode_unicode = decode_unicode
                yield 'data: {"type":"server.connected","properties":{}}'
                yield ""
                stop_event.set()

            def close(self):
                return None

        with patch.object(client, "_get", return_value=EventResponse()) as mock_get:
            client._stream_events(event_queue, stop_event, ready_event)

        self.assertTrue(ready_event.is_set())
        self.assertGreater(mock_get.call_args.kwargs["timeout"][1], 30)
        self.assertTrue(event_queue.get_nowait()["_monitor_connected"])

    def test_normalizes_live_tool_and_todo_progress_without_raw_output(self):
        tool_progress = OpenCodeClient._normalize_progress_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": "ses_123",
                    "part": {
                        "type": "tool",
                        "tool": "write",
                        "state": {
                            "status": "running",
                            "input": {"filePath": "/home/boss/jarvis-workspace/temp/demo.py"},
                        },
                    },
                },
            },
            "ses_123",
        )
        todo_progress = OpenCodeClient._normalize_progress_event(
            {
                "type": "todo.updated",
                "properties": {
                    "sessionID": "ses_123",
                    "todos": [
                        {"content": "Create the script", "status": "completed", "priority": "high"},
                        {"content": "Run its tests", "status": "in_progress", "priority": "high"},
                    ],
                },
            },
            "ses_123",
        )

        self.assertEqual(tool_progress["phase"], "tool")
        self.assertIn("workspace/temp/demo.py", tool_progress["status"])
        self.assertNotIn("output", tool_progress)
        self.assertEqual(todo_progress["status"], "OpenCode is working on: Run its tests")
        self.assertEqual(todo_progress["progress"], 50)

    def test_normalizes_pending_tool_state_for_poll_fallback(self):
        progress = OpenCodeClient._normalize_progress_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": "ses_123",
                    "part": {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"status": "pending", "input": {}},
                    },
                },
            },
            "ses_123",
        )

        self.assertEqual(progress["tool_status"], "pending")
        self.assertEqual(progress["status"], "OpenCode: Running a command")

    def test_progress_text_redacts_common_secret_shapes(self):
        cleaned = OpenCodeClient._clean_progress_text(
            "curl -H 'Authorization: Bearer secret-token' "
            "https://example.test API_KEY=abc123 "
            "OPENAI_API_KEY=openai-secret ANTHROPIC_API_KEY=anthropic-secret "
            "XAI_API_KEY=xai-secret --token cli-secret sk-1234567890abcdef",
            500,
        )

        for secret in (
            "secret-token",
            "abc123",
            "openai-secret",
            "anthropic-secret",
            "xai-secret",
            "cli-secret",
            "sk-1234567890abcdef",
        ):
            self.assertNotIn(secret, cleaned)
        self.assertIn("[redacted]", cleaned)

    def test_heartbeat_uses_real_phase_without_nesting_prior_heartbeat(self):
        substantive = {
            "event_type": "message.part.updated",
            "status": "OpenCode: Running tests",
        }
        first = OpenCodeClient._heartbeat_status(substantive, 65)
        second = OpenCodeClient._heartbeat_status(
            {"event_type": "jarvis.heartbeat", "status": first},
            125,
        )

        self.assertEqual(
            first,
            "OpenCode is still active (1m 5s elapsed) — Running tests",
        )
        self.assertEqual(second, "OpenCode is still active (2m 5s elapsed)")
        self.assertEqual(second.count("still active"), 1)

    def test_usable_final_response_accepts_legacy_content_but_not_reasoning(self):
        self.assertTrue(
            OpenCodeClient._has_usable_final_response(
                {"content": [{"type": "text", "text": "done"}]}
            )
        )
        self.assertFalse(
            OpenCodeClient._has_usable_final_response(
                {"parts": [{"type": "reasoning", "text": "private plan"}]}
            )
        )

    def test_normalizer_filters_other_sessions_and_surfaces_blockers(self):
        other = OpenCodeClient._normalize_progress_event(
            {
                "type": "session.status",
                "properties": {"sessionID": "ses_other", "status": {"type": "busy"}},
            },
            "ses_123",
        )
        blocked = OpenCodeClient._normalize_progress_event(
            {
                "type": "question.asked",
                "properties": {
                    "sessionID": "ses_123",
                    "questions": [{"question": "Which port should I use?"}],
                },
            },
            "ses_123",
        )

        self.assertIsNone(other)
        self.assertTrue(blocked["terminal"])
        self.assertIn("Which port", blocked["status"])

    def test_normalizes_current_next_tool_success_without_exposing_result(self):
        progress = OpenCodeClient._normalize_progress_event(
            {
                "type": "session.next.tool.success",
                "properties": {
                    "sessionID": "ses_123",
                    "callID": "call_123",
                    "result": {"stdout": "sensitive raw command output"},
                },
            },
            "ses_123",
        )

        self.assertEqual(progress["tool_status"], "completed")
        self.assertNotIn("result", progress)
        self.assertNotIn("sensitive", progress["status"])

    def test_execute_task_forwards_progress_and_preserves_final_response(self):
        client = self._make_client()
        client.logger = MagicMock()
        observed = []
        assistant = {"parts": [{"type": "text", "text": "done"}]}

        with patch.object(client, "create_session", return_value={"id": "ses_live"}), \
             patch.object(client, "send_message", side_effect=[{"ok": True}, {"ok": True}]), \
             patch.object(
                 client,
                 "_send_message_with_progress",
                 side_effect=lambda **kwargs: (
                     kwargs["progress_callback"]({
                         "phase": "tool",
                         "status": "OpenCode: Running tests",
                         "event_type": "message.part.updated",
                     }) or assistant,
                     "sse",
                 ),
             ):
            result = client.execute_task(
                task="Build a demo",
                context={"task_type": "coding"},
                progress_callback=observed.append,
            )

        self.assertTrue(result["ok"])
        self.assertIs(result["result"], assistant)
        self.assertEqual(result["progress_transport"], "sse")
        self.assertTrue(any(item["phase"] == "tool" for item in observed))
        self.assertEqual(observed[-1]["phase"], "complete")

    def test_execute_task_aborts_session_when_final_request_times_out(self):
        client = self._make_client()
        client.logger = MagicMock()

        def send_message(session_id, message, *args, **kwargs):
            del session_id, message, args
            if kwargs.get("no_reply"):
                return {"ok": True}
            raise TimeoutError("task deadline reached")

        with patch.object(client, "create_session", return_value={"id": "ses_timeout"}), \
             patch.object(client, "send_message", side_effect=send_message), \
             patch.object(client, "abort_session", return_value=True) as mock_abort:
            result = client.execute_task(
                task="Build a demo",
                context={"task_type": "coding"},
            )

        self.assertFalse(result["ok"])
        self.assertIn("task deadline reached", result["error"])
        mock_abort.assert_called_once_with("ses_timeout")

    def test_supervised_message_uses_polling_when_sse_is_unavailable(self):
        client = self._make_client()
        observed = []

        def failed_stream(event_queue, _stop_event, ready_event):
            ready_event.set()
            event_queue.put({"_monitor_error": "stream unavailable"})

        def delayed_final(*_args):
            time.sleep(0.1)
            return {"parts": [{"type": "text", "text": "done"}]}

        polled = {
            "session_id": "ses_poll",
            "event_type": "todo.updated",
            "phase": "todo",
            "status": "OpenCode is working on: Run tests",
            "source": "poll",
        }

        with patch.object(client, "_stream_events", side_effect=failed_stream), \
             patch.object(client, "send_message", side_effect=delayed_final), \
             patch.object(client, "_poll_session_progress", return_value=polled):
            result, progress_transport = client._send_message_with_progress(
                session_id="ses_poll",
                message="Build it",
                provider_id="xai",
                model_id="grok-build-0.1",
                progress_callback=observed.append,
            )

        self.assertEqual(progress_transport, "poll")
        self.assertEqual(result["parts"][0]["text"], "done")
        self.assertEqual(observed[0]["source"], "poll")

    def test_supervised_message_aborts_and_reports_question_blocker(self):
        client = self._make_client()
        release_request = threading.Event()

        def blocked_stream(event_queue, _stop_event, ready_event):
            ready_event.set()
            event_queue.put(
                {
                    "type": "question.asked",
                    "properties": {
                        "sessionID": "ses_blocked",
                        "questions": [{"question": "Which port should I use?"}],
                    },
                }
            )

        def delayed_final(*_args):
            release_request.wait(timeout=1)
            return {"parts": []}

        def abort(_session_id):
            release_request.set()
            return True

        with patch.object(client, "_stream_events", side_effect=blocked_stream), \
             patch.object(client, "send_message", side_effect=delayed_final), \
             patch.object(client, "abort_session", side_effect=abort) as mock_abort:
            with self.assertRaisesRegex(RuntimeError, "Which port"):
                client._send_message_with_progress(
                    session_id="ses_blocked",
                    message="Build it",
                    provider_id="xai",
                    model_id="grok-build-0.1",
                    progress_callback=lambda _event: None,
                )

        mock_abort.assert_called_once_with("ses_blocked")

    def test_late_terminal_event_does_not_discard_authoritative_final_text(self):
        client = self._make_client()
        final_returned = threading.Event()
        observed = []

        def late_terminal_stream(event_queue, _stop_event, ready_event):
            ready_event.set()
            final_returned.wait(timeout=1)
            time.sleep(0.03)
            event_queue.put(
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "ses_final",
                        "error": {"message": "late stale error"},
                    },
                }
            )

        def final_message(*_args):
            final_returned.set()
            return {"parts": [{"type": "text", "text": "authoritative answer"}]}

        with patch.object(client, "_stream_events", side_effect=late_terminal_stream), \
             patch.object(client, "send_message", side_effect=final_message), \
             patch.object(client, "abort_session") as mock_abort:
            result, _progress_transport = client._send_message_with_progress(
                session_id="ses_final",
                message="Build it",
                provider_id="xai",
                model_id="grok-build-0.1",
                progress_callback=observed.append,
            )

        self.assertEqual(result["parts"][0]["text"], "authoritative answer")
        self.assertFalse(any(event.get("terminal") for event in observed))
        mock_abort.assert_not_called()


if __name__ == "__main__":
    unittest.main()
