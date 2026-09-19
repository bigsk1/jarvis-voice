"""Web-origin operator controls and the sensitive credential lifecycle."""
import json
from types import SimpleNamespace

import pytest
from flask import Flask
from test_task_callbacks import configured
from test_web_attachment_bundle_chat import (
    chat as chat,  # Initialize the isolated Web test package.
)

from lib.background_tasks import TaskError


@pytest.fixture
def controls(tmp_path, monkeypatch):
    import webui_auth
    from jarvis_bundle_chat_test.routes.task_integrations import integrations_bp
    service, source, _, _ = configured(tmp_path)
    app = Flask(__name__)
    app.extensions['jarvis_background_tasks'] = SimpleNamespace(store=service.store)
    app.register_blueprint(integrations_bp)
    monkeypatch.setattr(webui_auth, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(webui_auth, 'verify_token', lambda value: {'operator': True} if value == 'test-operator' else None)
    return app.test_client(), service, source


AUTH = {'Authorization': 'Bearer test-operator', 'Origin': 'http://localhost'}


def test_operator_routes_reject_cookie_query_foreign_origin_and_unconfigured_auth(controls, monkeypatch):
    import webui_auth
    client, service, _ = controls
    for headers in ({}, {'Cookie': 'jarvis_auth_token=test-operator'}, {'Authorization': 'Bearer invalid'}):
        assert client.get('/api/task-integrations?token=test-operator', headers=headers).status_code == 401
        assert client.patch('/api/task-integrations', json={'enabled': False}, headers=headers).status_code == 401
    assert client.patch('/api/task-integrations', json={'enabled': False},
                        headers={**AUTH, 'Origin': 'https://foreign.invalid'}).status_code == 403
    monkeypatch.setattr(webui_auth, 'is_auth_enabled', lambda: False)
    assert client.get('/api/task-integrations', headers=AUTH).status_code == 401
    assert service.status()['enabled']


def test_credentials_show_once_and_mutations_are_revision_checked(controls):
    client, service, source = controls
    base = '/api/task-integrations/' + source['id']
    response = client.post(base + '/credentials', json={'scheme': 'hmac-sha256'}, headers=AUTH)
    assert response.status_code == 201 and response.headers['Cache-Control'] == 'no-store'
    credential = response.json
    assert credential['secret'] not in client.get('/api/task-integrations', headers=AUTH).text
    assert 'encrypted' not in client.get('/api/task-integrations', headers=AUTH).text
    assert client.post(base + '/credentials', json={'probe': True}, headers=AUTH).status_code == 409
    changed = client.patch(base, json={'revision': source['revision'], 'enabled': False}, headers=AUTH)
    assert changed.status_code == 200
    assert client.patch(base, json={'revision': source['revision'], 'enabled': True}, headers=AUTH).status_code == 409
    assert client.post(base + '/credentials/' + credential['id'] + '/revoke', json={}, headers=AUTH).status_code == 200
    assert client.get(base + '/deliveries?offset=-1', headers=AUTH).status_code == 409
    assert client.get(base + '/deliveries?limit=1', headers=AUTH).json['total'] == 1
    assert client.post('/api/task-integrations/keys', json={'action': 'rotate'}, headers=AUTH).status_code == 200


def test_key_rotation_failure_keeps_old_database_decryptable(tmp_path, monkeypatch):
    service, source, credential, _ = configured(tmp_path, scheme='hmac-sha256')
    original = service.keys.encrypt
    def interrupted(*args, **kwargs):
        raise OSError('interrupted rotation')
    monkeypatch.setattr(service.keys, 'encrypt', interrupted)
    with pytest.raises(OSError):
        service.rotate_key()
    assert len(service.keys.read()['keys']) == 2
    with service.store._connection() as conn:
        row = conn.execute('SELECT * FROM task_credentials WHERE id=?', (credential['id'],)).fetchone()
    assert service.keys.decrypt(row['encrypted'], source['id'], row['id'], row['version']) == credential['secret']
    monkeypatch.setattr(service.keys, 'encrypt', original)
    service.rotate_key()
    assert len(service.keys.read()['keys']) == 1
    service.keys.path.write_text(json.dumps({'active': 'wrong', 'keys': {'wrong': 'x' * 44}}))
    with pytest.raises(TaskError):
        service.keys.read()


def test_probe_cannot_validate_an_edited_source_and_revocation_is_permanent(tmp_path):
    from test_task_callbacks import headers

    from lib.webhook_integrations.contracts import CallbackError
    service, source, _, _ = configured(tmp_path)
    probe = service.create_credential(source['id'], probe=True)
    source = service.update_source(source['id'], source['revision'], submit_url='http://127.0.0.1:9002/submit')
    raw = b'{"schema_version":1,"event_id":"stale-test","type":"integration.test"}'
    with pytest.raises(CallbackError):
        service.accept(source['id'], raw, headers(service, source, probe, raw))
    assert not service.status()['sources'][0]['validated']
    service.update_source(source['id'], source['revision'], revoke=True)
    with pytest.raises(TaskError):
        service.create_credential(source['id'])


def test_setup_probe_is_revoked_when_signing_fails_before_http(tmp_path, monkeypatch):
    from lib.webhook_integrations import contracts, runner
    service, source, _, _ = configured(tmp_path, scheme='hmac-sha256')
    with service.store._connection() as conn:
        previous = {row[0] for row in conn.execute('SELECT id FROM task_credentials')}
    def broken_signature(*args):
        raise ValueError('Simulated header preparation failure')
    monkeypatch.setattr(contracts, 'signature', broken_signature)
    monkeypatch.setattr(runner, 'post_json', lambda *args, **kwargs: pytest.fail('No HTTP request expected'))
    with pytest.raises(TaskError, match='setup test failed'):
        service.test_source(source['id'])
    with service.store._connection() as conn:
        created = [row for row in conn.execute('SELECT * FROM task_credentials') if row['id'] not in previous]
    assert len(created) == 1 and created[0]['probe'] == 1
    assert created[0]['revoked_at'] is not None
