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

        with patch("opencode_client.requests.get", return_value=FakeResponse({"version": "2.1.0"})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            return OpenCodeClient(base_url="http://opencode.test")

    def test_create_session_includes_agent_mode_string(self):
        client = self._make_client()

        with patch("opencode_client.requests.post", return_value=FakeResponse({"data": {"id": "ses_123"}})) as mock_post, \
             patch("opencode_client.get_jarvis_workspace", return_value=Path("/tmp/opencode-unit-workspace")):
            response = client.create_session(title="Jarvis: demo", agent_mode="build")

        self.assertEqual(response["id"], "ses_123")
        mock_post.assert_called_once_with(
            "http://opencode.test/api/session",
            json={"title": "Jarvis: demo", "agent": "build", "location": {"directory": "/tmp/opencode-unit-workspace"}},
            timeout=client.timeout,
        )

    def test_no_reply_context_messages_use_a_short_http_timeout(self):
        client = self._make_client()

        with patch(
            "opencode_client.requests.post",
            return_value=FakeResponse({"data": {"id": "msg_context", "type": "synthetic"}}),
        ) as mock_post, patch("opencode_client.uuid.uuid4", return_value=MagicMock(hex="context")):
            client.send_message("ses_123", "context", no_reply=True)

        self.assertEqual(
            mock_post.call_args.kwargs["timeout"],
            client.NO_REPLY_TIMEOUT_SECONDS,
        )
        self.assertFalse(mock_post.call_args.kwargs["json"]["resume"])
        self.assertEqual(mock_post.call_args.args[0], "http://opencode.test/api/session/ses_123/synthetic")

    def test_final_task_wait_uses_configured_task_timeout(self):
        client = self._make_client({"OPENCODE_TASK_TIMEOUT_SECONDS": "900"})
        with patch.object(client, "_post", side_effect=[
            FakeResponse(None, 204),
            FakeResponse({"data": {"id": "msg_input", "type": "user"}}),
            FakeResponse(None, 204),
        ]) as mock_post, patch("opencode_client.uuid.uuid4", return_value=MagicMock(hex="input")), patch.object(client, "_collect_final_response", return_value={"parts": [{"type": "text", "text": "done"}]}):
            client.send_message("ses_123", "build it")
        self.assertEqual(client.task_timeout, 900)
        self.assertTrue(890 < mock_post.call_args.kwargs["timeout"] <= 900)
        self.assertEqual(mock_post.call_args.args[0], "/api/experimental/session/ses_123/wait")

    def test_invalid_task_timeout_uses_safe_default(self):
        client = self._make_client({"OPENCODE_TASK_TIMEOUT_SECONDS": "invalid"})

        self.assertEqual(client.task_timeout, client.DEFAULT_TASK_TIMEOUT_SECONDS)

    def test_uses_basic_auth_when_server_password_is_configured(self):
        client = self._make_client({
            "OPENCODE_SERVER_USERNAME": "opencode",
            "OPENCODE_SERVER_PASSWORD": "secret",
        })

        with patch("opencode_client.requests.post", return_value=FakeResponse({"data": {"id": "ses_123"}})) as mock_post, \
             patch("opencode_client.get_jarvis_workspace", return_value=Path("/tmp/opencode-unit-workspace")):
            client.create_session(title="Jarvis: demo", agent_mode="build")

        mock_post.assert_called_once_with(
            "http://opencode.test/api/session",
            json={"title": "Jarvis: demo", "agent": "build", "location": {"directory": "/tmp/opencode-unit-workspace"}},
            timeout=client.timeout,
            auth=("opencode", "secret"),
        )

    def test_resolve_opencode_defaults_uses_catalog_when_model_unset(self):
        def fake_get_config(key, default=""):
            values = {
                "OPENCODE_PROVIDER": "xai",
                "OPENCODE_MODEL": "",
            }
            return values.get(key, default)

        with patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.get_provider_fallback_model", return_value="fixture-xai-model") as fallback:
            defaults = resolve_opencode_defaults("cloud")

        self.assertEqual(defaults["providerID"], "xai")
        self.assertEqual(defaults["modelID"], "fixture-xai-model")
        fallback.assert_called_once_with("xai")

    def test_client_uses_catalog_fallback_when_opencode_model_unset(self):
        def fake_get_config(key, default=None):
            values = {
                "OPENCODE_PROVIDER": "anthropic",
                "OPENCODE_MODEL": "",
                "OPENCODE_SERVER_PASSWORD": "",
                "OPENCODE_SERVER_USERNAME": "opencode",
            }
            return values.get(key, default)

        with patch("opencode_client.requests.get", return_value=FakeResponse({"version": "2.1.0"})), \
             patch("config_loader.get_config_value", side_effect=fake_get_config), \
             patch("opencode_client.get_provider_fallback_model", return_value="fixture-anthropic-model") as fallback, \
             patch("opencode_client.OpenCodeLogger", return_value=MagicMock()):
            client = OpenCodeClient(base_url="http://opencode.test")

        self.assertEqual(client.default_provider_id, "anthropic")
        self.assertEqual(client.default_model_id, "fixture-anthropic-model")
        fallback.assert_called_once_with("anthropic")

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
            'event: session.execution.started',
            'data: {"type":"session.execution.started",',
            'data: "data":{"sessionID":"ses_123"}}',
            '',
        ]))

        self.assertEqual(payloads[0]["type"], "session.execution.started")
        self.assertEqual(payloads[0]["data"]["sessionID"], "ses_123")

    def test_sse_read_timeout_exceeds_legacy_keepalive_interval(self):
        client = self._make_client()
        stop_event = threading.Event()
        ready_event = threading.Event()
        event_queue = queue.Queue()

        class EventResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def iter_lines(self, chunk_size=None, decode_unicode=False):
                self.chunk_size = chunk_size
                self.decode_unicode = decode_unicode
                yield 'data: {"type":"server.connected","data":{}}'
                yield ""
                stop_event.set()

            def close(self):
                return None

        with patch.object(client, "_get", return_value=EventResponse()) as mock_get:
            client._stream_events(event_queue, stop_event, ready_event)

        self.assertTrue(ready_event.is_set())
        self.assertGreater(mock_get.call_args.kwargs["timeout"][1], 30)
        self.assertTrue(event_queue.get_nowait()["_monitor_connected"])

    def test_normalizes_v2_tool_progress_without_raw_output(self):
        progress = OpenCodeClient._normalize_progress_event({
            "id": "evt_tool", "created": 100,
            "type": "session.tool.success",
            "durable": {"aggregateID": "ses_123", "seq": 1, "version": 2},
            "data": {
                "sessionID": "ses_123", "assistantMessageID": "msg_assistant", "id": "call_123",
                "executed": True, "content": [{"type": "text", "text": "PRIVATE RAW OUTPUT"}],
            },
        }, "ses_123")
        self.assertEqual(progress["phase"], "tool")
        self.assertEqual(progress["tool_status"], "completed")
        self.assertNotIn("PRIVATE RAW OUTPUT", str(progress))

    def test_normalizes_v2_tool_input_start(self):
        progress = OpenCodeClient._normalize_progress_event({
            "id": "evt_tool", "created": 100,
            "type": "session.tool.input.started",
            "durable": {"aggregateID": "ses_123", "seq": 1, "version": 1},
            "data": {"sessionID": "ses_123", "assistantMessageID": "msg_assistant", "id": "call_123", "name": "bash"},
        }, "ses_123")
        self.assertEqual(progress["phase"], "tool")
        self.assertIn("command", progress["status"])

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
        other = OpenCodeClient._normalize_progress_event({
            "type": "session.execution.started", "data": {"sessionID": "ses_other"},
        }, "ses_123")
        blocked = OpenCodeClient._normalize_progress_event({
            "type": "form.created",
            "data": {"form": {"id": "form_123", "sessionID": "ses_123", "title": "Which port should I use?", "fields": [{"key": "port", "type": "string", "title": "Which port should I use?"}]}},
        }, "ses_123")
        self.assertIsNone(other)
        self.assertTrue(blocked["terminal"])
        self.assertIn("Which port", blocked["status"])

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
                    "type": "form.created",
                    "data": {"form": {"id": "form_123", "sessionID": "ses_blocked", "title": "Which port should I use?", "fields": [{"key": "port", "type": "string", "title": "Which port should I use?"}]}},
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
                    "type": "session.execution.failed",
                    "data": {
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
