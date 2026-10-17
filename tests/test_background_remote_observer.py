"""Paid submissions never repeat when a disposable SQLite observer restarts."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from lib.background_tasks import (
    Admission,
    Conflict,
    LostLease,
    ReceiptEvidence,
    TaskError,
    TaskStore,
)
from lib.background_tasks.models import remote_checkpoint
from lib.background_tasks.worker import (
    CancellationRequested,
    ExecutionContext,
    KnownCancelled,
    KnownRemoteCancelled,
    ResumableRemoteAdapter,
    TaskWorker,
)
from lib.config_loader import get_active_config_mode

ADAPTER = 'apify_actor_v1'
HANDLE = {'run_id': 'native-run-1', 'actor_id': 'example/actor'}


@pytest.fixture
def clock():
    return [1000.0]


@pytest.fixture
def store(tmp_path, clock):
    result = TaskStore(tmp_path / 'tasks.db', clock=lambda: clock[0])
    result.initialize()
    result.configure(background_enabled=True, background_tools=['fixture'], max_running=1,
                     max_per_adapter=1)
    return result


def ready(store, **changes):
    source = replace(Admission(
        conversation_id='conversation-1', generation=1, request_id='request-1',
        invocation_id='invocation-1', tool='fixture', adapter=ADAPTER, mode='cloud',
        arguments={'actor': 'example/actor', 'input': {'query': 'fixture'}},
        authorization_id='authorization-1', source='web', timeout_seconds=1800,
    ), **changes)
    job = store.admit(source)
    return store.release(job['id'], ReceiptEvidence(
        source.conversation_id, source.generation, source.request_id,
        'receipt-1', 'completed', True,
    ))


def started(store, **changes):
    job = ready(store, **changes)
    claim = store.claim('old-worker', {ADAPTER})
    store.running(claim)
    store.checkpoint_remote(claim, HANDLE)
    return job, claim


def no_start(context):
    pytest.fail('A saved native run must never be submitted again')


def test_submission_handle_is_committed_before_observation(store):
    job = ready(store)
    calls = []

    def start(context):
        calls.append('start')
        return HANDLE

    def observe(context, checkpoint):
        calls.append('observe')
        saved = store.get(job['id'])
        assert remote_checkpoint(saved['adapter'], saved['progress']) == HANDLE
        assert context.remote_checkpoint == checkpoint == HANDLE
        context.progress({'phase': 'Reading dataset'})
        assert remote_checkpoint(store.get(job['id'])['adapter'], store.get(job['id'])['progress']) == HANDLE
        return {'ok': True, 'data': checkpoint}

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(start, observe)}).run_once()
    assert calls == ['start', 'observe']
    assert store.get(job['id'])['state'] == 'succeeded'
    assert len(store.pending_deliveries()) == 1


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_restart_reacquires_only_observation_with_new_fence_and_original_mode(store, clock, mode):
    job, old = started(store, mode=mode)
    clock[0] += 31
    assert store.reconcile() == 0
    assert store.get(job['id'])['state'] == 'running'
    reopened = TaskStore(store.path, clock=lambda: clock[0])
    calls = []

    def observe(context, checkpoint):
        calls.append(checkpoint)
        assert context.claim.attempt_id != old.attempt_id
        assert context.claim.fence == old.fence + 1
        assert context.claim.job['deadline'] == job['deadline']
        assert context.claim.job['mode'] == get_active_config_mode() == mode
        assert context.environment['JARVIS_MODE'] == mode
        return {'ok': True, 'data': checkpoint}

    assert TaskWorker(reopened, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    assert calls == [HANDLE]
    assert reopened.get(job['id'])['state'] == 'succeeded'
    assert len(reopened.pending_deliveries()) == 1
    attempts = reopened.job_detail(job['id'])['attempts']
    assert [attempt['outcome'] for attempt in attempts] == ['observer_interrupted', 'succeeded']
    for mutation in (
        lambda: store.finish(old, {'ok': True}),
        lambda: store.progress(old, {'phase': 'Stale observer'}),
        lambda: store.checkpoint_remote(old, HANDLE),
        lambda: store.pause_remote_observation(old),
    ):
        with pytest.raises(LostLease):
            mutation()


def test_two_workers_cannot_reacquire_one_handle_or_free_its_capacity(store, clock):
    job, old = started(store)
    queued = ready(store, request_id='request-2', invocation_id='invocation-2')
    clock[0] += 31

    def claim(index):
        reopened = TaskStore(store.path, clock=lambda: clock[0])
        return reopened.claim(f'new-{index}', {ADAPTER}, resumable_adapters={ADAPTER})

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))
    assert len([claim for claim in claims if claim is not None]) == 1
    replacement = next(claim for claim in claims if claim is not None)
    assert replacement.job_id == job['id']
    assert replacement.fence == old.fence + 1
    assert store.get(queued['id'])['state'] == 'queued'
    assert store.counts()['running'] == 1


def test_ambiguous_submission_without_checkpoint_is_never_repeated(store, clock):
    job = ready(store)
    submissions = []

    def start(context):
        submissions.append('paid POST')
        raise ConnectionError('The native receipt was lost')

    worker = TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(start, lambda *args: pytest.fail())})
    assert worker.run_once()
    assert store.get(job['id'])['state'] == 'needs_attention'
    clock[0] += 31
    assert not worker.run_once()
    assert submissions == ['paid POST']


def test_ordinary_remote_adapter_does_not_gain_replay_from_native_recovery_id(store, clock):
    job = ready(store, adapter='remote_skill_v1')
    old = store.claim('old-worker', {'remote_skill_v1'})
    store.running(old)
    store.progress(old, {'phase': 'Waiting', 'recovery': {'run_id': HANDLE['run_id']}})
    clock[0] += 31
    assert store.reconcile() == 1
    assert store.get(job['id'])['state'] == 'needs_attention'
    assert store.claim('new-worker', {'remote_skill_v1'},
                       resumable_adapters={'remote_skill_v1'}) is None


def test_checkpoint_cannot_change_handle_or_be_injected_through_progress(store):
    _, old = started(store)
    with pytest.raises(Conflict, match='another run'):
        store.checkpoint_remote(old, {'run_id': 'different-run'})
    with pytest.raises(TaskError, match='trusted checkpoint'):
        store.progress(old, {'remote_observer': {'checkpoint': {'run_id': 'different-run'}}})
    with pytest.raises(TaskError):
        store.checkpoint_remote(old, {'run_id': 'native-run', 'token': 'secret'})


def test_observation_deadline_is_not_extended_by_restart_or_treated_as_native_failure(store, clock):
    job, _ = started(store, timeout_seconds=10)
    clock[0] += 11
    assert store.reconcile() == 1
    saved = store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['completion'] == 'unknown'
    assert saved['result']['data']['run_id'] == HANDLE['run_id']
    assert saved['deadline'] == job['deadline']
    assert not TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda *args: pytest.fail())}).run_once()


def test_graceful_shutdown_preserves_handle_for_read_only_resume(store):
    job = ready(store)
    stop = threading.Event()

    def observe(context, checkpoint):
        stop.set()
        context.wait(300)
        pytest.fail('Shutdown must interrupt the observer wait')

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(lambda context: HANDLE, observe)}).run_once(stop)
    assert store.get(job['id'])['state'] == 'running'
    assert store.pending_deliveries() == []
    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda context, handle: {'ok': True})}).run_once()
    assert store.get(job['id'])['state'] == 'succeeded'


def test_shutdown_between_reclaim_and_adapter_entry_preserves_native_observation(store, clock, monkeypatch):
    job, _ = started(store)
    clock[0] += 31
    stop = threading.Event()
    original = store.claim

    def claim_and_stop(*args, **kwargs):
        claim = original(*args, **kwargs)
        stop.set()
        return claim

    with monkeypatch.context() as patch:
        patch.setattr(store, 'claim', claim_and_stop)
        assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda *args: pytest.fail())}).run_once(stop)
    assert store.get(job['id'])['state'] == 'starting'
    assert store.pending_deliveries() == []
    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda *args: {'ok': True})}).run_once()
    assert store.get(job['id'])['state'] == 'succeeded'


def test_cancellation_racing_first_adapter_entry_prevents_native_submission(store, monkeypatch):
    job = ready(store)
    original = store.running

    def running_and_cancel(claim):
        original(claim)
        saved = store.get(job['id'])
        store.request_cancel(job['id'], saved['revision'], supported_adapters={ADAPTER})

    monkeypatch.setattr(store, 'running', running_and_cancel)
    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda *args: pytest.fail())}).run_once()
    assert store.get(job['id'])['state'] == 'cancelled'


def test_cancel_requested_while_worker_offline_reaches_saved_native_handle(store, clock):
    job, _ = started(store)
    saved = store.get(job['id'])
    store.request_cancel(job['id'], saved['revision'], supported_adapters={ADAPTER})
    clock[0] += 31

    def observe(context, checkpoint):
        with pytest.raises(CancellationRequested):
            context.checkpoint()
        context.checkpoint(allow_cancel=True)
        context.wait(0, allow_cancel=True)
        raise KnownRemoteCancelled(checkpoint['run_id'])

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    saved = store.get(job['id'])
    assert saved['cancelled']
    assert saved['state'] == 'cancelled'
    assert store.pending_deliveries() == []


def test_native_abort_progress_keeps_observing_until_same_handle_is_confirmed_stopped(store, clock):
    job, _ = started(store)
    saved = store.get(job['id'])
    store.request_cancel(job['id'], saved['revision'], supported_adapters={ADAPTER})
    clock[0] += 31
    reads, aborts = [], []

    def observe(context, checkpoint):
        for status in ('RUNNING', 'ABORTING', 'ABORTED'):
            context.checkpoint(allow_cancel=True)
            reads.append((checkpoint['run_id'], status))
            if status == 'ABORTED':
                raise KnownRemoteCancelled(checkpoint['run_id'])
            with pytest.raises(CancellationRequested):
                context.progress({'phase': 'Default progress still rejects cancellation'})
            if not aborts:
                aborts.append(checkpoint['run_id'])
            context.progress({'phase': 'Cancelling', 'status': status}, allow_cancel=True)
            assert store.get(job['id'])['progress']['status'] == status
            context.wait(0, allow_cancel=True)
        pytest.fail('The same native run must confirm cancellation')

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    assert aborts == [HANDLE['run_id']]
    assert reads == [(HANDLE['run_id'], status) for status in ('RUNNING', 'ABORTING', 'ABORTED')]
    assert store.get(job['id'])['state'] == 'cancelled'


def test_cancel_cannot_settle_a_different_remote_run(store, clock):
    job, _ = started(store)
    saved = store.get(job['id'])
    store.request_cancel(job['id'], saved['revision'], supported_adapters={ADAPTER})
    clock[0] += 31

    def observe(context, checkpoint):
        raise KnownRemoteCancelled('different-run')

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    saved = store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert not saved['cancelled']


def test_native_cancellation_requires_a_matching_operator_request(store, clock):
    job, _ = started(store)
    clock[0] += 31

    def observe(context, checkpoint):
        raise KnownRemoteCancelled(checkpoint['run_id'])

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    assert store.get(job['id'])['state'] == 'needs_attention'


def test_local_termination_cannot_acknowledge_native_run_cancellation(store, clock):
    job, _ = started(store)
    saved = store.get(job['id'])
    store.request_cancel(job['id'], saved['revision'], supported_adapters={ADAPTER})
    clock[0] += 31

    def observe(context, checkpoint):
        raise KnownCancelled('Local observer stopped')

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    assert store.get(job['id'])['state'] == 'needs_attention'
    assert not store.get(job['id'])['cancelled']


def test_disabling_new_admissions_does_not_orphan_a_saved_native_run(store, clock):
    job, _ = started(store)
    store.configure(background_enabled=False, background_tools=[])
    clock[0] += 31
    observed = []

    def observe(context, checkpoint):
        observed.append(checkpoint)
        return {'ok': True, 'data': checkpoint}

    assert TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, observe)}).run_once()
    assert observed == [HANDLE]
    assert store.get(job['id'])['state'] == 'succeeded'


def test_conversation_disposal_fences_saved_observation_and_late_output(store, clock):
    job, old = started(store)
    store.fence_conversation(job['conversation_id'], job['generation'], 'delete', dispose=True)
    clock[0] += 31
    assert not TaskWorker(store, {ADAPTER: ResumableRemoteAdapter(no_start, lambda *args: pytest.fail())}).run_once()
    with pytest.raises(LostLease):
        store.finish(old, {'ok': True})
    assert store.pending_deliveries() == []


def test_resumable_wrapper_rejects_unreviewed_adapter_and_wait_bounds(store):
    with pytest.raises(TaskError, match='reviewed adapter'):
        TaskWorker(store, {'remote_skill_v1': ResumableRemoteAdapter(no_start, lambda *args: {})})
    _, claim = started(store)
    context = ExecutionContext(claim, store, threading.Event(), threading.Event(), {})
    for seconds in (301, -1, True, float('inf')):
        with pytest.raises(TaskError, match='300'):
            context.wait(seconds)
