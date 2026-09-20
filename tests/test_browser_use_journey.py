"""Web admission through the browser HTTP service and one late continuation.

Default is a scripted skill result. JARVIS_LIVE_BROWSER_TEST=1 additionally runs
upstream's real Docker agent with the configured cloud model and public pages.
All stores, credentials and Stash output remain under pytest's temporary root.
"""
import json
import os
import socket
import threading

import pytest
import requests
import uvicorn
from test_task_callback_http import callback_app
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks.worker import TaskWorker
from lib.webhook_integrations.browser import provision, read_config
from lib.webhook_integrations.browser_service import BrowserService
from lib.webhook_integrations.service import IntegrationService


@pytest.mark.parametrize('caller', ['disabled', 'unselected', 'talk', 'firefox'])
def test_browser_web_denial_never_starts_foreground_or_callback(web_tasks, monkeypatch, caller):
    import executor
    import orchestrator_v2
    import tool_process
    from tool_schema import ToolSchema

    from lib.webhook_integrations.browser import ROOT

    h = web_tasks
    h.tasks.configure(background_enabled=caller != 'disabled',
                      background_tools=[] if caller == 'unselected' else ['browser_use'])
    schemas = h.background.registry.get_tool.__self__
    schemas['browser_use'] = ToolSchema.from_json_file(str(ROOT / 'skills/browser_use.tool.json'))
    h.background.adapters = {'browser_use': 'http_callback_v1'}
    factory = orchestrator_v2.Orchestrator
    def browser_factory(*args, **kwargs):
        instance = factory(*args, **kwargs)
        route = instance.router.route
        def choose(*a, **kw):
            assert 'browser_use' in kw['excluded_tools']
            decision = route(*a, **kw)
            if decision.get('tool_name') == 'fixture':
                decision.update(tool_name='browser_use', arguments={'task': 'Research', 'url': 'https://example.com'})
            return decision
        instance.router.route = choose
        return instance
    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', browser_factory)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: pytest.fail('must not start browser child'))
    results = []
    execute = executor.ToolExecutor.execute
    def record(self, *args, **kwargs):
        result = execute(self, *args, **kwargs)
        results.append(result)
        return result
    monkeypatch.setattr(executor.ToolExecutor, 'execute', record)
    client = h.connect(origin='moz-extension://fixture') if caller == 'firefox' else h.client
    client.emit('chat:send', {'message': 'Research this page', 'mode': 'cloud',
                             'input_mode': 'talk' if caller == 'talk' else 'text',
                             'background_tools': ['browser_use']})
    eventually(lambda: results)
    eventually(lambda: not h.handler.runs.active)
    assert all(not result['ok'] and result['error'] == 'Tool blocked for this request' for result in results)
    assert not h.tasks.conversation_jobs()


@pytest.mark.parametrize('live,result_ok', [(False, True), (False, False),
    pytest.param(True, True, marks=pytest.mark.skipif(
        os.environ.get('JARVIS_LIVE_BROWSER_TEST') != '1', reason='explicit Docker/provider live gate'))])
def test_browser_callback_after_intervening_web_tool(web_tasks, monkeypatch, live, result_ok):
    import orchestrator_v2
    import tool_process
    import tool_profiles
    from config_loader import config_scope
    from llm_provider import create_configured_provider
    from tool_schema import ToolSchema

    from lib.background_tasks.production import worker_adapters
    from lib.webhook_integrations import browser

    h = web_tasks
    h.worker.terminate()
    h.worker.communicate(timeout=6)
    api_socket = socket.socket()
    api_socket.bind(('127.0.0.1', 0))
    api_socket.listen(128)
    api_port = api_socket.getsockname()[1]
    # Only reserve this port until the service starts (same as the HTTP fixture).
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        service_port = listener.getsockname()[1]
    provision(h.tasks, f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{service_port}/submit')
    config = read_config(h.tasks)
    integration = IntegrationService(h.tasks)
    source = integration.status()['sources'][0]
    integration.update_source(source['id'], source['revision'], enabled=True)
    integration.configure(True)
    h.tasks.configure(background_tools=['browser_use'])

    # Enable a copy of the actual reviewed manifest, never modify the installed tool.
    root = h.tmp / 'reviewed-browser'
    (root / 'skills').mkdir(parents=True)
    manifest = json.loads((browser.ROOT / 'skills/browser_use.tool.json').read_text())
    manifest['enabled'] = True
    if not live:
        manifest.pop('availability', None)  # Scripted HTTP journey needs no Docker installation.
    (root / 'skills/browser_use.tool.json').write_text(json.dumps(manifest))
    (root / 'skills/browser_use.py').write_text((browser.ROOT / 'skills/browser_use.py').read_text())
    child_path = root / 'lib/webhook_integrations/browser_job.py'
    child_path.parent.mkdir(parents=True)
    child_path.write_text((browser.ROOT / 'lib/webhook_integrations/browser_job.py').read_text())
    monkeypatch.setattr(browser, 'ROOT', root)
    monkeypatch.setattr(tool_profiles, 'load_active_profile_overrides', lambda: {})
    schemas = h.background.registry.get_tool.__self__
    schemas['browser_use'] = ToolSchema.from_json_file(str(root / 'skills/browser_use.tool.json'))
    h.background.adapters = {'browser_use': 'http_callback_v1'}

    model_name = 'test:cloud'
    if live:
        with config_scope('cloud'):
            provider_name, model_name, _ = create_configured_provider(mode='cloud', disable_server_side_tools=True)
    else:
        provider_name = 'ollama'
    arguments = {'task': 'Read this page and report its title and what these domains are for. Cite the URL.',
                 'url': 'https://example.com/', 'max_steps': 3}
    force_followup = [False]
    factory = orchestrator_v2.Orchestrator
    def browser_factory(*args, **kwargs):
        instance = factory(*args, **kwargs)
        route = instance.router.route
        def choose(*a, **kw):
            decision = route(*a, **kw)
            if force_followup[0]:
                force_followup[0] = False
                decision.update(intent='tool', tool_name='browser_use', arguments=arguments)
            elif decision.get('tool_name') == 'fixture':
                decision.update(intent='tool', tool_name='browser_use', arguments=arguments)
            return decision
        instance.router.route = choose
        return instance
    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', browser_factory)
    authorize = h.background.authorize
    def selected_authorization(conversation_id, request_id, mode, selected, provider, model, query, registry):
        return authorize(conversation_id, request_id, mode, selected, provider_name, model_name, query, registry)
    monkeypatch.setattr(h.background, 'authorize', selected_authorization)

    started, allow_completion = threading.Event(), threading.Event()
    original_process = tool_process.run_local_process
    def browser_process(command, *args, **kwargs):
        if len(command) >= 3 and str(command[2]).endswith('/browser_job.py'):
            assert command[1] == '-I'
            started.set()
            assert allow_completion.wait(10)
            if not live:
                return json.dumps({'ok': result_ok, 'speech': 'Saved research: stash://test/report\nExample Domain is for documentation.' if result_ok
                                   else 'Saved research: stash://test/report\n\nPartial research: Example Domain is for documentation.',
                                   'stash_ref': 'stash://test/report',
                                   'sources': ['https://example.com/'],
                                   'provider': provider_name, 'model': model_name}), '', False
        return original_process(command, *args, **kwargs)
    monkeypatch.setattr(tool_process, 'run_local_process', browser_process)
    h.background.synthesize = h.background._synthesize
    service = BrowserService(h.tmp / 'browser.db', config, deployment_overrides={'STASH_DIR': str(h.tmp / 'stash')})
    service_thread = threading.Thread(target=service.run, daemon=True)
    app = callback_app(integration, h.tmp, monkeypatch)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, lifespan='off'))
    api_thread = threading.Thread(target=lambda: server.run(sockets=[api_socket]), daemon=True)
    stop = threading.Event()
    worker_thread = None
    try:
        service_thread.start()
        api_thread.start()
        eventually(lambda: server.started)
        def health():
            try:
                return requests.get(config['submit_url'].removesuffix('/submit')+'/health',
                    headers={'Authorization': config['credential']['authorization']}, timeout=.5).status_code == 200
            except requests.RequestException:
                return False
        eventually(health)
        assert integration.test_source(source['id'])['ok']
        worker = TaskWorker(h.tasks, worker_adapters(h.tasks), poll_seconds=.05)
        worker_thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
        worker_thread.start()
        eventually(lambda: any('http_callback_v1' in item['adapters'] for item in h.tasks.healthy_workers()))
        h.client.emit('chat:send', {'message': 'Research Example Domain in the background.', 'mode': 'cloud'})
        job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
        assert started.wait(10), h.tasks.get(job['id'])
        cid = job['conversation_id']
        eventually(lambda: h.handler.runs.snapshot(cid)['run']['status'] == 'completed')
        h.client.emit('chat:send', {'message': 'What time is it?', 'mode': 'cloud', 'conversation_id': cid})
        eventually(lambda: (h.root / 'foreground_started').exists())
        assert h.tasks.get(job['id'])['state'] == 'running'
        (h.root / 'foreground_finish').touch()
        eventually(lambda: any('foreground clock returned' in m['content'] for m in h.store.get_conversation(cid)['messages'] if m['role'] == 'assistant'))
        allow_completion.set()
        def delivered():
            with service.connection() as conn:
                assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] != 'uncertain', 'Browser observation failed; see captured service logs'
            return h.tasks.get(job['id'])['delivery_state'] == 'delivered'
        eventually(delivered, timeout=240 if live else 15)
        result = h.tasks.get(job['id'])
        assert result['state'] == ('succeeded' if result_ok else 'failed'), result
        assert 'stash://' in result['result']['speech']
        continuations = [m for m in h.store.get_conversation(cid)['messages']
                         if m['role'] == 'assistant' and 'Saved research:' in m['content']]
        assert len(continuations) == 1
        assert continuations[0]['data']['browser_use']['data']['browser_research']['stash_ref'].startswith('stash://')
        if not result_ok:
            assert not continuations[0]['data']['browser_use']['ok']
        with service.connection() as conn:
            assert conn.execute('SELECT count(*) FROM browser_jobs').fetchone()[0] == 1
            assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        if not live:
            arguments = {'task': 'Check the earlier answer again and report any correction.',
                         'continue_job_id': job['id']}
            force_followup[0] = True
            h.client.emit('chat:send', {
                'message': 'Continue the earlier Browser Use research.', 'mode': 'cloud',
                'conversation_id': cid,
            })
            second = eventually(lambda: next((item for item in h.tasks.conversation_jobs(cid)
                                              if item['id'] != job['id']), None))
            try:
                eventually(lambda: h.tasks.get(second['id'])['delivery_state'] == 'delivered', timeout=20)
            except AssertionError:
                pytest.fail(f'Follow-up did not deliver: {h.tasks.get(second["id"])}')
            with service.connection() as conn:
                payloads = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM browser_jobs')]
            assert len(payloads) == 2
            followup = next(item for item in payloads if 'followup' in item)
            assert followup['followup']['url'] == 'https://example.com/'
            assert 'Example Domain is for documentation' in followup['followup']['summary']
            assert followup['arguments']['continue_job_id'] == job['id']
        if live:
            assert list((h.tmp / 'stash').rglob('browser-research.md'))
    finally:
        allow_completion.set()
        stop.set()
        if worker_thread:
            worker_thread.join(6)
        service.stop.set()
        service_thread.join(20)
        server.should_exit = True
        api_thread.join(6)
        api_socket.close()
