"""Web admission through real MCP HTTP, worker completion and late projection.

Only model decisions and the remote Google service are scripted. Socket.IO,
conversation JSON, SQLite authorization/leases, MCP transport, result screening,
and tools-disabled continuation delivery use the production implementations.
"""

import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import config_loader
import pytest
from test_background_mcp import ARGUMENTS, NAME, RAW_NAME, SERVER, TOOL_INFO
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks import production
from lib.background_tasks.mcp_tool import MCPToolRunner
from lib.background_tasks.worker import TaskWorker
from lib.mcp_background_contract import ADAPTER

MODE_LOADER = config_loader._load_mode_config


@pytest.fixture
def mcp_web(web_tasks, monkeypatch):
    import llm_provider
    import orchestrator_v2
    import tool_profiles
    from mcp_client import MCPRemoteClient
    from tool_schema import ToolRegistry

    from lib import config_loader as package_config

    h = web_tasks
    # Replace the unrelated fixture worker with the real reviewed MCP worker.
    h.worker.terminate()
    h.worker.communicate(timeout=6)
    submitted, release = threading.Event(), threading.Event()
    calls, protocol, server_errors = [], [], []
    behavior = {'failed': False}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            method = request['method']
            protocol.append(method)
            if method.startswith('notifications/'):
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'isolated-google-fixture', 'version': '1'}}
            elif method == 'tools/list':
                result = {'tools': [copy.deepcopy(TOOL_INFO)]}
            elif method == 'tools/call':
                params = request['params']
                metadata = params.get('_meta', {}).get('jarvis/background_execution', {})
                calls.append({'name': params['name'], 'arguments': params['arguments'],
                    'metadata': metadata, 'authorization': self.headers.get('Authorization')})
                submitted.set()
                if not release.wait(25):
                    server_errors.append('The test did not release the remote response')
                text = (behavior['error'] if behavior['failed'] else
                        'Automation complete. Document ID: fixture-document. '
                        'https://docs.google.com/document/d/fixture-document/edit')
                result = {'isError': behavior['failed'], 'content': [{'type': 'text', 'text': text}],
                    '_meta': {'jarvis/background_execution': {
                        'version': 1, 'job_id': metadata.get('job_id'), 'completion': 'completed'}}}
            else:
                server_errors.append('Unexpected MCP method: ' + method)
                result = {'isError': True, 'content': [{'type': 'text', 'text': 'Unsupported method'}]}
            data = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            if method == 'initialize':
                self.send_header('Mcp-Session-Id', 'isolated-mcp-session')
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = h.tmp / 'mcp-installation'
    (root / 'config').mkdir(parents=True)
    (root / 'skills' / 'profiles').mkdir(parents=True)
    (root / 'skills' / 'profiles' / 'default.json').write_text('{"overrides": {}}')
    endpoint = f'http://127.0.0.1:{server.server_port}/mcp'
    for mode in ('cloud', 'local'):
        (root / 'config' / f'{mode}.env').write_text(
            f'GOOGLE_WORKSPACE_MCP_ENABLED=true\nGOOGLE_ACCOUNT={mode}@fixture.invalid\n'
            f'GOOGLE_WORKSPACE_MCP_TOKEN=fixture-{mode}-token\n'
            f'GOOGLE_WORKSPACE_MCP_URL={endpoint}\nJARVIS_TOOL_PROFILE=default\n'
            'STASH_ENABLED=false\n'
        )
    definition = {
        'type': 'http', 'url': endpoint, 'url_env': 'GOOGLE_WORKSPACE_MCP_URL',
        'proxy_policy': 'off', 'tool_call_timeout_seconds': 90,
        'enabled': True, 'enabled_env': 'GOOGLE_WORKSPACE_MCP_ENABLED',
        'required_env': ['GOOGLE_WORKSPACE_MCP_TOKEN', 'GOOGLE_ACCOUNT'],
        'headers': {'Authorization': 'Bearer ${GOOGLE_WORKSPACE_MCP_TOKEN}'},
        'tool_defaults': {'user_google_email': '${GOOGLE_ACCOUNT}'},
    }
    (root / 'config' / 'mcp-servers.json').write_text(json.dumps({'mcpServers': {SERVER: definition}}))
    for loader in (config_loader, package_config):
        monkeypatch.setattr(loader, 'get_project_root', lambda: root)
    monkeypatch.setattr(config_loader, '_load_mode_config', MODE_LOADER)
    monkeypatch.setattr(tool_profiles, 'get_project_root', lambda: root)
    monkeypatch.setattr(production, 'ROOT', root)
    runner = MCPToolRunner(root)
    schema_client = MCPRemoteClient(SERVER, endpoint, 'http', proxy_policy='off')
    schema_client.tool_defaults = {'user_google_email': 'cloud@fixture.invalid'}
    schema = ToolRegistry.schema_from_mcp_tool(SERVER, schema_client, definition, copy.deepcopy(TOOL_INFO))
    registry = h.background.registry
    original_get = registry.get_tool
    registry.get_tool = lambda name: schema if name == NAME else original_get(name)
    registry.list_tools = lambda: [NAME, 'get_time']
    registry.is_mcp_tool = lambda name: name == NAME
    registry.get_mcp_info = lambda _name: (SERVER, RAW_NAME)
    registry.mcp_clients = {}  # A foreground fallback cannot use this worker's client.
    h.background.adapters = {NAME: ADAPTER}
    h.tasks.configure(background_tools=[NAME])
    h.tasks.touch_worker('mcp-journey-ready', {ADAPTER})
    original_factory = orchestrator_v2.Orchestrator

    def factory(*args, **kwargs):
        instance = original_factory(*args, **kwargs)
        decisions = []

        def route(transcript, **_kwargs):
            from router_v2 import extract_current_user_request
            if not decisions:
                name = 'get_time' if 'What time is it?' in extract_current_user_request(transcript) else NAME
                decisions.append(name)
                return {'intent': 'tool', 'tool_name': name,
                    'arguments': {} if name == 'get_time' else copy.deepcopy(ARGUMENTS),
                    'tool_call_id': 'scripted-first-decision'}
            return {'intent': 'qa', 'text_response': 'The foreground clock returned.'
                if decisions[0] == 'get_time' else 'Queued; results will return here.'}

        instance.router.route = route
        return instance

    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', factory)
    summaries = []

    def configured_provider(**options):
        assert options.get('disable_server_side_tools') is True

        def chat(prompt, **kwargs):
            assert 'Do not execute tools' in kwargs['system_prompt']
            summaries.append({'options': options, 'evidence': json.loads(prompt)})
            evidence = summaries[-1]['evidence']
            return (evidence['result']['error'] if evidence['state'] == 'failed' else
                    'The automation completed and created the document.')

        return options['provider_override'], options['model_override'], SimpleNamespace(chat=chat)

    monkeypatch.setattr(llm_provider, 'create_configured_provider', configured_provider)
    h.background.synthesize = h.background._synthesize
    h.mcp = SimpleNamespace(root=root, calls=calls, protocol=protocol, submitted=submitted,
        release=release, summaries=summaries, runner=runner, behavior=behavior, errors=server_errors)
    (h.root / 'foreground_finish').touch()
    workers = []

    def start_worker():
        worker = TaskWorker(h.tasks, {ADAPTER: runner})
        running = threading.Thread(target=worker.run_once)
        running.start()
        workers.append(running)
        return worker

    h.mcp.start_worker = start_worker
    try:
        yield h
    finally:
        release.set()
        for running in workers:
            running.join(8)
            assert not running.is_alive()
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not server_errors


@pytest.mark.parametrize('error', [None, 'Error: Controlled Apps Script exception',
                                   'Error: timeout while updating the sheet'])
def test_web_mcp_response_delivers_once_after_intervening_foreground_turn_and_reconnect(mcp_web, error):
    h = mcp_web
    failed = error is not None
    h.mcp.behavior['failed'] = failed
    h.mcp.behavior['error'] = error
    h.client.emit('chat:send', {'message': 'Run my owned Google Apps Script automation.', 'mode': 'cloud'})
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    cid = job['conversation_id']
    eventually(lambda: h.tasks.get(job['id'])['dispatch_state'] == 'ready')
    receipt = h.store.get_conversation(cid)
    assert receipt['run']['status'] == 'completed'
    assert receipt['messages'][-1]['tools_used'] == []
    assert len(receipt['messages'][-1]['data']['pending_jobs']) == 1
    assert h.mcp.calls == []
    worker = h.mcp.start_worker()
    assert h.mcp.submitted.wait(6)
    assert h.tasks.get(job['id'])['state'] == 'running'
    eventually(lambda: h.store.get_conversation(cid)['messages'][1]['data']
               ['background_jobs'][job['id']]['state'] == 'running')
    h.client.disconnect()
    reconnected = h.connect()
    reconnected.emit('conversation:load', {'conversation_id': cid})
    restored = next(event['args'][0]['conversation'] for event in reconnected.get_received()
                    if event['name'] == 'conversation:loaded')
    assert restored['messages'][1]['data']['background_jobs'][job['id']]['state'] == 'running'
    reconnected.emit('tasks:subscribe', {'conversation_id': cid})
    reconnected.get_received()
    reconnected.emit('chat:send', {'message': 'What time is it?', 'conversation_id': cid, 'mode': 'local'})
    eventually(lambda: (h.root / 'foreground_started').exists())
    eventually(lambda: len(h.store.get_conversation(cid)['messages']) == 4)
    eventually(lambda: h.store.get_conversation(cid)['run']['status'] == 'completed')
    conversation = h.store.get_conversation(cid)
    assert conversation['run']['status'] == 'completed'
    assert conversation['messages'][3]['tools_used'] == ['get_time']
    assert h.tasks.get(job['id'])['state'] == 'running'
    assert h.mcp.summaries == []
    h.mcp.release.set()
    eventually(lambda: h.tasks.get(job['id'])['delivery_state'] == 'delivered', timeout=10)
    saved = h.tasks.get(job['id'])
    assert saved['state'] == ('failed' if failed else 'succeeded')
    assert saved['result']['ok'] is (not failed)
    assert saved['result']['completion'] == 'completed'
    assert saved['mode'] == 'cloud'
    assert h.tasks.counts()['reserved'] == 0
    conversation = h.store.get_conversation(cid)
    continuations = [message for message in conversation['messages']
                     if message.get('data', {}).get('_kind') == 'continuation']
    assert len(continuations) == 1
    assert continuations[0]['tools_used'] == []
    assert continuations[0]['data']['parent_message_id'] == job['admission']['request_id']
    assert continuations[0]['data'][NAME]['ok'] is (not failed)
    if failed:
        assert error in continuations[0]['content']
        assert continuations[0]['data'][NAME]['error'] == error
        assert not continuations[0]['data'].get('_background_timeout')
    delivered_events = []

    def continuation_arrived():
        delivered_events.extend(reconnected.get_received())
        return any(event['name'] == 'chat:continuation' for event in delivered_events)

    eventually(continuation_arrived)
    assert len([event for event in delivered_events if event['name'] == 'chat:continuation']) == 1
    assert len([event for event in delivered_events if event['name'] == 'chat:response']) == 1
    assert len(h.mcp.summaries) == 1
    summary = h.mcp.summaries[0]
    assert summary['options']['mode'] == 'cloud'
    assert summary['options']['disable_server_side_tools'] is True
    assert summary['evidence']['current_history'][-1]['content'] == 'The foreground clock returned.'
    assert len(h.mcp.calls) == 1
    remote = h.mcp.calls[0]
    assert remote['name'] == RAW_NAME
    assert remote['arguments'] == {**ARGUMENTS, 'user_google_email': 'cloud@fixture.invalid'}
    assert remote['authorization'] == 'Bearer fixture-cloud-token'
    assert remote['metadata']['job_id'] == job['id']
    assert 0 < remote['metadata']['deadline_unix'] - time.time() <= 420
    h.background.drain_once(inline=True)
    assert not worker.run_once()
    assert len(h.mcp.summaries) == len(h.mcp.calls) == 1
    reconnected.emit('conversation:load', {'conversation_id': cid})
    restored = next(event['args'][0]['conversation'] for event in reconnected.get_received()
                    if event['name'] == 'conversation:loaded')
    assert len(restored['messages']) == 5
    assert restored['messages'][1]['data']['background_jobs'][job['id']]['state'] == saved['state']
    assert len([message for message in restored['messages']
                if message.get('data', {}).get('_kind') == 'continuation']) == 1
    if failed:
        assert error in restored['messages'][-1]['content']
        assert restored['messages'][-1]['data'][NAME]['error'] == error
