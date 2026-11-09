"""MCP jobs use the existing remote task cards and uncertainty notices."""

import json
from types import SimpleNamespace

import pytest
from test_background_tasks import admission, receipt
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

TOOL = 'mcp_google_workspace_run_script_function'
ADAPTER = 'mcp_tool_v1'


@pytest.mark.parametrize('state', ['queued', 'starting', 'running'])
def test_mcp_card_and_cancel_api_distinguish_queued_from_started_work(web_tasks, state):
    h = web_tasks
    h.tasks.configure(background_tools=[TOOL])
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0, tool=TOOL, adapter=ADAPTER))
    if state != 'queued':
        h.tasks.release(job['id'], receipt(job))
        claim = h.tasks.claim('inert-mcp-owner', {ADAPTER})
        if state == 'running':
            h.tasks.running(claim)
    job = h.tasks.get(job['id'])

    card = h.background.card(job)

    assert card['remote_work'] is True
    assert card['can_cancel'] is (state == 'queued')
    response = h.app.test_client().post(
        f"/api/background-jobs/{job['id']}/actions",
        json={'action': 'cancel', 'revision': card['revision']},
        headers={'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'},
    )
    assert response.status_code == (200 if state == 'queued' else 409)
    assert h.tasks.get(job['id'])['state'] == ('cancelled' if state == 'queued' else state)


def test_mcp_uncertainty_notice_does_not_claim_remote_failure_or_retry(web_tasks):
    h = web_tasks
    h.tasks.configure(background_tools=[TOOL])
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0, tool=TOOL, adapter=ADAPTER))
    h.tasks.release(job['id'], receipt(job))
    claim = h.tasks.claim('inert-mcp-owner', {ADAPTER})
    h.tasks.running(claim)
    h.tasks.attention(claim, 'MCP observation timeout')
    job = h.tasks.get(job['id'])

    output = h.background._synthesize(job, {}, {'messages': []})

    assert 'Remote work may still be running' in output['text']
    assert 'not a confirmed operation failure' in output['text']
    assert 'No automatic retry was started' in output['text']
    assert output['data']['_background_attention'] is True
    assert len(h.tasks.conversation_jobs(cid)) == 1


@pytest.mark.parametrize('phase', ['discovery', 'preparation'])
def test_mcp_preflight_notice_reports_no_function_submission(web_tasks, phase):
    h = web_tasks
    h.tasks.configure(background_tools=[TOOL])
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0, tool=TOOL, adapter=ADAPTER))
    h.tasks.release(job['id'], receipt(job))
    claim = h.tasks.claim('inert-mcp-owner', {ADAPTER})
    h.tasks.running(claim)
    reason = f'MCP tool {phase} could not be completed'
    h.tasks.attention(claim, reason, result={
        'ok': False, 'completion': 'unknown', 'submission_started': False,
        'error_code': f'mcp_{phase}_incomplete',
        'error': reason,
    })

    output = h.background._synthesize(h.tasks.get(job['id']), {}, {'messages': []})

    assert phase in output['text'].lower()
    assert 'No function call was submitted' in output['text']
    assert 'Remote work may still be running' not in output['text']
    assert 'no longer offered' not in output['text']
    assert 'No automatic retry was started' in output['text']
    assert output['data']['_background_attention'] is True


@pytest.mark.parametrize('completion', ['completed', 'rejected'])
@pytest.mark.parametrize('error', [
    'Error: timeout while updating the sheet',
    'Error: the upstream report timed out',
    'Error: a configured waiting limit was exceeded',
])
def test_mcp_confirmed_error_is_delivered_even_when_it_mentions_timeout(web_tasks, monkeypatch, completion, error):
    import llm_provider

    h = web_tasks
    h.tasks.configure(background_tools=[TOOL])
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0, tool=TOOL, adapter=ADAPTER))
    h.tasks.release(job['id'], receipt(job))
    claim = h.tasks.claim('inert-mcp-owner', {ADAPTER})
    h.tasks.running(claim)
    result = {'ok': False, 'completion': completion, 'error': error, 'speech': error}
    h.tasks.finish(claim, result, succeeded=False)
    evidence = []

    def configured_provider(**options):
        assert options['disable_server_side_tools'] is True

        def chat(prompt, **_kwargs):
            evidence.append(json.loads(prompt))
            return evidence[-1]['result']['error']

        return 'test', 'test-model', SimpleNamespace(chat=chat)

    monkeypatch.setattr(llm_provider, 'create_configured_provider', configured_provider)

    output = h.background._synthesize(h.tasks.get(job['id']),
                                     {'provider': 'test', 'model': 'test-model'}, {'messages': []})

    assert output['text'] == error
    assert output['data'][TOOL] == result
    assert '_background_timeout' not in output['data']
    assert len(evidence) == 1
    assert evidence[0]['state'] == 'failed'
    assert evidence[0]['result'] == result


def test_mcp_settings_report_remote_work_and_current_worker_readiness(web_tasks):
    from tool_schema import ToolSchema

    h = web_tasks
    schema = ToolSchema(TOOL, 'Run a Google Apps Script function', {'type': 'object'},
                        '__mcp__google_workspace__run_script_function', execution={
                            'background': {'supported': True, 'adapter': ADAPTER},
                        })
    h.background.adapters = {TOOL: ADAPTER}
    h.background.registry.list_tools = lambda: [TOOL]
    h.background.registry.get_tool = lambda name: schema if name == TOOL else None
    h.tasks.touch_worker('inert-mcp-worker', {ADAPTER})

    response = h.app.test_client().get('/api/background-tasks?mode=cloud', headers={
        'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost',
    })

    assert response.status_code == 200
    status = response.get_json()
    assert status['tools'] == [TOOL]
    assert status['tool_details'][TOOL]['worker_ready'] is True
    assert status['tool_details'][TOOL]['remote_work'] is True
    assert status['tool_details'][TOOL]['label'] == 'Google Apps Script'
