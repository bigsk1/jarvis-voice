"""A background MCP observation owns one deadline and cannot replay a write."""

import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Barrier, Event
from unittest.mock import Mock

import mcp_client
import pytest
import requests
from mcp_client import MCPRemoteClient
from test_mcp_remote_timeouts import ImmediateThread, reply

META = {"job_id": "job-fixture", "deadline_unix": 4000.0}
META_KEY = "jarvis/background_execution"


@pytest.fixture
def clock(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: elapsed[0])
    ImmediateThread.joins = []
    monkeypatch.setattr(mcp_client, "Thread", ImmediateThread)
    return elapsed


def remote():
    client = MCPRemoteClient("google_workspace", "https://mcp.example.test/mcp", "http",
                             tool_call_timeout_seconds=90,
                             http_requester=lambda method, url, **kwargs:
                                 getattr(requests, method.lower())(url, **kwargs))
    client._initialized = True
    client._session_id = "fixture-session"
    return client


def result(*, completion="completed", job_id="job-fixture", error=False, metadata=True):
    raw = {"content": [{"type": "text", "text": "Execution failed" if error else "done"}],
           "isError": error}
    if metadata:
        raw["_meta"] = {META_KEY: {"version": 1, "job_id": job_id,
                                     "completion": completion}}
    return {"id": 1, "result": raw}


def test_call_override_extends_only_its_own_read_without_mutating_environment(clock, monkeypatch):
    monkeypatch.setenv("MCP_TOOL_CALL_TIMEOUT_SECONDS", "35")
    client = remote()
    observed = []

    def post(url, **kwargs):
        observed.append((kwargs["timeout"], mcp_client._remote_call_budget.get().deadline))
        clock[0] = 120
        return reply(result())

    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, timeout_seconds=390, deadline=300,
                             execution_metadata=META)
    assert saved["ok"] and saved["completion"] == "completed"
    assert observed == [((30, 300), 300)]
    assert client.tool_call_timeout_seconds == 90
    assert mcp_client.os.environ["MCP_TOOL_CALL_TIMEOUT_SECONDS"] == "35"
    assert mcp_client._remote_call_budget.get() is None
    assert client._call_budgets == {}


@pytest.mark.parametrize("cancelled", [False, True])
def test_expired_or_cancelled_observation_is_rejected_before_sending(clock, monkeypatch, cancelled):
    client = remote()
    send = Mock()
    monkeypatch.setattr(client, "_send_request", send)
    event = Event()
    if cancelled:
        event.set()
    saved = client.call_tool("run_script_function", {}, deadline=100 if cancelled else -1,
                             cancel_event=event, execution_metadata=META)
    assert not saved["ok"] and saved["completion"] == "rejected"
    send.assert_not_called()


def test_remaining_deadline_and_job_identity_reach_protocol_metadata(clock, monkeypatch):
    client = remote()
    post = Mock(return_value=reply(result()))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    client.call_tool("run_script_function", {"function_name": "one"},
                     timeout_seconds=390, deadline=12, execution_metadata=META)
    sent = post.call_args.kwargs
    assert sent["timeout"] == (12, 12)
    assert sent["json"]["params"]["_meta"] == {META_KEY: {"version": 1, **META}}
    assert sent["json"]["params"]["arguments"] == {"function_name": "one"}


@pytest.mark.parametrize("error", [False, True])
def test_matching_service_evidence_proves_a_settled_script(clock, monkeypatch, error):
    client = remote()
    post = Mock(return_value=reply(result(error=error)))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert saved["completion"] == "completed"
    assert saved["ok"] is not error
    post.assert_called_once()


@pytest.mark.parametrize("payload", [
    result(metadata=False), result(job_id="other-job"), result(completion="invented"),
])
def test_success_envelope_without_matching_service_evidence_remains_unknown(clock, monkeypatch, payload):
    client = remote()
    post = Mock(return_value=reply(payload))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert saved["completion"] == "unknown"
    post.assert_called_once()


def test_lost_write_response_is_unknown_and_never_replayed(clock, monkeypatch):
    client = remote()
    post = Mock(side_effect=requests.Timeout("response lost after request was sent"))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert not saved["ok"] and saved["completion"] == "unknown"
    post.assert_called_once()


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "390"])
def test_invalid_call_budget_never_starts_transport(clock, monkeypatch, value):
    client = remote()
    send = Mock()
    monkeypatch.setattr(client, "_send_request", send)
    with pytest.raises(ValueError):
        client.call_tool("run_script_function", {}, timeout_seconds=value)
    send.assert_not_called()


def test_cancellation_stops_waiting_for_the_isolated_observer(monkeypatch):
    client = remote()
    entered, release, cancelled = Event(), Event(), Event()

    def post(url, **kwargs):
        entered.set()
        release.wait(timeout=3)
        return reply(result())

    monkeypatch.setattr(mcp_client.requests, "post", post)
    waiter = mcp_client.Thread(target=lambda: (entered.wait(timeout=1), cancelled.set()), daemon=True)
    waiter.start()
    started = time.monotonic()
    try:
        saved = client.call_tool("run_script_function", {}, timeout_seconds=10,
                                 cancel_event=cancelled, execution_metadata=META)
        assert time.monotonic() - started < 1.5
        assert not saved["ok"] and saved["completion"] == "unknown"
    finally:
        release.set()
        waiter.join(timeout=1)


def test_foreground_result_does_not_gain_background_metadata(clock, monkeypatch):
    client = remote()
    post = Mock(return_value=reply(result(metadata=False)))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {})
    assert saved["ok"] and "completion" not in saved
    assert "_meta" not in post.call_args.kwargs["json"]["params"]


def test_worker_discovery_does_not_start_after_deadline_or_cancel(clock, monkeypatch):
    client = remote()
    start = Mock()
    monkeypatch.setattr(client, "start", start)
    assert mcp_client.probe_remote_tools(client, deadline=-1) == []
    cancelled = Event()
    cancelled.set()
    assert mcp_client.probe_remote_tools(client, deadline=100, cancel_event=cancelled) == []
    start.assert_not_called()


@pytest.mark.parametrize('interruption', ['deadline', 'cancel'])
def test_strict_discovery_reports_interruption_without_starting_client(clock, monkeypatch, interruption):
    client = remote()
    start = Mock()
    monkeypatch.setattr(client, 'start', start)
    cancelled = Event()
    if interruption == 'cancel':
        cancelled.set()

    with pytest.raises(mcp_client.MCPDiscoveryError):
        mcp_client.probe_remote_tools(client, deadline=-1 if interruption == 'deadline' else 100,
            cancel_event=cancelled, raise_on_error=True)

    start.assert_not_called()


@pytest.mark.parametrize('failure', ['start', 'first_page', 'later_page', 'invalid_reply'])
def test_strict_discovery_never_confirms_a_partial_or_failed_catalog(clock, monkeypatch, failure):
    client = remote()
    responses = []

    def send(method, params=None):
        assert method == 'tools/list'
        responses.append(params)
        if failure == 'invalid_reply':
            return None
        if failure == 'later_page' and not params:
            return {'tools': [{'name': 'run_script_function'}], 'nextCursor': 'next-page'}
        raise requests.ConnectionError('private-connection-value')

    monkeypatch.setattr(client, '_send_request', send)
    if failure == 'start':
        monkeypatch.setattr(client, 'start', Mock(side_effect=requests.ConnectionError('private-start-value')))

    with pytest.raises(mcp_client.MCPDiscoveryError) as caught:
        mcp_client.probe_remote_tools(client, raise_on_error=True)

    assert 'private-' not in str(caught.value)
    assert client._tools_cache is None
    assert client._call_budgets == {}
    assert len(responses) == {'start': 0, 'first_page': 1, 'later_page': 2, 'invalid_reply': 1}[failure]


def test_strict_discovery_accepts_a_successful_empty_catalog(clock, monkeypatch):
    client = remote()
    request = Mock(return_value={'tools': []})
    monkeypatch.setattr(client, '_send_request', request)

    assert mcp_client.probe_remote_tools(client, raise_on_error=True) == []

    request.assert_called_once_with('tools/list', None)


@pytest.mark.parametrize('invalid_row', [
    None,
    {'name': ''},
    {'name': 'run_script_function', 'inputSchema': {'properties': 'malformed'}},
    {'name': 'run_script_function', 'inputSchema': {'properties': {'script_id': 'malformed'}}},
    {'name': 'run_script_function', 'inputSchema': {'required': 'script_id'}},
    {'name': 'run_script_function', 'inputSchema': {'required': [False]}},
    {'name': 'run_script_function', 'description': 123},
    {'name': 'run_script_function', 'annotations': ['malformed']},
    {'name': 'other_tool'},
])
def test_strict_discovery_rejects_filtered_rows_even_after_graceful_cache(clock, monkeypatch, invalid_row):
    client = remote()
    valid_row = {'name': 'other_tool'}
    request = Mock(return_value={'tools': [valid_row, invalid_row]})
    monkeypatch.setattr(client, '_send_request', request)
    assert client.list_tools() == [valid_row]

    with pytest.raises(mcp_client.MCPDiscoveryError):
        mcp_client.probe_remote_tools(client, raise_on_error=True)

    assert request.call_count == 2


@pytest.mark.parametrize('cursor', [False, 0, [], {}])
def test_strict_discovery_rejects_false_non_string_page_cursors(clock, monkeypatch, cursor):
    client = remote()
    request = Mock(return_value={'tools': [], 'nextCursor': cursor})
    monkeypatch.setattr(client, '_send_request', request)
    assert client.list_tools() == []

    with pytest.raises(mcp_client.MCPDiscoveryError):
        mcp_client.probe_remote_tools(client, raise_on_error=True)


def test_worker_discovery_uses_the_earlier_absolute_deadline(clock, monkeypatch):
    client = remote()
    client._initialized = False
    observed = []

    def post(url, **kwargs):
        observed.append((kwargs["json"]["method"], kwargs["timeout"]))
        return reply({"result": {"tools": [{"name": "run_script_function"}]}})

    monkeypatch.setattr(mcp_client.requests, "post", post)
    assert mcp_client.probe_remote_tools(client, timeout_seconds=3, deadline=1) == [
        {"name": "run_script_function"}]
    assert observed == [("initialize", (1, 1)), ("notifications/initialized", (1, 1)),
                        ("tools/list", (1, 1))]
    assert client._call_budgets == {}


def test_concurrent_clients_keep_independent_deadlines_and_foreground_reads(monkeypatch):
    barrier = Barrier(2)
    observed = {}

    def post(url, **kwargs):
        budget = mcp_client._remote_call_budget.get()
        observed[url] = (kwargs["timeout"], budget.execution_metadata)
        barrier.wait(timeout=2)
        return reply(result(metadata="background" in url))

    monkeypatch.setattr(mcp_client.requests, "post", post)
    background, foreground = remote(), remote()
    background.url = "https://background.test/mcp"
    foreground.url = "https://foreground.test/mcp"
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(background.call_tool, "run_script_function", {},
                           timeout_seconds=300, execution_metadata=META)
        right = pool.submit(foreground.call_tool, "run_script_function", {})
        assert left.result(timeout=3)["completion"] == "completed"
        assert "completion" not in right.result(timeout=3)
    assert 299 < observed[background.url][0][1] <= 300
    assert observed[background.url][1] == {"version": 1, **META}
    assert 89 < observed[foreground.url][0][1] <= 90
    assert observed[foreground.url][1] is None


@pytest.mark.parametrize("policy", ["prefer", "require"])
def test_proxy_response_loss_never_switches_routes_and_replays_a_background_write(clock, monkeypatch, policy):
    client = remote()
    client.proxy_policy = policy
    monkeypatch.setattr(mcp_client, "get_proxy_url_chain", lambda **kwargs: ["http://proxy.test:8080"])
    select = Mock(return_value=("http://proxy.test:8080", "LOCAL_PROXY"))
    monkeypatch.setattr(mcp_client, "select_reachable_proxy_url", select)
    post = Mock(side_effect=requests.Timeout("proxy lost write response"))
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert saved["completion"] == "unknown"
    post.assert_called_once()
    assert post.call_args.kwargs["proxies"]["https"] == "http://proxy.test:8080"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_unavailable_required_proxy_rejects_before_background_write(clock, monkeypatch):
    client = remote()
    client.proxy_policy = "require"
    monkeypatch.setattr(mcp_client, "get_proxy_url_chain", lambda **kwargs: ["http://proxy.test:8080"])
    monkeypatch.setattr(mcp_client, "select_reachable_proxy_url", Mock(return_value=None))
    post = Mock()
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert saved["completion"] == "rejected" and not saved["ok"]
    post.assert_not_called()


def test_background_write_does_not_follow_a_redirect(clock, monkeypatch):
    client = remote()
    response = reply({}, status=307)
    response.headers["Location"] = "https://another.test/mcp"
    post = Mock(return_value=response)
    monkeypatch.setattr(mcp_client.requests, "post", post)
    saved = client.call_tool("run_script_function", {}, execution_metadata=META)
    assert saved["completion"] == "unknown"
    post.assert_called_once()
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize('operation', ['tool', 'discovery', 'strict_discovery'])
@pytest.mark.parametrize('phase', ['headers', 'body'])
@pytest.mark.parametrize('cancel', [False, True])
def test_absolute_stop_closes_trickling_http_observer_and_peer(operation, phase, cancel):
    """A timely return also releases the actual reader thread and TCP socket."""
    import threading

    entered, peer_closed, release, cancelled = Event(), Event(), Event(), Event()
    submissions = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_POST(self):
            submissions.append(self.rfile.read(int(self.headers['Content-Length'])))
            if phase == 'headers':
                self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Trickle: ')
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '1000000')
                self.end_headers()
            entered.set()
            try:
                while not release.wait(.015):
                    self.wfile.write(b' ')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                peer_closed.set()
            finally:
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    client = MCPRemoteClient('google_workspace', f'http://127.0.0.1:{server.server_port}/mcp',
                             'http', proxy_policy='off', tool_call_timeout_seconds=90)
    client._initialized = True
    client._session_id = 'fixture-session'
    stop_request = None
    if cancel:
        def request_stop():
            if entered.wait(2):
                cancelled.set()
        stop_request = threading.Thread(target=request_stop)
        stop_request.start()
    try:
        started = time.monotonic()
        # The absolute budget includes thread dispatch and local HTTP startup.
        # Leave room for those under parallel-suite load; the unchanged 1.5s
        # assertion still rejects an observer kept alive by trickling bytes.
        budget = 5 if cancel else 1
        if operation == 'tool':
            saved = client.call_tool('run_script_function', {}, timeout_seconds=budget,
                cancel_event=cancelled, execution_metadata={
                    'job_id': 'trickle-fixture', 'deadline_unix': time.time() + budget})
            assert saved['ok'] is False and saved['completion'] == 'unknown'
        elif operation == 'strict_discovery':
            with pytest.raises(mcp_client.MCPDiscoveryError):
                mcp_client.probe_remote_tools(client, timeout_seconds=budget,
                    cancel_event=cancelled, raise_on_error=True)
        else:
            assert mcp_client.probe_remote_tools(client, timeout_seconds=budget,
                                                cancel_event=cancelled) == []
        assert time.monotonic() - started < 1.5
        assert entered.is_set()
        client.stop()
        deadline = time.monotonic() + 1
        while client._call_budgets and time.monotonic() < deadline:
            time.sleep(.01)
        assert client._call_budgets == {}, 'The actual HTTP observer is still running'
        assert peer_closed.wait(1), 'The peer kept a socket after observation ended'
        assert len(submissions) == 1
        assert client.tool_call_timeout_seconds == 90
    finally:
        release.set()
        cancelled.set()
        client.stop()
        if stop_request:
            stop_request.join(2)
        server.shutdown()
        server.server_close()
        serving.join(2)
