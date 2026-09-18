"""Explicit Web actions and foreground priority, with isolated real conversion."""

import hashlib
import json
import os
import shutil
import threading
import uuid

import pytest
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks import production
from lib.background_tasks.local_contract import ADAPTER
from lib.background_tasks.worker import TaskWorker


@pytest.fixture
def direct(web_tasks, monkeypatch):
    import llm_provider
    from config_loader import config_scope

    h = web_tasks
    h.tasks.configure(background_tools=['convert_file'])
    h.background.adapters = production.bindings()
    original = h.background.registry.get_tool
    with config_scope('cloud'):
        schema, _ = production.runner().policy('convert_file')
    h.background.registry.get_tool = lambda name: schema if name == 'convert_file' else original(name)
    h.background.registry.list_tools = lambda: ['convert_file', 'fixture', 'get_time']
    # No live model call: admission may construct a provider to pin its resolved
    # model, but cannot ask that provider to route the explicit action.
    monkeypatch.setattr(llm_provider, 'create_configured_provider',
                        lambda **kw: ('test', 'test-model', object()))
    h.tasks.touch_worker('direct-test-ready', {ADAPTER})
    h.source = h.tmp / 'source.png'
    from PIL import Image
    Image.new('RGB', (64, 48), '#7961ed').save(h.source)
    h.payload = {'message': 'Convert the uploaded PNG to JPEG.', 'mode': 'cloud',
                 'request_id': str(uuid.uuid4()),
                 'tool_action': {'tool': 'convert_file', 'arguments': {
                     'source': str(h.source), 'target_format': 'jpg', 'options': {'quality': 90}}}}
    return h


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_direct_convert_receipt_chat_and_real_result(direct, monkeypatch, mode):
    from PIL import Image

    h = direct
    executable = shutil.which('convert')
    if not executable:
        pytest.skip('ImageMagick is optional')
    # Pause the actual conversion child before execing ImageMagick. The parent
    # skill, process supervision, decoding and stash output all remain real.
    shim = h.tmp / 'shim'
    shim.mkdir()
    started, release = h.tmp / 'convert-started', h.tmp / 'convert-release'
    wrapper = shim / 'convert'
    wrapper.write_text('#!/usr/bin/python3\nimport os, pathlib, sys, time\n'
                       f'pathlib.Path({str(started)!r}).touch()\n'
                       f'while not pathlib.Path({str(release)!r}).exists(): time.sleep(.01)\n'
                       f'os.execv({executable!r}, [{executable!r}, *sys.argv[1:]])\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv('PATH', str(shim) + os.pathsep + os.environ['PATH'])
    before = hashlib.sha256(h.source.read_bytes()).hexdigest()
    h.payload['mode'] = mode
    h.client.emit('chat:send', h.payload)
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    cid = job['conversation_id']
    eventually(lambda: h.tasks.get(job['id'])['dispatch_state'] == 'ready')
    saved = h.store.get_conversation(cid)
    assert saved['run']['status'] == 'completed'
    assert saved['messages'][-1]['tools_used'] == []
    assert len(saved['messages'][-1]['data']['pending_jobs']) == 1
    assert h.instances == []  # No Orchestrator or routing/receipt model calls.
    worker = TaskWorker(h.tasks, production.worker_adapters(), deployment_overrides={
        'STASH_DIR': str(h.tmp / 'conversion-stash'), 'JARVIS_TOOL_PROFILE': 'default'})
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    try:
        eventually(started.exists)
        assert h.tasks.get(job['id'])['state'] == 'running'
        h.client.emit('chat:send', {'message': 'What time is it?', 'mode': mode,
                                   'conversation_id': cid})
        eventually(lambda: (h.root / 'foreground_started').exists())
        assert h.tasks.get(job['id'])['state'] == 'running'
        assert h.store.get_conversation(cid)['run']['status'] == 'running'
        (h.root / 'foreground_finish').touch()
        eventually(lambda: h.store.get_conversation(cid)['run']['status'] == 'completed')
        release.touch()
        eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded', timeout=10)
        eventually(lambda: len(h.store.get_conversation(cid)['messages']) == 5)
        assert h.tasks.get(job['id'])['delivery_state'] == 'delivered'
        assert hashlib.sha256(h.source.read_bytes()).hexdigest() == before
        images = list((h.tmp / 'conversion-stash').rglob('*.jpg'))
        assert len(images) == 1
        with Image.open(images[0]) as image:
            image.load()
            assert image.format == 'JPEG' and image.size == (64, 48)
        assert len(h.instances) == 1  # Only the intervening foreground request.
    finally:
        release.touch()
        thread.join(10)
    assert not thread.is_alive()


def test_direct_request_reconnect_is_idempotent_and_changed_arguments_conflict(direct):
    h = direct
    h.client.emit('chat:send', h.payload)
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    eventually(lambda: h.tasks.get(job['id'])['dispatch_state'] == 'ready')
    h.client.get_received()
    h.client.emit('chat:send', h.payload)
    assert len(h.tasks.conversation_jobs()) == 1
    h.payload['tool_action']['arguments']['target_format'] = 'webp'
    h.client.emit('chat:send', h.payload)
    assert any(event['name'] == 'chat:rejected' for event in h.client.get_received())
    assert len(h.tasks.conversation_jobs()) == 1
    assert h.instances == []


@pytest.mark.parametrize('failure', ['arguments', 'worker_offline', 'save_receipt'])
def test_direct_admission_failures_do_not_execute_or_fall_back_to_model(direct, monkeypatch, failure):
    h = direct
    if failure == 'arguments':
        h.payload['tool_action']['arguments']['target_format'] = 'bad/format'
    elif failure == 'worker_offline':
        h.tasks.touch_worker('direct-test-ready', {ADAPTER}, draining=True)
    else:
        monkeypatch.setattr(h.store, 'add_message', lambda *a, **kw: (_ for _ in ()).throw(OSError('disk full')))
    h.client.emit('chat:send', h.payload)
    events = []
    eventually(lambda: (events.extend(h.client.get_received()) or
                        any(e['name'] == 'chat:error' for e in events)))
    assert not h.instances
    jobs = h.tasks.conversation_jobs()
    if failure == 'save_receipt':
        assert len(jobs) == 1 and jobs[0]['dispatch_state'] == 'held'
        assert h.tasks.claim('must-not-run', {ADAPTER}) is None
    else:
        assert not jobs


@pytest.mark.parametrize('case', ['disabled', 'talk', 'extension', 'unbound', 'chat_only', 'missing_origin'])
def test_explicit_intent_cannot_grant_permission(direct, monkeypatch, case):
    h = direct
    if case == 'disabled':
        h.tasks.configure(background_enabled=False)
    elif case == 'talk':
        h.payload['input_mode'] = 'talk'
    elif case == 'extension':
        h.client = h.connect('moz-extension://companion')
    elif case == 'missing_origin':
        h.client = h.connect('')
    elif case == 'chat_only':
        h.payload['tool_policy'] = 'none'
    else:
        h.payload['tool_action']['tool'] = 'get_time'
    entered = threading.Event()
    monkeypatch.setattr(h.background, 'submit_explicit', lambda *a: pytest.fail('must not bypass routing'))
    monkeypatch.setattr(h.handler, '_get_completion_guard_config', lambda mode: (entered.set() or {'enabled': False}))
    h.client.emit('chat:send', h.payload)
    assert entered.wait(6)
    assert not h.tasks.conversation_jobs()


def test_new_foreground_turn_wins_while_summary_is_generating(web_tasks):
    h = web_tasks
    entered, release = threading.Event(), threading.Event()
    original = h.background.synthesize
    calls = []

    def generate(job, authorization, conversation):
        calls.append(conversation)
        if len(calls) == 1:
            entered.set()
            assert release.wait(8)
        result = original(job, authorization, conversation)
        result['text'] = 'Current history' if len(calls) > 1 else 'Stale history'
        return result

    h.background.synthesize = generate
    job = h.send_background()
    cid = job['conversation_id']
    (h.root / 'finish').touch()
    try:
        assert entered.wait(6)
        assert cid not in h.handler.runs.active
        h.client.emit('chat:send', {'conversation_id': cid, 'message': 'What time is it?', 'mode': 'cloud'})
        eventually(lambda: (h.root / 'foreground_started').exists())
        release.set()
        eventually(lambda: cid not in h.background.delivering)
        assert h.store.get_conversation(cid)['run']['kind'] == 'chat'
        assert len(h.store.get_conversation(cid)['messages']) == 3
        (h.root / 'foreground_finish').touch()
        eventually(lambda: len(h.store.get_conversation(cid)['messages']) == 5, timeout=8)
        saved = h.store.get_conversation(cid)
        assert saved['messages'][-1]['content'] == 'Current history'
        assert 'What time is it?' in json.dumps(calls[-1])
        assert len(calls) == 2
        assert len(list(h.root.glob('*.started'))) == 1
    finally:
        release.set()


@pytest.mark.parametrize('action', ['clear', 'delete'])
def test_disposition_fences_summary_generated_without_a_chat_lease(web_tasks, action):
    h = web_tasks
    entered, release = threading.Event(), threading.Event()

    def generate(*args):
        entered.set()
        assert release.wait(8)
        return {'text': 'Must never appear', 'data': {}}

    h.background.synthesize = generate
    job = h.send_background()
    (h.root / 'finish').touch()
    try:
        assert entered.wait(6)
        h.store.dispose_background(job['conversation_id'], action, job['generation'])
        release.set()
        eventually(lambda: not h.background.delivering)
        assert h.tasks.get(job['id'])['delivery_state'] == 'suppressed'
        saved = h.store.get_conversation(job['conversation_id'])
        assert saved is None if action == 'delete' else saved['messages'] == []
    finally:
        release.set()
