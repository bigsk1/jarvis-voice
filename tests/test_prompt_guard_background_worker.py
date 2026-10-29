"""Worker screening separates withheld content from execution certainty."""

import json
from types import SimpleNamespace

import pytest
from test_background_local_skill import NAME
from test_background_local_skill import probe as probe
from test_background_remote_skill import remote as remote
from test_background_tasks import admission, receipt
from test_background_tasks import config_root as config_root
from test_background_tasks import store as store

from lib import config_loader
from lib import prompt_guard_observer as observer
from lib.background_tasks.local_contract import REMOTE_ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import KnownFailure, TaskWorker, UncertainOutcome
from lib.prompt_guard import PromptGuardResult
from lib.tool_logger import ToolLogger

PRIVATE = "UNTRUSTED_WORKER_CONTENT"
INCIDENT = "pg-" + "b" * 32


def configure_guard(root, tools):
    for mode in ('cloud', 'local'):
        with (root / 'config' / f'{mode}.env').open('a') as stream:
            stream.write(
                f'PROMPT_GUARD_ENABLED=true\nPROMPT_GUARD_TOOLS={tools}\n'
                f'PROMPT_GUARD_API_KEY=scanner-secret-{mode}\n'
            )


@pytest.fixture
def guard(config_root, monkeypatch):
    import config_loader as scanner_config

    monkeypatch.setattr(scanner_config, 'get_project_root', lambda: config_root)
    configure_guard(config_root, 'fixture,' + NAME)
    scans, evidence = [], []

    def scan(text, **source):
        scans.append((text, source, scanner_config.get_active_config_mode(),
                      scanner_config.get_config_value('PROMPT_GUARD_API_KEY')))
        return PromptGuardResult(
            'scanned', flagged=True, injection_score=.99, threshold=.8,
            coverage_complete=True, windows_scanned=1,
        )

    def save(**kwargs):
        evidence.append(kwargs)
        return SimpleNamespace(incident_id=INCIDENT, evidence_saved=True)

    monkeypatch.setattr(observer, 'scan_text', scan)
    monkeypatch.setattr(observer, 'save_incident', save)
    return SimpleNamespace(scans=scans, evidence=evidence, scan=scan)


def released(store, mode='cloud'):
    job = store.admit(admission(mode=mode))
    return store.release(job['id'], receipt(job))


def result(**changes):
    return {'ok': True, 'speech': PRIVATE + ' title', 'data': {'content': PRIVATE}, **changes}


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('outcome', ['success', 'completed_failure', 'rejected_failure'])
def test_terminal_worker_detections_are_saved_failed_without_uncertainty_or_replay(
        store, guard, mode, outcome):
    raw = result()
    if outcome != 'success':
        raw.update(ok=False, completion='completed' if outcome == 'completed_failure' else 'rejected')
    job = released(store, mode)
    calls, contexts = [], []

    def adapter(context):
        calls.append(context.claim.job_id)
        contexts.append(context)
        if outcome != 'success':
            raise KnownFailure(raw)
        return raw

    worker = TaskWorker(store, {'local_fixture': adapter})
    with config_loader.config_scope('local' if mode == 'cloud' else 'cloud'):
        assert worker.run_once()
    saved = store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['error_code'] == 'prompt_injection_detected'
    assert saved['result']['completion'] == ('rejected' if outcome == 'rejected_failure' else 'completed')
    assert saved['result']['data']['prompt_guard']['incident_id'] == INCIDENT
    assert saved['result']['data']['operation']['original_ok'] is raw['ok']
    assert PRIVATE not in json.dumps(saved['result'])
    assert store.counts()['reserved'] == 0
    assert len(store.pending_deliveries()) == 1
    assert saved['delivery_state'] == 'pending'
    assert not worker.run_once()
    assert len(calls) == len(guard.scans) == len(guard.evidence) == 1
    assert guard.scans[0][2:] == (mode, f'scanner-secret-{mode}')
    assert guard.evidence[0]['mode'] == mode
    assert PRIVATE in guard.evidence[0]['text']
    assert contexts[0].pending_tool_logs == [] and contexts[0].unreviewed_tool_result is None
    assert raw['speech'].startswith(PRIVATE)
    if outcome == 'success':
        assert 'completion' not in raw


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('status', ['clean', 'unknown', 'busy', 'disabled'])
def test_unflagged_or_unavailable_scans_preserve_worker_result(store, guard, monkeypatch, mode, status):
    verdict = {
        'clean': PromptGuardResult('scanned', flagged=False),
        'unknown': PromptGuardResult('unknown', 'timeout'),
        'busy': PromptGuardResult('skipped', 'busy'),
        'disabled': PromptGuardResult('disabled', 'disabled'),
    }[status]
    monkeypatch.setattr(observer, 'scan_text', lambda *_args, **_kwargs: verdict)
    raw = result()
    job = released(store, mode)
    worker = TaskWorker(store, {'local_fixture': lambda _context: raw})
    assert worker.run_once()
    saved = store.get(job['id'])
    assert saved['state'] == 'succeeded' and saved['result'] == raw
    assert len(store.pending_deliveries()) == 1 and store.counts()['reserved'] == 0
    assert not worker.run_once() and not guard.evidence


@pytest.mark.parametrize('flagged', [True, False])
def test_uncertain_remote_outcome_remains_uncertain_and_reserves_capacity(store, guard, monkeypatch, flagged):
    if not flagged:
        monkeypatch.setattr(observer, 'scan_text', lambda *_args, **_kwargs: PromptGuardResult('unknown', 'timeout'))
    job = released(store)
    calls = []

    def adapter(_context):
        calls.append(1)
        raise UncertainOutcome('Provider completion is unknown; not replayed.', result=result(ok=False, completion='unknown'))

    worker = TaskWorker(store, {'local_fixture': adapter})
    assert worker.run_once()
    saved = store.get(job['id'])
    assert saved['state'] == 'needs_attention' and saved['result']['completion'] == 'unknown'
    assert store.counts()['reserved'] == 1
    assert len(store.pending_deliveries()) == 1
    if flagged:
        assert saved['result']['error_code'] == 'prompt_injection_detected'
        assert PRIVATE not in json.dumps(saved['result'])
    else:
        assert saved['result']['speech'].startswith(PRIVATE)
    assert not worker.run_once() and calls == [1]


def test_review_runs_before_persistence_and_without_holding_sqlite_write_lock(store, guard, monkeypatch):
    job = released(store)

    def scan(text, **source):
        current = store.get(job['id'])
        assert current['state'] == 'running' and current['result'] is None
        assert not store.pending_deliveries()
        with store._connection(write=True) as connection:
            connection.execute('SELECT 1')
        return guard.scan(text, **source)

    monkeypatch.setattr(observer, 'scan_text', scan)
    assert TaskWorker(store, {'local_fixture': lambda _context: result()}).run_once()
    assert store.get(job['id'])['result']['error_code'] == 'prompt_injection_detected'


def test_deferred_log_keeps_proxy_metadata_and_never_persists_withheld_text(store, guard, tmp_path):
    job = released(store)
    logger = ToolLogger(tmp_path / 'tool-logs')
    raw = result(error=PRIVATE)

    def adapter(context):
        context.stage_tool_log(logger.log_tool_call, {
            'tool_name': 'fixture', 'arguments': {}, 'result': raw,
            'duration_ms': 12.5, 'mode': 'cloud',
            'proxy': {'policy': 'prefer', 'used': True, 'slot': 'primary'},
        })
        assert not logger.log_file.exists()
        return raw

    assert TaskWorker(store, {'local_fixture': adapter}).run_once()
    entries = [json.loads(line) for line in logger.log_file.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]['proxy'] == {'policy': 'prefer', 'used': True, 'slot': 'primary'}
    assert entries[0]['duration_ms'] == 12.5
    assert PRIVATE not in logger.log_file.read_text()
    assert store.get(job['id'])['state'] == 'failed'


def test_log_and_optional_review_failures_never_change_completed_execution(store, guard, monkeypatch, caplog):
    from lib.background_tasks import worker as worker_module

    job = released(store)
    raw = result()
    contexts, writes = [], []

    def fail_review(*_args, **_kwargs):
        raise RuntimeError(PRIVATE)

    def fail_log(**_entry):
        writes.append(1)
        raise OSError(PRIVATE)

    def adapter(context):
        contexts.append(context)
        context.stage_tool_log(fail_log, {'result': raw})
        return raw

    monkeypatch.setattr(worker_module, 'review_tool_result', fail_review)
    worker = TaskWorker(store, {'local_fixture': adapter})
    assert worker.run_once()
    assert store.get(job['id'])['state'] == 'succeeded'
    assert store.get(job['id'])['result'] == raw
    assert not worker.run_once() and writes == [1]
    assert not contexts[0].pending_tool_logs and contexts[0].unreviewed_tool_result is None
    assert PRIVATE not in caplog.text


@pytest.fixture(params=['local', 'remote'])
def supervised(request, probe, config_root, monkeypatch, tmp_path):
    import executor
    import tool_process

    p = probe if request.param == 'local' else request.getfixturevalue('remote')
    configure_guard(config_root, NAME)
    log = ToolLogger(tmp_path / 'supervised-tool-logs')
    monkeypatch.setattr(executor, 'get_logger', lambda _mode: log)
    calls = []

    def run(*_args, **kwargs):
        calls.append(kwargs)
        if kwargs.get('process_started'):
            kwargs['process_started'](12345)
        if kwargs.get('process_stopped'):
            kwargs['process_stopped']()
        return json.dumps(result()), '', False

    monkeypatch.setattr(tool_process, 'run_local_process', run)
    return SimpleNamespace(probe=p, log=log, calls=calls, tool_process=tool_process)


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_shared_supervised_runner_defers_actual_tool_logs_until_review(supervised, guard, mode):
    p = supervised.probe
    job = p.admit(mode=mode)
    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {job['adapter']: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'failed' and saved['result']['completion'] == 'completed'
    assert saved['result']['error_code'] == 'prompt_injection_detected'
    assert len(supervised.calls) == len(guard.scans) == 1
    assert PRIVATE not in supervised.log.log_file.read_text()
    assert len(supervised.log.log_file.read_text().splitlines()) == 1
    assert p.store.counts()['reserved'] == 0 and not worker.run_once()


def test_restricted_supervised_child_does_not_gain_scanner_credentials(supervised, guard):
    p = supervised.probe
    p.runner = LocalSkillRunner(p.root, {NAME: p.runner.bindings[NAME]}, child_environment_policies={
        NAME: {'always': {'FIXTURE_OUTPUT_ROOT', 'FIXTURE_TOKEN'}, 'if_true': {}},
    })
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    assert TaskWorker(p.store, {job['adapter']: p.runner}).run_once()
    assert guard.scans[0][3] == 'scanner-secret-cloud'
    child = supervised.calls[0]['tool_env']
    assert not any('PROMPT_GUARD' in key for key in child)


def test_supervised_ambiguous_remote_failure_still_reserves_capacity(supervised, guard, monkeypatch):
    p = supervised.probe

    def run(*_args, **kwargs):
        supervised.calls.append(kwargs)
        kwargs['process_started'](12345)
        kwargs['process_stopped']()
        return json.dumps(result(ok=False)), '', False

    monkeypatch.setattr(supervised.tool_process, 'run_local_process', run)
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {job['adapter']: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    remote = job['adapter'] == REMOTE_ADAPTER
    assert saved['state'] == ('needs_attention' if remote else 'failed')
    assert saved['result']['completion'] == 'unknown'
    assert saved['result']['error_code'] == 'prompt_injection_detected'
    assert p.store.counts()['reserved'] == int(remote)
    assert PRIVATE not in supervised.log.log_file.read_text()
    assert not worker.run_once() and len(supervised.calls) == len(guard.scans) == 1


@pytest.mark.parametrize('available', [True, False])
def test_supervised_clean_or_unavailable_scan_preserves_existing_diagnostics(supervised, guard, monkeypatch, available):
    p = supervised.probe
    verdict = (PromptGuardResult('scanned', flagged=False) if available
               else PromptGuardResult('unknown', 'timeout'))
    monkeypatch.setattr(observer, 'scan_text', lambda *_args, **_kwargs: verdict)
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {job['adapter']: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'succeeded' and saved['result'] == result()
    assert PRIVATE in supervised.log.log_file.read_text()
    assert len(supervised.log.log_file.read_text().splitlines()) == 1
    assert not worker.run_once() and len(supervised.calls) == 1
    assert not guard.evidence


def test_unbounded_original_failure_is_reviewed_before_storage_excerpt(supervised, guard, monkeypatch):
    p = supervised.probe
    # Lower the storage helper's cap so this small synthetic result exercises
    # its real bounded_failure path while still fitting the scanner's budget.
    from lib.background_tasks import local_skill

    monkeypatch.setattr(local_skill, 'MAX_RESULT_BYTES', 100)
    raw = result(ok=False, completion='completed', error='x' * 200 + PRIVATE)

    def run(*_args, **kwargs):
        supervised.calls.append(kwargs)
        return json.dumps(raw), '', False

    monkeypatch.setattr(supervised.tool_process, 'run_local_process', run)
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    assert TaskWorker(p.store, {job['adapter']: p.runner}).run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['error_code'] == 'prompt_injection_detected'
    assert guard.evidence[0]['result'] == raw
    assert 'Diagnostics were truncated' not in guard.evidence[0]['text']
    assert PRIVATE not in supervised.log.log_file.read_text()


@pytest.mark.parametrize('outcome', ['success', 'completed_failure', 'rejected_failure'])
def test_scan_deadline_race_keeps_incident_without_restoring_execution_ownership(
        supervised, guard, monkeypatch, outcome):
    p = supervised.probe
    raw = result()
    if outcome != 'success':
        raw.update(ok=False, completion='completed' if outcome == 'completed_failure' else 'rejected')

    def run(*_args, **kwargs):
        supervised.calls.append(kwargs)
        kwargs['process_started'](12345)
        kwargs['process_stopped']()
        return json.dumps(raw), '', False

    monkeypatch.setattr(supervised.tool_process, 'run_local_process', run)
    job = p.admit()
    p.store.release(job['id'], receipt(job))
    clock = [p.store.clock()]
    monkeypatch.setattr(p.store, 'clock', lambda: clock[0])

    def scan(text, **source):
        clock[0] = job['deadline'] + 1
        return guard.scan(text, **source)

    monkeypatch.setattr(observer, 'scan_text', scan)
    worker = TaskWorker(p.store, {job['adapter']: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    remote = job['adapter'] == REMOTE_ADAPTER
    assert saved['state'] == ('needs_attention' if remote else 'failed')
    assert saved['result']['error_code'] == 'prompt_injection_detected'
    assert saved['result']['data']['prompt_guard']['incident_id'] == INCIDENT
    assert saved['result']['data']['prompt_guard']['evidence_saved'] is True
    assert saved['result']['terminal_failure'] is True and saved['result']['retry_safe'] is False
    assert p.store.counts()['reserved'] == int(remote)
    assert len(p.store.pending_deliveries()) == 1
    assert PRIVATE not in json.dumps(saved['result'])
    assert PRIVATE not in supervised.log.log_file.read_text()
    assert not worker.run_once() and len(supervised.calls) == len(guard.scans) == 1
