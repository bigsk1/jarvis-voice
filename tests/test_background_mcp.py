"""Reviewed MCP jobs with real mode configuration and disposable task storage."""

import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import mcp_background_contract as contract
from lib.background_tasks import AdmissionDenied, ReceiptEvidence, TaskStore, production
from lib.background_tasks import mcp_tool as binding
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.worker import TaskWorker

NAME = 'mcp_google_workspace_run_script_function'
SERVER = 'google_workspace'
RAW_NAME = 'run_script_function'
ARGUMENTS = {'script_id': 'owned-script', 'function_name': 'automation', 'parameters': ['fixture']}
TOOL_INFO = {
    'name': RAW_NAME, 'description': 'Run an owned Apps Script API executable.',
    'inputSchema': {
        'type': 'object', 'properties': {
            'script_id': {'type': 'string'}, 'function_name': {'type': 'string'},
            'parameters': {'type': 'array'}, 'user_google_email': {'type': 'string'},
        }, 'required': ['script_id', 'function_name', 'user_google_email'],
    }, 'annotations': {'readOnlyHint': False},
}


class Client:
    """Only the remote transport is fake; policy, schema and jobs stay real."""

    def __init__(self, name, url, transport_type, headers=None, **kwargs):
        self.name, self.url, self.transport_type = name, url, transport_type
        self.headers = headers
        self.proxy_policy = kwargs.get('proxy_policy', 'inherit')
        self.result_contract = kwargs.get('result_contract')
        self.tool_call_timeout_seconds = kwargs.get('tool_call_timeout_seconds')
        self.tool_defaults = {}
        self._tools_cache = None
        self.closed = False
        self.calls = []
        self.infos = copy.deepcopy([TOOL_INFO])
        self.result = {'ok': True, 'completion': 'completed', 'speech': 'Automation complete.',
                       'data': {'created_document_id': 'fixture-document'}}
        self.before_call = None

    def list_tools(self, *, raise_on_error=False):
        self._tools_cache = self.infos
        return self.infos

    def start(self):
        pass

    def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments, kwargs))
        if self.before_call:
            self.before_call()
        return self.result

    def stop(self):
        self.closed = True

    def get_proxy_log_metadata(self):
        return {'proxy_policy': self.proxy_policy}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    import config_loader
    import tool_profiles

    from lib import config_loader as package_config

    root = tmp_path / 'installation'
    (root / 'config').mkdir(parents=True)
    (root / 'skills' / 'profiles').mkdir(parents=True)
    for loader in (config_loader, package_config):
        monkeypatch.setattr(loader, 'get_project_root', lambda: root)
    monkeypatch.setattr(tool_profiles, 'get_project_root', lambda: root)
    (root / 'skills' / 'profiles' / 'default.json').write_text('{"overrides": {}}')
    for mode in ('cloud', 'local'):
        (root / 'config' / f'{mode}.env').write_text(
            f'GOOGLE_WORKSPACE_MCP_ENABLED=true\nGOOGLE_ACCOUNT={mode}@fixture.invalid\n'
            f'GOOGLE_WORKSPACE_MCP_TOKEN=fixture-{mode}-token\n'
            f'GOOGLE_WORKSPACE_MCP_URL=https://{mode}.fixture.invalid/mcp\n'
            'JARVIS_TOOL_PROFILE=default\nUNRELATED_PROVIDER_KEY=private-not-for-mcp\n'
        )
    definition = {
        'type': 'http', 'url': 'http://127.0.0.1:8765/mcp',
        'url_env': 'GOOGLE_WORKSPACE_MCP_URL', 'proxy_policy': 'off',
        'tool_call_timeout_seconds': 90, 'enabled': True,
        'enabled_env': 'GOOGLE_WORKSPACE_MCP_ENABLED',
        'required_env': ['GOOGLE_WORKSPACE_MCP_TOKEN', 'GOOGLE_ACCOUNT'],
        'headers': {'Authorization': 'Bearer ${GOOGLE_WORKSPACE_MCP_TOKEN}'},
        'tool_defaults': {'user_google_email': '${GOOGLE_ACCOUNT}'},
    }
    config_path = root / 'config' / 'mcp-servers.json'
    config_path.write_text(json.dumps({'mcpServers': {SERVER: definition,
        'unreviewed': {'command': 'must-not-launch', 'args': []}}}))
    clients = []

    def factory(*args, **kwargs):
        client = Client(*args, **kwargs)
        clients.append(client)
        return client

    runner = binding.MCPToolRunner(root, client_factory=factory)
    clock = [1000.0]
    store = TaskStore(tmp_path / 'tasks.db', clock=lambda: clock[0])
    store.initialize()
    store.configure(background_enabled=True, background_tools=[NAME])
    store.touch_worker('fixture-worker', {contract.ADAPTER})

    def registry(mode):
        from config_loader import config_scope
        from tool_schema import ToolRegistry
        with config_scope(mode):
            _, spec = runner.connection(NAME)
            client = Client(SERVER, spec['url'], spec['type'], spec['headers'],
                            proxy_policy=spec['proxy_policy'])
            client.tool_defaults = spec['tool_defaults']
            schema = ToolRegistry.schema_from_mcp_tool(SERVER, client, definition, copy.deepcopy(TOOL_INFO))
        return SimpleNamespace(list_tools=lambda: [NAME], get_tool=lambda name: schema if name == NAME else None)

    def admit(mode='cloud', arguments=None, invocation='invoke-1'):
        from config_loader import config_scope
        with config_scope(mode):
            reg = registry(mode)
            schema, evidence = runner.policy(NAME, registry=reg)
            service = BackgroundAdmissionService(store, adapters={NAME: contract.ADAPTER},
                validate_source=lambda _: True, ready=lambda: True)
            context = service.authorize({
                'operator': 'installation', 'source': 'web', 'conversation_id': 'conversation-1',
                'generation': 1, 'request_id': 'request-' + invocation, 'mode': mode,
                'selected': [NAME], 'tool_policy': 'auto', 'tool_policies': {NAME: evidence},
            }, reg)
            accepted = context.admit(NAME, ARGUMENTS if arguments is None else arguments,
                                     invocation, schema)
        job = store.get(accepted['job_id'])
        source = job['admission']
        return store.release(job['id'], ReceiptEvidence(source['conversation_id'], source['generation'],
            source['request_id'], 'receipt-' + invocation, 'completed', True))

    return SimpleNamespace(root=root, config=config_path, definition=definition, clients=clients,
        runner=runner, clock=clock, store=store, registry=registry, admit=admit)


def test_capability_is_exact_reviewed_code_not_arbitrary_mcp_metadata():
    capability = contract.execution_for_tool(NAME, SERVER, RAW_NAME)
    assert capability['background']['adapter'] == contract.ADAPTER
    assert capability['background']['timeout_seconds'] == 420
    for name, server, raw in [(NAME, SERVER, 'delete_file'),
                               (NAME, 'different_account', RAW_NAME),
                               ('mcp_other_run_script_function', SERVER, RAW_NAME)]:
        assert contract.execution_for_tool(name, server, raw) == {}


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_admission_does_no_remote_work_and_worker_uses_isolated_originating_identity(harness, mode):
    original_environment = dict(os.environ)
    job = harness.admit(mode)
    assert harness.clients == []
    assert job['admission']['timeout_seconds'] == 420
    worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
    assert worker.run_once()
    saved = harness.store.get(job['id'])
    assert saved['state'] == 'succeeded', saved['result']
    assert saved['delivery_state'] == 'pending'
    assert saved['result']['data']['created_document_id'] == 'fixture-document'
    assert harness.store.counts()['reserved'] == 0
    assert len(harness.clients) == 1
    client = harness.clients[0]
    assert client.url == f'https://{mode}.fixture.invalid/mcp'
    assert client.headers == {'Authorization': f'Bearer fixture-{mode}-token'}
    assert client.tool_defaults == {'user_google_email': f'{mode}@fixture.invalid'}
    assert client.closed
    assert len(client.calls) == 1
    name, args, kwargs = client.calls[0]
    assert name == RAW_NAME and args == ARGUMENTS
    assert 0 < kwargs['timeout_seconds'] <= 420
    assert kwargs['execution_metadata']['job_id'] == job['id']
    assert dict(os.environ) == original_environment
    assert not worker.run_once()
    serialized = json.dumps(harness.store.authorization(job['admission']['authorization_id']))
    assert f'fixture-{mode}-token' not in serialized
    assert 'private-not-for-mcp' not in serialized


@pytest.mark.parametrize('arguments', [
    {}, {'script_id': 'owned-script'}, {**ARGUMENTS, 'user_google_email': 'other@fixture.invalid'},
    {**ARGUMENTS, 'unexpected': 'secret'}, {**ARGUMENTS, 'parameters': 'not-an-array'},
])
def test_invalid_arguments_never_create_a_job(harness, arguments):
    with pytest.raises(AdmissionDenied, match='arguments|schema'):
        harness.admit(arguments=arguments)
    assert harness.store.counts()['reserved'] == 0
    assert harness.clients == []


@pytest.mark.parametrize('mutation', [
    'disabled', 'allowlist', 'profile', 'blocked', 'url', 'account', 'token',
    'transport_implementation', 'routing_implementation',
])
def test_worker_rechecks_policy_before_calling_remote_tool(harness, monkeypatch, mutation):
    job = harness.admit()
    if mutation in {'disabled', 'allowlist'}:
        data = json.loads(harness.config.read_text())
        data['mcpServers'][SERVER].update(
            {'enabled': False} if mutation == 'disabled' else {'allowed_tools': ['other_tool']})
        harness.config.write_text(json.dumps(data))
    elif mutation == 'profile':
        (harness.root / 'skills' / 'profiles' / 'default.json').write_text(json.dumps({'overrides': {NAME: False}}))
    elif mutation == 'blocked':
        path = harness.root / 'jarvis-web' / 'config' / 'web_config.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'tools': {'blocked': [NAME]}}))
    elif mutation in {'transport_implementation', 'routing_implementation'}:
        original_read = Path.read_bytes
        changed_file = ('http_observation.py' if mutation == 'transport_implementation' else 'http_client.py')

        def changed_transport(path):
            content = original_read(path)
            return content + b'\n# changed transport\n' if path.name == changed_file else content

        monkeypatch.setattr(Path, 'read_bytes', changed_transport)
    else:
        path = harness.root / 'config' / 'cloud.env'
        text = path.read_text()
        key = {'url': 'GOOGLE_WORKSPACE_MCP_URL', 'account': 'GOOGLE_ACCOUNT',
               'token': 'GOOGLE_WORKSPACE_MCP_TOKEN'}[mutation]
        rows = [row for row in text.splitlines() if not row.startswith(key + '=')]
        rows.append(key + '=' + ('https://changed.fixture.invalid/mcp' if mutation == 'url' else 'changed'))
        path.write_text('\n'.join(rows) + '\n')
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    saved = harness.store.get(job['id'])
    assert saved['state'] == 'failed'
    assert saved['result']['completion'] == 'rejected'
    assert all(not client.calls for client in harness.clients)
    assert harness.store.counts()['reserved'] == 0


@pytest.mark.parametrize('completion,state,reserved', [
    ('completed', 'failed', 0), ('rejected', 'failed', 0), ('unknown', 'needs_attention', 1),
    (None, 'needs_attention', 1),
])
def test_only_known_remote_completion_releases_capacity_without_replay(harness, completion, state, reserved):
    job = harness.admit()
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.result = {'ok': False, 'error': 'Controlled script failure'}
        if completion is not None:
            client.result['completion'] = completion
        return client

    harness.runner.client_factory = make
    worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
    assert worker.run_once()
    assert harness.store.get(job['id'])['state'] == state
    assert harness.store.counts()['reserved'] == reserved
    assert not worker.run_once()
    assert sum(len(client.calls) for client in harness.clients) == 1


def test_success_without_completion_evidence_remains_uncertain(harness):
    job = harness.admit()
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.result.pop('completion')
        return client

    harness.runner.client_factory = make
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.store.get(job['id'])['state'] == 'needs_attention'


@pytest.mark.parametrize('discovery', ['connection_failure', 'stopped', 'worker_stopped', 'missing_tool'])
def test_real_worker_distinguishes_incomplete_discovery_from_tool_removal(harness, discovery):
    """Failed tools/list must not become evidence that the tool was removed."""
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from mcp_client import MCPRemoteClient

    requests = []
    stop, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            method = message['method']
            requests.append(method)
            if method == 'notifications/initialized':
                self.send_response(204)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if method == 'tools/list' and discovery != 'missing_tool':
                if discovery == 'stopped':
                    harness.clients[0].stop()
                elif discovery == 'worker_stopped':
                    stop.set()
                    release.wait(3)
                else:
                    self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True
                return
            result = ({'protocolVersion': '2025-03-26', 'capabilities': {},
                       'serverInfo': {'name': 'fixture', 'version': '1'}}
                      if method == 'initialize' else {'tools': []})
            body = json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Mcp-Session-Id', 'discovery-fixture')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    path = harness.root / 'config/cloud.env'
    path.write_text(path.read_text().replace('https://cloud.fixture.invalid/mcp',
        f'http://127.0.0.1:{server.server_port}/mcp'))

    def factory(*args, **kwargs):
        client = MCPRemoteClient(*args, **kwargs)
        harness.clients.append(client)
        return client

    harness.runner.client_factory = factory
    try:
        job = harness.admit()
        worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
        assert worker.run_once(stop)
        saved = harness.store.get(job['id'])
        assert requests.count('tools/list') == 1
        assert 'tools/call' not in requests
        if discovery == 'missing_tool':
            assert saved['state'] == 'failed'
            assert saved['result']['completion'] == 'rejected'
            assert 'no longer offered' in saved['result']['error']
            assert harness.store.counts()['reserved'] == 0
        else:
            assert saved['state'] == 'needs_attention'
            assert saved['result']['completion'] == 'unknown'
            assert saved['result']['submission_started'] is False
            assert saved['result']['error_code'] == 'mcp_discovery_incomplete'
            assert 'No remote tool execution was started' in saved['result']['speech']
            assert 'no longer offered' not in saved['result']['error']
            assert harness.store.counts()['reserved'] == 1
        assert not worker.run_once()
        assert requests.count('tools/list') == 1
    finally:
        release.set()
        for client in harness.clients:
            client.stop()
        server.shutdown()
        server.server_close()
        serving.join(2)


@pytest.mark.parametrize('catalog', ['empty', 'registered'])
def test_worker_stop_as_discovery_returns_cannot_confirm_tool_removal(harness, catalog):
    stop = threading.Event()
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)

        def list_tools(**_kwargs):
            stop.set()
            return [] if catalog == 'empty' else client.infos

        client.list_tools = list_tools
        return client

    harness.runner.client_factory = make
    job = harness.admit()
    worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
    assert worker.run_once(stop)

    saved = harness.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['completion'] == 'unknown'
    assert saved['result']['submission_started'] is False
    assert saved['result']['error_code'] == 'mcp_discovery_incomplete'
    assert all(not client.calls and client.closed for client in harness.clients)
    assert not worker.run_once()


@pytest.mark.parametrize('phase', ['connection', 'authorization'])
def test_worker_stop_during_preparation_retains_no_submission_evidence(harness, monkeypatch, phase):
    stop = threading.Event()
    job = harness.admit()
    original = getattr(harness.runner, 'connection' if phase == 'connection' else '_authorize')

    def stopped(*args, **kwargs):
        result = original(*args, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(harness.runner, 'connection' if phase == 'connection' else '_authorize', stopped)
    worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
    assert worker.run_once(stop)

    saved = harness.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['completion'] == 'unknown'
    assert saved['result']['submission_started'] is False
    assert saved['result']['error_code'] == 'mcp_preparation_incomplete'
    assert 'preparation' in saved['result']['speech']
    assert all(not client.calls for client in harness.clients)
    assert not worker.run_once()


def test_queue_delay_is_subtracted_from_call_budget(harness):
    job = harness.admit()
    harness.clock[0] += 80
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    kwargs = harness.clients[0].calls[0][2]
    assert 0 < kwargs['timeout_seconds'] <= 340
    assert kwargs['execution_metadata']['deadline_unix'] == job['deadline']


def test_expired_queued_job_never_opens_mcp_client(harness):
    job = harness.admit()
    harness.clock[0] = job['deadline'] + 1
    assert not TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.store.get(job['id'])['state'] == 'expired'
    assert harness.clients == []


def test_concurrent_jobs_use_different_clients_and_mode_credentials(harness):
    jobs = [harness.admit(mode, invocation=mode) for mode in ('cloud', 'local')]
    barrier = threading.Barrier(2)
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.before_call = lambda: barrier.wait(timeout=5)
        return client

    harness.runner.client_factory = make
    worker = TaskWorker(harness.store, {contract.ADAPTER: harness.runner})
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda _: worker.run_once(), range(2)))
    assert all(harness.store.get(job['id'])['state'] == 'succeeded' for job in jobs)
    assert len(harness.clients) == 2
    assert {client.tool_defaults['user_google_email'] for client in harness.clients} == {
        'cloud@fixture.invalid', 'local@fixture.invalid'}
    assert {client.headers['Authorization'] for client in harness.clients} == {
        'Bearer fixture-cloud-token', 'Bearer fixture-local-token'}


def test_registration_does_not_enable_a_saved_background_choice(harness):
    assert NAME in production.bindings()
    fresh = TaskStore(harness.root / 'new-tasks.db')
    fresh.initialize()
    assert fresh.settings()['background_tools'] == []
    assert fresh.settings()['background_enabled'] is False


@pytest.mark.parametrize('kind', ['terminal-success', 'terminal-failure'])
@pytest.mark.parametrize('shape', ['text', 'nested-array'])
def test_oversized_completed_result_stays_terminal_and_preserves_available_stash_links(harness, kind, shape):
    job = harness.admit()
    factory = harness.runner.client_factory
    report = 'x' * (2 * 1024 * 1024)
    if shape == 'nested-array':
        # Small numeric leaves beyond the depth limit still consume output
        # space when replaced by truncation notices. Bound container work too.
        report = [[[0] * 100] * 100] * 100
        for _ in range(4):
            report = [report]

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.result = {'ok': kind == 'terminal-success', 'completion': 'completed',
            'speech': 'Finished automation.', 'stash_ref': 'stash://fixture-space/fixture-file',
            'data': {'large_report': report}}
        return client

    harness.runner.client_factory = make
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    saved = harness.store.get(job['id'])
    assert saved['state'] == ('succeeded' if kind == 'terminal-success' else 'failed')
    assert saved['result']['result_truncated'] is True
    assert saved['result']['stash_ref'] == 'stash://fixture-space/fixture-file'
    assert harness.store.counts()['reserved'] == 0


def test_fresh_upstream_schema_change_rejects_before_remote_execution(harness):
    job = harness.admit()
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.infos[0]['inputSchema']['required'].append('new_argument')
        return client

    harness.runner.client_factory = make
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.store.get(job['id'])['state'] == 'failed'
    assert all(not client.calls for client in harness.clients)


def test_worker_restart_after_started_attempt_never_replays_mcp_write(harness):
    job = harness.admit()
    claim = harness.store.claim('old-worker', {contract.ADAPTER}, lease_seconds=30)
    harness.store.running(claim)
    harness.clock[0] += 31
    harness.store.reconcile()
    assert harness.store.get(job['id'])['state'] == 'needs_attention'
    assert harness.store.counts()['reserved'] == 1
    assert not TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.clients == []


def test_stopping_observer_does_not_claim_remote_cancellation(harness):
    job = harness.admit()
    stop = threading.Event()
    factory = harness.runner.client_factory

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)

        def during_call():
            stop.set()
            assert client.calls[-1][2]['cancel_event'].wait(timeout=2)
            client.result = {'ok': False, 'completion': 'unknown', 'error': 'Observation stopped'}

        client.before_call = during_call
        return client

    harness.runner.client_factory = make
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once(stop)
    saved = harness.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert harness.store.counts()['reserved'] == 1
    assert not TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert sum(len(client.calls) for client in harness.clients) == 1


def test_authorization_lookup_does_not_discover_or_start_an_unrelated_server(harness, monkeypatch):
    import config_loader
    import mcp_client

    monkeypatch.setattr(mcp_client.MCPManager, '__init__',
        lambda *_args, **_kwargs: pytest.fail('Admission must not instantiate all configured clients'))
    with config_loader.config_scope('cloud'):
        evidence = harness.runner.authorize_tools([NAME], registry=harness.registry('cloud'))
    assert evidence[NAME]['adapter'] == contract.ADAPTER
    assert harness.clients == []


@pytest.mark.parametrize('mutation', ['selected', 'operator', 'source', 'mode', 'policy', 'timeout'])
def test_worker_rejects_a_saved_authorization_mismatch_before_remote_write(harness, monkeypatch, mutation):
    job = harness.admit()
    original = harness.store.authorization

    def changed(reference):
        evidence = copy.deepcopy(original(reference))
        if mutation == 'selected':
            evidence['selected'] = []
        elif mutation == 'policy':
            evidence['tool_policies'][NAME]['schema_sha256'] = 'stale-schema'
        elif mutation == 'timeout':
            evidence['tool_policies'][NAME]['timeout_seconds'] = 900
        else:
            evidence[mutation] = 'different'
        return evidence

    monkeypatch.setattr(harness.store, 'authorization', changed)
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.store.get(job['id'])['state'] == 'failed'
    assert all(not client.calls for client in harness.clients)


def test_queued_cancellation_prevents_any_mcp_connection(harness):
    job = harness.admit()
    harness.store.request_cancel(job['id'], job['revision'], supported_adapters=set())
    assert not TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert harness.store.get(job['id'])['state'] == 'cancelled'
    assert harness.clients == []


def test_running_remote_mcp_job_cannot_claim_cancellation(harness):
    from lib.background_tasks import TaskError

    job = harness.admit()
    claim = harness.store.claim('running-fixture', {contract.ADAPTER})
    harness.store.running(claim)
    running = harness.store.get(job['id'])
    with pytest.raises(TaskError, match='cannot acknowledge'):
        harness.store.request_cancel(job['id'], running['revision'], supported_adapters=set())
    assert harness.store.get(job['id'])['state'] == 'running'


def test_prompt_guard_sees_original_content_before_truncation_and_audit(harness, monkeypatch):
    from lib.background_tasks import worker as worker_module

    job = harness.admit()
    factory = harness.runner.client_factory
    original = 'x' * (2 * 1024 * 1024) + 'scan this final marker'
    seen = []

    def make(*args, **kwargs):
        client = factory(*args, **kwargs)
        client.result['data'] = {'long_report': original}
        return client

    def review(tool, result, **kwargs):
        seen.append((tool, result['data']['long_report'], kwargs['mode']))
        return result

    harness.runner.client_factory = make
    monkeypatch.setattr(worker_module, 'review_tool_result', review)
    assert TaskWorker(harness.store, {contract.ADAPTER: harness.runner}).run_once()
    assert seen == [(NAME, original, 'cloud')]
    assert harness.store.get(job['id'])['result']['result_truncated'] is True


def test_result_compaction_keeps_artifact_references_after_large_fields():
    from lib.background_tasks.models import MAX_RESULT_BYTES, canonical_json

    value = {'ok': True, 'completion': 'completed', 'data': {
        'large': ['x' * 100000 for _ in range(100)],
        'saved': {'stash_ref': 'stash://fixture-space/fixture-file'},
    }}
    result = binding.bounded_result(value)
    assert result['data']['saved']['stash_ref'] == value['data']['saved']['stash_ref']
    assert len(canonical_json(result, MAX_RESULT_BYTES)) < MAX_RESULT_BYTES
