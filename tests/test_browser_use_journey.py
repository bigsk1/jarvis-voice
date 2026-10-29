"""Web admission through the browser HTTP service and one late continuation.

Default is a scripted skill result. JARVIS_LIVE_BROWSER_TEST=1 additionally runs
upstream's real Docker agent with the configured cloud model and public pages.
All stores, credentials and Stash output remain under pytest's temporary root.
"""
import json
import logging
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
from lib.webhook_integrations.contracts import ADAPTER
from lib.webhook_integrations.service import IntegrationService


@pytest.fixture
def observed_prompt_guard(monkeypatch):
    """Record real scanner receipts without retaining submitted content or keys."""
    from lib import prompt_guard_observer

    original = prompt_guard_observer.scan_text
    observations = []

    def scan(text, **labels):
        observation = original(text, **labels)
        observations.append((labels, observation))
        logging.getLogger(__name__).info(
            '[LIVE_PROMPT_GUARD] source=%s status=%s flagged=%s bytes=%s windows=%s '
            'elapsed_ms=%.1f request_id=%s',
            labels.get('source_name'), observation.status, observation.flagged,
            observation.input_bytes, observation.windows_scanned, observation.elapsed_ms,
            observation.service_request_id,
        )
        return observation

    monkeypatch.setattr(prompt_guard_observer, 'scan_text', scan)
    return observations


def browser_runtime_configuration(live, monkeypatch, stash_dir):
    """Opt only this live journey into configured credentials, never process env."""
    deployment = {'STASH_DIR': str(stash_dir)}
    if not live:
        return 'ollama', 'test:cloud', deployment

    import config_loader
    from llm_provider import create_configured_provider
    from suite_isolation import load_live_mode_config

    from lib import prompt_guard_observer

    deployment['PROMPT_GUARD_INCIDENT_DIR'] = str(stash_dir.parent / 'prompt-guard-incidents')
    settings = {**load_live_mode_config('cloud'), **deployment}
    real_scope = config_loader.config_scope

    def configured_scope(mode, overrides=None):
        # BrowserService enters a new scope in its own thread and limits its
        # deployment overrides to output settings. Supply the selected live
        # configuration at that existing scope seam; runtime model overrides
        # still take precedence. No other test opts into these values.
        selected = settings if mode == 'cloud' else {}
        return real_scope(mode, overrides={**selected, **dict(overrides or {})})

    monkeypatch.setattr(config_loader, 'config_scope', configured_scope)
    # Callback review owns an imported scope alias and deliberately opens the
    # job's mode again. Opt that alias into the same live configuration too.
    monkeypatch.setattr(prompt_guard_observer, 'config_scope', configured_scope)
    with configured_scope('cloud'):
        provider, model, _ = create_configured_provider(
            mode='cloud', disable_server_side_tools=True,
        )
    return provider, model, settings


def test_scripted_browser_configuration_never_reads_live_settings(monkeypatch, tmp_path):
    import suite_isolation

    monkeypatch.setattr(suite_isolation, 'load_live_mode_config',
                        lambda mode: pytest.fail('Scripted journey read operator configuration'))
    assert browser_runtime_configuration(False, monkeypatch, tmp_path) == (
        'ollama', 'test:cloud', {'STASH_DIR': str(tmp_path)},
    )


def test_live_browser_configuration_reaches_real_child_scope_without_global_leaks(monkeypatch, tmp_path):
    import config_loader
    import llm_provider
    import suite_isolation

    from lib.webhook_integrations.browser_service import child_environment

    original_environment = os.environ.copy()
    reads = []
    settings = {
        'LLM_PROVIDER': 'ollama', 'OLLAMA_CLOUD_MODEL': 'fixture-live:cloud',
        'OLLAMA_API_KEY': 'fixture-browser-token', 'STASH_DIR': '/unused/private/stash',
        'PROMPT_GUARD_ENABLED': 'true', 'PROMPT_GUARD_TOOLS': 'browser_use',
    }

    def read_selected(mode):
        reads.append(mode)
        return settings

    def create_provider(**kwargs):
        assert kwargs == {'mode': 'cloud', 'disable_server_side_tools': True}
        assert config_loader.get_config_value('OLLAMA_API_KEY') == 'fixture-browser-token'
        assert config_loader.get_config_value('OLLAMA_CLOUD_MODEL') == 'fixture-live:cloud'
        assert config_loader.get_config_value('STASH_DIR') == str(tmp_path)
        return 'ollama', 'fixture-live:cloud', object()

    monkeypatch.setattr(suite_isolation, 'load_live_mode_config', read_selected)
    monkeypatch.setattr(llm_provider, 'create_configured_provider', create_provider)
    provider, model, deployment = browser_runtime_configuration(True, monkeypatch, tmp_path)
    assert reads == ['cloud']
    assert (provider, model) == ('ollama', 'fixture-live:cloud')

    from lib import prompt_guard_observer

    with prompt_guard_observer.config_scope('cloud', {}):
        assert prompt_guard_observer.is_enabled()
        assert config_loader.get_config_value('PROMPT_GUARD_TOOLS') == 'browser_use'
        assert config_loader.get_config_value('PROMPT_GUARD_INCIDENT_DIR') == str(
            tmp_path.parent / 'prompt-guard-incidents',
        )

    # Exercise BrowserService's real scope and environment builder in the
    # separate-thread shape used by the journey, without starting a browser.
    environments = []
    thread = threading.Thread(target=lambda: environments.append(child_environment({
        'mode': 'cloud', 'provider': provider, 'model': 'authorized-runtime:cloud',
        'deadline': 1234, 'proxy_policy': 'off',
    }, deployment)))
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert len(environments) == 1
    assert environments[0]['OLLAMA_API_KEY'] == 'fixture-browser-token'
    assert environments[0]['OLLAMA_CLOUD_MODEL'] == 'authorized-runtime:cloud'
    assert environments[0]['STASH_DIR'] == str(tmp_path)
    assert os.environ == original_environment
    assert config_loader.get_scoped_config() is None


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
def test_browser_callback_after_intervening_web_tool(
    web_tasks, monkeypatch, observed_prompt_guard, live, result_ok,
):
    import orchestrator_v2
    import tool_process
    import tool_profiles
    from tool_schema import ToolSchema

    from lib.background_tasks.production import worker_adapters
    from lib.webhook_integrations import browser

    h = web_tasks
    provider_name, model_name, deployment = browser_runtime_configuration(live, monkeypatch, h.tmp / 'stash')
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

    arguments = {'task': 'Read this page and report its title and what these domains are for. Cite the URL.',
                 'url': 'https://example.com/', 'max_steps': 6 if live else 3}
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
    service = BrowserService(h.tmp / 'browser.db', config, deployment_overrides=deployment)
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
        worker = TaskWorker(h.tasks, worker_adapters(h.tasks), poll_seconds=.05,
                            deployment_overrides=deployment)
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
            if deployment.get('PROMPT_GUARD_ENABLED', '').lower() in {'true', '1', 'yes', 'on'}:
                selected = deployment.get('PROMPT_GUARD_TOOLS', 'browser_use').split(',')
                if 'browser_use' in {name.strip() for name in selected}:
                    scans = [observation for labels, observation in observed_prompt_guard
                             if labels.get('source_name') == 'browser_use']
                    assert len(scans) == 1, 'The live browser result did not reach Prompt Guard'
                    assert scans[0].status == 'scanned', scans[0]
                    assert scans[0].coverage_complete and scans[0].flagged is False
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


@pytest.mark.skipif(os.environ.get('JARVIS_LIVE_BROWSER_TEST') != '1',
                    reason='explicit Prompt Guard live gate')
@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_live_browser_callback_withholds_injection(
    tmp_path, monkeypatch, observed_prompt_guard, mode,
):
    """Screen a synthetic authenticated completion using the real configured API."""
    import config_loader
    from suite_isolation import load_live_mode_config
    from test_task_callback_prompt_guard import BODY, bind, completion
    from test_task_callbacks import configured, deliver

    from lib import prompt_guard_observer

    incident_dir = tmp_path / 'prompt-guard-incidents'
    settings = {**load_live_mode_config(mode), 'PROMPT_GUARD_INCIDENT_DIR': str(incident_dir)}
    real_scope = config_loader.config_scope

    def configured_scope(selected_mode, overrides=None):
        assert selected_mode == mode
        return real_scope(selected_mode, overrides={**settings, **dict(overrides or {})})

    monkeypatch.setattr(prompt_guard_observer, 'config_scope', configured_scope)
    with configured_scope(mode):
        selected = config_loader.get_config_value('PROMPT_GUARD_TOOLS', 'browser_use').split(',')
        if not prompt_guard_observer.is_enabled() or 'browser_use' not in {name.strip() for name in selected}:
            pytest.skip(f'Prompt Guard for browser_use is not configured in {mode} mode')

    service, source, credential, _ = configured(tmp_path / 'tasks')
    service.store.configure(background_tools=['browser_use'])
    claim, submission = bind(service, source, mode=mode)
    raw = completion(claim)
    deliver(service, source, credential, submission, raw)
    assert service.drain() == 1

    assert len(observed_prompt_guard) == 1
    labels, observation = observed_prompt_guard[0]
    assert labels == {'source_type': 'tool_result', 'source_name': 'browser_use'}
    assert observation.status == 'scanned' and observation.flagged is True, observation
    saved = service.store.get(claim.job_id)
    assert saved['state'] == 'failed' and saved['result']['completion'] == 'completed'
    assert prompt_guard_observer.is_prompt_guard_rejection(saved['result'])
    receipt = saved['result']['data']['prompt_guard']
    assert receipt['content_withheld'] and receipt['evidence_saved']
    evidence = incident_dir / mode / (receipt['incident_id'] + '.json')
    assert evidence.is_file() and evidence.stat().st_mode & 0o777 == 0o600
    assert BODY not in json.dumps(saved['result'])
    assert 'browser_research' not in saved['result']['data']
    deliveries = service.store.pending_deliveries()
    assert len(deliveries) == 1 and BODY not in json.dumps(deliveries)
    assert deliver(service, source, credential, submission, raw)['duplicate'] is True
    assert service.drain() == 0 and len(observed_prompt_guard) == 1
    assert service.store.claim('second-worker', {ADAPTER}) is None
