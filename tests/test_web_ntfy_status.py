import ast
import json
import time
from pathlib import Path

import pytest
from filelock import FileLock
from flask import Blueprint, Flask, jsonify, request
from server_package_utils import load_server_package

from lib.ntfy_notifications import DeliveryError, write_worker_status

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'jarvis_ntfy_status_test'
load_server_package(PACKAGE, ROOT / 'jarvis-web/server')
from jarvis_ntfy_status_test.services import ntfy_status as service  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    service._health_cache.clear()
    return tmp_path


def configure(root, **changes):
    (root / 'config').mkdir(exist_ok=True)
    value = {'enabled': True, 'server_url': 'https://ntfy.example.test',
             'publisher_token': 'tk_' + 'a' * 29, **changes}
    path = root / 'config/ntfy.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def client(isolated, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'lib'))
    import webui_auth

    monkeypatch.setattr(webui_auth, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(webui_auth, 'get_token_from_request', lambda req: req.headers.get('Authorization'))
    monkeypatch.setattr(webui_auth, 'verify_token', lambda value: value == 'Bearer test-login')
    app = Flask(__name__)
    blueprint = Blueprint('api', __name__, url_prefix='/api')
    scope = {'api_bp': blueprint, 'jsonify': jsonify, 'request': request,
             'require_auth': webui_auth.require_auth, '__package__': PACKAGE + '.routes'}
    source = ast.parse((ROOT / 'jarvis-web/server/routes/api.py').read_text())
    for node in source.body:
        if isinstance(node, ast.FunctionDef) and node.name in {'get_ntfy_status_route', 'send_ntfy_test_route'}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'api.py', 'exec'), scope)
    app.register_blueprint(blueprint)
    return app.test_client()


LOGIN = {'Authorization': 'Bearer test-login'}


def test_fresh_clone_and_disabled_configuration_never_connect(isolated, monkeypatch):
    monkeypatch.setattr(service, '_health', lambda *_: pytest.fail('Unexpected network request'))
    monkeypatch.setattr(service, 'publish', lambda *_: pytest.fail('Unexpected publish'))
    assert service.get_ntfy_status()['configuration'] == 'missing'
    assert service.send_ntfy_test()[1] == 409
    configure(isolated, enabled=False)
    status = service.get_ntfy_status()
    assert status['configuration'] == 'disabled' and status['configured']
    assert status['server_online'] is None and not status['test_available']
    assert service.send_ntfy_test()[1] == 409
    assert not (isolated / 'data').exists()


def test_configuration_and_heartbeat_are_sanitized(isolated, monkeypatch):
    path = configure(isolated)
    monkeypatch.setattr(service, '_health', lambda *_: True)
    write_worker_status(isolated, 'local', 'ready', 15)
    status = service.get_ntfy_status()
    assert status['enabled'] and status['configured'] and status['server_online']
    assert status['worker'] == {'state': 'ready', 'mode': 'local'}
    assert status['categories'] == ['alerts', 'reminders']
    assert 'tk_' not in json.dumps(status) and 'example.test' not in json.dumps(status)
    assert (isolated / 'logs/ntfy_notifications.status.json').stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    assert service.get_ntfy_status()['configuration'] == 'invalid'
    assert service.send_ntfy_test()[1] == 409


@pytest.mark.parametrize('heartbeat,expected', [
    ({'mode': 'cloud', 'state': 'ready', 'updated_at': 1, 'poll_seconds': 15}, 'stale'),
    ({'mode': 'cloud', 'state': 'stopped', 'updated_at': time.time(), 'poll_seconds': 15}, 'stopped'),
    ({'mode': 'cloud', 'state': 'degraded', 'updated_at': time.time(), 'poll_seconds': 15}, 'degraded'),
    ({'mode': 'secret-value', 'state': 'ready', 'updated_at': time.time(), 'poll_seconds': 15}, 'unknown'),
    ({'state': '<private error>'}, 'unknown'),
])
def test_stale_or_invalid_heartbeat_never_claims_running(isolated, heartbeat, expected):
    folder = isolated / 'logs'
    folder.mkdir()
    (folder / 'ntfy_notifications.status.json').write_text(json.dumps(heartbeat))
    assert service._worker_status()['state'] == expected
    assert 'secret' not in json.dumps(service._worker_status())


def test_health_is_bounded_cached_and_never_sends_publisher_credentials(isolated, monkeypatch):
    configure(isolated)
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, limit):
            assert limit == 4097
            return b'{"healthy":true}'

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            assert url == 'https://ntfy.example.test/v1/health' and timeout == 3
            return Response()

    monkeypatch.setattr(service.urllib.request, 'build_opener', lambda handler: Opener())
    assert service.get_ntfy_status()['server_online']
    assert service.get_ntfy_status()['server_online']
    assert len(calls) == 1


def test_status_read_and_test_publish_require_login(client, monkeypatch):
    monkeypatch.setattr(service, '_health', lambda *_: pytest.fail('Unauthenticated network call'))
    monkeypatch.setattr(service, 'publish', lambda *_: pytest.fail('Unauthenticated publish'))
    assert client.get('/api/ntfy/status').status_code == 401
    assert client.post('/api/ntfy/test', json={}).status_code == 401
    assert client.get('/api/ntfy/test', headers=LOGIN).status_code == 405
    response = client.get('/api/ntfy/status', headers=LOGIN)
    assert response.status_code == 200 and response.json['configuration'] == 'missing'
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_explicit_test_uses_enabled_topic_without_worker_or_body_overrides(client, isolated, monkeypatch):
    configure(isolated, alerts={'enabled': False})
    calls = []
    monkeypatch.setattr(service, 'publish', lambda config, payload: calls.append((config, payload)) or 'receipt')
    assert client.post('/api/ntfy/test', headers=LOGIN,
                       json={'topic': 'unexpected', 'server_url': 'https://other.test'}).status_code == 400
    assert client.post('/api/ntfy/test', headers=LOGIN, data='{}').status_code == 400
    assert not calls
    response = client.post('/api/ntfy/test', headers=LOGIN, json={})
    assert response.status_code == 200 and response.json['ok']
    assert calls[0][1]['topic'] == 'jarvis-reminders'
    assert calls[0][1]['title'] == 'Jarvis notification test'
    assert calls[0][0]['request_timeout_seconds'] == 5
    assert 'phone' in response.json['message'] and 'tk_' not in response.get_data(as_text=True)
    again = client.post('/api/ntfy/test', headers=LOGIN, json={})
    assert again.status_code == 429 and again.headers['Retry-After'] == '30'
    assert len(calls) == 1
    assert not (isolated / 'data/ntfy_notifications.db').exists()


def test_test_lock_and_bad_receipt_do_not_expose_credentials(client, isolated, monkeypatch):
    configure(isolated)
    (isolated / 'data').mkdir()
    with FileLock(isolated / 'data/ntfy_notifications.db.test.lock'):
        assert client.post('/api/ntfy/test', headers=LOGIN, json={}).status_code == 429

    def fail(*_):
        raise DeliveryError('private token and remote response body')

    monkeypatch.setattr(service, 'publish', fail)
    response = client.post('/api/ntfy/test', headers=LOGIN, json={})
    assert response.status_code == 502 and not response.json['ok']
    assert 'private' not in response.get_data(as_text=True)


def test_heartbeat_failure_does_not_stop_event_delivery(isolated, monkeypatch):
    from services import ntfy_notifications as daemon

    configure(isolated)
    calls = []

    class Worker:
        def __init__(self, root, mode):
            self.mode = mode

        def cycle(self, config):
            calls.append(config['enabled'])
            return {'delivered': 1, 'suppressed': 0, 'errors': []}

    def fail(*_):
        raise PermissionError('private status path')

    monkeypatch.setattr(daemon, 'PROJECT_ROOT', isolated)
    monkeypatch.setattr(daemon, 'NotificationWorker', Worker)
    monkeypatch.setattr(daemon, 'write_worker_status', fail)
    monkeypatch.setattr(daemon, 'get_active_config_mode', lambda: 'cloud')
    monkeypatch.setattr(daemon.sys, 'argv', ['worker', '--once'])
    assert daemon.main() == 1  # Diagnostics are unhealthy, but the event still delivered.
    assert calls == [True]
    with FileLock(isolated / 'data/ntfy_notifications.db.lock').acquire(timeout=0):
        pass
