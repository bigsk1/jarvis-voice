"""Uncertain tool outcomes notify chat once and retain evidence without replay."""
import json
import sqlite3
import threading
from dataclasses import replace

import pytest
from test_background_local_skill import probe as probe
from test_background_remote_skill import remote as remote
from test_background_task_delivery import complete_source
from test_background_task_delivery import destination as destination
from test_background_tasks import config_root as config_root
from test_background_tasks import ready
from test_background_tasks import store as store
from test_web_attachment_bundle_chat import journey as journey

from lib.background_tasks import LostLease
from lib.background_tasks.worker import ExecutionContext, KnownFailure, TaskWorker, UncertainOutcome

TASK = '00000000-0000-4000-8000-000000000001'
RESULT = {'ok': False, 'completion': 'unknown', 'error': 'Docling observation budget ended',
          'data': {'task_id': TASK, 'receipt_stash_ref': 'stash://space_receipt/f_task'}}


def test_remote_child_timeout_retains_native_receipt_and_notifies_without_replay(remote):
    p = remote
    script = p.manifest.with_suffix('').with_suffix('.py')
    script.write_text('print(' + repr(json.dumps(RESULT)) + ')\n')
    job = p.admit()
    worker = TaskWorker(p.store, {'remote_skill_v1': p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'needs_attention' and saved['result']['completion'] == 'unknown'
    assert saved['result']['data']['task_id'] == TASK
    assert saved['result']['data']['receipt_stash_ref'] == RESULT['data']['receipt_stash_ref']
    assert saved['delivery_state'] == 'pending' and p.store.counts()['reserved'] == 1
    assert not worker.run_once()
    assert len(p.store.pending_deliveries()) == 1


def test_attention_notice_is_atomic_and_recovery_backfills_silent_jobs_once(store):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    with sqlite3.connect(store.path) as conn:
        conn.execute("CREATE TRIGGER reject_notice BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.attention(claim, 'Waiting ended', result=RESULT)
    assert store.get(job['id'])['state'] == 'starting'
    assert store.get(job['id'])['result'] is None
    with sqlite3.connect(store.path) as conn:
        conn.execute('DROP TRIGGER reject_notice')
        conn.execute("UPDATE jobs SET state='needs_attention',fence=fence+1 WHERE id=?", (job['id'],))
    store.reconcile()
    first = store.pending_deliveries()
    assert len(first) == 1
    store.reconcile()
    assert store.pending_deliveries() == first
    assert store.get(job['id'])['state'] == 'needs_attention'
    assert store.claim('next-worker', {'local_fixture'}) is None


def test_verified_local_stop_replaces_uncertainty_notice_and_fences_old_delivery(store):
    job = ready(store, adapter='local_skill_v1')
    claim = store.claim('worker', {'local_skill_v1'})
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    notice = store.pending_deliveries()[0]
    old = store.claim_delivery(notice['id'], 'old-web')
    store.record_local_stop(claim)
    delivery = store.pending_deliveries()[0]
    assert delivery['id'] != notice['id']
    assert store.get(job['id'])['state'] == 'failed'
    with pytest.raises(LostLease):
        store.save_delivery_output(old, {'text': 'stale uncertainty'})
    assert store.counts()['reserved'] == 0


def test_worker_deadline_keeps_timeout_evidence_in_the_notice(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, timeout_seconds=2)
    store.claim('worker', {'local_fixture'})
    now[0] += 3
    store.reconcile()
    assert 'observation deadline' in store.get(job['id'])['result']['error']
    assert len(store.pending_deliveries()) == 1


@pytest.mark.parametrize(('budget', 'queue_delay'), [(2, 0), (960, 61)])
def test_deadline_winning_adapter_return_retains_receipt_without_restoring_lease(store, budget, queue_delay):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, timeout_seconds=budget)
    now[0] += queue_delay

    def expires(context):
        assert context.claim.job['deadline'] - now[0] == budget - queue_delay
        now[0] = context.claim.job['deadline'] + 1
        raise UncertainOutcome('Remote operation may continue', result=RESULT)

    worker = TaskWorker(store, {'local_fixture': expires})
    assert worker.run_once()
    saved = store.get(job['id'])
    assert saved['state'] == 'needs_attention' and saved['result']['completion'] == 'unknown'
    assert saved['result']['data'] == RESULT['data']
    assert saved['result']['error'] == 'Background observation deadline expired'
    assert saved['result']['observer_error'] == RESULT['error']
    assert saved['fence'] == 2 and store.counts()['reserved'] == 1
    assert len(store.pending_deliveries()) == 1 and not worker.run_once()


def test_early_recovery_progress_survives_other_progress_and_expiry(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, timeout_seconds=2)
    claim = store.claim('worker', {'local_fixture'})
    store.progress(claim, {'phase': 'Submitted', 'recovery': {'task_id': TASK}})
    store.progress(claim, {'phase': 'Receipt saved', 'recovery': RESULT['data']})
    store.progress(claim, {'phase': 'Waiting'})
    assert store.get(job['id'])['progress']['recovery'] == RESULT['data']
    now[0] += 3
    store.reconcile()
    assert store.get(job['id'])['result']['data'] == RESULT['data']


def test_late_recovery_progress_retains_only_metadata_and_still_raises_lost_lease(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, timeout_seconds=2)
    claim = store.claim('worker', {'local_fixture'})
    context = ExecutionContext(claim, store, threading.Event(), threading.Event(), {})
    now[0] += 3
    with pytest.raises(LostLease):
        context.progress({'phase': 'Late receipt', 'recovery': {**RESULT['data'], 'api_key': 'do-not-retain'}})
    assert store.get(job['id'])['result']['data'] == RESULT['data']
    assert store.get(job['id'])['progress'] is None
    with pytest.raises(LostLease):
        context.checkpoint()


def test_remote_child_receipt_progress_survives_supervisor_timeout_before_stdout(remote):
    p = remote
    manifest = json.loads(p.manifest.read_text())
    manifest['execution']['background']['timeout_seconds'] = 2
    p.manifest.write_text(json.dumps(manifest))
    script = p.manifest.with_suffix('').with_suffix('.py')
    progress = '__JARVIS_TOOL_PROGRESS__:' + json.dumps({'phase': 'Accepted', 'recovery': RESULT['data']})
    script.write_text('import sys, time\nprint(' + repr(progress) + ', file=sys.stderr, flush=True)\ntime.sleep(60)\n')
    job = p.admit()
    worker = TaskWorker(p.store, {'remote_skill_v1': p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['data'] == RESULT['data']
    assert saved['delivery_state'] == 'pending' and p.store.counts()['reserved'] == 1
    assert not worker.run_once()


@pytest.mark.parametrize('fence', ['operator', 'dispose', 'attempt', 'owner', 'execution_fence'])
def test_late_uncertainty_cannot_cross_existing_fences(store, fence):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    if fence == 'operator':
        store.reconcile_job(job['id'], store.get(job['id'])['revision'], disposition='failed',
                            evidence='Operator verified the provider stopped', stopped=True)
    elif fence == 'dispose':
        store.fence_conversation(job['conversation_id'], job['generation'], 'clear', dispose=True)
    else:
        claim = replace(claim, **{'attempt_id': 'different-attempt'} if fence == 'attempt'
                        else {'owner': 'different-worker'} if fence == 'owner' else {'fence': claim.fence + 1})
    before = store.get(job['id'])
    deliveries = store.pending_deliveries()
    assert not store.retain_uncertain_result(claim, RESULT)
    assert store.get(job['id']) == before and store.pending_deliveries() == deliveries


def test_late_receipt_fences_stale_synthesis_and_is_idempotent(store):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    old = store.claim_delivery(store.pending_deliveries()[0]['id'], 'web')
    store.save_delivery_output(old, {'text': 'No recovery details yet'})
    assert store.retain_uncertain_result(claim, RESULT)
    with pytest.raises(LostLease):
        with store.delivery_commit(old):
            pass
    delivery = store.pending_deliveries()[0]
    assert delivery['id'] != old['id'] and delivery['output_json'] is None
    assert store.retain_uncertain_result(claim, RESULT)
    assert store.pending_deliveries() == [delivery]


def test_late_result_and_notice_refresh_commit_atomically(store):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    before = store.get(job['id'])
    deliveries = store.pending_deliveries()
    with sqlite3.connect(store.path) as conn:
        conn.execute("CREATE TRIGGER reject_refresh BEFORE UPDATE ON outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.retain_uncertain_result(claim, RESULT)
    assert store.get(job['id']) == before and store.pending_deliveries() == deliveries
    with sqlite3.connect(store.path) as conn:
        conn.execute('DROP TRIGGER reject_refresh')
    assert store.retain_uncertain_result(claim, RESULT)
    assert store.get(job['id'])['result']['data'] == RESULT['data']


def test_late_receipt_respects_delivery_suppression(store):
    job = ready(store)
    claim = store.claim('worker', {'local_fixture'})
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE id=?', (job['id'],))
    store.reconcile()
    notice = store.pending_deliveries()[0]
    delivery_claim = store.claim_delivery(notice['id'], 'web')
    store.save_delivery_output(delivery_claim, {'text': 'Old notice without references'})
    store.control_delivery(job['id'], store.get(job['id'])['revision'], 'suppress_delivery')
    assert store.retain_uncertain_result(claim, RESULT)
    assert store.get(job['id'])['result']['data'] == RESULT['data']
    assert store.get(job['id'])['delivery_state'] == 'suppressed' and not store.pending_deliveries()
    # Explicit delivery retry regenerates from the enriched result, not stale output.
    store.control_delivery(job['id'], store.get(job['id'])['revision'], 'retry_delivery')
    assert store.pending_deliveries()[0]['output_json'] is None


def test_receipt_arriving_after_delivered_timeout_posts_one_recovery_followup(destination, monkeypatch):
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks

    h = destination
    complete_source(h)
    h.pending.clear()
    monkeypatch.setattr(h.socket, 'emit_background', h.socket.emit, raising=False)
    claim = h.tasks.claim('worker', {'local_fixture'})
    with sqlite3.connect(h.tasks.path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0,deadline=0 WHERE id=?', (h.job['id'],))
    h.tasks.reconcile()
    background = WebBackgroundTasks(h.handler, adapters={'local_fixture': lambda _: None})
    monkeypatch.setattr(background, 'ready', lambda: True)
    cid = h.job['conversation_id']
    old = h.tasks.pending_deliveries()[0]
    background._deliver(old, h.tasks.get(h.job['id']))
    assert h.tasks.get(h.job['id'])['delivery_state'] == 'delivered'
    assert h.tasks.retain_uncertain_result(claim, RESULT)
    followup = h.tasks.pending_deliveries()[0]
    assert followup['id'] != old['id']
    # A thread holding the original outbox snapshot cannot claim the new notice.
    background._deliver(old, h.tasks.get(h.job['id']))
    background._deliver(followup, h.tasks.get(h.job['id']))
    notices = [m for m in h.store.get_conversation(cid)['messages']
               if (m.get('data') or {}).get('_background_attention')]
    assert len(notices) == 2 and TASK not in notices[0]['content']
    assert TASK in notices[1]['content'] and RESULT['data']['receipt_stash_ref'] in notices[1]['content']
    assert h.tasks.retain_uncertain_result(claim, RESULT) and not h.tasks.pending_deliveries()
    assert h.tasks.get(h.job['id'])['state'] == 'needs_attention'
    assert h.tasks.counts()['reserved'] == 1 and len(h.tasks.conversation_jobs(cid)) == 1
    restored = type(h.store)(h.store.conversations_dir, background_tasks=h.tasks)
    assert restored.get_conversation(cid)['messages'][-1]['data']['_background_recovery'] == RESULT['data']


@pytest.mark.parametrize('uncertain_result', [True, False])
def test_timeout_notice_survives_reload_and_followup_has_existing_task(destination, monkeypatch, uncertain_result):
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks

    h = destination
    complete_source(h)
    h.pending.clear()
    monkeypatch.setattr(h.socket, 'emit_background', h.socket.emit, raising=False)

    def uncertain(context):
        if uncertain_result:
            raise UncertainOutcome('Provider work may continue; not retried', result=RESULT)
        raise KnownFailure({**RESULT, 'completion': 'completed'})

    assert TaskWorker(h.tasks, {'local_fixture': uncertain}).run_once()
    # Exercise the real deterministic delivery, without an LLM summary.
    background = WebBackgroundTasks(h.handler, adapters={'local_fixture': uncertain})
    h.handler.background_tasks = background
    monkeypatch.setattr(background, 'ready', lambda: True)
    cid = h.job['conversation_id']
    delivery = h.tasks.pending_deliveries()[0]
    job = h.tasks.get(h.job['id'])
    background._deliver(delivery, job)
    current = h.store.get_conversation(cid)
    notices = [m for m in current['messages'] if (m.get('data') or {}).get('_background_timeout')]
    assert len(notices) == 1
    assert 'waiting limit was reached' in notices[0]['content']
    assert 'No automatic retry' in notices[0]['content']
    assert notices[0]['data']['background_job_id'] == job['id']
    assert notices[0]['data']['_background_attention'] is uncertain_result
    assert TASK in notices[0]['content'] and RESULT['data']['receipt_stash_ref'] in notices[0]['content']
    assert notices[0]['data']['_background_recovery'] == RESULT['data']
    assert 'fixture' not in notices[0]['data']  # No media/tool result presented as completed.
    assert h.tasks.get(job['id'])['delivery_state'] == 'delivered'
    background.drain_once(inline=True)
    assert sum(bool((m.get('data') or {}).get('_background_timeout'))
               for m in h.store.get_conversation(cid)['messages']) == 1
    # A new conversation-store instance sees the persisted message after reload.
    restored = type(h.store)(h.store.conversations_dir, background_tasks=h.tasks)
    assert any((m.get('data') or {}).get('_background_timeout')
               for m in restored.get_conversation(cid)['messages'])
    prompt = background.conversation_context(cid, 'cloud')
    assert TASK in prompt and 'status question is not permission' in prompt
    before = h.tasks.conversation_jobs(cid)
    h.send(message='What is happening with the existing task?', conversation_id=cid)
    h.process()
    assert h.tasks.conversation_jobs(cid) == before
