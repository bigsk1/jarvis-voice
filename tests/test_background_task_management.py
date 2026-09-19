"""Operator control preserves execution ownership and delivery fences."""

import pytest
from test_background_tasks import admission, ready, receipt
from test_background_tasks import store as store

from lib.background_tasks import Conflict, LostLease, TaskError


def running(store):
    job = store.admit(admission())
    store.release(job['id'], receipt(job))
    claim = store.claim('worker', {'local_fixture'})
    store.running(claim)
    return claim


def test_cancel_queued_never_executes_and_has_durable_disposition(store):
    job = store.admit(admission())
    result = store.request_cancel(job['id'], job['revision'], supported_adapters=set())
    assert result['state'] == 'cancelled'
    assert result['delivery_state'] == 'suppressed'
    assert store.claim('worker', {'local_fixture'}) is None
    assert store.job_detail(job['id'])['operator_events'][0]['evidence'] == 'Never dispatched'
    assert not store.outstanding(job['conversation_id'])


def test_running_cancel_requires_ack_and_success_can_win(store):
    claim = running(store)
    job = store.get(claim.job_id)
    requested = store.request_cancel(job['id'], job['revision'], supported_adapters={'local_fixture'})
    assert requested['state'] == 'cancel_requested'
    assert store.counts()['running'] == 1
    store.finish(claim, {'ok': True})
    assert store.get(job['id'])['state'] == 'succeeded'
    with pytest.raises(Conflict):
        store.request_cancel(job['id'], store.get(job['id'])['revision'], supported_adapters={'local_fixture'})


def test_acknowledged_cancel_fences_old_writer(store):
    claim = running(store)
    job = store.get(claim.job_id)
    store.request_cancel(job['id'], job['revision'], supported_adapters={'local_fixture'})
    store.acknowledge_cancel(claim, 'Child and process group termination verified')
    assert store.get(job['id'])['state'] == 'cancelled'
    with pytest.raises(LostLease):
        store.finish(claim, {'ok': True})


def test_reconciliation_releases_reserved_capacity_without_replaying(store):
    store.configure(max_running=1)
    claim = running(store)
    store.attention(claim, 'Execution owner disappeared')
    queued = store.admit(admission(invocation_id='next'))
    store.release(queued['id'], receipt(queued))
    assert store.claim('next-worker', {'local_fixture'}) is None
    job = store.get(claim.job_id)
    with pytest.raises(TaskError):
        store.reconcile_job(job['id'], job['revision'], disposition='failed', evidence='no', stopped=True)
    with pytest.raises(TaskError):
        store.reconcile_job(job['id'], job['revision'], disposition='failed', evidence='Reviewed process termination and output', stopped=False)
    assert store.counts()['reserved'] == 1
    settled = store.reconcile_job(job['id'], job['revision'], disposition='failed',
                                 evidence='Verified original worker and conversion processes have exited.', stopped=True)
    assert settled['state'] == 'failed'
    assert store.counts()['reserved'] == 0
    assert store.claim('next-worker', {'local_fixture'}).job_id == queued['id']
    with pytest.raises(LostLease):
        store.finish(claim, {'ok': True})
    assert len(store.job_detail(job['id'])['attempts']) == 1


def test_delivery_suppression_fences_generation_and_retry_reuses_output(store):
    claim = running(store)
    delivery_id = store.finish(claim, {'ok': True})
    delivery = store.claim_delivery(delivery_id, 'web')
    store.save_delivery_output(delivery, {'text': 'Finished'})
    job = store.get(claim.job_id)
    store.control_delivery(job['id'], job['revision'], 'suppress_delivery')
    with pytest.raises(LostLease):
        with store.delivery_commit(delivery):
            pass
    job = store.get(claim.job_id)
    store.control_delivery(job['id'], job['revision'], 'retry_delivery')
    retried = store.claim_delivery(delivery_id, 'web')
    assert retried['output_json'] == '{"text":"Finished"}'
    assert len(store.job_detail(job['id'])['attempts']) == 1


def test_operator_pagination_counts_and_revision_conflicts(store):
    for index in range(4):
        store.admit(admission(invocation_id=f'call-{index}'))
    first = store.list_jobs(limit=2, tool='fixture', conversation_id='conversation-1')
    second = store.list_jobs(limit=2, offset=first['next_offset'])
    assert first['total'] == 4 and second['next_offset'] is None
    assert len({job['id'] for job in first['jobs'] + second['jobs']}) == 4
    job = first['jobs'][0]
    store.mark_read(job['id'])
    with pytest.raises(Conflict):
        store.request_cancel(job['id'], job['revision'], supported_adapters=set())
    with pytest.raises(TaskError):
        store.list_jobs(state="queued' OR 1=1")


def test_result_retention_preserves_pending_work_artifacts_and_invocation_identity(store, tmp_path):
    now = [100000.0]
    store.clock = lambda: now[0]
    store.configure(result_retention_days=1)
    artifact = tmp_path / 'still-referenced.txt'
    artifact.write_text('keep this artifact')
    claim = running(store)
    store.finish(claim, {'ok':True,'artifact':str(artifact)})
    now[0] += 2 * 86400
    assert store.archive_results() == 0  # Pending follow-up is protected.
    job = store.get(claim.job_id)
    store.control_delivery(job['id'], job['revision'], 'suppress_delivery')
    now[0] += 2 * 86400
    assert store.archive_results(dry_run=True) == 1
    assert store.get(job['id'])['result'] is not None
    assert store.archive_results() == 1
    archived = store.get(job['id'])
    assert archived['archived_at'] == now[0] and archived['result'] is None
    assert artifact.read_text() == 'keep this artifact'
    assert store.admit(admission())['id'] == job['id']  # No replay after payload cleanup.
    with pytest.raises(TaskError, match='expired'):
        store.control_delivery(job['id'], archived['revision'], 'retry_delivery')
    assert store.claim('later', {'local_fixture'}) is None


def test_heartbeat_preserves_cancel_token_but_progress_changes_it(store):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    store.running(claim)
    before = store.get(job['id'])
    store.renew(claim)
    assert store.get(job['id'])['revision'] == before['revision']
    requested = store.request_cancel(job['id'], before['revision'], supported_adapters={'local_fixture'})
    assert requested['state'] == 'cancel_requested'
    assert requested['revision'] > before['revision']


def test_revision_migration_preserves_live_attempt_and_meaningful_changes(tmp_path, monkeypatch):
    from lib.background_tasks import TaskStore
    from lib.background_tasks import store as store_module
    from lib.background_tasks.models import Claim
    task_store = TaskStore(tmp_path / 'old-schema.db')
    with monkeypatch.context() as patch:
        patch.setattr(store_module, 'MIGRATIONS', store_module.MIGRATIONS[:6])
        # Emulate the pre-callback binary. This fresh fixture has no expired
        # work; the current recovery SQL requires the later callback column.
        patch.setattr(task_store, '_recover', lambda conn, now: None)
        task_store.initialize()
        task_store.configure(background_enabled=True, background_tools=['fixture'])
        job = ready(task_store)
        # Seed the active attempt as the old binary did. The current claim()
        # intentionally requires callback_waiting from the later migration.
        now = task_store.clock()
        with task_store._connection(write=True) as conn:
            conn.execute('''UPDATE jobs SET state='running',owner='old-worker',attempt_id='old-attempt',
                fence=fence+1,lease_expires_at=?,heartbeat_at=?,updated_at=? WHERE id=?''',
                (now + 30, now, now, job['id']))
            fence = conn.execute('SELECT fence FROM jobs WHERE id=?', (job['id'],)).fetchone()[0]
            conn.execute('INSERT INTO attempts(id,job_id,owner,fence,started_at) VALUES(?,?,?,?,?)',
                         ('old-attempt', job['id'], 'old-worker', fence, now))
        claim = Claim(job['id'], 'old-attempt', 'old-worker', fence, task_store.get(job['id']))
    task_store.initialize()
    before = task_store.get(job['id'])
    task_store.renew(claim)
    assert task_store.get(job['id'])['revision'] == before['revision']
    task_store.progress(claim, {'phase': 'Encoding'})
    progress = task_store.get(job['id'])
    assert progress['revision'] > before['revision']
    assert progress['attempt_id'] == before['attempt_id']
    task_store.finish(claim, {'ok': True})
    assert task_store.get(job['id'])['revision'] > progress['revision']
