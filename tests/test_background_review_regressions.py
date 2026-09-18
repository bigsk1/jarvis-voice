"""Optional task failures must not break chat or retain unnecessary execution slots."""

import json
import sqlite3
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_background_local_skill import NAME, probe as probe
from test_background_tasks import admission, ready, receipt
from test_background_tasks import config_root as config_root, store as store
from test_web_background_tasks import eventually, journey as journey, web_tasks as web_tasks

from lib.background_tasks import AdmissionDenied, LostLease, TaskError, TaskStore
from lib.background_tasks import store as store_module
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.local_contract import ADAPTER, REMOTE_ADAPTER
from lib.background_tasks.worker import TaskWorker


def authorization_payload(**changes):
    return {'source': 'web', 'operator': 'installation', 'conversation_id': 'conversation-1',
            'generation': 1, 'request_id': 'request-1', 'mode': 'local', 'selected': ['fixture'],
            'tool_policy': 'auto', **changes}


def authorization_count(store):
    with store._connection() as conn:
        return conn.execute('SELECT count(*) FROM authorizations').fetchone()[0]


def fixture_context(store, validate_source=lambda _: True):
    schema = SimpleNamespace(background_adapter='local_fixture')
    registry = SimpleNamespace(list_tools=lambda: ['fixture'], get_tool=lambda _: schema)
    service = BackgroundAdmissionService(store, adapters={'fixture': 'local_fixture'},
        validate_source=validate_source, ready=lambda: True)
    store.touch_worker('fixture-ready', {'local_fixture'})
    return service.authorize(authorization_payload(query='private text' * 70000), registry), schema


def test_authorization_is_atomic_with_admission_and_never_copies_query(store):
    context, schema = fixture_context(store)
    assert authorization_count(store) == 0
    accepted = context.admit('fixture', {}, 'first', schema)
    assert authorization_count(store) == 1
    payload = store.authorization(context.authorization_id)
    assert 'query' not in payload
    assert payload == authorization_payload()
    assert store.get(accepted['job_id'])['admission']['authorization_id'] == context.authorization_id


def test_failed_admission_rolls_back_authorization_insert(store):
    context, schema = fixture_context(store)
    with store._connection(write=True) as conn:
        conn.execute("""CREATE TRIGGER reject_job BEFORE INSERT ON jobs
            BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END""")
    with pytest.raises(AdmissionDenied, match='storage is unavailable'):
        context.admit('fixture', {}, 'first', schema)
    assert authorization_count(store) == 0
    assert store.conversation_jobs() == []


def test_allowlist_is_rechecked_after_source_validation_inside_admission(store):
    checks = []

    def current(_):
        checks.append(True)
        if len(checks) == 2:
            store.configure(background_tools=[])
        return True

    context, schema = fixture_context(store, current)
    with pytest.raises(AdmissionDenied, match='no longer enabled'):
        context.admit('fixture', {}, 'first', schema)
    assert authorization_count(store) == 0
    assert store.conversation_jobs() == []


def test_unchecking_rejects_new_work_but_preserves_receipt_identity(store):
    job = store.admit(admission())
    store.configure(background_tools=[])
    assert store.admit(admission())['id'] == job['id']
    with pytest.raises(AdmissionDenied, match='no longer enabled'):
        store.admit(admission(invocation_id='second'))


@pytest.mark.parametrize('action', ['clear', 'delete'])
def test_disposal_removes_authorizations_for_its_generation_only(store, action):
    context, schema = fixture_context(store)
    context.admit('fixture', {}, 'first', schema)
    unrelated = store.save_authorization(authorization_payload(conversation_id='other'))
    store.fence_conversation('conversation-1', 1, action, dispose=True)
    assert store.authorization(context.authorization_id) is None
    assert store.authorization(unrelated)


def test_authorization_retention_preserves_active_and_pending_then_purges_archived_and_orphan(store):
    now = [100000.0]
    store.clock = lambda: now[0]
    store.configure(result_retention_days=1)
    context, schema = fixture_context(store)
    accepted = context.admit('fixture', {}, 'first', schema)
    job = store.get(accepted['job_id'])
    orphan = store.save_authorization(authorization_payload(conversation_id='orphan'))
    now[0] += 2 * 86400
    assert store.archive_results(dry_run=True) == 0
    assert store.authorization(orphan)
    store.archive_results()
    assert store.authorization(orphan) is None
    assert store.authorization(context.authorization_id)  # Held work still needs policy.
    # Return to before its execution deadline; advance again only after finish.
    now[0] = 100001.0
    store.release(job['id'], receipt(job))
    claim = store.claim('worker', {'local_fixture'})
    store.finish(claim, {'ok': True})
    now[0] += 2 * 86400
    assert store.archive_results() == 0
    assert store.authorization(context.authorization_id)  # Pending continuation needs provider.
    job = store.get(job['id'])
    store.control_delivery(job['id'], job['revision'], 'suppress_delivery')
    now[0] += 2 * 86400
    assert store.archive_results() == 1
    assert store.authorization(context.authorization_id) is None


def test_migration_redacts_legacy_queries_without_changing_accepted_identity(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / 'previous.db')
    with monkeypatch.context() as patch:
        patch.setattr(store_module, 'MIGRATIONS', store_module.MIGRATIONS[:5])
        store.initialize()
        store.configure(background_enabled=True, background_tools=['fixture'])
        job = store.admit(admission())
        with store._connection(write=True) as conn:
            conn.execute('INSERT INTO authorizations VALUES(?,?,?)',
                         ('authorization-1', json.dumps(authorization_payload(query='private legacy text')), 1))
    store.initialize()
    assert store.authorization('authorization-1') == authorization_payload()
    assert store.admit(admission())['id'] == job['id']


@pytest.mark.parametrize('broken', ['schema', 'corrupt', 'permissions'])
def test_task_store_failure_preserves_chat_reads_and_sends_but_not_disposal(journey, store, broken):
    h = journey
    h.store.background_tasks = store
    cid = h.store.create_conversation()['id']
    h.store.add_message(cid, 'assistant', 'Existing answer')
    if broken == 'schema':
        with store._connection(write=True) as conn:
            conn.execute('INSERT INTO schema_migrations VALUES(999,0)')
    elif broken == 'corrupt':
        store.path.write_bytes(b'not a sqlite database')
    else:
        store.path.chmod(0o644)
    assert h.store.get_conversation(cid)['messages'][0]['content'] == 'Existing answer'
    assert h.store.create_conversation()['id']
    h.send(conversation_id=cid, message='An unrelated question')
    h.process()
    assert h.store.get_conversation(cid)['run']['status'] == 'completed'
    assert any(name == 'chat:response' for name, *_ in h.socket.events)
    assert not any(name == 'chat:error' for name, *_ in h.socket.events)
    with pytest.raises((TaskError, sqlite3.Error)):
        store.fence_conversation(cid, 0, 'delete', dispose=True)


def test_large_unrelated_web_turn_never_authorizes_any_background_tool(web_tasks, monkeypatch):
    from lib.background_tasks import production

    h = web_tasks
    monkeypatch.setattr(production, 'authorize_tools',
                        lambda names: pytest.fail('Unrelated chat must not validate background manifests'))
    (h.root / 'foreground_finish').touch()
    h.client.emit('chat:send', {'message': 'What time is it?\n' + 'large paste ' * 10000, 'mode': 'cloud'})
    events = []

    def answered():
        events.extend(h.client.get_received())
        return any(e['name'] == 'chat:response' for e in events)

    eventually(answered)
    assert not any(e['name'] == 'chat:error' for e in events)
    assert (h.root / 'foreground_started').exists()
    assert authorization_count(h.tasks) == 0
    assert h.tasks.conversation_jobs() == []


def test_unreadable_preferences_do_not_break_unrelated_web_tools_or_fall_back_selected_tools(web_tasks, monkeypatch):
    h = web_tasks

    def unreadable():
        raise sqlite3.DatabaseError('fixture unavailable')

    monkeypatch.setattr(h.tasks, 'settings', unreadable)
    (h.root / 'foreground_finish').touch()
    for query in ('What time is it?', 'Run fixture'):
        h.client.emit('chat:send', {'message': query, 'mode': 'cloud'})
        events = []

        def answered():
            events.extend(h.client.get_received())
            return any(e['name'] == 'chat:response' for e in events)

        eventually(answered)
        assert not any(e['name'] == 'chat:error' for e in events)
    assert (h.root / 'foreground_started').exists()
    assert not list(h.root.glob('*.started'))
    assert h.tasks.conversation_jobs() == []
    assert authorization_count(h.tasks) == 0


def test_initialization_failure_keeps_web_service_available(web_tasks, monkeypatch):
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks

    h = web_tasks
    h.background.close()
    other = WebBackgroundTasks(h.handler, adapters=h.background.adapters)
    monkeypatch.setattr(h.tasks, 'initialize', lambda: (_ for _ in ()).throw(sqlite3.DatabaseError('fixture')))
    assert not other.start()
    assert other.ownership is None and other.thread is None
    assert other.unavailable_reason == 'Background task storage is unavailable'
    # Failure releases the ownership lock for a repaired successor.
    from filelock import FileLock
    with FileLock(str(h.tasks.path) + '.web.lock', timeout=0):
        pass


def test_delivery_publishes_committed_card_without_another_drain(web_tasks, monkeypatch):
    h = web_tasks
    job = h.send_background()
    monkeypatch.setattr(h.background, 'drain_once', lambda **kwargs: None)
    h.client.emit('tasks:subscribe', {'conversation_id': job['conversation_id']})
    (h.root / 'finish').touch()
    eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded')
    h.client.get_received()
    delivery = h.tasks.pending_deliveries()[0]
    h.background._deliver(delivery, h.tasks.get(job['id']))
    events = h.client.get_received()
    assert any(e['name'] == 'chat:continuation' for e in events)
    assert any(e['name'] == 'task:updated' and e['args'][0]['delivery_state'] == 'delivered' for e in events)
    conversation = h.store.get_conversation(job['conversation_id'])
    assert '"delivery_state": "delivered"' in json.dumps(conversation)


def test_repeated_verified_shutdowns_release_capacity_without_replay(probe):
    p = probe
    p.store.configure(max_running=1, max_outstanding=10)
    for number in range(3):
        context = p.authorize()
        accepted = context.admit(NAME, {'label': str(number), 'delay': 10}, f'call-{number}', p.schema)
        job = p.store.get(accepted['job_id'])
        p.store.release(job['id'], receipt(job))
        stop = threading.Event()
        worker = TaskWorker(p.store, {ADAPTER: p.runner})
        thread = threading.Thread(target=worker.run_once, args=(stop,))
        thread.start()
        try:
            eventually(lambda: (p.output / f'{number}.started').exists())
            stop.set()
            thread.join(6)
            assert not thread.is_alive()
            assert p.store.get(job['id'])['state'] == 'failed'
            assert p.store.counts()['reserved'] == p.store.counts()['running'] == 0
            assert not worker.run_once()
        finally:
            stop.set()
            thread.join(6)
    assert len(list(p.output.glob('*.started'))) == 3


def test_unverified_local_termination_keeps_capacity_reserved(probe, monkeypatch):
    import tool_process

    p = probe
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    terminate = tool_process.terminate_verified

    def unverified(process, grace_seconds):
        terminate(process, grace_seconds)  # Clean up the real fixture child.
        return False  # Simulate a supervisor unable to establish group death.

    monkeypatch.setattr(tool_process, 'terminate_verified', unverified)
    worker = TaskWorker(p.store, {ADAPTER: p.runner})
    assert worker.run_once()
    assert p.store.get(job['id'])['state'] == 'needs_attention'
    assert p.store.counts()['reserved'] == 1
    assert not p.store.pending_deliveries()
    assert not worker.run_once()


@pytest.mark.parametrize('adapter', [ADAPTER, REMOTE_ADAPTER])
def test_expiry_alone_is_not_stop_proof_and_remote_proof_cannot_release(store, adapter):
    job = ready(store, adapter=adapter)
    claim = store.claim('worker', {adapter})
    with store._connection(write=True) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    assert store.get(job['id'])['state'] == 'needs_attention'
    assert store.counts()['reserved'] == 1
    if adapter == REMOTE_ADAPTER:
        with pytest.raises(LostLease):
            store.record_local_stop(claim)
    else:
        store.record_local_stop(claim)  # Trusted supervisor proof for the same attempt.
        assert store.get(job['id'])['state'] == 'failed'
        assert store.counts()['reserved'] == 0
    assert store.claim('successor', {adapter}) is None


@pytest.mark.parametrize('superseding', ['disposal', 'operator', 'other-attempt'])
def test_verified_stop_cannot_cross_an_unrelated_fence(store, superseding):
    job = ready(store, adapter=ADAPTER)
    claim = store.claim('worker', {ADAPTER})
    with store._connection(write=True) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    if superseding == 'disposal':
        store.fence_conversation('conversation-1', 1, 'delete', dispose=True)
    elif superseding == 'operator':
        current = store.get(job['id'])
        store.reconcile_job(job['id'], current['revision'], disposition='cancelled', stopped=True,
                            evidence='Operator verified that the process group stopped.')
    else:
        claim = replace(claim, attempt_id='unrelated-attempt')
    before = store.get(job['id'])
    with pytest.raises(LostLease):
        store.record_local_stop(claim)
    assert store.get(job['id']) == before
