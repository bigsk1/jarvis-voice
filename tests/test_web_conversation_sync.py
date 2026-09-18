"""Push sidebar invalidation across clients, without joining another chat."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import flask_socketio
from flask import Flask
import pytest

from test_web_attachment_bundle_chat import journey  # noqa: F401
from test_web_socket_auth import socket_auth, webui_auth
from jarvis_bundle_chat_test.services import conversation_store, tool_discovery
from jarvis_bundle_chat_test.sockets import chat
from jarvis_bundle_chat_test.routes import api


@pytest.fixture
def clients(journey, monkeypatch):
    monkeypatch.setenv('WEBUI_PASSWORD', 'disposable-test-password')
    monkeypatch.setenv('WEBUI_SECRET', 'disposable-test-secret')
    monkeypatch.setattr(webui_auth, '_log_auth_event', lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, 'jarvis_bundle_chat_test.app',
                        SimpleNamespace(get_startup_mode=lambda: 'cloud'))
    monkeypatch.setattr(tool_discovery, 'get_tool_service',
                        lambda mode: SimpleNamespace(get_tool_count=lambda: 0))
    monkeypatch.setattr(chat, 'emit', flask_socketio.emit)
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    socket = socket_auth.AuthenticatedSocketIO(app, async_mode='threading')
    handler = chat.ChatHandler(socket)
    work = []
    monkeypatch.setattr(handler, '_start_blocking_task', lambda *a, **k: work.append(a))
    opened = []

    def connect(origin='http://localhost', *, cookie=False):
        http = app.test_client()
        token = webui_auth.create_token()
        if cookie:
            http.set_cookie('jarvis_auth', token)
        client = socket.test_client(app, headers={'Origin': origin}, flask_test_client=http,
                                    auth=None if cookie else {'token': token})
        opened.append(client)
        client.get_received()
        return client

    yield SimpleNamespace(connect=connect, http=app.test_client(), store=journey.store,
                          handler=handler, work=work)
    for client in opened:
        if client.is_connected():
            client.disconnect()
    for lease in handler.runs.leases.values():
        lease.release()


def subscribe(client):
    client.emit('conversations:subscribe', {})
    assert [event['name'] for event in client.get_received()] == ['conversations:changed']


@pytest.mark.parametrize('origin', ['moz-extension://companion', 'http://localhost'])
def test_new_chat_elsewhere_invalidates_only_the_sidebar(clients, origin):
    desktop = clients.connect(cookie=True)
    companion = clients.connect(origin)
    own = clients.store.create_conversation('Desktop draft context')
    desktop.emit('conversation:load', {'conversation_id': own['id']})
    desktop.get_received()
    subscribe(desktop)
    subscribe(desktop)  # Repeated subscriptions must not multiply listeners.
    companion.emit('chat:send', {'message': 'New conversation from another device', 'mode': 'cloud'})
    source_events = companion.get_received()
    assert not any(e['name'] == 'conversations:changed' for e in source_events)
    created = next(e['args'][0]['conversation_id'] for e in source_events
                   if e['name'] == 'conversation:created')
    updates = desktop.get_received()
    assert updates and all(e['name'] == 'conversations:changed' and e['args'] == [{}] for e in updates)
    assert len(clients.store._index_listeners) == 1
    assert len(clients.work) == 1  # Captured; never starts a provider.
    assert any(s['conversation_id'] == own['id'] for s in clients.handler.sessions.values())
    assert not clients.handler.pending_cancellations
    listed = clients.http.get('/api/conversations?include_archived=true').get_json()['conversations']
    assert created in {c['id'] for c in listed}


def test_rest_changes_and_reconnect_catchup(clients):
    desktop = clients.connect()
    mobile = clients.connect()
    subscribe(desktop)
    subscribe(mobile)
    created = clients.http.post('/api/conversations', json={'title': 'Original'}).get_json()
    cid = created['conversation']['id']
    clients.store.add_message(cid, 'user', 'Original')
    desktop.get_received()
    mobile.get_received()
    response = clients.http.put(f'/api/conversations/{cid}/title', json={'title': 'Renamed on mobile'})
    assert response.status_code == 200
    for client in (desktop, mobile):
        assert [e['name'] for e in client.get_received()] == ['conversations:changed']
    desktop.disconnect()
    assert clients.http.patch(f'/api/conversations/{cid}/state', json={'pinned': True}).status_code == 200
    desktop = clients.connect()
    subscribe(desktop)
    listed = clients.http.get('/api/conversations').get_json()['conversations']
    assert listed[0]['title'] == 'Renamed on mobile' and listed[0]['pinned']
    assert clients.http.delete(f'/api/conversations/{cid}').status_code == 200
    assert [e['name'] for e in desktop.get_received()] == ['conversations:changed']
    assert not clients.http.get('/api/conversations').get_json()['conversations']


def test_revoked_subscriber_receives_no_invalidation(clients, monkeypatch):
    desktop = clients.connect()
    subscribe(desktop)
    monkeypatch.setattr(socket_auth, 'verify_token', lambda token: None)
    clients.store.create_conversation('Private')
    assert not desktop.is_connected()


def test_auth_disabled_installation_still_syncs(clients, monkeypatch):
    monkeypatch.delenv('WEBUI_PASSWORD')
    desktop = clients.connect()
    subscribe(desktop)
    clients.store.create_conversation('Local installation')
    assert [e['name'] for e in desktop.get_received()] == ['conversations:changed']


def test_nested_writes_notify_once_after_commit_and_outside_locks(journey):
    store = journey.store
    notifications = []

    def changed():
        assert not store._file_lock.is_locked
        assert not store._lock._is_owned()
        notifications.append(json.loads(store._index_file.read_text()))

    store.add_index_listener(changed)

    @conversation_store._transaction
    def batch(store):
        conv = store.create_conversation('Nested')
        store.add_message(conv['id'], 'user', 'Saved title')
        assert not notifications

    batch(store)
    assert len(notifications) == 1
    assert notifications[0]['conversations'][0]['title'] == 'Saved title'


def test_failed_index_write_does_not_announce_and_listener_failure_cannot_fail_save(journey, monkeypatch):
    store = journey.store
    notifications = []
    store.add_index_listener(lambda: notifications.append(True))
    write = store._write_json

    def fail_index(path, data):
        if path == store._index_file:
            raise OSError('Simulated disk full')
        write(path, data)

    monkeypatch.setattr(store, '_write_json', fail_index)
    with pytest.raises(OSError):
        store.create_conversation('Not committed to the index')
    assert not notifications
    monkeypatch.setattr(store, '_write_json', write)

    def broken_delivery():
        raise RuntimeError('Simulated disconnected transport')

    store.add_index_listener(broken_delivery)
    saved = store.create_conversation('Committed')
    assert store.get_conversation(saved['id'])['title'] == 'Committed'
    assert notifications == [True]


def test_progress_and_unchanged_list_reads_do_not_flood_subscribers(journey):
    journey.send(message='Keep working')
    store = journey.store
    cid = journey.handler.sessions['client']['conversation_id']
    run = store.get_conversation(cid)['run']
    notifications = []
    store.add_index_listener(lambda: notifications.append(True))
    for i in range(5):
        store.update_run(cid, run['message_id'], progress=f'Working {i}')
        store.list_conversations()
    assert not notifications


def test_concurrent_first_access_shares_the_listening_store(monkeypatch):
    instances = []
    started, release = threading.Event(), threading.Event()
    start_together = threading.Barrier(2)

    def factory():
        instance = object()
        instances.append(instance)
        started.set()
        assert release.wait(2)
        return instance

    monkeypatch.setattr(conversation_store, '_store', None)
    monkeypatch.setattr(conversation_store, 'ConversationStore', factory)

    def get():
        start_together.wait(timeout=2)
        return conversation_store.get_conversation_store()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(get) for _ in range(2)]
        try:
            assert started.wait(2)
        finally:
            release.set()
        results = [future.result(timeout=2) for future in futures]
    assert len(instances) == 1
    assert results[0] is results[1]
