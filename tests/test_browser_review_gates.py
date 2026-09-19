"""The Browser Use commit gates: no replay, a terminal card, and pinned egress."""
import io
import json
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
import requests
from test_task_callbacks import configured, deliver, event

from lib.background_tasks import Admission, ReceiptEvidence
from lib.background_tasks.worker import TaskWorker
from lib.webhook_integrations.browser_service import BrowserService
from lib.webhook_integrations.contracts import ADAPTER
from lib.webhook_integrations.runner import LocalCallbackRunner, SubmissionRejected

pytest_plugins = ('test_browser_use',)


@pytest.mark.parametrize('outcome', ['lost_receipt', 'lost_record', 'rejected'])
def test_submission_receipt_outcomes_keep_callback_fence_or_finish_known_failure(tmp_path, monkeypatch, outcome):
    from lib.webhook_integrations import runner

    service, source, credential, _ = configured(tmp_path)
    admission = Admission('conversation', 0, 'request', 'call', 'callback_probe', ADAPTER,
                          'cloud', {}, 'authorization-call', 'web')
    job = service.store.admit(admission, authorization={
        'source': 'web', 'conversation_id': 'conversation', 'generation': 0, 'request_id': 'request',
        'mode': 'cloud', 'selected': ['callback_probe'], 'callback_sources': {'callback_probe': source['id']},
    })
    service.store.release(job['id'], ReceiptEvidence('conversation', 0, 'request', 'receipt', 'completed', True))
    submitted = {}

    def post(_url, payload, **_kwargs):
        submitted.update(payload)
        if outcome == 'lost_receipt':
            raise requests.ConnectionError('202 response was lost')
        if outcome == 'rejected':
            raise SubmissionRejected('HTTP 400')
        return {'remote_id': payload['attempt_id']}

    monkeypatch.setattr(runner, 'post_json', post)
    if outcome == 'lost_record':
        monkeypatch.setattr(service, 'record_submission', lambda *_: (_ for _ in ()).throw(OSError('receipt disk unavailable')))
    adapter = LocalCallbackRunner(service, {'callback_probe':
                                  (source['id'], {'type': 'object', 'properties': {}})})
    assert TaskWorker(service.store, {ADAPTER: adapter}).run_once()
    saved = service.store.get(job['id'])
    if outcome == 'rejected':
        assert saved['state'] == 'failed' and saved['callback_waiting'] == 0
        assert len(service.store.pending_deliveries()) == 1
        assert service.store.claim('second-worker', {ADAPTER}) is None
        return

    assert saved['state'] == 'running' and saved['callback_waiting'] == 1
    assert saved['fence'] > 0
    claim = SimpleNamespace(job_id=job['id'], attempt_id=submitted['attempt_id'])
    deliver(service, source, credential, submitted, event(claim))
    assert service.drain() == 1
    finished = service.store.get(job['id'])
    assert finished['state'] == 'succeeded' and finished['fence'] == saved['fence']
    assert finished['callback_waiting'] == 0
    assert len(service.store.pending_deliveries()) == 1
    assert service.store.claim('second-worker', {ADAPTER}) is None


def test_callback_wait_does_not_consume_local_execution_slot(tmp_path):
    from test_task_callbacks import bound

    service, source, _, _ = configured(tmp_path)
    first, _ = bound(service, source)
    service.store.configure(max_running=1, background_tools=['callback_probe', 'other_tool'])
    next_job = service.store.admit(Admission('conversation', 0, 'request', 'other', 'other_tool',
        'local_skill_v1', 'cloud', {}, 'authorization-other', 'web'), authorization={
            'source': 'web', 'conversation_id': 'conversation', 'generation': 0, 'request_id': 'request',
            'mode': 'cloud', 'selected': ['other_tool'],
        })
    service.store.release(next_job['id'], ReceiptEvidence('conversation', 0, 'request', 'receipt', 'completed', True))
    assert service.store.get(first.job_id)['callback_waiting'] == 1
    second = service.store.claim('local-worker', {'local_skill_v1'})
    assert second and second.job_id == next_job['id']


def test_uncertain_helper_history_does_not_fill_the_live_queue(browser_host):
    host, payload, _ = browser_host
    with host.connection() as conn:
        conn.executemany('INSERT INTO browser_jobs VALUES(?,?,?,?,?)', [
            (f'old-{number}', '0' * 64, '{}', 'uncertain', time.time() - 3600)
            for number in range(32)
        ])
    assert host.accept(payload)[1] == 202
    with host.connection() as conn:
        assert conn.execute("SELECT count(*) FROM browser_jobs WHERE state='uncertain'").fetchone()[0] == 32


@pytest.mark.parametrize('status,expected', [(400, -1), (403, -1), (409, -1),
                                               (408, 0), (429, 0), (503, 0)])
def test_helper_parks_permanent_rejections_and_retries_transient_delivery(browser_host, monkeypatch, status, expected):
    from lib.webhook_integrations import browser_service

    host, payload, _ = browser_host
    host.accept(payload)
    host.event(payload, 'task.completed', {'summary': 'Observed answer'})
    sent = []

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def post(self, _url, **_kwargs):
            sent.append(status)
            return Response()

    # Special methods must be defined on the class, not attached to a namespace.
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    monkeypatch.setattr(browser_service.requests, 'Session', Session)
    assert host.deliver_one()
    with host.connection() as conn:
        row = conn.execute('SELECT delivered, attempts FROM browser_events').fetchone()
        assert (row['delivered'], row['attempts']) == (expected, 1)
        conn.execute('UPDATE browser_events SET retry_at=0')
    assert host.deliver_one() is (expected == 0)
    assert len(sent) == (2 if expected == 0 else 1)


def test_operator_can_redrive_only_a_parked_callback_before_deadline(browser_host, monkeypatch):
    from lib.webhook_integrations import browser_service

    host, payload, _ = browser_host
    host.accept(payload)
    host.event(payload, 'task.failed', {'summary': 'Partial report saved'})
    statuses = iter([403, 202])

    class Response:
        def __init__(self, status): self.status_code = status
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def post(self, *_args, **_kwargs): return Response(next(statuses))

    monkeypatch.setattr(browser_service.requests, 'Session', Session)
    assert host.deliver_one()
    assert not host.deliver_one()
    assert BrowserService.retry_rejected(host.path, payload['attempt_id']) == 1
    assert host.deliver_one()
    with host.connection() as conn:
        assert conn.execute('SELECT delivered,attempts FROM browser_events').fetchone()[:] == (1, 2)
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'queued'
    with pytest.raises(Exception, match='No rejected callbacks'):
        BrowserService.retry_rejected(host.path, payload['attempt_id'])


@pytest.mark.parametrize('child_outcome', ['verified_exception', 'cancelled_without_json'])
def test_verified_browser_stop_delivers_partial_card(browser_host, monkeypatch, child_outcome):
    import tool_process
    from tool_progress import emit_tool_progress

    from lib.webhook_integrations import browser_service

    host, payload, _ = browser_host
    host.accept(payload)
    monkeypatch.setattr(browser_service, 'stop_browser_container', lambda _name: True)

    def child(*_args, consume_progress, **_kwargs):
        line = io.StringIO()
        emit_tool_progress({'phase': 'Browsing', 'stash_ref': 'stash://space/partial'}, stream=line)
        assert consume_progress(line.getvalue())
        if child_outcome == 'verified_exception':
            raise RuntimeError('child exited after saving evidence')
        return '', '', True

    monkeypatch.setattr(tool_process, 'run_local_process', child)
    assert host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        body = json.loads(conn.execute("SELECT body FROM browser_events WHERE body LIKE '%task.failed%'").fetchone()[0])
    assert body['type'] == 'task.failed'
    assert body['result']['summary'].startswith('Saved research: stash://space/partial')
    assert body['result']['presentation']['stash_ref'] == 'stash://space/partial'


def cancel_bound_browser(tmp_path):
    service, source, credential, _ = configured(tmp_path, clock=time.time)
    service.store.configure(background_tools=['browser_use'])
    admission = Admission('conversation', 0, 'request', 'browser-call', 'browser_use', ADAPTER,
                          'cloud', {'task': 'Research', 'url': 'https://example.com/'},
                          'authorization-browser', 'web')
    job = service.store.admit(admission, authorization={
        'source': 'web', 'conversation_id': 'conversation', 'generation': 0,
        'request_id': 'request', 'mode': 'cloud', 'selected': ['browser_use'],
        'callback_sources': {'browser_use': source['id']},
    })
    service.store.release(job['id'], ReceiptEvidence('conversation', 0, 'request',
                                                      'receipt', 'completed', True))
    claim = service.store.claim('test-worker', {ADAPTER})
    service.store.running(claim)
    submission = service.prepare_submission(claim, source['id'])
    host = BrowserService(tmp_path / 'browser.db', {
        'callback_url': source['endpoint'], 'credential': credential,
    }, task_store=service.store)
    payload = {**{key: submission[key] for key in ('job_id', 'attempt_id', 'idempotency_key',
        'callback_url', 'callback_capability')}, 'arguments': admission.arguments,
        'runtime': {'mode': 'cloud', 'provider': 'ollama', 'model': 'test:cloud',
                    'deadline': job['deadline'], 'proxy_policy': 'inherit'}}
    host.accept(payload)
    return service, source, credential, claim, submission, host


@pytest.mark.parametrize('during_execution', [False, True])
def test_browser_cancel_stops_only_bound_attempt_and_keeps_partial_evidence(tmp_path, monkeypatch, during_execution):
    import tool_process
    from tool_progress import emit_tool_progress

    from lib.webhook_integrations import browser_service

    service, source, credential, claim, submission, host = cancel_bound_browser(tmp_path)
    monkeypatch.setattr(browser_service, 'stop_browser_container', lambda _name: True)
    if during_execution:
        def child(*_args, cancel_check, consume_progress, **_kwargs):
            line = io.StringIO()
            emit_tool_progress({'phase': 'Browsing', 'stash_ref': 'stash://space/partial'}, stream=line)
            assert consume_progress(line.getvalue())
            assert not cancel_check()
            job = service.store.get(claim.job_id)
            service.store.request_cancel(job['id'], job['revision'], supported_adapters={ADAPTER})
            time.sleep(1.01)  # The helper checks the task store at most once a second.
            assert cancel_check()
            assert cancel_check()  # A seen cancellation remains sticky.
            return '', '', True
    else:
        def child(*_args, **_kwargs):
            pytest.fail('Cancelled queued browser work must never spawn a child')
        job = service.store.get(claim.job_id)
        service.store.request_cancel(job['id'], job['revision'], supported_adapters={ADAPTER})
    monkeypatch.setattr(tool_process, 'run_local_process', child)
    assert host.execute_one()
    with host.connection() as conn:
        rows = conn.execute('SELECT body FROM browser_events ORDER BY id').fetchall()
    terminal = json.loads(rows[-1][0])
    assert terminal['type'] == 'task.cancelled'
    if during_execution:
        assert terminal['result']['presentation']['stash_ref'] == 'stash://space/partial'
    for row in rows:
        deliver(service, source, credential, submission, row[0].encode())
    service.drain()
    saved = service.store.get(claim.job_id)
    assert saved['state'] == 'cancelled' and saved['delivery_state'] == 'suppressed'
    if during_execution:
        assert saved['result']['data']['browser_research']['stash_ref'] == 'stash://space/partial'
    assert not service.store.pending_deliveries()


def test_browser_fetch_pins_verified_peer_through_proxy_and_retains_tls_host(monkeypatch):
    import browser_agent
    from stash_helper import SecurityError

    lookups, wire = [], []

    def resolve(host, port, *_args):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '',
                 ('93.184.215.14' if len(lookups) == 1 else '127.0.0.1', port))]

    class Response:
        status_code = 200
        headers = {}
        raw = None
        def iter_content(self, _size): yield b'public body'
        def close(self): pass

    class Session:
        trust_env = True
        def __init__(self): self.adapter = None
        def mount(self, _prefix, adapter): self.adapter = adapter
        def request(self, method, url, **kwargs):
            wire.append((method, url, kwargs, self.trust_env, self.adapter.hostname))
            return Response()
        def close(self): pass

    monkeypatch.setattr(browser_agent.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(browser_agent.requests, 'Session', Session)
    monkeypatch.setattr(browser_agent, 'build_proxy_url_attempts', lambda **_: ['http://proxy:3128'])
    answer = browser_agent.BrowserFetch(time.time() + 30)({
        'method': 'GET', 'resource_type': 'Document', 'url': 'https://public.example/page',
    })
    assert answer['body'] and lookups == ['public.example']
    assert wire[0][1] == 'https://93.184.215.14/page'
    assert wire[0][2]['headers']['Host'] == 'public.example'
    assert wire[0][2]['proxies']['https'] == 'http://proxy:3128'
    assert wire[0][3:] == (False, 'public.example')

    monkeypatch.setattr(browser_agent.socket, 'getaddrinfo', lambda host, port, *_: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.215.14', port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port)),
    ])
    with pytest.raises(SecurityError):
        browser_agent.validate_url('https://public.example/', allowed_hosts=('public.example',))


def test_managed_browser_callback_base_requires_loopback(tmp_path):
    from lib.background_tasks import TaskStore
    from lib.webhook_integrations.browser import provision

    store = TaskStore(tmp_path / 'tasks.db')
    with pytest.raises(Exception, match='loopback'):
        provision(store, 'https://remote.example', 'http://127.0.0.1:8790/submit')


def test_bridge_accepts_multi_megabyte_snapshot_as_one_frame(monkeypatch):
    import browser_agent

    snapshots = []
    frame = {'id': 7, 'method': 'snapshot', 'value': {
        'title': 'Large page', 'url': 'https://example.com/', 'text': 'x' * (2 * 1024 * 1024),
        'step': 2,
    }}
    protocol = (json.dumps(frame) + '\n' + json.dumps({'result': {
        'ok': True, 'report': 'Observed', 'sources': ['https://example.com/']}}) + '\n').encode()
    assert len(protocol) > 1024 * 1024 and len(protocol) < browser_agent.BRIDGE_MAX_FRAME

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO(protocol)
        def poll(self): return 0
        def wait(self, **_kwargs): return 0
    monkeypatch.setattr(browser_agent.subprocess, 'Popen', lambda *_a, **_kw: Process())
    monkeypatch.setattr(browser_agent.subprocess, 'run', lambda *_a, **_kw: SimpleNamespace(returncode=0))
    archive = SimpleNamespace(checkpoint=lambda value: snapshots.append(value))
    result = browser_agent.run_container({'deadline': time.time() + 10, 'max_steps': 3},
        provider=object(), provider_name='ollama', fetch=None, archive=archive,
        progress=lambda _text: None)
    assert result['ok'] and len(snapshots) == 1 and len(snapshots[0]['text']) == 2 * 1024 * 1024
    source = (browser_agent.ROOT / 'docker/browser-use/agent.py').read_text()
    assert 'BRIDGE_MAX_FRAME = 8 * 1024 * 1024' in source


def test_browser_observation_reserves_callback_time_after_a_long_queue():
    from browser_agent import BrowserPreflightError, observation_deadline

    now = time.time()
    assert observation_deadline(now, now + 900) == now + 855
    assert observation_deadline(now, now + 120) == now + 75
    with pytest.raises(BrowserPreflightError, match='too little time'):
        observation_deadline(now, now + 40)


@pytest.mark.skipif(not shutil.which('openssl'), reason='TLS fixture needs openssl')
def test_pinned_https_keeps_sni_and_validates_logical_hostname(tmp_path, monkeypatch):
    import browser_agent

    certificate, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(key), '-out', str(certificate), '-days', '1',
        '-subj', '/CN=public.example', '-addext', 'subjectAltName=DNS:public.example'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed['host'] = self.headers['Host']
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *_args): pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(certificate), str(key))
    tls.set_servername_callback(lambda _socket, name, _context: observed.update(sni=name))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(browser_agent, 'build_proxy_url_attempts', lambda **_: [None])
    class ProxyHandler(socketserver.StreamRequestHandler):
        def handle(self):
            observed['connect'] = self.rfile.readline(4096).decode().strip()
            while self.rfile.readline(4096) not in {b'\r\n', b'\n', b''}:
                pass
            with socket.create_connection(('127.0.0.1', server.server_port), timeout=3) as peer:
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                self.wfile.flush()
                while True:
                    ready, _, _ = select.select([self.connection, peer], [], [], 3)
                    if not ready:
                        break
                    for source in ready:
                        chunk = source.recv(65536)
                        if not chunk:
                            return
                        (peer if source is self.connection else self.connection).sendall(chunk)

    class ProxyServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    proxy = ProxyServer(('127.0.0.1', 0), ProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    try:
        url = f'https://public.example:{server.server_port}/evidence'
        with browser_agent.pinned_http_request('GET', url, '127.0.0.1', verify=str(certificate),
                                               timeout=3, stream=True) as response:
            assert response.status_code == 200 and response.content == b'ok'
        assert observed['sni'] == 'public.example'
        assert observed['host'] == f'public.example:{server.server_port}'
        monkeypatch.setattr(browser_agent, 'build_proxy_url_attempts',
                            lambda **_: [f'http://127.0.0.1:{proxy.server_address[1]}'])
        with browser_agent.pinned_http_request('GET', url, '127.0.0.1', verify=str(certificate),
                                               timeout=3, stream=True) as response:
            assert response.status_code == 200 and response.content == b'ok'
        assert observed['connect'].startswith(f'CONNECT 127.0.0.1:{server.server_port} ')
        assert observed['sni'] == 'public.example'
        with pytest.raises(requests.exceptions.SSLError):
            with browser_agent.pinned_http_request('GET', url.replace('public.example', 'other.example'),
                                                   '127.0.0.1', verify=str(certificate), timeout=3):
                pass
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=3)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
