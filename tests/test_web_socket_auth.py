"""Real Socket.IO authentication without provider calls or live data writes."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
load_server_package('jarvis_socket_auth_test', ROOT / 'jarvis-web/server')
from jarvis_socket_auth_test import socket_auth  # noqa: E402
import webui_auth  # noqa: E402


@pytest.fixture
def authenticated(monkeypatch):
    monkeypatch.setenv('WEBUI_PASSWORD', 'disposable-test-password')
    monkeypatch.setenv('WEBUI_SECRET', 'disposable-test-secret')
    monkeypatch.setattr(webui_auth, '_log_auth_event', lambda *a, **k: None)
    app = Flask(__name__)
    socket = socket_auth.AuthenticatedSocketIO(app, async_mode='threading')
    seen = []

    @socket.on('connect')
    def connected(auth=None):
        seen.append('connect')

    @socket.on('disconnect')
    def disconnected(reason=None):
        seen.append('disconnect')

    # Includes mutating/configuration events, not only chat admission.
    events = ('chat:send', 'mode:set', 'proactive:ack_alert', 'logs:set_sources')
    for event in events:
        socket.on_event(event, lambda data, name=event: seen.append(name))
    clients = []

    def connect(**kwargs):
        client = socket.test_client(app, **kwargs)
        clients.append(client)
        return client

    yield SimpleNamespace(app=app, socket=socket, connect=connect, seen=seen)
    for client in clients:
        if client.is_connected():
            client.disconnect()
    assert not socket._credentials


@pytest.mark.parametrize('auth', [None, {}, {'token': ''}, {'token': 123}, {'token': 'bad'}])
def test_missing_or_invalid_handshake_never_enters_handlers(authenticated, auth):
    client = authenticated.connect(auth=auth)
    assert not client.is_connected()
    assert not authenticated.seen


def test_expired_handshake_is_rejected(authenticated):
    token = webui_auth.create_token({'exp': time.time() - 1})
    assert not authenticated.connect(auth={'token': token}).is_connected()
    assert not authenticated.seen


def test_valid_extension_auth_and_auth_disabled_compatibility(authenticated, monkeypatch):
    token = webui_auth.create_token()
    client = authenticated.connect(auth={'token': token}, headers={'Origin': 'moz-extension://test'})
    assert client.is_connected()
    client.emit('chat:send', {'message': 'No provider is called'})
    assert authenticated.seen == ['connect', 'chat:send']
    client.disconnect()
    monkeypatch.delenv('WEBUI_PASSWORD')
    open_client = authenticated.connect()
    assert open_client.is_connected()
    open_client.emit('mode:set', {'mode': 'local'})
    assert authenticated.seen[-1] == 'mode:set'


def test_same_origin_cookie_and_http_bearer_compatibility(authenticated):
    token = webui_auth.create_token()
    http = authenticated.app.test_client()
    http.set_cookie('jarvis_auth', token)
    assert authenticated.connect(flask_test_client=http, headers={'Origin': 'http://localhost'}).is_connected()
    assert authenticated.connect(headers={'Authorization': f'Bearer {token}'}).is_connected()
    assert not authenticated.connect(flask_test_client=http, headers={'Origin': 'https://other.test'}).is_connected()
    assert not authenticated.connect(auth={'token': 'invalid'}, flask_test_client=http).is_connected()
    assert not authenticated.connect(query_string=f'auth_token={token}').is_connected()


@pytest.mark.parametrize('event', ['chat:send', 'mode:set', 'proactive:ack_alert', 'logs:set_sources'])
def test_each_event_revalidates_auth_before_entering_its_handler(authenticated, monkeypatch, event):
    now = time.time()
    monkeypatch.setattr(webui_auth, 'time', SimpleNamespace(time=lambda: now))
    token = webui_auth.create_token({'exp': now + 3600})
    client = authenticated.connect(auth={'token': token})
    now += 3601
    client.emit(event, {})
    assert not client.is_connected()
    assert authenticated.seen == ['connect', 'disconnect']


def test_idle_connection_expires_without_waiting_for_a_client_event(authenticated):
    token = webui_auth.create_token({'exp': time.time() + 0.15})
    client = authenticated.connect(auth={'token': token})
    assert client.is_connected()
    deadline = time.monotonic() + 2
    while client.is_connected() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not client.is_connected()
    assert authenticated.seen == ['connect', 'disconnect']


def test_server_status_advertises_the_companion_contract_without_auth(monkeypatch):
    from jarvis_socket_auth_test import app as web_app
    from jarvis_socket_auth_test.routes import api

    monkeypatch.setenv('WEBUI_PASSWORD', 'disposable-test-password')
    monkeypatch.setattr(api, 'get_settings_manager', lambda mode: SimpleNamespace(mode='cloud'))
    monkeypatch.setattr(api, 'get_web_setting', lambda key, default=None: default)
    monkeypatch.setattr(api, 'get_tool_service', lambda mode: SimpleNamespace(get_tool_count=lambda: 0))
    monkeypatch.setattr(api, 'read_tool_sync_status', lambda *a, **k: None)
    assert isinstance(web_app.socketio, socket_auth.AuthenticatedSocketIO)
    response = web_app.app.test_client().get('/api/status')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['features']['auth'] is True
    assert payload['extension'] == {
        'api': 1,
        'socket_auth': True,
        'features': dict.fromkeys(('chat', 'images', 'conversations', 'recovery', 'cancel', 'text', 'library_capture', 'profile', 'talk', 'tool_approval'), True),
    }


def test_auth_expiry_keeps_a_real_admitted_run_recoverable(monkeypatch, journey):
    import flask_socketio
    import test_web_attachment_bundle_chat as helpers
    from jarvis_bundle_chat_test.services import tool_discovery

    monkeypatch.setenv('WEBUI_PASSWORD', 'disposable-test-password')
    monkeypatch.setenv('WEBUI_SECRET', 'disposable-test-secret')
    monkeypatch.setattr(webui_auth, '_log_auth_event', lambda *a, **k: None)
    now = time.time()
    monkeypatch.setattr(webui_auth, 'time', SimpleNamespace(time=lambda: now))
    monkeypatch.setitem(sys.modules, 'jarvis_bundle_chat_test.app',
                        SimpleNamespace(get_startup_mode=lambda: 'cloud'))
    monkeypatch.setattr(tool_discovery, 'get_tool_service',
                        lambda mode: SimpleNamespace(get_tool_count=lambda: 0))
    monkeypatch.setattr(helpers.chat, 'emit', flask_socketio.emit)
    app = Flask(__name__)
    socket = socket_auth.AuthenticatedSocketIO(app, async_mode='threading')
    handler = helpers.chat.ChatHandler(socket)
    tasks = []
    monkeypatch.setattr(handler, '_start_blocking_task', lambda *a, **k: tasks.append(a))
    first = socket.test_client(app, auth={'token': webui_auth.create_token({'exp': now + 3600})})
    second = None
    try:
        first.emit('chat:send', {'message': 'Keep this admitted task', 'mode': 'cloud'})
        cid = next(item['args'][0]['conversation_id'] for item in first.get_received()
                   if item['name'] == 'conversation:created')
        assert len(tasks) == 1  # Worker captured, never run against a provider.
        now += 3601
        first.emit('logs:get_sources')
        assert not first.is_connected()
        assert handler.runs.snapshot(cid)['run']['status'] == 'running'
        assert not handler.pending_cancellations
        second = socket.test_client(app, auth={'token': webui_auth.create_token()})
        second.emit('conversation:load', {'conversation_id': cid, 'reconnect_only': True})
        restored = next(item['args'][0]['conversation'] for item in second.get_received()
                        if item['name'] == 'conversation:loaded')
        assert restored['run']['status'] == 'running'
        assert len(tasks) == 1
    finally:
        for client in (first, second):
            if client and client.is_connected():
                client.disconnect()
        for lease in handler.runs.leases.values():
            lease.release()


# Reuse the established temporary conversation/config/provider isolation fixture.
from test_web_attachment_bundle_chat import journey  # noqa: E402, F401


def test_live_web_socket_approval_survives_reconnect_and_new_turn(journey, monkeypatch):
    """Exercise real authenticated socket events and worker threads without a provider."""
    import flask_socketio
    import orchestrator_v2
    import test_web_attachment_bundle_chat as helpers
    from jarvis_bundle_chat_test.services import tool_discovery

    monkeypatch.setenv('WEBUI_PASSWORD', 'disposable-test-password')
    monkeypatch.setenv('WEBUI_SECRET', 'disposable-test-secret')
    monkeypatch.setattr(webui_auth, '_log_auth_event', lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, 'jarvis_bundle_chat_test.app',
                        SimpleNamespace(get_startup_mode=lambda: 'cloud'))
    monkeypatch.setattr(tool_discovery, 'get_tool_service',
                        lambda mode: SimpleNamespace(get_tool_count=lambda: 0))
    monkeypatch.setattr(helpers.chat, 'emit', flask_socketio.emit)

    fake_orchestrator = orchestrator_v2.Orchestrator
    monkeypatch.setattr(fake_orchestrator, 'set_tool_approval_callback',
                        lambda self, callback: setattr(self, 'approval_callback', callback), raising=False)
    executed = []

    def process(self, _prompt, **_kwargs):
        decision = self.approval_callback('api_call',
            {'url': 'https://example.test/ping', 'method': 'GET'},
            {'network': True, 'auto_approve': False}, 0)
        if decision == 'approved':
            executed.append('api_call')
            return {'ok': True, 'speech': 'The approved call completed.',
                    'data': {'api_call': {'status': 'ok'}}, 'tools_used': ['api_call']}
        return {'ok': True, 'speech': 'You declined api_call. No calls completed.',
                'data': {}, 'tools_used': [], 'cancelled': True,
                'approval_outcome': {'tool': 'api_call', 'decision': decision}}

    monkeypatch.setattr(fake_orchestrator, 'process', process)
    app = Flask(__name__)
    socket = socket_auth.AuthenticatedSocketIO(app, async_mode='threading')
    handler = helpers.chat.ChatHandler(socket)
    monkeypatch.setattr(handler, '_get_completion_guard_config', lambda mode: {'enabled': False})
    monkeypatch.setattr(handler, '_compute_effective_evidence', lambda *args: None)
    monkeypatch.setattr(handler, '_is_user_reaction_eligible', lambda *args, **kwargs: False)
    monkeypatch.setattr(handler, '_hydrate_uploaded_image_payload', lambda payload, **kwargs: None)
    first = socket.test_client(app, auth={'token': webui_auth.create_token()})
    second = None

    def receive_until(client, event_name, message_id=None):
        seen = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            seen.extend(client.get_received())
            for item in seen:
                if (item['name'] == event_name and
                        (message_id is None or item['args'][0].get('message_id') == message_id)):
                    return item['args'][0], seen
            time.sleep(0.01)
        pytest.fail(f'{event_name} did not arrive; received {[item["name"] for item in seen]}')

    try:
        first.emit('chat:send', {'message': 'Call a harmless endpoint', 'mode': 'cloud'})
        pending, first_events = receive_until(first, 'tool:approval_required')
        conversation_id = pending['conversation_id']
        assert any(item['name'] == 'conversation:created' for item in first_events)
        assert not executed
        first.disconnect()

        second = socket.test_client(app, auth={'token': webui_auth.create_token()})
        second.emit('tool:approval_decide', {
            'approval_id': pending['approval_id'], 'conversation_id': conversation_id,
            'message_id': pending['message_id'], 'approved': True,
        })
        rejected, _ = receive_until(second, 'tool:approval_rejected')
        assert rejected['approval_id'] == pending['approval_id']
        assert not executed
        second.emit('conversation:load', {'conversation_id': conversation_id, 'reconnect_only': True})
        restored, _ = receive_until(second, 'conversation:loaded')
        assert restored['conversation']['run']['approval']['approval_id'] == pending['approval_id']
        second.emit('tool:approval_decide', {
            'approval_id': pending['approval_id'], 'conversation_id': conversation_id,
            'message_id': pending['message_id'], 'approved': False,
        })
        denied, denied_events = receive_until(second, 'chat:response', pending['message_id'])
        assert denied['cancelled'] is True
        assert denied['run_status'] == 'completed'
        assert any(item['name'] == 'chat:run' and item['args'][0].get('status') == 'completed'
                   for item in denied_events)
        assert denied['approval_outcome']['decision'] == 'denied'
        assert not executed

        second.emit('chat:send', {'message': 'Try the call again', 'mode': 'cloud',
                                  'conversation_id': conversation_id})
        retry, _ = receive_until(second, 'tool:approval_required')
        assert retry['approval_id'] != pending['approval_id']
        second.emit('tool:approval_decide', {
            'approval_id': retry['approval_id'], 'conversation_id': conversation_id,
            'message_id': retry['message_id'], 'approved': True,
        })
        completed, _ = receive_until(second, 'chat:response', retry['message_id'])
        assert completed['cancelled'] is False
        assert completed['tools_used'] == ['api_call']
        assert executed == ['api_call']

        second.emit('chat:send', {'message': 'Stop at the approval', 'mode': 'cloud',
                                  'conversation_id': conversation_id})
        stopped_call, _ = receive_until(second, 'tool:approval_required')
        second.emit('chat:cancel', {'conversation_id': conversation_id,
                                    'message_id': stopped_call['message_id']})
        stopped, _ = receive_until(second, 'chat:response', stopped_call['message_id'])
        assert stopped['cancelled'] is True
        assert stopped['run_status'] == 'cancelled'
        assert stopped['approval_outcome']['decision'] == 'cancelled'
        assert executed == ['api_call']
    finally:
        for client in (first, second):
            if client and client.is_connected():
                client.disconnect()
        for lease in handler.runs.leases.values():
            lease.release()


def test_existing_browser_refreshes_auth_and_preserves_recovery_on_login():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let token = 'first-token', options;
const handlers = {};
const values = new Map([
  ['jarvis.activeConversation', 'conversation'], ['jarvis.pendingRequest', 'request']
]);
const storage = {getItem: key => values.get(key), setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k)};
let disconnected = false;
const sandbox = {
  console: {log() {}, error() {}},
  Utils: {storage: {get: (key,fallback) => fallback}, auth: {getToken: () => token, clearToken: () => {token = null;}}},
  window: {sessionStorage: storage, location: {protocol:'http:', host:'localhost', pathname:'/'}},
  io: config => {options = config; return {on: (name, fn) => {handlers[name] = fn;}, disconnect: () => {disconnected = true;}}}
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SOURCE, 'utf8'), sandbox);
const socket = sandbox.window.jarvisSocket;
socket.connect();
let auth;
options.auth(value => {auth = value;});
assert.equal(auth.token, 'first-token');
token = 'renewed-token';
options.auth(value => {auth = value;});
assert.equal(auth.token, 'renewed-token');
handlers['connect_error']({message:'Authentication required', data:{code:'authentication_required'}});
assert.equal(disconnected, true);
assert.equal(sandbox.window.location.href, '/login?redirect=%2F');
assert.equal(values.get('jarvis.activeConversation'), 'conversation');
assert.equal(values.get('jarvis.pendingRequest'), 'request');
token = null;
options.auth(value => {auth = value;});
assert.equal(Object.keys(auth).length, 0);
"""
    subprocess.run(['node', '-e', f'const SOURCE = {json.dumps(str(ROOT / "jarvis-web/client/js/socket.js"))};\n' + script],
                   check=True, cwd=ROOT, timeout=15)
