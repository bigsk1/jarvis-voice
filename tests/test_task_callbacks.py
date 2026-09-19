"""Isolated callback control, cryptography and durable state tests."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from lib.background_tasks import Admission, ReceiptEvidence, TaskError, TaskStore
from lib.webhook_integrations.contracts import ADAPTER, CallbackError, signature
from lib.webhook_integrations.service import IntegrationService


def headers(service, source, credential, raw, capability=None):
    timestamp = str(int(service.store.clock()))
    value = {'Content-Type': 'application/json', 'X-Jarvis-Timestamp': timestamp}
    if credential['scheme'] == 'bearer':
        value['Authorization'] = credential['authorization']
    else:
        value['X-Jarvis-Key-Id'] = credential['id']
        value['X-Jarvis-Signature'] = signature(credential['secret'], source['id'], timestamp, raw)
    if capability:
        value['X-Jarvis-Task-Capability'] = capability
    return value


def configured(tmp_path, *, scheme='bearer', clock=None):
    now = [1000.]
    store = TaskStore(tmp_path / 'tasks.db', clock=clock or (lambda: now[0]))
    store.initialize()
    store.configure(background_enabled=True, background_tools=['callback_probe'])
    service = IntegrationService(store)
    service.initialize_key()
    source = service.create_source(name='Local fixture', callback_base='http://127.0.0.1:8880',
                                   submit_url='http://127.0.0.1:9001/submit')
    credential = service.create_credential(source['id'], scheme=scheme)
    source = service.update_source(source['id'], source['revision'], enabled=True)
    service.configure(True)
    probe = service.create_credential(source['id'], expires_in=60, probe=True)
    raw = json.dumps({'schema_version': 1, 'event_id': 'setup', 'type': 'integration.test'}).encode()
    service.accept(source['id'], raw, headers(service, source, probe, raw))
    return service, source, credential, now


@pytest.mark.parametrize('changed_url', [
    'https://other.private.ts.net/submit',
    'http://127.0.0.1:9002/submit?bad=1',
])
def test_reviewed_remote_submit_is_exact_and_cannot_be_set_by_generic_source_controls(
    tmp_path, monkeypatch, changed_url,
):
    from lib.background_tasks.worker import AwaitingCallback, KnownFailure
    from lib.webhook_integrations import runner as callback_runner
    from lib.webhook_integrations.runner import LocalCallbackRunner

    service, source, _, _ = configured(tmp_path)
    reviewed = 'https://bridge.private.ts.net/submit'
    with pytest.raises(TaskError):
        service.create_source(name='Unreviewed remote', callback_base='http://127.0.0.1:8880',
                              submit_url=reviewed)
    source = service.update_source(source['id'], source['revision'], submit_url=reviewed,
                                   _reviewed_submit_url=reviewed)
    with pytest.raises(TaskError, match='reviewed binding'):
        service.update_source(source['id'], source['revision'],
                              submit_url='https://other.private.ts.net/submit',
                              _reviewed_submit_url=reviewed)
    with service.store._connection(write=True) as conn:
        conn.execute('UPDATE task_integrations SET validated_revision=revision WHERE id=?', (source['id'],))

    def claim(invocation):
        authorization = {'source': 'web', 'conversation_id': 'conversation', 'generation': 0,
                         'request_id': invocation, 'mode': 'cloud', 'selected': ['callback_probe'],
                         'callback_sources': {'callback_probe': source['id']}}
        job = service.store.admit(Admission('conversation', 0, invocation, invocation,
            'callback_probe', ADAPTER, 'cloud', {}, 'authorization-' + invocation, 'web'),
            authorization=authorization)
        service.store.release(job['id'], ReceiptEvidence('conversation', 0, invocation,
                                                         'receipt-' + invocation, 'completed', True))
        claimed = service.store.claim('test-worker', {ADAPTER})
        service.store.running(claimed)
        return claimed

    sent = []
    monkeypatch.setattr(callback_runner, 'post_json', lambda url, body, **kwargs:
                        (sent.append(url) or {'remote_id': 'remote-1'}))
    adapter = LocalCallbackRunner(service, {'callback_probe': (source['id'],
        {'type': 'object', 'properties': {}, 'additionalProperties': False})},
        prepare=lambda _: ({}, {}, reviewed))
    assert isinstance(adapter(SimpleNamespace(claim=claim('first'), checkpoint=lambda: None)), AwaitingCallback)
    assert sent == [reviewed]

    with service.store._connection(write=True) as conn:
        conn.execute('UPDATE task_integrations SET submit_url=? WHERE id=?',
                     (changed_url, source['id']))
    with pytest.raises(KnownFailure):
        adapter(SimpleNamespace(claim=claim('second'), checkpoint=lambda: None))
    assert sent == [reviewed]


def test_callback_worker_finds_a_reviewed_source_added_after_startup(tmp_path, monkeypatch):
    from lib.background_tasks.production import worker_adapters
    from lib.webhook_integrations import browser

    store = TaskStore(tmp_path / 'new-source.db')
    store.initialize()
    sources = {}
    monkeypatch.setattr(browser, 'callback_sources', lambda _: dict(sources))
    runner = worker_adapters(store)[ADAPTER]
    assert 'browser_use' not in runner.binding_loader()
    sources['browser_use'] = 'f' * 32
    assert runner.binding_loader()['browser_use'][0] == 'f' * 32


def bound(service, source, *, invocation='call'):
    payload = dict(source='web', conversation_id='conversation', generation=0, request_id='request', mode='cloud',
                   selected=['callback_probe'], callback_sources={'callback_probe': source['id']})
    job = service.store.admit(Admission('conversation', 0, 'request', invocation, 'callback_probe', ADAPTER,
                                       'cloud', {}, 'authorization-' + invocation, 'web'), authorization=payload)
    service.store.release(job['id'], ReceiptEvidence('conversation', 0, 'request', 'receipt', 'completed', True))
    claim = service.store.claim('test-worker', {ADAPTER})
    service.store.running(claim)
    submission = service.prepare_submission(claim, source['id'])
    return claim, submission


def event(claim, *, event_id='completion', kind='task.completed', summary='Finished'):
    body = dict(schema_version=1, event_id=event_id, job_id=claim.job_id, attempt_id=claim.attempt_id, type=kind)
    body['progress' if kind == 'task.progress' else 'result'] = (
        {'phase': 'Working', 'percent': 20} if kind == 'task.progress' else {'summary': summary, 'artifacts': []})
    return json.dumps(body).encode()


def deliver(service, source, credential, submission, raw):
    return service.accept(source['id'], raw, headers(service, source, credential, raw, submission['callback_capability']))


@pytest.mark.parametrize('scheme', ['bearer', 'hmac-sha256'])
def test_credentials_are_shown_once_and_encrypted_values_are_bound_to_identity(tmp_path, scheme):
    service, source, credential, _ = configured(tmp_path, scheme=scheme)
    assert credential['secret'] not in json.dumps(service.status())
    with service.store._connection() as conn:
        row = conn.execute('SELECT * FROM task_credentials WHERE id=?', (credential['id'],)).fetchone()
    assert credential['secret'] not in str(dict(row))
    assert oct(service.keys.path.stat().st_mode & 0o777) == '0o600'
    if scheme == 'hmac-sha256':
        assert service.keys.decrypt(row['encrypted'], source['id'], row['id'], row['version']) == credential['secret']
        with pytest.raises(TaskError):
            service.keys.decrypt(row['encrypted'], 'other-source', row['id'], row['version'])
        envelope = json.loads(row['encrypted'])
        envelope['value'] = envelope['value'][:-4] + 'AAAA'
        with pytest.raises(TaskError):
            service.keys.decrypt(json.dumps(envelope), source['id'], row['id'], row['version'])


def test_missing_wrong_or_open_key_fails_closed_and_rotation_preserves_secrets(tmp_path):
    service, source, credential, _ = configured(tmp_path, scheme='hmac-sha256')
    old_key = service.keys.path.read_bytes()
    service.rotate_key()
    assert service.keys.path.read_bytes() != old_key
    assert len(service.keys.read()['keys']) == 1
    claim, submission = bound(service, source)
    raw = event(claim)
    deliver(service, source, credential, submission, raw)
    os.chmod(service.keys.path, 0o644)
    with pytest.raises(TaskError):
        service.keys.read()
    os.chmod(service.keys.path, 0o600)
    service.keys.path.unlink()
    with pytest.raises(TaskError, match='restore the original'):
        service.initialize_key()
    assert not service.keys.path.exists()
    with pytest.raises(TaskError):
        deliver(service, source, credential, submission, raw)


@pytest.mark.parametrize('scheme', ['bearer', 'hmac-sha256'])
def test_early_completion_survives_worker_loss_and_commits_result_outbox_once(tmp_path, scheme):
    service, source, credential, now = configured(tmp_path, scheme=scheme)
    claim, submission = bound(service, source)
    raw = event(claim)
    assert not deliver(service, source, credential, submission, raw)['duplicate']
    now[0] += 31  # No heartbeat. Callback handoff owns completion, not the dead worker.
    service.store.reconcile()
    assert service.store.get(claim.job_id)['state'] == 'running'
    restarted = IntegrationService(TaskStore(service.store.path, clock=service.store.clock))
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(lambda _: restarted.drain(), range(2))) == 1
    assert restarted.store.get(claim.job_id)['state'] == 'succeeded'
    service.record_submission(claim, 'late-submit-receipt')
    assert deliver(service, source, credential, submission, raw)['duplicate']
    with pytest.raises(CallbackError, match='different content'):
        deliver(service, source, credential, submission, event(claim, summary='Changed'))
    deliver(service, source, credential, submission, event(claim, event_id='distinct-duplicate'))
    deliver(service, source, credential, submission, event(claim, event_id='late-progress', kind='task.progress'))
    service.drain()
    with service.store._connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 1
    assert service.store.get(claim.job_id)['progress'] is None


def test_receiver_disable_drains_but_source_disable_and_revocation_hold(tmp_path):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    raw = event(claim)
    deliver(service, source, credential, submission, raw)
    service.configure(False)
    assert deliver(service, source, credential, submission, raw)['duplicate']
    with pytest.raises(CallbackError) as error:
        deliver(service, source, credential, submission, event(claim, event_id='new-while-disabled'))
    assert error.value.status == 503
    source = service.update_source(source['id'], source['revision'], enabled=False)
    assert service.drain() == 0
    source = service.update_source(source['id'], source['revision'], enabled=True)
    assert service.drain() == 1
    assert service.store.get(claim.job_id)['state'] == 'succeeded'
    service.configure(True)
    second, submission = bound(service, source, invocation='second')
    deliver(service, source, credential, submission, event(second, event_id='second-completion'))
    service.revoke_credential(source['id'], credential['id'])
    assert service.drain() == 0
    assert service.deliveries(source['id'])['deliveries'][0]['reason'] == 'credential_revoked'


def test_acknowledged_callback_cancel_is_card_only_and_stays_terminal(tmp_path):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    raw = event(claim, event_id='cancel-before-request', kind='task.cancelled')
    deliver(service, source, credential, submission, raw)
    service.drain()
    assert service.deliveries(source['id'])['deliveries'][0]['reason'] == 'cancellation_not_requested'
    assert service.store.get(claim.job_id)['state'] == 'running'
    assert not service.store.pending_deliveries()
    # Exercise a future reviewed adapter's acknowledged cancel, without enabling
    # cancellation for the currently advertised production adapters.
    job = service.store.get(claim.job_id)
    service.store.request_cancel(job['id'], job['revision'], supported_adapters={ADAPTER})
    raw = event(claim, event_id='cancel-ack', kind='task.cancelled', summary='Remote cancellation confirmed.')
    deliver(service, source, credential, submission, raw)
    service.drain()
    job = service.store.get(claim.job_id)
    assert job['state'] == 'cancelled' and job['result']['cancelled'] is True
    assert job['delivery_state'] == 'suppressed'
    assert service.store.counts()['running'] == 0
    assert not service.store.pending_deliveries()
    deliver(service, source, credential, submission, event(claim, event_id='late-success'))
    service.drain()
    assert service.deliveries(source['id'])['deliveries'][0]['state'] == 'late'
    with service.store._connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 1
    assert service.store.get(claim.job_id)['state'] == 'cancelled'


@pytest.mark.parametrize('received', ['', 'not-hex', 'g' * 64, 'é' * 64])
def test_invalid_hmac_formats_compare_but_never_authenticate(tmp_path, monkeypatch, received):
    from lib.webhook_integrations import credentials
    service, source, credential, _ = configured(tmp_path, scheme='hmac-sha256')
    claim, submission = bound(service, source)
    raw = event(claim)
    auth = headers(service, source, credential, raw, submission['callback_capability'])
    auth['X-Jarvis-Signature'] = received
    comparisons = []
    compare = credentials.hmac.compare_digest
    def observed(left, right):
        comparisons.append((left, right))
        return compare(left, right)
    monkeypatch.setattr(credentials.hmac, 'compare_digest', observed)
    monkeypatch.setattr(credentials, 'signature', lambda *args: '0' * 64)
    with pytest.raises(CallbackError) as error:
        service.accept(source['id'], raw, auth)
    assert error.value.status == 401
    assert comparisons == [('0' * 64, '0' * 64)]


def test_result_and_inbox_application_roll_back_with_outbox_failure(tmp_path):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    deliver(service, source, credential, submission, event(claim))
    with service.store._connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'test disk failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        service.drain()
    assert service.store.get(claim.job_id)['result'] is None
    assert service.deliveries(source['id'])['deliveries'][0]['state'] == 'pending'
    with service.store._connection(write=True) as conn:
        conn.execute('DROP TRIGGER fail_outbox')
    assert service.drain() == 1


@pytest.mark.parametrize('field,value', [('attempt_id', 'wrong-attempt'), ('job_id', 'other-job'),
                                         ('conversation_id', 'forged'), ('provider', 'forged')])
def test_forged_routing_and_untrusted_artifacts_cannot_reach_a_job(tmp_path, field, value):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    body = json.loads(event(claim))
    body[field] = value
    with pytest.raises(CallbackError):
        deliver(service, source, credential, submission, json.dumps(body).encode())
    body = json.loads(event(claim))
    body['result']['artifacts'] = ['http://127.0.0.1/private', 'stash://other/file', '<svg/onload=alert(1)>']
    with pytest.raises(CallbackError):
        deliver(service, source, credential, submission, json.dumps(body).encode())
    body = json.loads(event(claim))
    body['result']['presentation'] = {
        'kind': 'browser_research', 'stash_ref': 'stash://space/report',
        'sources': ['https://example.com/'], 'provider': 'ollama', 'model': 'test',
    }
    with pytest.raises(CallbackError) as error:
        deliver(service, source, credential, submission, json.dumps(body).encode())
    assert error.value.status == 403
    assert service.store.get(claim.job_id)['result'] is None


def test_rotated_credentials_overlap_then_expire_and_progress_is_bounded(tmp_path):
    service, source, old, now = configured(tmp_path)
    new = service.create_credential(source['id'], replace_id=old['id'], overlap_seconds=60)
    claim, submission = bound(service, source)
    deliver(service, source, old, submission, event(claim, event_id='progress1', kind='task.progress'))
    deliver(service, source, new, submission, event(claim, event_id='progress2', kind='task.progress'))
    service.drain()
    assert service.deliveries(source['id'])['deliveries'][0]['reason'] == 'progress_throttled'
    now[0] += 61
    with pytest.raises(CallbackError) as error:
        deliver(service, source, old, submission, event(claim))
    assert error.value.status == 401
    deliver(service, source, new, submission, event(claim))
    service.drain()
    assert service.store.get(claim.job_id)['state'] == 'succeeded'


def test_deadline_and_disposal_fence_late_results_and_never_replay(tmp_path):
    service, source, credential, now = configured(tmp_path)
    claim, submission = bound(service, source)
    now[0] += 901
    service.store.reconcile()
    assert service.store.get(claim.job_id)['state'] == 'needs_attention'
    deliver(service, source, credential, submission, event(claim))
    service.drain()
    assert service.deliveries(source['id'])['deliveries'][0]['state'] == 'late'
    assert service.store.claim('other-worker', {ADAPTER}) is None


@pytest.mark.parametrize('action', ['clear', 'delete', 'cancel'])
def test_disposal_and_verified_cancellation_do_not_reopen_on_completion(tmp_path, action):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    if action == 'cancel':
        job = service.store.get(claim.job_id)
        service.store.request_cancel(job['id'], job['revision'], supported_adapters={ADAPTER})
        service.store.acknowledge_cancel(claim, 'Fixture service confirms remote execution stopped.')
    else:
        service.store.fence_conversation('conversation', 0, action, dispose=True)
    deliver(service, source, credential, submission, event(claim))
    service.drain()
    assert service.deliveries(source['id'])['deliveries'][0]['state'] == 'late'
    assert not service.store.pending_deliveries()


def test_wrong_source_capability_timestamp_and_duplicate_json_fail_closed(tmp_path):
    service, source, credential, _ = configured(tmp_path, scheme='hmac-sha256')
    claim, submission = bound(service, source)
    raw = event(claim)
    for changes in ({'X-Jarvis-Task-Capability': 'wrong'}, {'X-Jarvis-Timestamp': '0'},
                    {'X-Jarvis-Signature': 'not-a-signature'}):
        with pytest.raises(CallbackError):
            service.accept(source['id'], raw, {**headers(service, source, credential, raw, submission['callback_capability']), **changes})
    other = service.create_source(name='Other', callback_base='http://127.0.0.1:8880', submit_url='http://127.0.0.1:9002/submit')
    other = service.update_source(other['id'], other['revision'], enabled=True)
    other_credential = service.create_credential(other['id'])
    with pytest.raises(CallbackError):
        deliver(service, other, other_credential, submission, raw)
    malformed = raw[:-1] + b',"event_id":"repeated"}'
    with pytest.raises(CallbackError):
        deliver(service, source, credential, submission, malformed)
    assert service.deliveries(source['id'])['total'] == 1  # Inert setup only.


def test_confirmed_callback_failure_releases_capacity_and_stores_one_result(tmp_path):
    service, source, credential, _ = configured(tmp_path)
    service.store.configure(max_running=1)
    claim, submission = bound(service, source)
    deliver(service, source, credential, submission, event(claim, kind='task.failed', summary='Service rejected this request.'))
    service.drain()
    job = service.store.get(claim.job_id)
    assert job['state'] == 'failed' and job['result']['ok'] is False
    assert service.store.counts()['reserved'] == 0
    assert service.store.counts()['running'] == 0
    assert len(service.store.pending_deliveries()) == 1


@pytest.mark.parametrize('kind,ok,state', [
    ('task.completed', True, 'succeeded'),
    ('task.failed', False, 'failed'),
])
def test_browser_callback_preserves_only_its_reviewed_presentation(tmp_path, kind, ok, state):
    service, source, credential, _ = configured(tmp_path)
    service.store.configure(background_tools=['browser_use'])
    admission = dict(source='web', conversation_id='conversation', generation=0,
                     request_id='request', mode='cloud', selected=['browser_use'],
                     callback_sources={'browser_use': source['id']})
    job = service.store.admit(Admission('conversation', 0, 'request', 'browser-call',
        'browser_use', ADAPTER, 'cloud', {}, 'browser-authorization', 'web'), authorization=admission)
    service.store.release(job['id'], ReceiptEvidence('conversation', 0, 'request',
                                                     'receipt', 'completed', True))
    claim = service.store.claim('browser-worker', {ADAPTER})
    service.store.running(claim)
    submission = service.prepare_submission(claim, source['id'])
    body = json.loads(event(claim, kind=kind,
                            summary='Saved research: stash://space/report\n\nFull report'))
    body['result']['presentation'] = {
        'kind': 'browser_research', 'stash_ref': 'stash://space/report',
        'sources': ['https://example.com/source'], 'provider': 'ollama', 'model': 'selected',
    }
    raw = json.dumps(body).encode()
    deliver(service, source, credential, submission, raw)
    assert service.drain() == 1
    saved = service.store.get(claim.job_id)
    assert saved['state'] == state
    result = saved['result']
    assert result['ok'] is ok
    assert result['data']['browser_research'] == body['result']['presentation']


def test_bad_optional_browser_presentation_drops_card_but_preserves_summary_and_identity(tmp_path):
    service, source, credential, _ = configured(tmp_path)
    service.store.configure(background_tools=['browser_use'])
    job = service.store.admit(Admission('conversation', 0, 'request', 'browser-call',
        'browser_use', ADAPTER, 'cloud', {}, 'browser-authorization', 'web'), authorization={
            'source': 'web', 'conversation_id': 'conversation', 'generation': 0,
            'request_id': 'request', 'mode': 'cloud', 'selected': ['browser_use'],
            'callback_sources': {'browser_use': source['id']},
        })
    service.store.release(job['id'], ReceiptEvidence('conversation', 0, 'request',
                                                     'receipt', 'completed', True))
    claim = service.store.claim('browser-worker', {ADAPTER})
    service.store.running(claim)
    submission = service.prepare_submission(claim, source['id'])
    body = json.loads(event(claim, summary='Observed text survives invalid decoration'))
    body['result']['presentation'] = {
        'kind': 'browser_research', 'stash_ref': 'stash://space/report',
        'sources': [None], 'provider': 'ollama', 'model': 'selected',
    }
    raw = json.dumps(body).encode()
    assert not deliver(service, source, credential, submission, raw)['duplicate']
    assert deliver(service, source, credential, submission, raw)['duplicate']
    altered = json.loads(raw)
    altered['result']['presentation']['sources'] = [42]
    with pytest.raises(CallbackError, match='different content'):
        deliver(service, source, credential, submission, json.dumps(altered).encode())
    assert service.drain() == 1
    result = service.store.get(claim.job_id)['result']
    assert result['ok'] and result['speech'] == 'Observed text survives invalid decoration'
    assert result['data'] == {}


@pytest.mark.parametrize('failure', ['receiver', 'source', 'credential', 'route', 'key'])
def test_unready_callback_path_denies_admission_before_receipt(tmp_path, failure):
    service, source, credential, _ = configured(tmp_path)
    if failure == 'receiver':
        service.configure(False)
    elif failure == 'source':
        service.update_source(source['id'], source['revision'], enabled=False)
    elif failure == 'credential':
        service.revoke_credential(source['id'], credential['id'])
    elif failure == 'route':
        service.update_source(source['id'], source['revision'], submit_url='http://127.0.0.1:9002/submit')
    else:
        service.keys.path.unlink()
    with pytest.raises(TaskError):
        bound(service, source)
    assert service.store.conversation_jobs() == []


def test_callback_source_authorization_is_trusted_and_shared_across_one_turn(tmp_path):
    from types import SimpleNamespace

    from lib.background_tasks.admission import BackgroundAdmissionService
    service, source, _, _ = configured(tmp_path)
    service.store.configure(background_tools=['callback_probe', 'inert'])
    service.store.touch_worker('worker', {ADAPTER, 'local_fixture'})
    schemas = {'callback_probe': SimpleNamespace(background_adapter=ADAPTER, parameters={'type': 'object'}),
               'inert': SimpleNamespace(background_adapter='local_fixture')}
    registry = SimpleNamespace(list_tools=lambda: list(schemas), get_tool=schemas.get)
    admission = BackgroundAdmissionService(service.store, adapters={'callback_probe': ADAPTER, 'inert': 'local_fixture'},
        callback_sources={'callback_probe': source['id']}, ready=lambda: True, validate_source=lambda payload: True)
    payload = {'source': 'web', 'selected': list(schemas), 'tool_policy': 'auto', 'conversation_id': 'conversation',
               'generation': 0, 'request_id': 'request', 'mode': 'cloud', 'callback_sources': {'callback_probe': 'forged'}}
    context = admission.authorize(payload, registry)
    context.admit('inert', {}, 'first', schemas['inert'])
    context.admit('callback_probe', {}, 'second', schemas['callback_probe'])
    assert len(service.store.conversation_jobs()) == 2
    assert service.status()['sources'][0]['outstanding'] == 1  # Includes held, not-yet-submitted work.
    assert service.store.authorization(context.authorization_id)['callback_sources'] == {'callback_probe': source['id']}
    for caller in ['api', 'voice', 'workflow', 'scheduled']:
        with pytest.raises(TaskError):
            admission.authorize({**payload, 'source': caller}, registry)
