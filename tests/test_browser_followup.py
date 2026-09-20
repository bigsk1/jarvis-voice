"""Browser follow-up references stay bound to the original Web conversation."""

import pytest
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from lib.background_tasks.browser_followup import prior_browser_job
from lib.background_tasks.admission import BackgroundAdmissionService, WebTaskContext
from lib.background_tasks.local_contract import REMOTE_ADAPTER
from lib.background_tasks.models import Admission, AdmissionDenied
from lib.background_tasks.store import TaskStore


class Store:
    def __init__(self, job):
        self.job = job

    def get(self, reference):
        return self.job if reference == self.job['id'] else None


def prior(tool='browser_use_cloud', *, state='succeeded', conversation='conversation-1',
          generation=1, use_profile=False):
    return {
        'id': 'a' * 32, 'conversation_id': conversation, 'generation': generation,
        'state': state, 'admission': {'tool': tool, 'arguments': {
            'task': 'Original research', 'url': 'https://example.com',
            'use_profile': use_profile,
        }}, 'result': {'data': {'run_id': '3c90c3cc-0d44-4b50-8888-8dd25736052a'}},
    }


@pytest.mark.parametrize('change', [
    {'conversation_id': 'other'}, {'generation': 2}, {'tool': 'browser_use'},
])
def test_rejects_cross_conversation_generation_or_provider(change):
    job = prior()
    current = {'id': 'b' * 32, 'conversation_id': 'conversation-1',
               'generation': 1, 'tool': 'browser_use_cloud'}
    current.update(change)
    with pytest.raises(AdmissionDenied):
        prior_browser_job(Store(job), current, {'continue_job_id': job['id']})


def test_cloud_followup_requires_finished_run_and_same_profile_setting():
    current = {'id': 'b' * 32, 'conversation_id': 'conversation-1',
               'generation': 1, 'tool': 'browser_use_cloud'}
    job = prior(state='running', use_profile=True)
    with pytest.raises(AdmissionDenied, match='finished'):
        prior_browser_job(Store(job), current,
                          {'continue_job_id': job['id'], 'use_profile': True})
    job['state'] = 'succeeded'
    with pytest.raises(AdmissionDenied, match='profile'):
        prior_browser_job(Store(job), current,
                          {'continue_job_id': job['id'], 'use_profile': False})
    assert prior_browser_job(Store(job), current, {'continue_job_id': job['id']}) is job
    assert prior_browser_job(Store(job), current,
                             {'continue_job_id': job['id'], 'use_profile': True}) is job
    job['result']['data']['browser_stop_verified'] = False
    with pytest.raises(AdmissionDenied, match='shutdown'):
        prior_browser_job(Store(job), current,
                          {'continue_job_id': job['id'], 'use_profile': True})


def test_local_followup_requires_finished_job_but_no_provider_run():
    current = {'id': 'b' * 32, 'conversation_id': 'conversation-1',
               'generation': 1, 'tool': 'browser_use'}
    job = prior(tool='browser_use', state='running')
    with pytest.raises(AdmissionDenied, match='finished'):
        prior_browser_job(Store(job), current, {'continue_job_id': job['id']})
    job['state'] = 'failed'
    job['result'] = {'speech': 'Partial report'}
    assert prior_browser_job(Store(job), current, {'continue_job_id': job['id']}) is job


def test_web_admission_inherits_profile_before_storing_followup_arguments():
    previous = prior(use_profile=True)
    stored = []

    class AdmissionStore(Store):
        def admit(self, admission, *, authorization=None):
            stored.append(admission)
            return {'id': 'b' * 32, 'state': 'queued', 'conversation_id': 'conversation-1',
                    'generation': 1, 'revision': 1}

    store = AdmissionStore(previous)
    service = BackgroundAdmissionService(store, adapters={'browser_use_cloud': REMOTE_ADAPTER})
    authorization = {'conversation_id': 'conversation-1', 'generation': 1,
                     'request_id': 'request-2', 'mode': 'cloud', 'source': 'web',
                     'tool_policies': {'browser_use_cloud': {'timeout_seconds': 1800}}}
    service.check_ready = lambda *_: authorization
    context = WebTaskContext(service, 'auth-2', ('browser_use_cloud',),
                             authorization=authorization)
    schema = SimpleNamespace(background_adapter=REMOTE_ADAPTER)
    receipt = service._admit(context, 'browser_use_cloud',
                             {'task': 'Proceed', 'continue_job_id': previous['id']},
                             'call-2', schema)
    assert receipt['status'] == 'accepted'
    assert stored[0].arguments['use_profile'] is True


def test_cloud_followup_admission_serializes_successors_and_allows_known_rejection(tmp_path):
    store = TaskStore(tmp_path / 'tasks.db')
    store.initialize()
    store.configure(background_enabled=True, background_tools=['browser_use_cloud'])

    def make_admission(index, previous=None):
        return Admission(conversation_id='conversation-1', generation=1,
                         request_id=f'request-{index}', invocation_id=f'call-{index}',
                         tool='browser_use_cloud', adapter='local_fixture', mode='cloud',
                         arguments={'task': 'Continue', **({'continue_job_id': previous}
                                                          if previous else {})},
                         authorization_id=f'auth-{index}', source='web')

    previous = store.admit(make_admission(0))

    def admit(index):
        try:
            return TaskStore(store.path).admit(make_admission(index, previous['id']))
        except AdmissionDenied as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(admit, (1, 2)))
    accepted = [item for item in outcomes if isinstance(item, dict)]
    denied = [item for item in outcomes if isinstance(item, str)]
    assert len(accepted) == len(denied) == 1
    assert 'already has a follow-up' in denied[0]
    winner = 1 if isinstance(outcomes[0], dict) else 2
    assert store.admit(make_admission(winner, previous['id']))['id'] == accepted[0]['id']

    with store._connection(write=True) as conn:
        conn.execute('UPDATE jobs SET state=?, result_json=? WHERE id=?',
                     ('failed', json.dumps({'ok': False, 'completion': 'rejected'}),
                      accepted[0]['id']))
    retry = store.admit(make_admission(3, previous['id']))
    with store._connection(write=True) as conn:
        conn.execute('UPDATE jobs SET state=?, result_json=? WHERE id=?',
                     ('succeeded', json.dumps({'ok': True, 'completion': 'completed',
                                               'data': {'browser_stop_verified': False}}),
                      retry['id']))
    with pytest.raises(AdmissionDenied, match='already has a follow-up'):
        store.admit(make_admission(4, previous['id']))
