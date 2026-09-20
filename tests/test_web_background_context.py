"""Task evidence in actual Web prompts; isolated stores and scripted providers."""

import json
from types import SimpleNamespace

import pytest
from test_background_tasks import admission, ready
from test_background_tasks import store as store
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks import TaskStore


def snapshot_from_prompt(prompt):
    block = prompt.split('[BACKGROUND TASK CONTEXT]\n', 1)[1]
    block = block.split('\n[END BACKGROUND TASK CONTEXT]', 1)[0]
    return json.loads(block.splitlines()[-1])


def test_context_read_does_not_initialize_a_disabled_installation(tmp_path):
    tasks = TaskStore(tmp_path / 'missing' / 'tasks.db')
    assert tasks.context_jobs('conversation', 0) == {'jobs': [], 'total': 0}
    assert not tasks.path.parent.exists()


def test_context_spans_modes_but_preserves_generation_and_conversation_after_disable(store):
    current = store.admit(admission())
    other_mode = store.admit(admission(mode='cloud', invocation_id='cloud'))
    for changes in ({'generation': 0}, {'conversation_id': 'another-conversation'}):
        store.admit(admission(**changes))
    store.configure(background_enabled=False)
    result = store.context_jobs('conversation-1', 1)
    assert result['total'] == 2
    assert {job['id'] for job in result['jobs']} == {current['id'], other_mode['id']}
    store.fence_conversation('conversation-1', 1, 'clear', dispose=True)
    assert store.context_jobs('conversation-1', 1) == {'jobs': [], 'total': 0}
    assert store.context_jobs('conversation-1', 2) == {'jobs': [], 'total': 0}


def test_context_is_bounded_and_keeps_old_unfinished_work_ahead_of_recent_results(store):
    store.configure(max_outstanding=20)
    oldest = store.admit(admission())  # Held; cannot be claimed by the loop below.
    for index in range(10):
        ready(store, invocation_id=f'completed-{index}')
        claim = store.claim('worker', {'local_fixture'})
        store.finish(claim, {'ok': True, 'data': {'artifact': f'{index}.txt'}})
    snapshot = store.context_jobs('conversation-1', 1)
    assert snapshot['total'] == 11
    assert len(snapshot['jobs']) == 8
    assert snapshot['jobs'][0]['id'] == oldest['id']
    assert all(job['state'] == 'succeeded' for job in snapshot['jobs'][1:])


@pytest.mark.parametrize('terminal', ['cancelled', 'expired'])
def test_old_cancelled_or_expired_jobs_do_not_crowd_out_recent_successes(store, terminal):
    now = [1000.0]
    store.clock = lambda: now[0]
    for index in range(8):
        job = store.admit(admission(invocation_id=f'old-{index}', timeout_seconds=1))
        if terminal == 'cancelled':
            store.request_cancel(job['id'], job['revision'], supported_adapters=set())
        else:
            now[0] += 2
            store.reconcile()
        assert store.get(job['id'])['state'] == terminal
        now[0] += 1
    successes = set()
    for index in range(8):
        job = ready(store, invocation_id=f'recent-{index}')
        claim = store.claim('worker', {'local_fixture'})
        delivery_id = store.finish(claim, {'ok': True})
        delivery = store.claim_delivery(delivery_id, 'web')
        store.save_delivery_output(delivery, {'text': 'Finished'})
        with store.delivery_commit(delivery):
            pass
        successes.add(job['id'])
        now[0] += 1
    snapshot = store.context_jobs('conversation-1', 1)
    assert snapshot['total'] == 16
    assert {job['id'] for job in snapshot['jobs']} == successes


@pytest.mark.parametrize('state', ['running', 'succeeded', 'generating', 'ready', 'delivered'])
@pytest.mark.parametrize('admission_enabled', [True, False])
def test_next_web_tool_turn_gets_current_state_not_old_receipt(
    web_tasks, monkeypatch, state, admission_enabled,
):
    import orchestrator_v2

    h = web_tasks
    job = h.send_background()
    cid = job['conversation_id']
    if state != 'delivered':
        h.background.close()  # Keep a finished result pending its late answer.
    if state != 'running':
        (h.root / 'finish').touch()
        eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded')
    if state == 'delivered':
        eventually(lambda: h.tasks.get(job['id'])['delivery_state'] == 'delivered')
        eventually(lambda: cid not in h.handler.runs.active)
    if state in {'generating', 'ready'}:
        delivery = h.tasks.pending_deliveries()[0]
        claim = h.tasks.claim_delivery(delivery['id'], 'context-test')
        if state == 'ready':
            h.tasks.save_delivery_output(claim, {'text': 'Prepared answer', 'data': {}})
    h.tasks.configure(background_enabled=admission_enabled)
    captured = []
    original_factory = orchestrator_v2.Orchestrator

    def factory(*args, **kwargs):
        instance = original_factory(*args, **kwargs)
        process = instance.process

        def capture(prompt, **kwargs):
            captured.append(prompt)
            return process(prompt, **kwargs)

        instance.process = capture
        return instance

    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', factory)
    (h.root / 'foreground_finish').touch()
    h.client.emit('chat:send', {'conversation_id': cid, 'message': 'What time is it?',
                               'mode': 'cloud'})
    eventually(lambda: (h.root / 'foreground_started').exists())
    eventually(lambda: cid not in h.handler.runs.active)
    snapshot = snapshot_from_prompt(captured[0])
    assert snapshot['total_jobs'] == 1
    assert snapshot['omitted_jobs'] == 0
    evidence = snapshot['jobs'][0]
    assert evidence['job_id'] == job['id']
    assert evidence['state'] == ('running' if state == 'running' else 'succeeded')
    assert evidence['delivery_state'] == {'running': None, 'succeeded': 'pending',
                                          'generating': 'generating', 'ready': 'ready',
                                          'delivered': 'delivered'}[state]
    assert 'list pending jobs' not in captured[0]
    assert 'Do not append a pending-job recap to unrelated answers.' in captured[0]
    saved = h.store.get_conversation(cid)
    assert saved['messages'][-1]['tools_used'] == ['get_time']
    assert len(h.tasks.conversation_jobs(cid)) == 1  # Reading evidence cannot admit/replay work.


@pytest.mark.parametrize('original,current', [('cloud', 'local'), ('local', 'cloud')])
@pytest.mark.parametrize('completed', [False, True])
def test_status_question_after_mode_switch_sees_same_conversation_job(
    web_tasks, monkeypatch, original, current, completed,
):
    import orchestrator_v2
    import tool_schema
    from jarvis_bundle_chat_test.services import settings_manager
    from test_web_attachment_bundle_chat import web_config

    h = web_tasks
    selected = []
    monkeypatch.setattr(settings_manager, 'get_settings_manager',
                        lambda: SimpleNamespace(set_mode=selected.append))
    monkeypatch.setattr(web_config, 'reload_web_config', lambda: None)
    monkeypatch.setattr(tool_schema, 'reset_tool_registry', lambda: None)
    job = h.send_background(original)
    cid = job['conversation_id']
    h.background.close()  # Hold late delivery so the old receipt remains in history.
    if completed:
        (h.root / 'finish').touch()
        eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded')
    h.tasks.configure(background_enabled=False)
    original_factory = orchestrator_v2.Orchestrator
    captured = []

    def factory(*args, **kwargs):
        instance = original_factory(*args, **kwargs)
        process = instance.process
        instance.router.route = lambda *a, **kw: {'intent': 'qa', 'text_response': 'Status checked.'}

        def capture(prompt, **kwargs):
            captured.append(prompt)
            return process(prompt, **kwargs)

        instance.process = capture
        return instance

    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', factory)
    h.client.get_received()
    h.client.emit('mode:set', {'mode': current})
    assert selected == [current]
    assert any(event['name'] == 'mode:changed' for event in h.client.get_received())
    h.client.emit('chat:send', {'conversation_id': cid, 'message': 'Is it done?', 'mode': current})
    eventually(lambda: captured)
    eventually(lambda: cid not in h.handler.runs.active)
    evidence = snapshot_from_prompt(captured[0])
    assert evidence['chat_mode'] == current
    assert evidence['total_jobs'] == 1
    task = evidence['jobs'][0]
    assert task['job_id'] == job['id'] and task['mode'] == original
    assert task['state'] == ('succeeded' if completed else 'running')
    assert task['delivery_state'] == ('pending' if completed else None)
    assert h.instances[-1].executor.mode == current
    assert len(h.tasks.conversation_jobs(cid)) == 1
    assert len(h.tasks.job_detail(job['id'])['attempts']) == 1
    assert not h.summaries  # Merely reading across modes cannot deliver or execute work.


def test_progress_and_uncertainty_are_bounded_current_evidence(journey, store):
    h = journey
    h.store.background_tasks = store
    h.send(message='Run the background fixture.')
    cid = h.handler.sessions['client']['conversation_id']
    ready(store, conversation_id=cid, generation=0)
    claim = store.claim('worker', {'local_fixture'})
    store.running(claim)
    store.progress(claim, {'phase': 'Inspecting page 4 of 10', 'completed': 3,
                           'total': 10, 'notes': 'x' * 3000, 'api_key': 'private-progress',
                           'live_view_url': 'https://live.browser-use.com/session/private-viewer'})
    prompt = h.handler.background_tasks.conversation_context(cid, 'cloud')
    job = snapshot_from_prompt(prompt)['jobs'][0]
    assert job['mode'] == 'local' and job['state'] == 'running'
    assert job['progress']['phase'] == 'Inspecting page 4 of 10'
    assert job['progress']['completed'] == 3
    assert len(json.dumps(job['progress'])) <= 1500
    assert 'private-progress' not in prompt
    assert 'private-viewer' not in prompt
    assert job['attention_reason'] is None
    assert job['updated_at'] == store.get(claim.job_id)['updated_at']
    reason = 'Worker ownership lost during page inspection; outcome is unconfirmed.'
    store.attention(claim, reason)
    job = snapshot_from_prompt(h.handler.background_tasks.conversation_context(cid, 'cloud'))['jobs'][0]
    assert job['state'] == 'needs_attention'
    assert job['attention_reason'] == reason
    assert job['progress']['phase'] == 'Inspecting page 4 of 10'
    assert job['result'] is None and not job['result_archived']
    assert store.counts()['reserved'] == 1


def test_expiry_is_distinct_from_result_archival(journey, store):
    h = journey
    h.store.background_tasks = store
    h.send(message='Run the background fixture.')
    cid = h.handler.sessions['client']['conversation_id']
    now = [1000.0]
    store.clock = lambda: now[0]
    store.configure(result_retention_days=1)
    ready(store, conversation_id=cid, generation=0, timeout_seconds=1)
    now[0] += 2
    store.reconcile()
    prompt = h.handler.background_tasks.conversation_context(cid, 'cloud')
    evidence = snapshot_from_prompt(prompt)['jobs'][0]
    assert evidence['state'] == 'expired' and evidence['result']['ok'] is False
    assert 'not dispatched' in evidence['attention_reason']
    assert evidence['result_archived'] is False
    now[0] += 2 * 86400
    assert store.archive_results() == 1
    evidence = snapshot_from_prompt(h.handler.background_tasks.conversation_context(cid, 'cloud'))['jobs'][0]
    assert evidence['state'] == 'expired' and evidence['result_archived'] is True
    assert evidence['result'] is None


def test_context_failure_leaves_normal_chat_available(journey, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('private database detail')

    monkeypatch.setattr(journey.handler.background_tasks.store, 'context_jobs', unavailable)
    journey.send(message='Hello')
    journey.process()
    prompt = journey.routes[0][0]
    assert 'Current background task status is unavailable.' in prompt
    assert 'private database detail' not in prompt
    assert journey.store.get_conversation(
        journey.handler.sessions['client']['conversation_id']
    )['messages'][-1]['role'] == 'assistant'


@pytest.mark.parametrize('delivery_state', ['pending', 'generating', 'ready'])
def test_late_answer_and_next_turn_share_input_and_output_roles(journey, store, monkeypatch, delivery_state):
    import llm_provider

    h = journey
    h.store.background_tasks = store
    h.send(message='Convert my uploaded file.')
    cid = h.handler.sessions['client']['conversation_id']
    source = 'stash://source-space/source-file'
    output = 'stash://output-space/output-file'
    store.configure(background_tools=['convert_file'])
    job = ready(store, conversation_id=cid, generation=0, mode='cloud', tool='convert_file',
                arguments={'source': source, 'target_format': 'avi', 'api_key': 'private-input'})
    claim = store.claim('worker', {'local_fixture'})
    result = {'ok': True, 'speech': 'Converted MP4 to AVI.', 'data': {
        'stash_ref': output, 'space_id': 'output-space', 'file_id': 'output-file',
        'filename': 'example.avi', 'source_format': 'mp4', 'target_format': 'avi',
        'diagnostic': 'x' * 100000, 'access_token': 'private-result'}}
    delivery_id = store.finish(claim, result)
    if delivery_state != 'pending':
        delivery = store.claim_delivery(delivery_id, 'prompt-test')
        if delivery_state == 'ready':
            store.save_delivery_output(delivery, {'text': 'Prepared answer', 'data': {}})
    job = store.get(job['id'])
    captured = []

    class Provider:
        def chat(self, prompt, **kwargs):
            captured.append((json.loads(prompt), kwargs['system_prompt']))
            return 'Converted to AVI.'

    monkeypatch.setattr(llm_provider, 'create_configured_provider',
                        lambda **kw: (None, None, Provider()))
    background = h.handler.background_tasks
    rendered = background._synthesize(job, {'provider': 'test', 'model': 'fake-model',
                                           'query': 'Convert my uploaded file.'},
                                      h.store.get_conversation(cid))
    prompt, guidance = captured[0]
    assert prompt['input_arguments']['source'] == source
    assert prompt['result']['data']['stash_ref'] == output
    assert prompt['state'] == 'succeeded'
    assert 'delivery_state' not in prompt
    assert 'This response is the result delivery message' in guidance
    assert 'Do not describe this same result or answer as pending' in guidance
    assert 'Different input and output identifiers alone are not evidence' in guidance
    encoded = json.dumps(prompt)
    assert len(encoded) < 8000
    assert 'private-input' not in encoded and 'private-result' not in encoded
    assert rendered['data']['convert_file'] == result  # Prompt compaction never rewrites evidence.
    # Composing a result must not acknowledge delivery before durable projection.
    assert store.get(job['id'])['delivery_state'] == delivery_state
    foreground = snapshot_from_prompt(background.conversation_context(cid, 'cloud'))['jobs'][0]
    assert foreground['delivery_state'] == delivery_state
    assert {key: value for key, value in foreground.items() if key != 'delivery_state'} == {
        key: prompt[key] for key in foreground if key != 'delivery_state'
    }
