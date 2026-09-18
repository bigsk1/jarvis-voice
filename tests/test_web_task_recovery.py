"""Web task ownership journeys: real disposable storage, no provider or service I/O."""
from __future__ import annotations

import selectors
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import test_web_attachment_bundle_chat as journey_helpers
from flask import Flask, request

chat = journey_helpers.chat
conversation_store = journey_helpers.conversation_store
journey = journey_helpers.journey
ChatRuns = chat.ChatRuns
ConversationBusyError = chat.ConversationBusyError


def call(journey, event, data=None, sid='client'):
    with Flask(__name__).test_request_context('/'):
        request.sid = sid
        journey.socket.handlers[event](data or {})


def current(journey):
    cid = journey.handler.sessions['client']['conversation_id']
    return cid, journey.handler.runs.snapshot(cid)['run']


def abandon(journey, cid):
    """Simulate losing an execution lease without running the captured worker."""
    journey.handler.runs.leases.pop(cid).release()
    journey.handler.runs.active.pop(cid)


def test_reconnect_restores_running_task_and_stop_with_progress_disabled(journey, monkeypatch):
    journey.send()
    cid, run = current(journey)
    assert run['status'] == 'running'
    assert len(journey.store.get_conversation(cid)['messages']) == 1
    monkeypatch.setattr(chat, 'leave_room', lambda *args: None)
    with Flask(__name__).test_request_context('/'):
        request.sid = 'client'
        journey.socket.handlers['disconnect']()
    journey.handler.sessions['new-socket'] = {'mode': 'local'}
    call(journey, 'conversation:load', {'conversation_id': cid, 'reconnect_only': True}, sid='new-socket')
    event, payload, _ = journey.socket.events[-1]
    assert event == 'conversation:loaded'
    assert payload['conversation']['run']['message_id'] == run['message_id']
    assert payload['conversation']['run']['mode'] == 'cloud'
    call(journey, 'chat:cancel', {'conversation_id': cid, 'message_id': run['message_id']}, sid='new-socket')
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'stopping'
    journey.process()
    assert not journey.routes  # Stopped before attachment/model preparation.
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'cancelled'
    assert journey.store.get_conversation(cid)['messages'][-1]['data']['_run_status'] == 'cancelled'
    assert not journey.handler.pending_cancellations


def test_missed_completion_is_restored_without_reexecuting(journey):
    journey.send()
    cid, run = current(journey)
    journey.process()
    journey.socket.events.clear()  # Browser missed every terminal event.
    call(journey, 'conversation:load', {'conversation_id': cid, 'reconnect_only': True})
    restored = journey.socket.events[-1][1]['conversation']
    assert restored['run']['status'] == 'completed'
    assert restored['messages'][-1]['data']['_web_message_id'] == run['message_id']
    assert len(journey.routes) == 1
    assert not journey.pending


def test_admission_rejects_overlapping_turn_but_other_conversation_runs(journey):
    journey.send()
    cid, run = current(journey)
    journey.send(message='Second request', conversation_id=cid)
    assert journey.socket.events[-1][0] == 'chat:rejected'
    assert len(journey.pending) == 1
    assert len(journey.store.get_conversation(cid)['messages']) == 1
    journey.send(message='Independent task')
    assert len(journey.pending) == 2
    assert len(journey.handler.runs.active) == 2
    journey.process()
    journey.process()
    assert not journey.handler.runs.active


def test_same_request_id_never_adds_or_executes_a_second_turn(journey):
    request_id = str(uuid.uuid4())
    journey.send(request_id=request_id)
    cid, _ = current(journey)
    journey.send(conversation_id=cid, request_id=request_id)
    assert len(journey.pending) == 1
    journey.process()
    journey.send(conversation_id=cid, request_id=request_id)
    assert len(journey.routes) == 1
    assert not journey.pending
    assert len(journey.store.get_conversation(cid)['messages']) == 2


def test_first_send_can_be_recovered_and_deduplicated_without_conversation_id(journey):
    request_id = str(uuid.uuid4())
    journey.send(request_id=request_id)
    cid, run = current(journey)
    journey.send(request_id=request_id)  # conversation:created was lost
    assert len(journey.pending) == 1
    assert len(journey.store.list_conversations()) == 1
    call(journey, 'chat:resume', {'request_id': request_id}, sid='new-browser')
    restored = journey.socket.events[-1][1]['conversation']
    assert restored['id'] == cid
    assert restored['run']['message_id'] == run['message_id']
    journey.process()
    call(journey, 'chat:resume', {'request_id': request_id}, sid='another-browser')
    assert journey.socket.events[-1][1]['conversation']['run']['status'] == 'completed'
    assert len(journey.routes) == 1


def test_unknown_resume_does_not_start_work(journey):
    call(journey, 'chat:resume', {'request_id': str(uuid.uuid4())})
    assert journey.socket.events[-1][0] == 'chat:resume_missing'
    assert not journey.pending
    assert not journey.store.list_conversations()


def test_resume_storage_failure_is_visible_without_starting_work(journey, monkeypatch):
    def unavailable(request_id):
        raise OSError('storage unavailable')
    monkeypatch.setattr(journey.store, 'find_request_conversation', unavailable)
    call(journey, 'chat:resume', {'request_id': str(uuid.uuid4())})
    assert journey.socket.events[-1][0] == 'chat:resume_missing'
    assert 'storage unavailable' in journey.socket.events[-1][1]['error']
    assert not journey.pending


def test_new_conversation_storage_failure_rejects_without_starting_work(journey, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('storage unavailable')
    monkeypatch.setattr(journey.store, 'create_conversation', unavailable)
    journey.send()
    assert journey.socket.events[-1][0] == 'chat:rejected'
    assert 'storage unavailable' in journey.socket.events[-1][1]['error']
    assert not journey.pending


def test_manual_review_context_survives_socket_loss_and_is_returned_on_load(journey):
    journey.send()
    cid, run = current(journey)
    journey.process()
    del journey.handler.sessions['client']
    record = {'conversation_id': cid, 'message_id': run['message_id'],
              'completion_guard_prompt': True, 'timestamp': time.time(),
              'completion_guard': {'mode': 'manual', 'manual_prompt_ttl_seconds': 600},
              'conversation_context': [{'private': 'heavy context stays on the server'}]}
    journey.handler._remember_completion_guard_record('client', run['message_id'], record)
    assert 'client' not in journey.handler.sessions
    assert journey.handler._get_completion_guard_record('new', run['message_id']) is record
    call(journey, 'conversation:load', {'conversation_id': cid}, sid='new')
    guard = journey.socket.events[-1][1]['conversation']['completion_guards'][run['message_id']]
    assert guard['prompt_user'] is True
    assert 0 < guard['expires_in_ms'] <= 600000
    assert 'conversation_context' not in guard
    record['expires_at'] = time.time() - 1
    call(journey, 'conversation:load', {'conversation_id': cid}, sid='new')
    assert 'completion_guards' not in journey.socket.events[-1][1]['conversation']


def test_repair_admission_storage_failure_cannot_execute_or_stay_repairing(journey, monkeypatch):
    cid = journey.store.create_conversation()['id']
    record = {'conversation_id': cid, 'message_id': 'parent', 'mode': 'cloud', 'status': 'repairing'}
    def unavailable(*args, **kwargs):
        raise OSError('storage unavailable')
    monkeypatch.setattr(journey.store, 'claim_run', unavailable)
    journey.handler._run_completion_guard_repair('client', record)
    assert record['status'] == 'error'
    assert journey.socket.events[-1][0] == 'completion_guard:error'
    assert not journey.routes
    assert not journey.handler.runs.active


def test_interrupted_repair_is_recorded_beside_its_parent_answer(journey):
    journey.send()
    cid, parent = current(journey)
    journey.process()
    journey.handler.runs.claim(cid, str(uuid.uuid4()), 'cloud', kind='repair',
                               parent_message_id=parent['message_id'])
    abandon(journey, cid)
    restored = ChatRuns(lambda: journey.store, journey.socket.emit).snapshot(cid)
    data = restored['messages'][-1]['data']
    assert restored['run']['status'] == 'interrupted'
    assert data['_repair_run']['status'] == 'interrupted'
    assert data['_completion_guard']['status'] == 'interrupted'


def test_cross_mode_execution_is_rejected_before_creating_an_empty_chat(journey):
    journey.send(mode='cloud')
    journey.send(message='Local work', mode='local')
    assert len(journey.pending) == 1
    assert len(journey.store.list_conversations()) == 1
    assert journey.socket.events[-1][0] == 'chat:rejected'
    assert 'other mode' in journey.socket.events[-1][1]['error']
    journey.process()
    journey.send(message='Local work', mode='local')
    journey.process()
    assert len(journey.routes) == 2


def test_mode_selector_does_not_close_tools_used_by_an_active_task(journey, monkeypatch):
    import tool_schema
    from jarvis_bundle_chat_test import config
    from jarvis_bundle_chat_test.services import settings_manager, tool_discovery

    resets, settings_changes = [], []
    monkeypatch.setattr(tool_schema, 'reset_tool_registry', lambda: resets.append(True))
    monkeypatch.setattr(settings_manager, 'get_settings_manager',
                        lambda: SimpleNamespace(set_mode=lambda mode: settings_changes.append(mode)))
    monkeypatch.setattr(config, 'reload_web_config', lambda: None)
    monkeypatch.setattr(tool_discovery, 'get_tool_service',
                        lambda mode: SimpleNamespace(refresh=lambda: None))
    journey.send()
    call(journey, 'mode:set', {'mode': 'local'})
    assert not resets
    assert not settings_changes
    assert journey.handler.sessions['client']['mode'] == 'cloud'
    assert journey.socket.events[-1][0] == 'mode:rejected'
    journey.process()
    call(journey, 'mode:set', {'mode': 'local'})
    assert resets == [True]
    assert settings_changes == ['local']


@pytest.mark.parametrize('endpoint, method', [('/api/mode', 'PUT'), ('/api/settings/web', 'PUT'),
                                             ('/api/settings/reset', 'POST')])
def test_http_mode_changes_cannot_bypass_active_work(monkeypatch, tmp_path, endpoint, method):
    from test_web_conversation_workflow_roundtrip import _make_client, api

    client, store = _make_client(tmp_path / 'http', monkeypatch)
    from jarvis_web_workflow_roundtrip_test_server.services.chat_runs import ChatRuns as ApiRuns

    runs = ApiRuns(lambda: store, lambda *args, **kwargs: None)
    client.application.extensions['jarvis_chat_runs'] = runs
    mutations = []
    monkeypatch.setattr(api, 'get_settings_manager', lambda: mutations.append('settings'))
    cid = store.create_conversation()['id']
    runs.claim(cid, 'run', 'cloud', message='Work')
    try:
        response = client.open(endpoint, method=method, json={'mode': 'local'})
        assert response.status_code == 409
        assert 'other mode' in response.json['error']
        assert not mutations
    finally:
        runs.finish(cid, 'run', 'completed')


def test_repair_cannot_overlap_chat_and_its_stop_survives_socket_change(journey, monkeypatch):
    journey.send()
    cid, run = current(journey)
    record = {'conversation_id': cid, 'message_id': run['message_id'], 'mode': 'local'}
    called = []

    def repair(session_id, record, note, message_id):
        current_run = journey.handler.runs.snapshot(cid)['run']
        assert current_run['kind'] == 'repair'
        assert current_run['mode'] == 'local'
        assert current_run['message_id'] == message_id
        called.append(message_id)
        call(journey, 'chat:cancel', {'conversation_id': cid, 'message_id': message_id}, sid='new-client')
        assert journey.handler.pending_cancellations[message_id]
        record['status'] = 'cancelled'

    monkeypatch.setattr(journey.handler, '_process_completion_guard_repair', repair)
    journey.handler._run_completion_guard_repair('client', record)
    assert not called
    assert record['status'] == 'superseded'
    assert current(journey)[1]['message_id'] == run['message_id']
    journey.process()
    journey.handler._run_completion_guard_repair('client', record)
    assert len(called) == 1
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'cancelled'
    assert not journey.handler.pending_cancellations


def test_cancel_is_scoped_and_stopping_does_not_release_admission(journey):
    journey.send()
    cid, run = current(journey)
    call(journey, 'cancel', {'conversation_id': cid, 'message_id': 'wrong'})
    call(journey, 'cancel', {'conversation_id': 'wrong', 'message_id': run['message_id']})
    assert not journey.handler.pending_cancellations
    call(journey, 'cancel', {'conversation_id': cid, 'message_id': run['message_id']})
    journey.send(conversation_id=cid)
    assert journey.socket.events[-1][0] == 'chat:rejected'
    journey.process()
    journey.send(conversation_id=cid)
    _, next_run = current(journey)
    call(journey, 'cancel', {'conversation_id': cid, 'message_id': run['message_id']})
    assert next_run['message_id'] not in journey.handler.pending_cancellations
    journey.process()


def test_restart_reports_interruption_and_never_replays(journey):
    journey.send()
    cid, old = current(journey)
    abandon(journey, cid)
    restarted = ChatRuns(lambda: journey.store, journey.socket.emit)
    snapshot = restarted.snapshot(cid)
    assert snapshot['run']['status'] == 'interrupted'
    assert 'not retried' in snapshot['run']['error']
    assert snapshot['messages'][0]['data']['_run']['status'] == 'interrupted'
    assert not journey.routes
    assert not restarted.active
    # The only start remains the original captured worker, never replayed.
    assert len(journey.pending) == 1


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
def test_restart_after_answer_saved_recovers_its_actual_outcome(journey, status):
    journey.send()
    cid, old = current(journey)
    journey.store.add_message(cid, 'assistant', 'Already saved', data={
        '_web_message_id': old['message_id'], '_run_status': status,
    })
    abandon(journey, cid)
    restarted = ChatRuns(lambda: journey.store, journey.socket.emit)
    assert restarted.snapshot(cid)['run']['status'] == status
    assert not journey.routes


def test_worker_launch_and_provider_failures_remain_visible_after_load(journey, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('mock worker launch failure')
    monkeypatch.setattr(journey.handler, '_start_blocking_task', fail)
    journey.send()
    cid, run = current(journey)
    assert run['status'] == 'failed'
    assert 'worker launch failure' in run['error']
    assert not journey.handler.runs.active
    assert journey.store.get_conversation(cid)['messages'][0]['data']['_run']['status'] == 'failed'


def test_active_conversation_cannot_be_deleted_or_cleared(journey):
    journey.send()
    cid, _ = current(journey)
    with pytest.raises(ConversationBusyError):
        journey.store.delete_conversation(cid)
    with pytest.raises(ConversationBusyError):
        journey.store.clear_conversation(cid)
    journey.process()
    assert journey.store.clear_conversation(cid)
    assert journey.store.get_conversation(cid)['messages'] == []
    assert 'run' not in journey.store.get_conversation(cid)
    journey.store.delete_conversation(cid)
    with pytest.raises(ValueError, match='not found'):
        journey.store.add_message(cid, 'assistant', 'Late result')
    assert not journey.store.list_conversations()


@pytest.mark.parametrize('endpoint, method', [('', 'DELETE'), ('/clear', 'POST')])
def test_http_active_conversation_protection_is_explicit(tmp_path, monkeypatch, endpoint, method):
    from test_web_conversation_workflow_roundtrip import _make_client

    client, store = _make_client(tmp_path, monkeypatch)
    cid = store.create_conversation()['id']
    with store.run_lease(cid):
        store.claim_run(cid, {'message_id': 'run', 'status': 'running'}, message='Work')
        response = client.open(f'/api/conversations/{cid}{endpoint}', method=method)
        assert response.status_code == 409
        assert 'running task' in response.json['error']
        assert len(store.get_conversation(cid)['messages']) == 1
        store.update_run(cid, 'run', status='completed')
    assert client.open(f'/api/conversations/{cid}{endpoint}', method=method).json['ok']


def test_late_events_keep_conversation_identity_and_cannot_finish_new_run(journey):
    journey.send()
    cid, old = current(journey)
    journey.process()
    journey.send(conversation_id=cid)
    _, new = current(journey)
    journey.handler._emit_run_event('tool:progress', {
        'message_id': old['message_id'], 'status': 'Old status',
    }, room=f'conversation:{cid}')
    assert journey.socket.events[-1][1]['conversation_id'] == cid
    journey.handler._emit_run_event('chat:response', {
        'message_id': old['message_id'], 'text': 'Old response',
    }, room=f'conversation:{cid}')
    assert current(journey)[1]['message_id'] == new['message_id']
    assert current(journey)[1]['status'] == 'running'
    journey.process()


def test_concurrent_store_instances_keep_every_message_and_metadata(tmp_path):
    from lib.background_tasks import TaskStore
    tasks = TaskStore(tmp_path / 'tasks.db')
    stores = [conversation_store.ConversationStore(tmp_path / 'chats', background_tasks=tasks) for _ in range(2)]
    cid = stores[0].create_conversation()['id']
    barrier = threading.Barrier(2, timeout=5)

    def write(index):
        barrier.wait()
        for number in range(15):
            stores[index].add_message(cid, 'user', f'{index}:{number}')
            stores[index].update_llm_metadata(cid, provider='test', model='fake')

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, index) for index in range(2)]
        for future in futures:
            future.result(timeout=10)
    restored = conversation_store.ConversationStore(tmp_path / 'chats', background_tasks=tasks)
    messages = restored.get_conversation(cid)['messages']
    assert len(messages) == 30
    assert len({item['content'] for item in messages}) == 30
    assert restored.list_conversations()[0]['message_count'] == 30


def test_failed_atomic_replace_leaves_previous_document_readable(journey, monkeypatch):
    cid = journey.store.create_conversation()['id']
    before = journey.store.get_conversation(cid)
    def fail(*args): raise OSError('simulated full disk')
    monkeypatch.setattr(conversation_store.os, 'replace', fail)
    with pytest.raises(OSError, match='full disk'):
        journey.store.add_message(cid, 'user', 'Cannot save')
    assert journey.store.get_conversation(cid) == before
    assert not list(journey.store.conversations_dir.glob('*.tmp'))


def test_storage_outage_is_visible_and_recovery_does_not_leave_a_busy_lock(journey, monkeypatch):
    journey.send()
    cid, run = current(journey)
    update = journey.store.update_run
    def fail(*args, **kwargs): raise OSError('simulated full disk')
    monkeypatch.setattr(journey.store, 'update_run', fail)
    journey.process()
    snapshot = journey.handler.runs.snapshot(cid)
    assert snapshot['run']['persistence_error']
    assert not journey.handler.runs.active
    monkeypatch.setattr(journey.store, 'update_run', update)
    snapshot = journey.handler.runs.snapshot(cid)
    assert snapshot['run']['status'] == 'completed'
    assert 'persistence_error' not in snapshot['run']
    assert not journey.handler.runs.unsaved
    journey.send(conversation_id=cid)
    assert len(journey.pending) == 1
    journey.process()


def test_failed_admission_after_user_write_is_recoverable_without_execution(journey, monkeypatch):
    cid = journey.store.create_conversation()['id']
    save = journey.store._save_index
    def fail(): raise OSError('simulated index write failure')
    monkeypatch.setattr(journey.store, '_save_index', fail)
    journey.send(conversation_id=cid)
    assert not journey.pending
    assert journey.socket.events[-1][0] == 'chat:rejected'
    monkeypatch.setattr(journey.store, '_save_index', save)
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'failed'
    assert 'worker could not be started' in journey.handler.runs.snapshot(cid)['run']['error']
    summary = journey.store.list_conversations()[0]
    assert summary['message_count'] == 1
    assert summary['title'] == journey.store.get_conversation(cid)['title']
    assert journey.store.find_request_conversation(summary['last_request_id']) == cid
    journey.send(conversation_id=cid)
    journey.process()
    assert len(journey.routes) == 1


def test_corrupt_index_is_not_silently_replaced(journey):
    cid = journey.store.create_conversation()['id']
    journey.store._index_file.write_text('{broken')
    with pytest.raises(ValueError, match='not been overwritten'):
        journey.store.add_message(cid, 'user', 'Do not erase other history')
    assert journey.store._index_file.read_text() == '{broken'


def test_first_send_retry_recovers_a_document_after_index_write_failure(journey, monkeypatch):
    save = journey.store._save_index
    writes = 0
    def fail_after_creation():
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError('index unavailable after conversation creation')
        save()
    monkeypatch.setattr(journey.store, '_save_index', fail_after_creation)
    request_id = str(uuid.uuid4())
    journey.send(request_id=request_id)
    assert not journey.pending
    cid = next(data['conversation_id'] for event, data, _ in journey.socket.events if event == 'conversation:created')
    monkeypatch.setattr(journey.store, '_save_index', save)
    # No conversation ID or reliable index receipt reached this browser.
    journey.send(request_id=request_id)
    assert len(journey.store.list_conversations()) == 1
    assert journey.store.find_request_conversation(request_id) == cid
    assert journey.socket.events[-1][0] == 'conversation:loaded'
    assert journey.socket.events[-1][1]['conversation']['run']['status'] == 'failed'
    assert not journey.pending
    assert not journey.routes


def test_listing_reconciles_abandoned_runs_without_opening_them(journey):
    journey.send()
    cid, run = current(journey)
    other_store = conversation_store.ConversationStore(journey.store.conversations_dir)
    assert other_store.list_conversations()[0]['run_status'] == 'running'
    abandon(journey, cid)
    assert other_store.list_conversations()[0]['run_status'] == 'interrupted'
    assert not journey.routes


@pytest.mark.parametrize('orphan', [False, True])
def test_listing_recovers_admission_missing_from_index(journey, monkeypatch, orphan):
    cid = journey.store.create_conversation()['id']
    if orphan:
        journey.store._index_file.write_text('{"conversations": []}')
    with monkeypatch.context() as patch:
        patch.setattr(journey.store, '_save_index', lambda: (_ for _ in ()).throw(OSError('index unavailable')))
        with pytest.raises(OSError):
            journey.store.claim_run(cid, {'message_id': 'lost', 'status': 'running'}, message='Crash window')
    summaries = journey.store.list_conversations()
    assert len(summaries) == 1
    assert summaries[0]['id'] == cid
    assert summaries[0]['run_status'] == 'interrupted'
    assert summaries[0]['message_count'] == 1


def test_new_send_never_parses_archive_and_resume_skips_unreadable_files(journey, monkeypatch):
    directory = journey.store.conversations_dir
    (directory / 'bad name.json').write_text('{}')
    (directory / 'corrupt.json').write_text('{broken')
    legacy = journey.store.create_conversation()['id']
    receipt = str(uuid.uuid4())
    journey.store.add_message(legacy, 'user', 'Older accepted request', data={'_request_id': receipt})
    read = journey.store._read_conversation
    reads = []
    def tracked(cid):
        reads.append(cid)
        return read(cid)
    monkeypatch.setattr(journey.store, '_read_conversation', tracked)
    journey.send()
    cid, _ = current(journey)
    assert set(reads) == {cid}
    assert len(journey.pending) == 1
    assert journey.store.find_request_conversation(receipt) == legacy
    assert journey.store.find_request_conversation(str(uuid.uuid4())) is None
    assert len(journey.store.list_conversations()) == 2
    journey.process()


@pytest.mark.parametrize('marker, expected', [(None, 'interrupted'), ('running', 'interrupted'),
                                            ('completed', 'completed'), ('failed', 'failed'),
                                            ('cancelled', 'cancelled')])
def test_crash_requires_explicit_terminal_assistant_outcome(journey, marker, expected):
    journey.send()
    cid, run = current(journey)
    data = {'_web_message_id': run['message_id']}
    if marker:
        data['_run_status'] = marker
    journey.store.add_message(cid, 'assistant', 'Saved answer', data=data)
    abandon(journey, cid)
    restored = journey.store.get_conversation(cid)['run']
    assert restored['status'] == expected
    if expected == 'interrupted':
        assert 'not retried' in restored['error']


def test_unsaved_failure_survives_sidebar_open_and_retention(journey, monkeypatch):
    journey.send()
    cid, run = current(journey)
    update = journey.store.update_run
    monkeypatch.setattr(journey.store, 'update_run', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('full disk')))
    journey.handler.runs.finish(cid, run['message_id'], 'failed', 'Known worker failure')
    other = conversation_store.ConversationStore(journey.store.conversations_dir)
    assert other.list_conversations()[0]['run_status'] == 'running'
    assert other.get_conversation(cid)['run']['status'] == 'running'
    assert other.cleanup_old_unpinned()['preserved_active'] == 1
    snapshot = journey.handler.runs.snapshot(cid)
    assert snapshot['run']['status'] == 'failed'
    assert snapshot['run']['error'] == 'Known worker failure'
    assert cid in journey.handler.runs.leases
    monkeypatch.setattr(journey.store, 'update_run', update)
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'failed'
    assert other.list_conversations()[0]['run_status'] == 'failed'
    assert not journey.handler.runs.unsaved
    assert not journey.handler.runs.leases


def test_unsaved_outcome_is_not_discarded_when_store_returns_a_different_terminal(journey, monkeypatch):
    journey.send()
    cid, run = current(journey)
    update = journey.store.update_run
    monkeypatch.setattr(journey.store, 'update_run', lambda *args, **kwargs: {**run, 'status': 'interrupted'})
    journey.handler.runs.finish(cid, run['message_id'], 'failed', 'Known failure')
    assert journey.handler.runs.snapshot(cid)['run']['status'] == 'failed'
    assert cid in journey.handler.runs.unsaved
    monkeypatch.setattr(journey.store, 'update_run', update)
    assert journey.handler.runs.snapshot(cid)['run']['error'] == 'Known failure'
    assert not journey.handler.runs.unsaved


def test_slow_terminal_storage_does_not_block_other_conversation_events_or_stop_signal(journey, monkeypatch):
    journey.send()
    first, first_run = current(journey)
    journey.send()
    second, second_run = current(journey)
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    write = journey.store._write_conversation
    def slow(conversation):
        if conversation['id'] == first:
            entered.set()
            assert release.wait(3)
        return write(conversation)
    monkeypatch.setattr(journey.store, '_write_conversation', slow)
    class Cancellations(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            stopped.set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        finishing = pool.submit(journey.handler.runs.finish, first, first_run['message_id'], 'completed')
        try:
            assert entered.wait(2)
            progress = pool.submit(journey.handler.runs.event, 'tool:progress', {
                'conversation_id': second, 'message_id': second_run['message_id'], 'status': 'Still working',
            })
            progress.result(timeout=1)
            stopping = pool.submit(journey.handler.runs.cancel, second, second_run['message_id'], Cancellations())
            assert stopped.wait(1), 'Stop signal waited for unrelated disk I/O'
        finally:
            release.set()
        finishing.result(timeout=2)
        stopping.result(timeout=2)
    journey.process()
    journey.process()


def test_mode_reservation_blocks_admission_without_blocking_events(journey, monkeypatch):
    from jarvis_bundle_chat_test import config
    from jarvis_bundle_chat_test.services import settings_manager, tool_discovery

    journey.send()
    cid, run = current(journey)
    entered, release = threading.Event(), threading.Event()
    def slow_reload():
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(settings_manager, 'get_settings_manager', lambda: SimpleNamespace(set_mode=lambda mode: None))
    monkeypatch.setattr(config, 'reload_web_config', slow_reload)
    monkeypatch.setattr(tool_discovery, 'get_tool_service', lambda mode: SimpleNamespace(refresh=lambda: None))
    with ThreadPoolExecutor(max_workers=3) as pool:
        changing = pool.submit(call, journey, 'mode:set', {'mode': 'cloud'})
        try:
            assert entered.wait(2)
            progress = pool.submit(journey.handler.runs.event, 'chat:status', {
                'conversation_id': cid, 'message_id': run['message_id'], 'status': 'Working through settings reload',
            })
            progress.result(timeout=1)
            sending = pool.submit(journey.send, message='During transition')
            sending.result(timeout=1)
            assert journey.socket.events[-1][0] == 'chat:rejected'
            assert 'Settings are changing' in journey.socket.events[-1][1]['error']
            assert len(journey.pending) == 1
        finally:
            release.set()
        changing.result(timeout=2)
    journey.process()


def test_repair_is_admitted_before_launch_and_owned_through_ticketing(journey, monkeypatch):
    journey.send()
    cid, parent = current(journey)
    journey.process()
    record = {'conversation_id': cid, 'message_id': parent['message_id'], 'mode': 'cloud', 'status': 'pending'}
    def ticketing(session_id, record, note, message_id):
        journey.handler._emit_run_event('chat:response', {
            'conversation_id': cid, 'message_id': message_id, 'text': 'Unresolved', 'run_status': 'failed',
        }, room=f'conversation:{cid}')
        assert journey.handler.runs.active[cid]['message_id'] == message_id
        journey.send(conversation_id=cid)
        assert journey.socket.events[-1][0] == 'chat:rejected'
        record['status'] = 'ticket_created'
    monkeypatch.setattr(journey.handler, '_process_completion_guard_repair', ticketing)
    journey.handler._run_completion_guard_repair('client', record, 'Fix this', background=True)
    saved = journey.store.get_conversation(cid)
    assert saved['run']['kind'] == 'repair'
    assert saved['messages'][-1]['data']['_completion_guard']['status'] == 'repairing'
    assert cid in journey.handler.runs.leases
    journey.process()
    assert not journey.handler.runs.active
    assert not journey.handler.runs.leases
    assert journey.store.get_conversation(cid)['run']['status'] == 'failed'


@pytest.mark.parametrize('stage', ['launch', 'announce', 'execution'])
def test_repair_startup_failure_settles_lease_and_guard(journey, monkeypatch, stage):
    journey.send()
    cid, parent = current(journey)
    journey.process()
    record = {'conversation_id': cid, 'message_id': parent['message_id'], 'mode': 'cloud', 'status': 'pending'}
    def fail(*args, **kwargs):
        raise RuntimeError(f'{stage} failed')
    if stage == 'announce':
        emit = journey.handler._emit_run_event
        def announce(event, data, **kwargs):
            if event == 'chat:run' and data['status'] == 'running':
                fail()
            emit(event, data, **kwargs)
        monkeypatch.setattr(journey.handler, '_emit_run_event', announce)
    else:
        monkeypatch.setattr(journey.handler, '_start_blocking_task' if stage == 'launch'
                            else '_process_completion_guard_repair', fail)
    journey.handler._run_completion_guard_repair('client', record, background=True)
    if stage == 'execution':
        journey.process()
    assert record['status'] == 'error'
    saved = journey.store.get_conversation(cid)
    assert saved['run']['status'] == 'failed'
    assert saved['messages'][-1]['data']['_completion_guard']['status'] == 'error'
    assert not journey.handler.runs.active
    assert not journey.handler.runs.leases


def test_imported_active_metadata_becomes_interrupted(journey):
    journey.send()
    cid, _ = current(journey)
    imported = journey.store.get_conversation(cid)
    journey.process()
    journey.store.save_import(imported)
    saved = journey.store.get_conversation(cid)
    assert 'run' not in saved
    assert saved['messages'][0]['data']['_run']['status'] == 'interrupted'


def test_retention_preserves_live_work_and_projects_crashed_work_without_writes(journey):
    journey.send()
    cid, run = current(journey)
    old = (datetime.now() - timedelta(days=100)).isoformat()
    saved = journey.store.get_conversation(cid)
    saved['updated_at'] = old
    journey.store._write_conversation(saved)
    other_store = conversation_store.ConversationStore(journey.store.conversations_dir)
    active = other_store.cleanup_old_unpinned(retention_days=90)
    assert active['preserved_active'] == 1
    assert not active['candidates']
    assert not active['errors']
    abandon(journey, cid)
    before = {path.name: path.read_bytes() for path in journey.store.conversations_dir.glob('*.json')}
    preview = other_store.cleanup_old_unpinned(retention_days=90, dry_run=True)
    assert [item['id'] for item in preview['candidates']] == [cid]
    assert before == {path.name: path.read_bytes() for path in journey.store.conversations_dir.glob('*.json')}
    result = other_store.cleanup_old_unpinned(retention_days=90)
    assert result['deleted_conversations'] == 1
    assert not result['errors']


def test_execution_lease_is_released_when_its_process_dies(journey):
    cid = journey.store.create_conversation()['id']
    lease = journey.store.run_lease(cid)
    script = """
import sys
from filelock import FileLock
with FileLock(sys.argv[1], thread_local=False):
    print('ready', flush=True)
    sys.stdin.read()
"""
    process = subprocess.Popen([sys.executable, '-c', script, str(lease.lock_file)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=3), 'Lease owner did not become ready'
        assert process.stdout.readline().strip() == 'ready'
        journey.store.claim_run(cid, {'message_id': 'child', 'status': 'running'}, message='Work')
        assert journey.store.list_conversations()[0]['run_status'] == 'running'
        process.terminate()
        process.wait(timeout=3)
        assert journey.store.list_conversations()[0]['run_status'] == 'interrupted'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()


def test_feedback_received_while_disconnected_is_in_the_reconnect_snapshot(journey):
    journey.send()
    cid, run = current(journey)
    journey.process()
    journey.handler._emit_run_event('feedback:start', {'message_id': run['message_id']}, room=f'conversation:{cid}')
    journey.handler._emit_run_event('feedback:complete', {'message_id': run['message_id'], 'success': True, 'rating': 5}, room=f'conversation:{cid}')
    call(journey, 'conversation:load', {'conversation_id': cid, 'reconnect_only': True}, sid='reconnected')
    event = journey.socket.events[-1][1]
    assert event['reconnect_only'] is True
    assert event['conversation']['feedback']['event'] == 'feedback:complete'
    assert event['conversation']['feedback']['data']['rating'] == 5
    assert event['conversation']['feedback']['data']['feedback_revision']


@pytest.mark.parametrize('late_count', [0, 2])
def test_reaction_from_a_new_socket_uses_the_original_experience(journey, monkeypatch, late_count):
    import intelligence_hooks

    journey.send()
    cid, run = current(journey)
    journey.process()
    journey.store.update_message_data_by_web_message_id(cid, run['message_id'], {
        '_human_reaction_eligible': True, 'experience_id': 42, '_intelligence_mode': 'cloud',
    })
    for index in range(late_count):
        journey.store.add_message(cid, 'assistant', 'An earlier background job finished.', data={
            '_kind': 'continuation', '_continuation_id': f'late-{index}',
            '_web_message_id': f'late-{index}',
        })
    del journey.handler.sessions['client']
    updates = []
    def react(experience_id, reaction, **kwargs):
        updates.append((experience_id, reaction, kwargs['mode']))
        return {'updated': True}
    monkeypatch.setattr(intelligence_hooks, 'update_experience_from_user_reaction', react)
    call(journey, 'conversation:load', {'conversation_id': cid}, sid='new')
    assert journey.socket.events[-1][1]['conversation']['reaction_message_id'] == run['message_id']
    call(journey, 'message_reaction:submit', {'conversation_id': cid, 'message_id': run['message_id'], 'reaction': 'up'}, sid='new')
    assert updates == [(42, 'up', 'cloud')]
    answer = next(m for m in journey.store.get_conversation(cid)['messages']
                  if m.get('data', {}).get('_web_message_id') == run['message_id'])
    assert answer['data']['_user_feedback']['reaction'] == 'up'


def test_user_message_before_late_reply_still_invalidates_old_reactions(journey, monkeypatch):
    import intelligence_hooks

    journey.send()
    cid, run = current(journey)
    journey.process()
    journey.store.update_message_data_by_web_message_id(cid, run['message_id'], {
        '_human_reaction_eligible': True, 'experience_id': 42, '_intelligence_mode': 'cloud',
    })
    journey.store.add_message(cid, 'user', 'A later question')
    journey.store.add_message(cid, 'assistant', 'An earlier background job finished.', data={
        '_kind': 'continuation', '_continuation_id': 'late', '_web_message_id': 'late',
    })
    updates = []
    monkeypatch.setattr(intelligence_hooks, 'update_experience_from_user_reaction',
                        lambda *args, **kwargs: updates.append(args))
    call(journey, 'conversation:load', {'conversation_id': cid}, sid='new')
    assert not journey.socket.events[-1][1]['conversation'].get('reaction_message_id')
    call(journey, 'message_reaction:submit', {
        'conversation_id': cid, 'message_id': run['message_id'], 'reaction': 'up',
    }, sid='new')
    assert not updates
    assert journey.socket.events[-1][1]['reason'] == 'not_latest_live_response'


def test_real_socketio_reconnect_stops_a_real_bounded_worker(journey, monkeypatch):
    """Real Flask-SocketIO rooms/clients/OS thread; the LLM is a disposable fake."""
    import flask_socketio
    import orchestrator_v2
    from jarvis_bundle_chat_test.services import tool_discovery

    monkeypatch.setitem(sys.modules, 'jarvis_bundle_chat_test.app',
                        SimpleNamespace(get_startup_mode=lambda: 'cloud'))
    monkeypatch.setattr(tool_discovery, 'get_tool_service',
                        lambda mode: SimpleNamespace(get_tool_count=lambda: 0))
    monkeypatch.setattr(chat, 'emit', flask_socketio.emit)
    app = Flask(__name__)
    socketio = flask_socketio.SocketIO(app, async_mode='threading')
    handler = chat.ChatHandler(socketio)
    for name in ('_get_completion_guard_config', '_compute_effective_evidence', '_is_user_reaction_eligible'):
        monkeypatch.setattr(handler, name, getattr(journey.handler, name))
    entered, release = threading.Event(), threading.Event()
    threads = []
    launch = handler._start_blocking_task

    def start(*args, **kwargs):
        thread = launch(*args, **kwargs)
        threads.append(thread)
        return thread

    def process(self, prompt, **kwargs):
        entered.set()
        if not release.wait(3):
            raise TimeoutError('Test worker was not released')
        cancelled = self.cancel_check()
        return {'ok': True, 'speech': 'Stopped' if cancelled else 'Done',
                'data': {}, 'tools_used': [], 'cancelled': cancelled}

    monkeypatch.setattr(handler, '_start_blocking_task', start)
    monkeypatch.setattr(orchestrator_v2.Orchestrator, 'process', process)
    first = socketio.test_client(app)
    second = None
    try:
        first.emit('chat:send', {'message': 'Wait for cancellation', 'mode': 'local'})
        assert entered.wait(1)
        events = first.get_received()
        cid = next(item['args'][0]['conversation_id'] for item in events if item['name'] == 'conversation:created')
        mid = next(item['args'][0]['message_id'] for item in events if item['name'] == 'chat:thinking')
        first.disconnect()
        second = socketio.test_client(app)
        second.emit('conversation:load', {'conversation_id': cid, 'reconnect_only': True})
        loaded = next(item['args'][0]['conversation'] for item in second.get_received() if item['name'] == 'conversation:loaded')
        assert loaded['run']['status'] == 'running'
        assert loaded['run']['mode'] == 'local'
        second.emit('chat:send', {'conversation_id': cid, 'message': 'Overlap', 'mode': 'cloud'})
        assert any(item['name'] == 'chat:rejected' for item in second.get_received())
        second.emit('chat:cancel', {'conversation_id': cid, 'message_id': mid})
        assert journey.store.get_conversation(cid)['run']['status'] == 'stopping'
        release.set()
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
        events = second.get_received()
        response = next(item['args'][0] for item in events if item['name'] == 'chat:response')
        assert response['cancelled'] is True
        assert response['conversation_id'] == cid
        assert journey.store.get_conversation(cid)['run']['status'] == 'cancelled'
        assert not handler.pending_cancellations
        with journey.store.run_lease(cid):
            pass  # The other thread released the execution lease on settlement.
    finally:
        release.set()
        for thread in threads:
            thread.join(4)
        if first.is_connected():
            first.disconnect()
        if second and second.is_connected():
            second.disconnect()
