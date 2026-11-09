"""Per-server MCP execution budgets must reach every transport guard."""

import io
import json
from threading import TIMEOUT_MAX
from types import SimpleNamespace
from unittest.mock import Mock

import mcp_client
import pytest
import requests
from mcp_client import MCPManager, MCPRemoteClient, probe_remote_tools


class ImmediateThread:
    joins = []

    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)

    def join(self, timeout=None):
        self.joins.append(timeout)

    def is_alive(self):
        return False


@pytest.fixture
def clock(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr(mcp_client.time, 'monotonic', lambda: elapsed[0])
    ImmediateThread.joins = []
    monkeypatch.setattr(mcp_client, 'Thread', ImmediateThread)
    return elapsed


def remote(timeout=None, transport='http', *, overrides=None):
    client = MCPRemoteClient('fixture', 'https://mcp.example.test/mcp', transport,
                             tool_call_timeout_seconds=timeout,
                             tool_call_timeout_overrides=overrides,
                             http_requester=lambda method, url, **kwargs:
                                 getattr(requests, method.lower())(url, **kwargs))
    client._initialized = True
    client._session_id = 'fixture-session'
    client._sse_endpoint = 'https://mcp.example.test/messages'
    return client


def reply(payload, *, sse=False, status=200):
    response = requests.Response()
    response.status_code = status
    response.headers['Content-Type'] = 'text/event-stream' if sse else 'application/json'
    body = ('data: ' + json.dumps(payload) + '\n\n') if sse else json.dumps(payload)
    response._content = body.encode()
    response._content_consumed = True
    response.raw = io.BytesIO(response._content)
    return response


@pytest.mark.parametrize('sse', [False, True])
def test_explicit_budget_allows_google_sized_sixty_second_http_result(clock, monkeypatch, sse):
    monkeypatch.setenv('MCP_TOOL_CALL_TIMEOUT_SECONDS', '35')
    client = remote(90)
    observed = []

    def post(url, **kwargs):
        budget = mcp_client._remote_call_budget.get()
        observed.append((kwargs['timeout'], budget.deadline))
        # Advance a controlled clock past both previous 30s/35s limits.
        clock[0] = 60
        return reply({'id': 1, 'result': {'content': [{'type': 'text', 'text': 'done'}]}}, sse=sse)

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('lookup', {})['ok']
    assert observed == [((30, 90), 90)]
    assert ImmediateThread.joins == [90]
    assert client._call_budgets == {}
    assert mcp_client._remote_call_budget.get() is None
    assert client.get_proxy_log_metadata()['policy'] == 'inherit'


@pytest.mark.parametrize('environment,expected', [(None, 35), ('77', 77)])
def test_unconfigured_server_preserves_global_worker_and_thirty_second_reads(clock, monkeypatch, environment, expected):
    if environment is None:
        monkeypatch.delenv('MCP_TOOL_CALL_TIMEOUT_SECONDS', raising=False)
    else:
        monkeypatch.setenv('MCP_TOOL_CALL_TIMEOUT_SECONDS', environment)
    client = remote()
    observed = []

    def post(url, **kwargs):
        observed.append(kwargs['timeout'])
        return reply({'id': 1, 'result': {'content': []}})

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('lookup', {})['ok']
    assert observed == [(30, 30)]
    assert ImmediateThread.joins == [expected]
    assert client.tool_call_timeout_seconds is None


def test_explicit_budget_extends_legacy_sse_wait_and_post_read(clock, monkeypatch):
    client = remote(90, 'sse')
    observed = []

    class DelayedQueue:
        def empty(self):
            return True

        def get(self, timeout):
            observed.append(('queue', timeout))
            clock[0] = 60
            return {'id': 1, 'result': {'content': [{'type': 'text', 'text': 'done'}]}}

    def post(url, **kwargs):
        observed.append(('post', kwargs['timeout']))
        return reply(None, status=202)

    client._sse_response_queue = DelayedQueue()
    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('lookup', {})['ok']
    assert observed == [('post', (30, 90)), ('queue', 90)]
    assert ImmediateThread.joins == [90]


def test_sse_listener_read_can_outlast_long_tool_but_connect_remains_bounded(monkeypatch):
    client = remote(90, 'sse')
    request = Mock(return_value=reply(None))
    monkeypatch.setattr(client, '_http_request', request)
    client._sse_listener()
    assert request.call_args.kwargs['timeout'] == (30, 90)


def test_long_tool_override_does_not_extend_initialization_or_discovery(clock, monkeypatch):
    client = remote(90)
    client._initialized = False
    observed = []

    def post(url, **kwargs):
        observed.append((kwargs['json']['method'], kwargs['timeout']))
        return reply({'result': {'tools': [{'name': 'lookup'}]}})

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    client.start()
    assert client.list_tools() == [{'name': 'lookup'}]
    assert observed == [('initialize', 30), ('notifications/initialized', 10), ('tools/list', 30)]

    client = remote(90)
    client._initialized = False
    observed.clear()
    assert probe_remote_tools(client, timeout_seconds=3) == [{'name': 'lookup'}]
    assert observed == [('initialize', (3, 3)), ('notifications/initialized', (3, 3)), ('tools/list', (3, 3))]
    assert ImmediateThread.joins == [3]


def test_configured_read_still_obeys_an_earlier_call_deadline(clock, monkeypatch):
    client = remote(90)
    request = Mock(return_value=reply({'id': 1, 'result': {'content': []}}))
    monkeypatch.setattr(mcp_client.requests, 'post', request)
    budget = mcp_client._RemoteCallBudget(deadline=12)
    token = mcp_client._remote_call_budget.set(budget)
    try:
        client._send_request('tools/call', {'name': 'lookup'})
        assert request.call_args.kwargs['timeout'] == (12, 12)
        budget.cancelled.set()
        with pytest.raises(requests.Timeout, match='deadline'):
            client._send_request('tools/call', {'name': 'lookup'})
    finally:
        mcp_client._remote_call_budget.reset(token)
    assert request.call_count == 1


def test_configured_timeout_never_replays_an_ambiguous_write(clock, monkeypatch):
    client = remote(90)
    request = Mock(side_effect=requests.Timeout('read timeout after write admission'))
    restart = Mock()
    monkeypatch.setattr(mcp_client.requests, 'post', request)
    monkeypatch.setattr(client, '_force_restart', restart)
    result = client.call_tool('create', {'name': 'one'})
    assert not result['ok']
    assert 'read timeout after write admission' in result['error']
    request.assert_called_once()
    restart.assert_called_once()
    assert client._call_budgets == {}


@pytest.mark.parametrize('value', [0, -1, True, False, '90', [], {}, float('nan'), float('inf'), -float('inf'), TIMEOUT_MAX, 10**1000])
def test_invalid_per_server_budgets_are_rejected_before_worker_start(value):
    with pytest.raises(ValueError, match='tool_call_timeout_seconds'):
        remote(value)


@pytest.mark.parametrize('value', [0.25, 90, 120.5])
def test_positive_finite_budgets_are_preserved(value):
    assert remote(value).tool_call_timeout_seconds == value


@pytest.mark.parametrize('sse', [False, True])
def test_script_timeout_override_covers_a_long_result_and_preserves_other_google_calls(clock, monkeypatch, sse):
    client = remote(90, overrides={'run_script_function': 390})
    observed = []

    def post(url, **kwargs):
        budget = mcp_client._remote_call_budget.get()
        name = kwargs['json']['params']['name']
        observed.append((name, kwargs['timeout'], budget.deadline, budget.managed_http))
        if name == 'run_script_function':
            clock[0] += 135
        return reply({'id': 1, 'result': {'content': [{'type': 'text', 'text': 'done'}]}}, sse=sse)

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('run_script_function', {})['ok']
    assert client.call_tool('get_doc_content', {})['ok']
    assert observed == [('run_script_function', (30, 390), 390, True),
                        ('get_doc_content', (30, 90), 225, False)]
    assert ImmediateThread.joins == [390, 90]
    assert client.tool_call_timeout_seconds == 90
    assert client.tool_call_timeout_overrides == {'run_script_function': 390}


def test_explicit_call_budget_and_deadline_win_over_configured_script_override(clock, monkeypatch):
    client = remote(90, overrides={'run_script_function': 390})
    observed = []

    def post(url, **kwargs):
        observed.append((kwargs['timeout'], mcp_client._remote_call_budget.get().deadline))
        return reply({'id': 1, 'result': {'content': []}})

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('run_script_function', {}, timeout_seconds=45, deadline=20)['ok']
    assert observed == [((20, 20), 20)]
    assert client.get_tool_call_timeout_seconds('run_script_function') == 390


@pytest.mark.parametrize('status', [307, 308])
def test_foreground_script_override_does_not_replay_a_redirect(clock, monkeypatch, status):
    client = remote(90, overrides={'run_script_function': 390})
    response = reply({}, status=status)
    response.headers['Location'] = 'https://another.test/mcp'
    post = Mock(return_value=response)
    monkeypatch.setattr(mcp_client.requests, 'post', post)
    result = client.call_tool('run_script_function', {})
    assert not result['ok']
    assert 'completion' not in result
    post.assert_called_once()
    assert post.call_args.kwargs['allow_redirects'] is False


def test_script_override_keeps_initialization_and_discovery_limits(clock, monkeypatch):
    client = remote(90, overrides={'run_script_function': 390})
    client._initialized = False
    observed = []

    def post(url, **kwargs):
        observed.append((kwargs['json']['method'], kwargs['timeout']))
        return reply({'result': {'tools': []}})

    monkeypatch.setattr(mcp_client.requests, 'post', post)
    client.start()
    client.list_tools()
    assert observed == [('initialize', 30), ('notifications/initialized', 10), ('tools/list', 30)]


def test_legacy_sse_stream_can_carry_the_long_script_without_extending_other_call_waits(clock, monkeypatch):
    client = remote(90, 'sse', overrides={'run_script_function': 390})
    stream = Mock(return_value=reply(None))
    with monkeypatch.context() as listener_patch:
        listener_patch.setattr(client, '_http_request', stream)
        client._sse_listener()
    assert stream.call_args.kwargs['timeout'] == (30, 390)
    observed = []

    class DelayedQueue:
        def empty(self):
            return True

        def get(self, timeout):
            observed.append(timeout)
            clock[0] += 135 if len(observed) == 1 else 1
            return {'id': len(observed), 'result': {'content': []}}

    client._sse_response_queue = DelayedQueue()
    post = Mock(return_value=reply(None, status=202))
    monkeypatch.setattr(mcp_client.requests, 'post', post)
    assert client.call_tool('run_script_function', {})['ok']
    assert client.call_tool('get_doc_content', {})['ok']
    assert observed == [390, 90]


@pytest.mark.parametrize('value', [True, [], '390', {'': 390}, {' script': 390}, {1: 390},
                                   {'run': None}, {'run': True}, {'run': 0}, {'run': -1},
                                   {'run': '390'}, {'run': float('nan')},
                                   {'run': float('inf')}, {'run': TIMEOUT_MAX}, {'run': 10**1000}])
def test_invalid_tool_timeout_overrides_are_rejected_before_dispatch(value):
    with pytest.raises(ValueError, match='tool_call_timeout_overrides'):
        remote(90, overrides=value)


def test_google_config_extends_only_exact_script_execution():
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parents[1] / 'config/mcp-servers.json').read_text())
    google = config['mcpServers']['google_workspace']
    client = remote(google['tool_call_timeout_seconds'], overrides=google['tool_call_timeout_overrides'])
    assert client.get_tool_call_timeout_seconds('run_script_function') == 390
    for tool in ('get_doc_content', 'manage_deployment', 'send_gmail_message', 'run_script_function_extra'):
        assert client.get_tool_call_timeout_seconds(tool) == 90


def test_manager_forwards_override_and_keeps_unconfigured_siblings_independent(tmp_path):
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'mcpServers': {
        'configured': {'type': 'http', 'url': 'https://one.test/mcp', 'tool_call_timeout_seconds': 90,
                       'tool_call_timeout_overrides': {'run_script_function': 390}},
        'default': {'type': 'http', 'url': 'https://two.test/mcp'},
        'invalid': {'type': 'sse', 'url': 'https://three.test/sse', 'tool_call_timeout_seconds': -3},
        'invalid_override': {'type': 'http', 'url': 'https://four.test/mcp',
                             'tool_call_timeout_overrides': {'run_script_function': False}},
    }}))
    manager = MCPManager(str(path))
    assert manager.servers['configured'].tool_call_timeout_seconds == 90
    assert manager.servers['configured'].get_tool_call_timeout_seconds('run_script_function') == 390
    assert manager.servers['configured'].get_tool_call_timeout_seconds('other_tool') == 90
    assert manager.servers['default'].tool_call_timeout_seconds is None
    assert 'invalid' not in manager.servers
    assert 'invalid_override' not in manager.servers


@pytest.mark.parametrize('tool,expected', [('run_script_function', 395), ('get_doc_content', 95)])
def test_executor_uses_the_same_tool_override_as_the_remote_call(monkeypatch, tool, expected):
    from orchestrator.executor import ToolExecutor

    client = remote(90, overrides={'run_script_function': 390})
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.mode = 'cloud'
    executor.registry = SimpleNamespace(mcp_clients={'remote': client},
                                       get_mcp_info=lambda name: ('remote', tool))
    executor.logger = Mock()
    future = Mock()
    future.result.return_value = {'ok': True}
    pool = Mock()
    pool.submit.return_value = future
    monkeypatch.setattr('orchestrator.executor.ThreadPoolExecutor', Mock(return_value=pool))
    assert executor._execute_mcp_tool('mcp_remote_' + tool, {})['ok']
    future.result.assert_called_once_with(timeout=expected)


@pytest.mark.parametrize('configured,environment,expected', [(90, None, 95), (90, '2', 95), (None, None, 45), (None, '17', 17)])
def test_executor_guard_allows_explicit_budget_plus_cleanup_and_retains_legacy_fallback(monkeypatch, configured, environment, expected):
    from orchestrator.executor import ToolExecutor

    if environment is None:
        monkeypatch.delenv('MCP_EXECUTOR_TIMEOUT_SECONDS', raising=False)
    else:
        monkeypatch.setenv('MCP_EXECUTOR_TIMEOUT_SECONDS', environment)
    client = SimpleNamespace(tool_call_timeout_seconds=configured, call_tool=Mock(return_value={'ok': True}))
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.mode = 'cloud'
    executor.registry = SimpleNamespace(mcp_clients={'remote': client}, get_mcp_info=lambda name: ('remote', 'lookup'))
    executor.logger = Mock()
    future = Mock()
    future.result.return_value = {'ok': True}
    pool = Mock()
    pool.submit.return_value = future
    monkeypatch.setattr('orchestrator.executor.ThreadPoolExecutor', Mock(return_value=pool))
    assert executor._execute_mcp_tool('mcp_remote_lookup', {})['ok']
    future.result.assert_called_once_with(timeout=expected)
    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_executor_timeout_still_cancels_client_once_without_waiting_or_replaying(monkeypatch):
    from concurrent.futures import TimeoutError as FutureTimeout

    from orchestrator.executor import ToolExecutor

    client = SimpleNamespace(tool_call_timeout_seconds=90, call_tool=Mock(), _force_restart=Mock())
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.mode = 'cloud'
    executor.registry = SimpleNamespace(mcp_clients={'remote': client}, get_mcp_info=lambda name: ('remote', 'create'))
    executor.logger = Mock()
    future = Mock()
    future.result.side_effect = FutureTimeout()
    pool = Mock()
    pool.submit.return_value = future
    monkeypatch.setattr('orchestrator.executor.ThreadPoolExecutor', Mock(return_value=pool))
    result = executor._execute_mcp_tool('mcp_remote_create', {'name': 'one'})
    assert not result['ok']
    assert result['error'] == 'Executor timeout after 95s'
    future.result.assert_called_once_with(timeout=95)
    pool.submit.assert_called_once()
    client._force_restart.assert_called_once()
    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_expired_configured_worker_cancels_its_budget_without_starting_another_request(monkeypatch):
    class UnfinishedThread(ImmediateThread):
        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(mcp_client, 'Thread', UnfinishedThread)
    client = remote(90)
    request = Mock()
    monkeypatch.setattr(client, '_send_request', request)
    result = client.call_tool('create', {'name': 'one'})
    assert not result['ok'] and 'timed out after 90' in result['error']
    assert len(client._call_budgets) == 1
    budget = next(iter(client._call_budgets.values()))
    assert budget.cancelled.is_set()
    request.assert_not_called()
