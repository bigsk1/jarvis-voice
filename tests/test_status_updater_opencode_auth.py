#!/usr/bin/env python3
"""
Regression tests for OpenCode status polling auth.

Run:
    python3 tests/test_status_updater_opencode_auth.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from status_updater import StatusUpdater


class FakeResponse:
    status_code = 200

    def __init__(self, data=None, status_code=200):
        self.data = data if data is not None else [{
            'id': 'msg_recent',
            'type': 'assistant',
            'content': [{'type': 'text', 'text': 'Working on project files'}],
            'time': {'created': 123},
        }]
        self.status_code = status_code

    def json(self):
        return {'data': self.data, 'cursor': {'next': None, 'previous': None}}


class StatusUpdaterOpenCodeAuthTests(unittest.TestCase):
    def test_poll_opencode_session_uses_basic_auth_when_configured(self):
        def fake_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://opencode.test",
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": "secret",
            }
            return values.get(key, default)

        updater = StatusUpdater.__new__(StatusUpdater)

        with patch("status_updater.get_config_value", side_effect=fake_config), \
             patch("requests.get", return_value=FakeResponse()) as mock_get:
            context = updater._poll_opencode_session("ses_123")

        self.assertEqual(context, "Working on project files")
        mock_get.assert_called_once_with(
            "http://opencode.test/api/session/ses_123/message",
            params={'order': 'desc', 'limit': '3'},
            timeout=3,
            auth=("opencode", "secret"),
        )

    def test_poll_opencode_session_omits_auth_without_password(self):
        def fake_config(key, default=None):
            values = {
                "OPENCODE_BASE_URL": "http://opencode.test",
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": "",
            }
            return values.get(key, default)

        updater = StatusUpdater.__new__(StatusUpdater)

        with patch("status_updater.get_config_value", side_effect=fake_config), \
             patch("requests.get", return_value=FakeResponse()) as mock_get:
            context = updater._poll_opencode_session("ses_123")

        self.assertEqual(context, "Working on project files")
        mock_get.assert_called_once_with(
            "http://opencode.test/api/session/ses_123/message",
            params={'order': 'desc', 'limit': '3'},
            timeout=3,
        )

    def test_poll_reads_v2_activity_in_order_without_private_content(self):
        messages = [
            {'type': 'idle', 'outcome': 'succeeded'},
            {'type': 'assistant', 'content': [
                {'type': 'reasoning', 'text': 'PRIVATE REASONING'},
                {'type': 'tool', 'name': 'bash', 'state': {
                    'status': 'completed',
                    'input': {'command': 'PRIVATE COMMAND'},
                    'content': [{'type': 'text', 'text': 'PRIVATE TOOL OUTPUT'}],
                }},
                {'type': 'text', 'text': 'Finished, api_key=private-value'},
            ]},
            {'type': 'user', 'text': 'PRIVATE USER PROMPT'},
        ]
        updater = StatusUpdater.__new__(StatusUpdater)
        with patch('status_updater.get_config_value', side_effect=lambda key, default='': default), \
             patch('requests.get', return_value=FakeResponse(messages)):
            context = updater._poll_opencode_session('ses_123')
        self.assertEqual(context, 'Tool bash: completed\nFinished, api_key=[redacted]\nOpenCode session succeeded')

    def test_poll_handles_failed_request_and_malformed_messages(self):
        updater = StatusUpdater.__new__(StatusUpdater)
        for response in [FakeResponse(status_code=401), FakeResponse(data={'not': 'a list'})]:
            with self.subTest(response=response), \
                 patch('status_updater.get_config_value', side_effect=lambda key, default='': default), \
                 patch('requests.get', return_value=response):
                self.assertIsNone(updater._poll_opencode_session('ses_123'))

    def test_poll_does_not_send_an_unsupported_v2_auth_username(self):
        values = {'OPENCODE_SERVER_USERNAME': 'custom-user', 'OPENCODE_SERVER_PASSWORD': 'secret'}
        updater = StatusUpdater.__new__(StatusUpdater)
        with patch('status_updater.get_config_value', side_effect=lambda key, default='': values.get(key, default)), \
             patch('requests.get') as request:
            self.assertIsNone(updater._poll_opencode_session('ses_123'))
        request.assert_not_called()

    def test_poll_escapes_session_id_and_bounds_context(self):
        updater = StatusUpdater.__new__(StatusUpdater)
        response = FakeResponse([{'type': 'assistant', 'content': [
            {'type': 'text', 'text': 'x' * 1000},
        ]}])
        with patch('status_updater.get_config_value', side_effect=lambda key, default='': default), \
             patch('requests.get', return_value=response) as mock_get:
            context = updater._poll_opencode_session('ses_a/b?c')
        self.assertEqual(len(context), 200)
        self.assertEqual(mock_get.call_args.args[0], 'http://localhost:4096/api/session/ses_a%2Fb%3Fc/message')


if __name__ == "__main__":
    unittest.main()
