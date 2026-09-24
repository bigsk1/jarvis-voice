"""One-shot approvals for foreground Web chat tool calls.

Only the running Web worker owns the prepared arguments. Clients receive a
bounded, redacted description and can resolve that one pending call by ID.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from security_utils import redact_sensitive_data, redact_sensitive_text
from ssh_remote_commands import (
    SSH_TEST_COMMAND, SSH_APT_UPDATE_COMMAND, SSH_APT_CHECK_COMMAND,
    SSH_APT_UPGRADE_COMMAND,
)


APPROVAL_TTL_SECONDS = 180
_PREVIEW_KEYS = (
    'action', 'method', 'to', 'recipient', 'subject', 'host', 'webhook', 'url',
    'command', 'commands', 'task', 'context', 'persona', 'body', 'data', 'params',
    'message', 'sudo', 'upgrade', 'stop_on_error', 'attachment', 'attachment_path',
    'attachment_ref', 'image_url', 'link_url', 'link_text', 'add_name', 'add_number',
    'call_id', 'output_limit',
)


def _safe_preview(arguments: dict) -> dict[str, str]:
    preview = {}
    for key in _PREVIEW_KEYS:
        value = arguments.get(key)
        if key == 'webhook' and isinstance(value, str) and '://' in value:
            key_is_url = True
        else:
            key_is_url = key in ('url', 'image_url', 'link_url')
        if isinstance(value, bool):
            shown = 'yes' if value else 'no'
        elif isinstance(value, (dict, list)):
            shown = json.dumps(redact_sensitive_data(value), ensure_ascii=False, sort_keys=True)
        elif isinstance(value, (str, int, float)):
            shown = str(value).strip()
        else:
            continue
        if not shown:
            continue
        if key_is_url:
            try:
                parsed = urlsplit(shown)
                if parsed.scheme:
                    hostname = parsed.hostname or ''
                    if ':' in hostname:
                        hostname = f'[{hostname}]'
                    port = f':{parsed.port}' if parsed.port is not None else ''
                    shown = f'{parsed.scheme}://{hostname}{port}{parsed.path}'
                else:
                    shown = '[invalid URL]'
            except ValueError:
                shown = '[invalid URL]'
        shown = redact_sensitive_text(shown).replace('\n', ' ')
        preview[key] = shown if len(shown) <= 500 else shown[:500] + '… [preview truncated]'
    headers = arguments.get('headers')
    if isinstance(headers, dict):
        names = ', '.join(str(key) for key in headers)
        preview['headers'] = (redact_sensitive_text(names[:400]) + ' [values hidden]'
                              if names else '[values hidden]')
    omitted = sorted(str(key) for key in arguments if key not in _PREVIEW_KEYS and key != 'headers')
    if omitted:
        preview['other_arguments'] = ', '.join(omitted[:20]) + ('…' if len(omitted) > 20 else '') + ' [values hidden]'
    return preview


def _call_description(tool: str, preview: dict[str, str], permissions: dict,
                      arguments: dict | None = None) -> dict:
    """Describe the prepared action once for every Web approval surface."""
    get = lambda key, fallback='': preview.get(key) or fallback
    arguments = arguments or {}
    detail = []
    ssh_action = None
    if tool == 'send_email':
        summary = f"Send an email to {get('to', 'the selected recipient')}?"
        if get('subject'):
            detail.append(f"Subject: {get('subject')}")
        if get('body'):
            detail.append(f"Message: {get('body')}")
        if get('attachment') or get('attachment_path'):
            detail.append(f"Attachment: {get('attachment') or get('attachment_path')}")
    elif tool == 'ssh_remote':
        action = arguments.get('action') or get('action', 'run')
        ssh_action = action
        host = get('host', 'the selected host')
        if action == 'test':
            summary = f"Test the SSH connection to {host}?"
            detail.append(f"Built-in check: {SSH_TEST_COMMAND}")
        elif action == 'list_hosts':
            summary = 'List configured SSH hosts?'
            detail.append('No remote command will run.')
        elif action == 'apt_update':
            upgrade = arguments.get('upgrade', True) is not False
            summary = f"Check and upgrade packages on {host}?" if upgrade else f"Check package updates on {host}?"
            detail.extend((f"Runs with sudo: {SSH_APT_UPDATE_COMMAND}",
                           f"Then checks: {SSH_APT_CHECK_COMMAND}"))
            if upgrade:
                detail.append(f"If updates are available, runs with sudo: {SSH_APT_UPGRADE_COMMAND}")
            detail.append('The sudo password is sent over SSH and is not shown here.')
            if upgrade:
                detail.append('If interrupted, check package state on the host before retrying.')
        else:
            commands = arguments.get('commands') if action == 'multi' else [arguments.get('command')]
            commands = commands if isinstance(commands, list) else []
            summary = (f"Run {len(commands)} commands on {host}?" if action == 'multi'
                       else f"Run a command on {host}?")
            for index, command in enumerate(commands[:10], 1):
                if not isinstance(command, str):
                    continue
                shown = redact_sensitive_text(command)
                if len(shown) > 500:
                    shown = shown[:500] + '… [preview truncated]'
                exact = shown == command
                label = f"Command {index}" if action == 'multi' else 'Command'
                detail.append(f"{label}{' preview' if not exact else ''}: {shown}")
            if len(commands) > 10:
                detail.append(f"{len(commands) - 10} additional commands are not shown.")
            if arguments.get('sudo') is True:
                detail.append('Runs with sudo; the password is sent over SSH and is not shown here.')
    elif tool == 'api_call':
        summary = f"Send a {get('method', 'web')} request to {get('url', 'the selected URL')}?"
        if get('body') or get('data'):
            detail.append(f"Content: {get('body') or get('data')}")
    elif tool == 'send_webhook':
        summary = f"Send a webhook to {get('webhook') or get('url', 'the selected destination')}?"
        if get('data'):
            detail.append(f"Content: {get('data')}")
    elif tool == 'phone_call':
        action = get('action', 'call')
        if action == 'contacts' and get('add_number'):
            summary = f"Save {get('add_name', 'a contact')} at {get('add_number')}?"
        elif action == 'call':
            summary = f"Call {get('recipient', 'the selected recipient')}?"
            if get('task'):
                detail.append(f"Purpose: {get('task')}")
        else:
            summary = f"Use phone calls to {action}?"
    else:
        summary = f"Run {tool.replace('_', ' ')}?"
        if preview:
            detail.append('Review the prepared call details before allowing it.')
    risks = []
    if permissions.get('dangerous'):
        risks.append('have lasting effects')
    if permissions.get('bash'):
        risks.append('run commands')
    if permissions.get('network'):
        risks.append('connect to the network')
    if permissions.get('filesystem'):
        risks.append('access files')
    warning = 'This call may ' + ', '.join(risks) + '.' if risks else ''
    if ssh_action == 'test':
        warning = 'Connects to the host and runs the read-only check above.'
    elif ssh_action == 'list_hosts':
        warning = ''
    return {'summary': summary, 'detail': detail, 'warning': warning}


@dataclass
class _PendingApproval:
    public: dict
    call_hash: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: str | None = None


class ToolApprovals:
    def __init__(self, handler):
        self.handler = handler
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingApproval] = {}

    @staticmethod
    def call_hash(tool: str, arguments: dict) -> str:
        canonical = json.dumps({'tool': tool, 'arguments': arguments}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def request(self, *, conversation_id: str, message_id: str, tool: str,
                arguments: dict, permissions: dict, call_index: int,
                cancel_check) -> str:
        approval_id = uuid.uuid4().hex
        preview = _safe_preview(arguments)
        if tool == 'ssh_remote':
            # The bounded command description below is the only public copy.
            preview.pop('command', None)
            preview.pop('commands', None)
        public = {
            'approval_id': approval_id,
            'conversation_id': conversation_id,
            'message_id': message_id,
            'tool': tool,
            'call_index': call_index,
            'preview': preview,
            **_call_description(tool, preview, permissions, arguments),
            'permissions': {str(key): value for key, value in permissions.items()
                            if isinstance(value, bool)},
            'expires_at': time.time() + APPROVAL_TTL_SECONDS,
        }
        pending = _PendingApproval(public=public, call_hash=self.call_hash(tool, arguments))
        runs = self.handler.runs
        room = self.handler._delivery_room('', conversation_id)
        with self._lock:
            self._pending[approval_id] = pending
        outcome = 'expired'
        published = False
        try:
            with runs.conversation_lock(conversation_id):
                run = runs.active.get(conversation_id)
                if not run or run['message_id'] != message_id or cancel_check():
                    outcome = 'cancelled'
                    return outcome
                run['approval'] = public
                run['status_text'] = 'Waiting for your decision…'
                published = True
                self.handler._emit_run_event('chat:run', runs.public(run), room=room)
                self.handler._emit_run_event('tool:approval_required', public, room=room)
            while not pending.event.wait(0.2):
                if cancel_check():
                    outcome = 'cancelled'
                    return outcome
                if time.time() >= public['expires_at']:
                    return outcome
            if cancel_check():
                outcome = 'cancelled'
                return outcome
            if pending.decision != 'approved':
                outcome = 'denied'
                return outcome
            if time.time() >= public['expires_at'] or self.call_hash(tool, arguments) != pending.call_hash:
                return outcome
            outcome = 'approved'
            return outcome
        finally:
            with self._lock:
                self._pending.pop(approval_id, None)
            if published:
                with runs.conversation_lock(conversation_id):
                    run = runs.active.get(conversation_id)
                    if run and run['message_id'] == message_id and run.get('approval', {}).get('approval_id') == approval_id:
                        run.pop('approval', None)
                        run['status_text'] = 'Continuing…' if outcome == 'approved' else 'Finishing partial result…'
                        self.handler._emit_run_event('chat:run', runs.public(run), room=room)
                    self.handler._emit_run_event('tool:approval_resolved', {
                        'approval_id': approval_id, 'conversation_id': conversation_id,
                        'message_id': message_id,
                        'decision': outcome,
                    }, room=room)

    def decide(self, *, approval_id: str, conversation_id: str, message_id: str,
               approved: bool) -> bool:
        if type(approved) is not bool:
            return False
        with self._lock:
            pending = self._pending.get(approval_id)
            if (not pending or pending.decision is not None
                    or pending.public['conversation_id'] != conversation_id
                    or pending.public['message_id'] != message_id
                    or time.time() >= pending.public['expires_at']):
                return False
            with self.handler.runs.lock:
                run = self.handler.runs.active.get(conversation_id)
                if (not run or run['message_id'] != message_id or run.get('status') != 'running'
                        or run.get('approval', {}).get('approval_id') != approval_id):
                    return False
            pending.decision = 'approved' if approved else 'denied'
            pending.event.set()
            return True
