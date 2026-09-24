"""Approval is a one-shot decision on a prepared foreground Web call."""

import sys
import threading
import time
from pathlib import Path

from server_package_utils import load_server_package


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jarvis-web"))
sys.path.insert(0, str(ROOT / "lib"))
load_server_package("jarvis_web_approval_test_server", ROOT / "jarvis-web" / "server")
from jarvis_web_approval_test_server.services.tool_approvals import ToolApprovals  # noqa: E402
from jarvis_web_approval_test_server.services import tool_approvals  # noqa: E402
from jarvis_web_approval_test_server.services.chat_runs import ChatRuns  # noqa: E402


class _Handler:
    def __init__(self):
        self.events = []
        self.runs = ChatRuns(lambda: None, lambda *args, **kwargs: None)
        self.runs.active['conversation'] = {
            'conversation_id': 'conversation', 'message_id': 'message',
            'status': 'running', 'status_text': 'Working…',
        }

    def _delivery_room(self, _sid, conversation_id):
        return conversation_id

    def _emit_run_event(self, event, payload, **_kwargs):
        self.events.append((event, payload))


def _request_in_thread(manager, result, *, cancelled=lambda: False, arguments=None,
                       tool='api_call', permissions=None):
    thread = threading.Thread(target=lambda: result.append(manager.request(
        conversation_id='conversation', message_id='message', tool=tool,
        arguments=arguments or {'url': 'https://example.test/path?token=secret', 'method': 'GET'},
        permissions=permissions or {'network': True, 'auto_approve': False}, call_index=0,
        cancel_check=cancelled,
    )), daemon=True)
    thread.start()
    for _ in range(100):
        if manager.handler.runs.active['conversation'].get('approval'):
            break
        time.sleep(0.01)
    assert manager.handler.runs.active['conversation'].get('approval')
    return thread, manager.handler.runs.active['conversation']['approval']


def test_denial_stops_without_reusing_or_exposing_exact_arguments():
    handler = _Handler()
    manager = ToolApprovals(handler)
    result = []
    thread, approval = _request_in_thread(manager, result)
    assert approval['preview']['url'] == 'https://example.test/path'
    assert 'secret' not in str(approval)
    assert manager.decide(approval_id=approval['approval_id'], conversation_id='wrong',
                          message_id='message', approved=True) is False
    assert manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                          message_id='message', approved=False) is True
    assert manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                          message_id='message', approved=True) is False
    thread.join(2)
    assert result == ['denied']
    assert handler.runs.active['conversation'].get('approval') is None
    assert handler.events[-1][1]['decision'] == 'denied'


def test_approval_runs_only_once_and_stop_wins_race():
    handler = _Handler()
    manager = ToolApprovals(handler)
    result = []
    thread, approval = _request_in_thread(manager, result)
    assert manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                          message_id='message', approved=True)
    thread.join(2)
    assert result == ['approved']
    assert not manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                              message_id='message', approved=True)

    cancelled = threading.Event()
    thread, approval = _request_in_thread(manager, result, cancelled=cancelled.is_set)
    cancelled.set()
    thread.join(2)
    assert result[-1] == 'cancelled'
    assert handler.events[-1][1]['decision'] == 'cancelled'


def test_full_call_hash_changes_with_prepared_arguments():
    first = ToolApprovals.call_hash('api_call', {'method': 'POST', 'url': 'https://example.test', 'body': 'one'})
    second = ToolApprovals.call_hash('api_call', {'method': 'POST', 'url': 'https://example.test', 'body': 'two'})
    assert first != second


def test_preview_keeps_target_port_but_not_credentials_or_query():
    preview = tool_approvals._safe_preview({
        'url': 'https://user:password@example.test:8443/path?token=private',
        'body': {'title': 'Visible', 'api_key': 'private'},
        'headers': {'Authorization': 'Bearer private', 'X-Request-ID': 'private'},
        'unknown_future_field': 'private',
    })
    assert preview['url'] == 'https://example.test:8443/path'
    assert 'Visible' in preview['body']
    assert 'Authorization' in preview['headers']
    assert 'unknown_future_field' in preview['other_arguments']
    assert 'private' not in str(preview)


def test_webhook_target_and_phone_contact_change_are_visible_without_url_secrets():
    preview = tool_approvals._safe_preview({
        'webhook': 'https://user:password@hooks.example.test/send?token=private',
        'add_name': 'Alex', 'add_number': '+15551234567',
        'attachment': 'stash://example/document.pdf',
    })
    assert preview['webhook'] == 'https://hooks.example.test/send'
    assert preview['add_number'] == '+15551234567'
    assert preview['attachment'] == 'stash://example/document.pdf'
    assert 'private' not in str(preview)


def test_action_description_uses_the_target_and_a_short_risk_warning():
    describe = tool_approvals._call_description
    email = describe('send_email', {'to': 'alex@example.test', 'subject': 'Friday',
                                    'body': 'See you then'}, {'network': True, 'auto_approve': False})
    assert email['summary'] == 'Send an email to alex@example.test?'
    assert email['detail'] == ['Subject: Friday', 'Message: See you then']
    assert 'network' in email['warning']
    assert 'auto approve' not in str(email)
    ssh = describe('ssh_remote', {'host': 'host.example.test', 'command': 'uptime'},
                   {'bash': True, 'dangerous': True},
                   {'action': 'run', 'host': 'host.example.test', 'command': 'uptime'})
    assert ssh['summary'] == 'Run a command on host.example.test?'
    assert ssh['detail'] == ['Command: uptime']
    assert 'lasting effects' in ssh['warning']


def test_ssh_approval_describes_the_actual_action_and_builtin_commands():
    describe = tool_approvals._call_description
    test = describe('ssh_remote', {'host': 'vps2', 'action': 'test'},
                    {'bash': True, 'network': True}, {'action': 'test', 'host': 'vps2'})
    assert test['summary'] == 'Test the SSH connection to vps2?'
    assert test['detail'] == [f'Built-in check: {tool_approvals.SSH_TEST_COMMAND}']
    assert 'lasting effects' not in test['warning']
    assert 'read-only' in test['warning']

    listing = describe('ssh_remote', {'action': 'list_hosts'},
                       {'network': True}, {'action': 'list_hosts'})
    assert listing['detail'] == ['No remote command will run.']
    assert listing['warning'] == ''

    update = describe('ssh_remote', {'host': 'vps2', 'action': 'apt_update', 'upgrade': 'no'},
                      {'bash': True}, {'action': 'apt_update', 'host': 'vps2', 'upgrade': False})
    assert update['summary'] == 'Check package updates on vps2?'
    assert update['detail'] == [
        'Runs with sudo: apt update',
        "Then checks: apt list --upgradable 2>/dev/null | grep -v 'Listing'",
        'The sudo password is sent over SSH and is not shown here.',
    ]
    upgrading = describe('ssh_remote', {'host': 'vps2', 'action': 'apt_update'},
                         {'bash': True}, {'action': 'apt_update', 'host': 'vps2'})
    assert 'If interrupted, check package state on the host before retrying.' in upgrading['detail']


def test_ssh_command_preview_redacts_secrets_and_marks_truncation():
    command = 'curl -H "Authorization: Bearer abcdefghijklmnopqrstuvwxyz" https://example.test'
    shown = tool_approvals._call_description(
        'ssh_remote', {'host': 'vps2'}, {'bash': True},
        {'action': 'run', 'host': 'vps2', 'command': command, 'sudo': True},
    )
    assert shown['detail'][0].startswith('Command preview: curl -H')
    assert '[redacted]' in shown['detail'][0]
    assert 'abcdefghijklmnopqrstuvwxyz' not in str(shown)
    assert shown['detail'][1] == 'Runs with sudo; the password is sent over SSH and is not shown here.'

    multiline = tool_approvals._call_description(
        'ssh_remote', {'host': 'vps2'}, {'bash': True},
        {'action': 'run', 'host': 'vps2', 'command': 'printf first\nprintf second'},
    )
    assert multiline['detail'] == ['Command: printf first\nprintf second']

    truncated = tool_approvals._call_description(
        'ssh_remote', {'host': 'vps2'}, {'bash': True},
        {'action': 'run', 'host': 'vps2', 'command': 'x' * 501},
    )
    assert truncated['detail'][0].startswith('Command preview: ')
    assert '[preview truncated]' in truncated['detail'][0]

    long_commands = ['printf hello'] * 10 + ['printf hidden']
    multiple = tool_approvals._call_description(
        'ssh_remote', {'host': 'vps2'}, {'bash': True},
        {'action': 'multi', 'host': 'vps2', 'commands': long_commands},
    )
    assert multiple['summary'] == 'Run 11 commands on vps2?'
    assert multiple['detail'][-1] == '1 additional commands are not shown.'
    assert 'hidden' not in str(multiple)


def test_ssh_builtin_commands_and_sudo_are_backed_by_execution(monkeypatch):
    from skills import ssh_remote

    class Client:
        def close(self):
            pass

    calls = []
    monkeypatch.setattr(ssh_remote, 'get_host_config', lambda _host: {'sudo_env': 'SUDO_SECRET'})
    monkeypatch.setattr(ssh_remote, 'get_config_value', lambda _key: 'backend-only')
    monkeypatch.setattr(ssh_remote, 'connect_ssh', lambda _config: Client())

    def run_command(_client, command, **options):
        calls.append((command, options))
        return {'success': True, 'stdout': 'one upgradable package', 'stderr': '',
                'exit_code': 0, 'truncated': False}

    monkeypatch.setattr(ssh_remote, 'run_command', run_command)
    ssh_remote.test_connection('vps2')
    assert calls[0][0] == tool_approvals.SSH_TEST_COMMAND
    assert calls[0][1].get('sudo') is None

    calls.clear()
    ssh_remote.apt_update('vps2', upgrade=True)
    assert [command for command, _options in calls] == [
        tool_approvals.SSH_APT_UPDATE_COMMAND,
        tool_approvals.SSH_APT_CHECK_COMMAND,
        tool_approvals.SSH_APT_UPGRADE_COMMAND,
    ]
    assert [options.get('sudo') for _command, options in calls] == [True, False, True]
    assert calls[0][1]['sudo_password'] == 'backend-only'
    assert calls[2][1]['sudo_password'] == 'backend-only'


def test_ssh_request_exposes_only_one_bounded_command_description():
    handler = _Handler()
    manager = ToolApprovals(handler)
    result = []
    command = 'printf hello'
    thread, approval = _request_in_thread(
        manager, result, tool='ssh_remote',
        arguments={'action': 'run', 'host': 'vps2', 'command': command},
    )
    assert approval['detail'] == ['Command: printf hello']
    assert 'command' not in approval['preview']
    manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                   message_id='message', approved=False)
    thread.join(2)
    assert result == ['denied']


def test_unanswered_approval_expires_and_cannot_be_reused(monkeypatch):
    monkeypatch.setattr(tool_approvals, 'APPROVAL_TTL_SECONDS', 0.03)
    handler = _Handler()
    manager = ToolApprovals(handler)
    result = []
    thread, approval = _request_in_thread(manager, result)
    thread.join(2)
    assert result == ['expired']
    assert not manager.decide(approval_id=approval['approval_id'], conversation_id='conversation',
                              message_id='message', approved=True)
