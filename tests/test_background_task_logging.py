"""Daily background-task diagnostics, isolated from live logs and providers."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_background_tasks import admission, receipt
from test_background_tasks import config_root as config_root, store as store
from test_log_explorer import LogExplorerService
from test_web_background_tasks import eventually, journey as journey, web_tasks as web_tasks

from lib.background_tasks import TaskStore
from lib.background_tasks.events import ROOT, TaskEventLog
from lib.background_tasks.worker import KnownFailure, TaskWorker


def entries(log):
    return [json.loads(line) for path in sorted(log.directory.glob('*.jsonl'))
            for line in path.read_text().splitlines()]


def test_log_creation_is_lazy_and_custom_databases_are_isolated(tmp_path):
    store = TaskStore(tmp_path / 'control' / 'tasks.db')
    assert store.events.directory == tmp_path / 'control/logs/background-tasks'
    assert not store.events.directory.exists()
    assert TaskEventLog(ROOT / 'data/background_tasks.db').directory == ROOT / 'logs/background-tasks'
    store.events.emit('worker_starting', component='worker')
    assert len(entries(store.events)) == 1
    assert not store.path.exists()


def test_daily_rotation_uses_utc_and_private_files(tmp_path):
    now = [86400.0]
    log = TaskEventLog(tmp_path / 'tasks.db', clock=lambda: now[0])
    log.emit('worker_ready', component='worker')
    now[0] += 86400
    log.emit('worker_stopped', component='worker')
    files = sorted(log.directory.glob('*.jsonl'))
    assert [f.name for f in files] == ['background-tasks-1970-01-02.jsonl', 'background-tasks-1970-01-03.jsonl']
    assert all(f.stat().st_mode & 0o077 == 0 for f in files)
    assert all(e['timestamp'].endswith('+00:00') for e in entries(log))


def test_only_safe_metadata_is_logged(tmp_path):
    log = TaskEventLog(tmp_path / 'tasks.db')
    job = {'id': 'job-1', 'mode': 'cloud', 'state': 'failed', 'conversation_id': 'chat-1',
           'admission': {'tool': 'convert_file', 'request_id': 'request-1',
                         'arguments': {'secret': 'private-arguments'}},
           'result': {'error': 'private-result'}, 'attention_reason': 'private-reason'}
    log.emit('job_outcome', component='worker', job=job, level='WARNING', duration_ms=42,
             query='private-query', api_key='private-key', error='private-error',
             headers={'Authorization': 'private-header'})
    raw = next(log.directory.glob('*.jsonl')).read_text()
    assert 'private-' not in raw
    row = entries(log)[0]
    assert row['job_id'] == 'job-1' and row['tool'] == 'convert_file' and row['duration_ms'] == 42
    assert row['service'] == 'background-tasks' and row['level'] == 'WARNING'


def test_repeated_errors_are_throttled_and_report_suppressed_count(tmp_path):
    now = [1000.0]
    log = TaskEventLog(tmp_path / 'tasks.db', clock=lambda: now[0])
    for _ in range(10):
        log.emit('drain_failed', component='web', level='ERROR', error_type='DatabaseError', throttle=True)
    assert len(entries(log)) == 1
    now[0] += 60
    log.emit('drain_failed', component='web', level='ERROR', error_type='DatabaseError', throttle=True)
    assert entries(log)[1]['suppressed_repeats'] == 9


def test_thread_and_process_writes_are_complete_json_lines(tmp_path):
    log = TaskEventLog(tmp_path / 'tasks.db')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: log.emit('thread_event', component='worker', count=i), range(40)))
    script = """import sys
from lib.background_tasks.events import TaskEventLog
log = TaskEventLog(sys.argv[1])
for i in range(20):
    log.emit('process_event', component='web', count=i)
"""
    children = [subprocess.Popen([sys.executable, '-c', script, str(tmp_path / 'tasks.db')], cwd=ROOT)
                for _ in range(3)]
    try:
        for child in children:
            assert child.wait(timeout=15) == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
    rows = entries(log)
    assert len(rows) == 100
    assert len({row['pid'] for row in rows}) == 4


def test_existing_log_viewer_discovers_and_searches_background_records(tmp_path):
    log = TaskEventLog(tmp_path / 'tasks.db')
    log.emit('job_outcome', component='worker', level='WARNING', job_id='job-for-search', state='needs_attention')
    explorer = LogExplorerService(tmp_path / 'logs')
    assert [folder['label'] for folder in explorer.list_folders()] == ['background-tasks']
    path = next(log.directory.glob('*.jsonl')).relative_to(tmp_path / 'logs').as_posix()
    page = explorer.read_file(path, search='job-for-search')
    assert page['returned'] == 1 and page['view_type'] == 'yaml-records'


def test_log_failure_cannot_abort_admission_or_execution(store, config_root, tmp_path, caplog):
    unavailable = tmp_path / 'regular-file'
    unavailable.write_text('not a directory')
    store.events.directory = unavailable
    job = store.admit(admission())
    store.release(job['id'], receipt(job))
    assert TaskWorker(store, {'local_fixture': lambda context: {'ok': True}}).run_once()
    assert store.get(job['id'])['state'] == 'succeeded'
    assert caplog.text.count('Background event log unavailable') == 1


def test_admission_event_requires_commit_and_does_not_repeat_identity(store):
    with store._connection(write=True) as conn:
        conn.execute("""CREATE TRIGGER reject_job BEFORE INSERT ON jobs
            BEGIN SELECT RAISE(ABORT,'fixture'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.admit(admission())
    assert not any(e['event'] == 'job_accepted' for e in entries(store.events))
    with store._connection(write=True) as conn:
        conn.execute('DROP TRIGGER reject_job')
    job = store.admit(admission())
    assert store.admit(admission())['id'] == job['id']
    assert sum(e['event'] == 'job_accepted' for e in entries(store.events)) == 1


@pytest.mark.parametrize('outcome', ['succeeded', 'failed', 'needs_attention'])
def test_worker_logs_correlated_terminal_outcomes_without_result_contents(store, config_root, outcome):
    job = store.admit(admission())
    store.release(job['id'], receipt(job))

    def execute(context):
        if outcome == 'failed':
            raise KnownFailure({'ok': False, 'error': 'private-result'})
        if outcome == 'needs_attention':
            raise RuntimeError('private-error')
        return {'ok': True, 'data': 'private-result'}

    worker = TaskWorker(store, {'local_fixture': execute})
    assert worker.run_once()
    rows = [e for e in entries(store.events) if e.get('job_id') == job['id']]
    assert [r['event'] for r in rows][:2] == ['job_accepted', 'job_started']
    assert rows[-1]['event'] == 'job_outcome' and rows[-1]['state'] == outcome
    assert rows[-1]['duration_ms'] >= 0
    assert all(r['tool'] == 'fixture' and r['conversation_id'] == 'conversation-1' for r in rows)
    assert 'private-' not in json.dumps(rows)
    before = entries(store.events)
    assert not worker.run_once()  # Idle presence/claim polling is silent.
    assert entries(store.events) == before


def test_web_receipt_worker_outcome_and_late_delivery_share_job_identity(web_tasks):
    h = web_tasks
    job = h.send_background()
    (h.root / 'finish').touch()
    expected = {'job_accepted', 'job_started', 'job_outcome', 'continuation_delivered'}
    eventually(lambda: expected <= {r['event'] for r in entries(h.tasks.events) if r.get('job_id') == job['id']})
    rows = [r for r in entries(h.tasks.events) if r.get('job_id') == job['id']]
    assert expected <= {r['event'] for r in rows}
    assert len({r['conversation_id'] for r in rows}) == 1
    assert next(r for r in rows if r['event'] == 'continuation_delivered')['delivery_state'] == 'delivered'
