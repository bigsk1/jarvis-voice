"""Real FastAPI middleware and streaming limits, using disposable credentials."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_task_callbacks import bound, configured, event, headers

from api.routes.task_callbacks import router
from lib.webhook_integrations.http import CallbackBoundary


def callback_app(service, tmp_path, monkeypatch, *, shared_auth=True, **boundary):
    from api import server
    from lib.rate_limiter import APIRateLimitMiddleware

    monkeypatch.setattr(server, 'get_config_value', lambda key, default='': {
        'JARVIS_API_AUTH': 'true' if shared_auth else 'false', 'JARVIS_API_KEY': 'unrelated-shared-key',
    }.get(key, default))
    order = [item.cls for item in server.app.user_middleware]
    assert order.index(CallbackBoundary) < order.index(server.RequestLoggingMiddleware)
    app = FastAPI()
    app.state.task_integrations = service
    app.include_router(router)

    @app.post('/api/alerts')
    def unchanged_alert_path():
        return {'existing_alert_boundary': True}

    app.add_middleware(APIRateLimitMiddleware)
    app.add_middleware(server.APIAuthMiddleware)
    app.add_middleware(server.RequestLoggingMiddleware, logs_dir=tmp_path / 'api-logs', log_loopback=True)
    app.add_middleware(CallbackBoundary, **boundary)
    return app


@pytest.mark.parametrize('shared_auth', [False, True])
@pytest.mark.parametrize('scheme', ['bearer', 'hmac-sha256'])
def test_source_auth_is_mandatory_on_loopback_and_independent_of_shared_api_auth(tmp_path, monkeypatch, shared_auth, scheme):
    service, source, credential, _ = configured(tmp_path, scheme=scheme)
    claim, submission = bound(service, source)
    raw = event(claim)
    app = callback_app(service, tmp_path, monkeypatch, shared_auth=shared_auth)
    path = f"/api/task-callbacks/{source['id']}/events"
    for peer in ('127.0.0.1', '198.51.100.42'):
        with TestClient(app, client=(peer, 54321)) as client:
            assert client.post(path, content=raw, headers={'Content-Type': 'application/json'}).status_code == 401
            assert client.post(path, content=raw, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer unrelated-shared-key'}).status_code == 401
            response = client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability']))
            assert response.status_code in {200, 202}
    assert service.store.get(claim.job_id)['result'] is None
    service.drain()
    assert service.store.get(claim.job_id)['state'] == 'succeeded'
    logs = ''.join(file.read_text() for file in (tmp_path / 'api-logs').glob('*.jsonl'))
    assert credential['secret'] not in logs and submission['callback_capability'] not in logs and 'Finished' not in logs
    with TestClient(app, client=('198.51.100.43', 54321)) as client:
        assert client.post('/api/alerts', json={}).status_code == (401 if shared_auth else 200)


def test_source_rate_limit_duplicate_ack_and_unauthenticated_limit_have_no_loopback_exemption(tmp_path, monkeypatch):
    service, source, credential, now = configured(tmp_path)
    source = service.update_source(source['id'], source['revision'], rate_limit=1)
    now[0] += 61
    claim, submission = bound(service, source)
    app = callback_app(service, tmp_path, monkeypatch)
    path = f"/api/task-callbacks/{source['id']}/events"
    raw = event(claim)
    with TestClient(app, client=('127.0.0.1', 100)) as client:
        assert client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability'])).status_code == 202
        assert client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability'])).status_code == 200
        raw = event(claim, event_id='another')
        response = client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability']))
        assert response.status_code == 429 and response.headers['retry-after']
    app = callback_app(service, tmp_path, monkeypatch, per_client=1)
    with TestClient(app, client=('127.0.0.1', 101)) as client:
        assert client.post(path, json={}).status_code == 401
        assert client.post(path, json={}).status_code == 429


def test_remote_unauthenticated_flood_cannot_spend_loopback_delivery_budget():
    boundary = CallbackBoundary(lambda *_: None, global_limit=3, per_client=3,
                                clock=lambda: 600)
    assert all(boundary.allowed(f'198.51.100.{index}') for index in (1, 2, 3))
    assert not boundary.allowed('198.51.100.4')
    assert boundary.allowed('127.0.0.1')
    assert boundary.allowed('::1')


@pytest.mark.parametrize('length', [None, b'1', b'2000000'])
def test_streaming_oversize_is_rejected_before_any_logging_body_read(tmp_path, monkeypatch, length):
    service, source, _, _ = configured(tmp_path)
    app = callback_app(service, tmp_path, monkeypatch, max_body=128)
    calls = []
    from api.server import RequestLoggingMiddleware
    original = RequestLoggingMiddleware.dispatch

    async def observed(self, request, call_next):
        calls.append(True)
        return await original(self, request, call_next)

    monkeypatch.setattr(RequestLoggingMiddleware, 'dispatch', observed)
    response = []
    chunks = iter([{'type': 'http.request', 'body': b'secret-diagnostic=' + b'x' * 80, 'more_body': True},
                   {'type': 'http.request', 'body': b'y' * 80, 'more_body': False}])

    async def receive():
        return next(chunks)

    async def send(message):
        response.append(message)

    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
             'scheme': 'http', 'path': f"/api/task-callbacks/{source['id']}/events", 'query_string': b'',
             'root_path': '', 'headers': [] if length is None else [(b'content-length', length)],
             'server': ('testserver', 80), 'client': ('127.0.0.1', 100)}
    asyncio.run(app(scope, receive, send))
    assert response[0]['status'] == 413
    assert not calls
    assert not list((tmp_path / 'api-logs').glob('*.jsonl'))


def test_query_secrets_and_failed_auth_payloads_do_not_enter_request_logs(tmp_path, monkeypatch):
    service, source, _, _ = configured(tmp_path)
    app = callback_app(service, tmp_path, monkeypatch)
    path = f"/api/task-callbacks/{source['id']}/events"
    with TestClient(app) as client:
        assert client.post(path + '?token=secret-in-query', json={'secret': 'secret-in-body'}).status_code == 400
        assert client.post(path, json={'secret': 'secret-in-body'}).status_code == 401
    logs = ''.join(file.read_text() for file in tmp_path.rglob('*.jsonl'))
    assert 'secret-in-query' not in logs and 'secret-in-body' not in logs


def test_receiver_disabled_and_storage_failure_never_acknowledge_success(tmp_path, monkeypatch):
    service, source, credential, _ = configured(tmp_path)
    claim, submission = bound(service, source)
    raw = event(claim)
    app = callback_app(service, tmp_path, monkeypatch)
    path = f"/api/task-callbacks/{source['id']}/events"
    with TestClient(app) as client:
        service.configure(False)
        assert client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability'])).status_code == 503
        service.configure(True)
        with service.store._connection(write=True) as conn:
            conn.execute("CREATE TRIGGER broken BEFORE INSERT ON task_callback_inbox BEGIN SELECT RAISE(ABORT,'disk full'); END")
        assert client.post(path, content=raw, headers=headers(service, source, credential, raw, submission['callback_capability'])).status_code == 503
    assert service.store.get(claim.job_id)['result'] is None


@pytest.mark.parametrize('scheme', ['bearer', 'hmac-sha256'])
@pytest.mark.parametrize('pause', ['receiver', 'source', 'events'])
def test_committed_duplicate_ack_survives_pause_but_keeps_authentication(tmp_path, monkeypatch, scheme, pause):
    service, source, credential, now = configured(tmp_path, scheme=scheme)
    claim, submission = bound(service, source)
    app = callback_app(service, tmp_path, monkeypatch)
    path = f"/api/task-callbacks/{source['id']}/events"
    raw = event(claim)
    with TestClient(app) as client:
        def post(body=raw, **changes):
            auth = headers(service, source, credential, body, submission['callback_capability'])
            return client.post(path, content=body, headers={**auth, **changes})
        assert post().status_code == 202
        if pause == 'receiver':
            service.configure(False)
        elif pause == 'source':
            source = service.update_source(source['id'], source['revision'], enabled=False)
        else:
            source = service.update_source(source['id'], source['revision'], events=['task.progress'])
        before = service.deliveries(source['id'])
        response = post()
        assert response.status_code == 200 and response.json()['duplicate'] is True
        assert post(event(claim, summary='Changed content')).status_code == 409
        assert post(event(claim, event_id='new-after-pause')).status_code == (503 if pause == 'receiver' else 403)
        assert post(**{'X-Jarvis-Task-Capability': 'wrong'}).status_code == 403
        assert post(**{'X-Jarvis-Timestamp': '0'}).status_code == 401
        assert service.deliveries(source['id']) == before  # ACK changes no inbox disposition.
        service.revoke_credential(source['id'], credential['id'])
        assert post().status_code == 401
        assert service.store.get(claim.job_id)['result'] is None


@pytest.mark.parametrize('shared_auth', [False, True])
@pytest.mark.parametrize('source_id', ['invalid!', 'short', 'A' * 32, '0' * 32])
def test_malformed_and_unknown_callback_sources_are_not_storage_failures(tmp_path, monkeypatch, shared_auth, source_id):
    service, _, _, _ = configured(tmp_path)
    app = callback_app(service, tmp_path, monkeypatch, shared_auth=shared_auth)
    with TestClient(app, client=('198.51.100.40', 100)) as client:
        response = client.post(f'/api/task-callbacks/{source_id}/events', json={})
    assert response.status_code == 404
    assert 'storage' not in response.text
