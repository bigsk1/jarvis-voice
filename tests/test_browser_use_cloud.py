"""Browser Use Cloud V4 wire and one-submit outcome rules, without live billing."""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = '3c90c3cc-0d44-4b50-8888-8dd25736052a'
SESSION_ID = '1b4c92da-331a-49f3-a03d-49212ec6b7a7'
BROWSER_ID = '53177fb2-8457-44d7-b534-fc5d79caaf33'
WORKSPACE_ID = '8347ae0d-49de-41b7-ae48-2a6930be4c7b'
SPEC = importlib.util.spec_from_file_location('browser_use_cloud', ROOT / 'skills/browser_use_cloud.py')
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload


class Session:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        expected_method, expected_suffix, response = self.steps.pop(0)
        assert (method, url.endswith(expected_suffix)) == (expected_method, True)
        assert kwargs['allow_redirects'] is False
        if isinstance(response, Exception):
            raise response
        return response


def created():
    return Response({'id': RUN_ID, 'sessionId': SESSION_ID, 'status': 'queued'})


def no_active_browsers():
    return ('GET', '/browsers', Response({'items': [], 'totalItems': 0}))


def active_browser():
    return ('GET', '/browsers', Response({'items': [{
        'id': BROWSER_ID, 'agentSessionId': SESSION_ID, 'status': 'active',
    }], 'totalItems': 1}))


@pytest.fixture(autouse=True)
def config(monkeypatch):
    values = {'BROWSER_USE_API_KEY': 'test-key', 'JARVIS_BACKGROUND_DEADLINE': str(time.time() + 120)}
    monkeypatch.setattr(cloud, 'get_config_value', lambda name, default='': values.get(name, default))
    return values


def test_completed_run_publishes_live_link_and_archives_full_report(monkeypatch, config):
    config['BROWSER_USE_CLOUD_PROFILE_ID'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    report = '# Findings\n\n' + 'Verified source. ' * 2500
    archived = []
    monkeypatch.setattr(cloud, '_archive', lambda task, full: archived.append((task, full)) or 'stash://space/report')
    viewer = 'https://live.browser-use.com?token=private'
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': [{'id': 2, 'type': 'browser.ready',
            'data': {'live_view_url': viewer}}], 'hasMore': False})),
        ('GET', '/status', Response({'status': 'running'})),
        ('GET', '/status', Response({'status': 'completed'})),
        active_browser(),
        ('PATCH', f'/browsers/{BROWSER_ID}', Response({'id': BROWSER_ID, 'status': 'stopped'})),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
            'result': report, 'model': 'hosted-model', 'totalCostUsd': '0.153'})),
        ('GET', '/browsers', Response({'items': [{
            'id': BROWSER_ID, 'agentSessionId': SESSION_ID, 'status': 'stopped',
            'browserCost': '0.001', 'proxyCost': '0.096',
        }], 'totalItems': 1})),
    ])
    updates = []
    result = cloud.run({'task': 'Research this'}, session=session, sleep=lambda _: None, progress=updates.append)
    assert result['ok'] is True
    assert result['data']['browser_research']['stash_ref'] == 'stash://space/report'
    assert result['data']['browser_research']['model'] == 'hosted-model'
    assert result['data']['browser_research']['cost_usd'] == {
        'run': '0.153', 'browser': '0.001', 'proxy': '0.096', 'total': '0.250',
    }
    assert '[Report truncated in chat' in result['speech']
    assert archived == [('Research this', report.strip())]
    assert any(update.get('live_view_url') == viewer for update in updates)
    assert [call[0] for call in session.calls].count('POST') == 1
    assert session.calls[0][2]['json'] == {'task': 'Research this', 'maxCostUsd': 3.0}
    browser_calls = [call for call in session.calls if '/browsers' in call[1]]
    assert browser_calls[0][2]['params']['agentSessionId'] == SESSION_ID
    assert browser_calls[1][2]['json'] == {'action': 'stop'}
    assert result['data'].get('browser_stop_verified') is not False
    assert 'test-key' not in result['speech']


def test_explicit_profile_uses_only_the_configured_id(config, monkeypatch):
    profile_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    config['BROWSER_USE_CLOUD_PROFILE_ID'] = profile_id
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Read my account', 'use_profile': True}, session=session,
                       progress=lambda _: None)
    assert result['ok'] is True
    assert session.calls[0][2]['json'] == {
        'task': 'Read my account', 'maxCostUsd': 3.0,
        'browserSettings': {'profileId': profile_id},
    }
    assert profile_id not in json.dumps(result)
    assert result['data']['browser_research']['workspace_used'] is False


def test_configured_workspace_is_sent_on_every_run(config, monkeypatch):
    workspace_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    config['BROWSER_USE_CLOUD_WORKSPACE_ID'] = workspace_id
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Reuse files'}, session=session, progress=lambda _: None)
    assert result['ok'] is True
    assert session.calls[0][2]['json'] == {
        'task': 'Reuse files', 'maxCostUsd': 3.0, 'workspaceId': workspace_id,
    }
    assert result['data']['browser_research']['workspace_used'] is True
    assert workspace_id not in json.dumps(result)


@pytest.mark.parametrize('use_profile', [False, True])
def test_followup_uses_previous_session_with_run_cost_cap(config, monkeypatch, use_profile):
    config['BROWSER_USE_CLOUD_WORKSPACE_ID'] = WORKSPACE_ID
    if use_profile:
        config['BROWSER_USE_CLOUD_PROFILE_ID'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    monkeypatch.setenv('JARVIS_BROWSER_CONTINUE_RUN_ID', RUN_ID)
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/followup')
    next_run = '8bfbc4db-c6b4-44b8-852c-457841b9ef8e'
    session = Session([
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
                                            'sessionId': SESSION_ID, 'workspaceId': WORKSPACE_ID})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    'latestRunId': RUN_ID, 'status': 'completed'})),
        ('POST', '/runs', Response({'id': next_run, 'sessionId': SESSION_ID, 'status': 'queued'})),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    'latestRunId': next_run})),
        no_active_browsers(),
        ('GET', f'/runs/{next_run}', Response({'id': next_run, 'status': 'completed',
                                              'result': 'Follow-up done',
                                              'totalCostUsd': '0.25'})),
    ])
    result = cloud.run({'task': 'Use the address I supplied', 'continue_job_id': 'a' * 32,
                        'use_profile': use_profile},
                       session=session, progress=lambda _: None)
    assert result['ok'] is True
    expected = {
        'task': 'Use the address I supplied', 'maxCostUsd': 3.0, 'sessionId': SESSION_ID,
    }
    if use_profile:
        expected['browserSettings'] = {'profileId': config['BROWSER_USE_CLOUD_PROFILE_ID']}
    assert session.calls[2][2]['json'] == expected
    assert result['data']['run_id'] == next_run
    assert 'cost_usd' not in result['data']['browser_research']
    assert SESSION_ID not in json.dumps(result)


def test_followup_never_stops_a_newer_run_on_the_same_session(config, monkeypatch):
    monkeypatch.setenv('JARVIS_BROWSER_CONTINUE_RUN_ID', RUN_ID)
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/followup')
    next_run = '8bfbc4db-c6b4-44b8-852c-457841b9ef8e'
    newer_run = '9c315e2f-1b47-4ae5-9dda-95d8e80b56e7'
    session = Session([
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
                                            'sessionId': SESSION_ID})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    'latestRunId': RUN_ID, 'status': 'completed'})),
        ('POST', '/runs', Response({'id': next_run, 'sessionId': SESSION_ID, 'status': 'queued'})),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    'latestRunId': newer_run})),
        ('GET', f'/runs/{next_run}', Response({'id': next_run, 'status': 'completed',
                                              'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Continue', 'continue_job_id': 'a' * 32},
                       session=session, progress=lambda _: None)
    assert result['data']['browser_stop_verified'] is False
    assert all('/browsers' not in call[1] for call in session.calls)


def test_followup_rejects_unverifiable_prior_run_without_submitting(monkeypatch):
    monkeypatch.setenv('JARVIS_BROWSER_CONTINUE_RUN_ID', RUN_ID)
    session = Session([
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'running',
                                            'sessionId': SESSION_ID})),
    ])
    result = cloud.run({'task': 'Answer the question', 'continue_job_id': 'a' * 32},
                       session=session)
    assert result['completion'] == 'rejected'
    assert [call[0] for call in session.calls] == ['GET']


@pytest.mark.parametrize('session_state', [
    {'latestRunId': RUN_ID, 'status': 'running'},
    {'latestRunId': '8bfbc4db-c6b4-44b8-852c-457841b9ef8e', 'status': 'completed'},
])
def test_followup_rejects_busy_or_advanced_session_without_submitting(monkeypatch, session_state):
    monkeypatch.setenv('JARVIS_BROWSER_CONTINUE_RUN_ID', RUN_ID)
    session = Session([
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
                                            'sessionId': SESSION_ID})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    **session_state})),
    ])
    result = cloud.run({'task': 'Continue', 'continue_job_id': 'a' * 32}, session=session)
    assert result['completion'] == 'rejected'
    assert [call[0] for call in session.calls] == ['GET', 'GET']


def test_followup_busy_create_is_a_known_rejection(monkeypatch):
    monkeypatch.setenv('JARVIS_BROWSER_CONTINUE_RUN_ID', RUN_ID)
    session = Session([
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
                                            'sessionId': SESSION_ID})),
        ('GET', f'/sessions/{SESSION_ID}', Response({'sessionId': SESSION_ID,
                                                    'latestRunId': RUN_ID, 'status': 'completed'})),
        ('POST', '/runs', Response({'detail': 'Session is busy'}, status=409)),
    ])
    result = cloud.run({'task': 'Continue', 'continue_job_id': 'a' * 32}, session=session)
    assert result['completion'] == 'rejected'
    assert 'busy' in result['speech']
    assert [call[0] for call in session.calls] == ['GET', 'GET', 'POST']


def test_profile_and_workspace_can_be_used_together(config, monkeypatch):
    profile_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    workspace_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    config['BROWSER_USE_CLOUD_PROFILE_ID'] = profile_id
    config['BROWSER_USE_CLOUD_WORKSPACE_ID'] = workspace_id
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Read my account', 'use_profile': True}, session=session,
                       progress=lambda _: None)
    assert result['ok'] is True
    assert session.calls[0][2]['json'] == {
        'task': 'Read my account', 'maxCostUsd': 3.0,
        'workspaceId': workspace_id,
        'browserSettings': {'profileId': profile_id},
    }


@pytest.mark.parametrize('value', [None, '', '  '])
def test_blank_workspace_id_is_omitted(config, value, monkeypatch):
    if value is not None:
        config['BROWSER_USE_CLOUD_WORKSPACE_ID'] = value
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is True
    assert session.calls[0][2]['json'] == {'task': 'Research', 'maxCostUsd': 3.0}
    assert result['data']['browser_research']['workspace_used'] is False


def test_invalid_workspace_id_rejects_before_submit(config):
    config['BROWSER_USE_CLOUD_WORKSPACE_ID'] = 'not-a-uuid'
    session = Session([])
    result = cloud.run({'task': 'Research'}, session=session)
    assert result['ok'] is False and result['completion'] == 'rejected'
    assert session.calls == []


@pytest.mark.parametrize('value', [None, '', 'not-a-uuid'])
def test_requested_profile_must_be_configured_before_submit(config, value):
    if value is not None:
        config['BROWSER_USE_CLOUD_PROFILE_ID'] = value
    session = Session([])
    result = cloud.run({'task': 'Read my account', 'use_profile': True}, session=session)
    assert result['ok'] is False and result['completion'] == 'rejected'
    assert session.calls == []


def test_profile_selection_must_be_a_boolean():
    session = Session([])
    result = cloud.run({'task': 'Research', 'use_profile': 'true'}, session=session)
    assert result['ok'] is False and result['completion'] == 'rejected'
    assert session.calls == []


@pytest.mark.parametrize('status', [402, 422])
def test_definite_submit_rejection_is_known_and_does_not_retry(status):
    session = Session([('POST', '/runs', Response({'detail': 'denied'}, status))])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is False and result['completion'] == 'rejected'
    assert len(session.calls) == 1


def test_lost_submit_receipt_is_uncertain_and_never_resubmitted():
    session = Session([('POST', '/runs', requests.ConnectionError('connection lost'))])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['completion'] == 'unknown' and len(session.calls) == 1


def test_safe_status_get_retries_without_recreating_run(monkeypatch):
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'detail': 'rate limit'}, 429)),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, sleep=lambda _: None, progress=lambda _: None)
    assert result['ok'] is True
    assert [call[0] for call in session.calls].count('POST') == 1


def test_terminal_failure_with_partial_report_is_deliverable(monkeypatch):
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/partial')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'failed'})),
        active_browser(),
        ('PATCH', f'/browsers/{BROWSER_ID}', Response({'id': BROWSER_ID, 'status': 'stopped'})),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'failed',
            'result': 'Partial evidence', 'error': 'Budget exhausted'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, sleep=lambda _: None, progress=lambda _: None)
    assert result['ok'] is False and result['completion'] == 'completed'
    assert 'Partial evidence' in result['speech']
    assert result['data']['browser_research']['stash_ref'] == 'stash://space/partial'


def test_known_terminal_state_does_not_reserve_slot_when_report_get_fails(config):
    clock = [time.time()]
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'detail': 'temporary'}, 503)),
    ])
    result = cloud.run({'task': 'Research'}, session=session, now=lambda: clock[0],
                       sleep=lambda _: clock.__setitem__(0, float(config['JARVIS_BACKGROUND_DEADLINE'])),
                       progress=lambda _: None)
    assert result['ok'] is False and result['completion'] == 'completed'
    assert result['data']['run_id'] == RUN_ID
    assert 'could not retrieve its report' in result['speech']


def test_uncertain_stop_receipt_is_verified_without_repeating_patch(monkeypatch):
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        active_browser(),
        ('PATCH', f'/browsers/{BROWSER_ID}', requests.ConnectionError('lost stop receipt')),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is True
    assert 'cleanup needs attention' not in result['speech']
    assert [method for method, _, _ in session.calls].count('PATCH') == 1


def test_unverified_browser_stop_keeps_report_and_warns_operator(monkeypatch):
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        ('GET', '/browsers', Response({'items': [{
            'id': BROWSER_ID, 'agentSessionId': RUN_ID, 'status': 'active',
        }], 'totalItems': 1})),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is True and result['data']['browser_stop_verified'] is False
    assert 'Browser cleanup needs attention' in result['speech']
    assert 'Done' in result['speech']
    assert not any(method == 'PATCH' for method, _, _ in session.calls)


def test_has_more_without_preview_checks_status_and_sleeps(monkeypatch):
    monkeypatch.setattr(cloud, '_archive', lambda *_: 'stash://space/report')
    sleeps = []
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': [], 'hasMore': True})),
        ('GET', '/status', Response({'status': 'running'})),
        ('GET', '/events', Response({'events': [], 'hasMore': True})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed', 'result': 'Done'})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, sleep=sleeps.append, progress=lambda _: None)
    assert result['ok'] is True
    assert sleeps == [cloud.POLL_SECONDS]


def test_key_absence_rejects_before_paid_request(config):
    config['BROWSER_USE_API_KEY'] = ''
    session = Session([])
    result = cloud.run({'task': 'Research'}, session=session)
    assert result['completion'] == 'rejected' and not session.calls


def test_direct_call_without_background_deadline_cannot_submit(config):
    config['JARVIS_BACKGROUND_DEADLINE'] = ''
    session = Session([])
    result = cloud.run({'task': 'Research'}, session=session)
    assert result['completion'] == 'rejected' and not session.calls


def test_skill_entrypoint_reads_executor_json_argument():
    process = subprocess.run([sys.executable, str(ROOT / 'skills/browser_use_cloud.py'),
                              json.dumps({'task': ''})], capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(process.stdout)['speech'] == 'A research goal is required.'


def test_full_research_archive_uses_stash(tmp_path):
    from config_loader import config_scope

    with config_scope('cloud', overrides={'STASH_DIR': str(tmp_path)}):
        ref = cloud._archive('Find a source', '# Verified\n\nA report')
    assert ref.startswith('stash://')
    assert (tmp_path / ref.removeprefix('stash://').split('/')[0]).is_dir()


@pytest.mark.parametrize('url', [
    'http://live.browser-use.com/session/x',
    'https://live.browser-use.com.evil.invalid/session/x',
    'https://user@live.browser-use.com/session/x',
    'https://live.browser-use.com:8443/session/x',
    ' https://live.browser-use.com/session/x',
])
def test_live_viewer_rejects_untrusted_destinations(url):
    assert cloud._live_url(url) is None


def test_live_viewer_accepts_documented_host_with_query_and_no_path():
    url = 'https://live.browser-use.com?session=private-capability'
    assert cloud._live_url(url) == url


def test_costs_reject_browser_from_another_agent_session():
    session = Session([('GET', '/browsers', Response({'items': [{
        'id': BROWSER_ID, 'agentSessionId': RUN_ID, 'status': 'stopped',
        'browserCost': '0.01', 'proxyCost': '0.02',
    }], 'totalItems': 1}))])
    with pytest.raises(ValueError, match='not final'):
        cloud._costs(session, SESSION_ID, '0.10')


@pytest.mark.parametrize('summary', [
    'Five stories summarized.\n\nFull report: `outputs/ai_news.md`',
    'Five stories summarized.\n\nFull report with 13 daily and 21 weekly repositories, '
    'descriptions, languages, stars, momentum, URLs, project notes, and licenses: '
    '`outputs/ai_news.md`',
])
def test_provider_workspace_report_is_imported_and_linked_from_stash(monkeypatch, summary):
    full = '# Full report\n\nMore verified detail.'
    saved = []
    monkeypatch.setattr(cloud, '_fetch_full_report',
                        lambda session, workspace_id, path: full if (workspace_id, path) ==
                        (WORKSPACE_ID, 'outputs/ai_news.md') else None)
    monkeypatch.setattr(cloud, '_archive',
                        lambda task, content: saved.append(content) or 'stash://space/full_report')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
            'result': summary, 'workspaceId': WORKSPACE_ID})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is True
    assert saved == [full]
    assert result['data']['browser_research']['stash_ref'] == 'stash://space/full_report'
    assert result['data']['browser_research']['full_report_imported'] is True
    assert 'outputs/ai_news.md' not in result['speech']
    assert 'Full report saved in Jarvis Stash' in result['speech']


def test_workspace_artifact_download_is_bounded_and_does_not_forward_api_key():
    url = 'https://browser-use-production-private.s3.us-east-2.amazonaws.com/report?X-Amz-Signature=secret'
    body = b'# Full report\n'
    session = Session([('GET', '/files', Response({'files': [{
        'path': 'outputs/report.md', 'size': len(body), 'url': url,
    }], 'hasMore': False}))])
    calls = []

    class Download:
        status_code = 200
        headers = {'Content-Length': str(len(body))}

        def iter_content(self, chunk_size):
            yield body

        def close(self):
            pass

    def download(download_url, **kwargs):
        calls.append((download_url, kwargs))
        return Download()

    assert cloud._fetch_full_report(session, WORKSPACE_ID, 'outputs/report.md', download=download) == body.decode()
    assert calls[0][1] == {'timeout': 10, 'allow_redirects': False, 'stream': True}
    assert session.calls[0][2]['params']['prefix'] == 'outputs/report.md'
    assert not cloud._signed_artifact_url('http://127.0.0.1/private?X-Amz-Signature=secret')
    assert not cloud._signed_artifact_url('https://browser-use-production-private.s3.us-east-2.amazonaws.com.evil.invalid/report?sig=x')


def test_unimported_workspace_report_is_labeled_as_summary(monkeypatch):
    summary = 'Short answer.\n\nFull report: `outputs/ai_news.md`'
    monkeypatch.setattr(cloud, '_fetch_full_report',
                        lambda *args: (_ for _ in ()).throw(ValueError('download unavailable')))
    monkeypatch.setattr(cloud, '_archive', lambda task, content: 'stash://space/summary')
    session = Session([
        ('POST', '/runs', created()),
        ('GET', '/events', Response({'events': []})),
        ('GET', '/status', Response({'status': 'completed'})),
        no_active_browsers(),
        ('GET', f'/runs/{RUN_ID}', Response({'id': RUN_ID, 'status': 'completed',
            'result': summary, 'workspaceId': WORKSPACE_ID})),
    ])
    result = cloud.run({'task': 'Research'}, session=session, progress=lambda _: None)
    assert result['ok'] is True
    assert result['data']['browser_research']['full_report_imported'] is False
    assert 'Open saved summary' in result['speech']
    assert 'outputs/ai_news.md' not in result['speech']


@pytest.mark.parametrize('path', ['outputs/../private.md', '/tmp/report.md', 'outputs//report.md',
                                  'outputs/report.pdf', 'https://example.com/report.md'])
def test_full_report_path_rejects_untrusted_locations(path):
    marker, accepted = cloud._full_report_path(f'Full report: `{path}`')
    assert marker is not None and accepted is None


def test_manifest_requires_background_and_reviewed_remote_binding():
    from config_loader import config_scope

    from lib.background_tasks import production
    from lib.background_tasks.local_contract import REMOTE_ADAPTER

    assert production.bindings()['browser_use_cloud'] == REMOTE_ADAPTER
    with config_scope('cloud', overrides={'BROWSER_USE_API_KEY': 'test-key', 'JARVIS_TOOL_PROFILE': 'default'}):
        schema, evidence = production.runner().policy('browser_use_cloud')
    assert schema.background_execution['required'] is True
    assert evidence['timeout_seconds'] == 1800
    assert evidence['adapter'] == REMOTE_ADAPTER
