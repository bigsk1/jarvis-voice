"""Profile appearance persists only in temporary storage during these checks."""

import base64
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image, PngImagePlugin
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
load_server_package('jarvis_appearance_test', ROOT / 'jarvis-web/server')
from jarvis_appearance_test.routes import api  # noqa: E402
from jarvis_appearance_test.services import profile_appearance as service  # noqa: E402
import webui_auth  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'PROFILE_PATH', tmp_path / 'profile.json')
    monkeypatch.delenv('WEBUI_PASSWORD', raising=False)
    monkeypatch.setenv('WEBUI_SECRET', 'test-appearance-secret')
    monkeypatch.setattr(webui_auth, '_log_auth_event', lambda *a, **k: None)
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    events = []
    app.extensions['socketio'] = SimpleNamespace(emit=lambda *args: events.append(args))
    app.config['TEST_PROFILE_EVENTS'] = events
    return app.test_client()


def image_bytes(format='PNG', size=(400, 200)):
    output = io.BytesIO()
    image = Image.new('RGB', size, '#35babe')
    if format == 'PNG':
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Private metadata', 'DO_NOT_RETAIN')
        image.save(output, format=format, pnginfo=metadata)
    else:
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = 'DO_NOT_RETAIN'
        image.save(output, format=format, exif=exif)
    return output.getvalue()


def save(client, name='Morgan', payload=None, **fields):
    data = {'display_name': name, **fields}
    if payload is not None:
        data['avatar'] = (io.BytesIO(payload), 'avatar.png', 'image/png')
    return client.put('/api/profile-appearance', data=data, content_type='multipart/form-data')


def test_defaults_do_not_create_storage(client):
    response = client.get('/api/profile-appearance')
    assert response.get_json()['profile'] == {'display_name': 'Administrator', 'avatar': None}
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert not service.PROFILE_PATH.exists()


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
def test_image_is_cropped_reencoded_and_metadata_removed(client, format):
    response = save(client, '  Morgan 🦊  ', image_bytes(format))
    assert response.status_code == 200
    profile = response.get_json()['profile']
    assert profile['display_name'] == 'Morgan 🦊'
    decoded = base64.b64decode(profile['avatar'].split(',', 1)[1])
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.format == 'PNG'
        assert image.size == (256, 256)
        assert not image.getexif()
        assert not image.info
    assert b'DO_NOT_RETAIN' not in decoded
    assert json.loads(service.PROFILE_PATH.read_text()) == profile
    assert service.PROFILE_PATH.stat().st_mode & 0o777 == 0o600
    assert client.get('/api/profile-appearance?mode=local').get_json()['profile'] == profile
    assert client.get('/api/profile-appearance?mode=cloud').get_json()['profile'] == profile
    assert client.application.config['TEST_PROFILE_EVENTS'] == [('profile:changed', {})]


def test_name_only_update_preserves_avatar_and_reset_removes_it(client):
    first = save(client, payload=image_bytes()).get_json()['profile']
    assert save(client, 'Alex').get_json()['profile'] == {**first, 'display_name': 'Alex'}
    reset = save(client, '', remove_avatar='true').get_json()['profile']
    assert reset == {'display_name': 'Administrator', 'avatar': None}
    assert service.get_profile_appearance() == reset


@pytest.mark.parametrize('name,payload,fields', [
    ('x' * 81, None, {}), ('name\x00hidden', None, {}), ('spoof\u202ename', None, {}),
    ('Morgan', b'<svg onload="alert(1)"></svg>', {}), ('Morgan', b'not an image', {}),
    ('Morgan', b'', {}), ('Morgan', None, {'remove_avatar': 'maybe'}),
    ('Morgan', image_bytes(), {'remove_avatar': 'true'}),
])
def test_invalid_updates_leave_previous_profile_intact(client, name, payload, fields):
    save(client, 'Original', image_bytes())
    before = service.PROFILE_PATH.read_bytes()
    response = save(client, name, payload, **fields)
    assert response.status_code == 400
    assert service.PROFILE_PATH.read_bytes() == before
    assert len(client.application.config['TEST_PROFILE_EVENTS']) == 1


def test_size_and_pixel_limits_reject_without_storage(client, monkeypatch):
    assert save(client, payload=b'x' * (service.MAX_AVATAR_BYTES + 65537)).status_code == 413
    assert not service.PROFILE_PATH.exists()
    monkeypatch.setattr(service, 'MAX_AVATAR_PIXELS', 10)
    assert save(client, payload=image_bytes()).status_code == 400
    assert not service.PROFILE_PATH.exists()


def test_atomic_write_failure_keeps_previous_profile(client, monkeypatch):
    save(client, 'Original')
    before = service.PROFILE_PATH.read_bytes()
    def fail(*args):
        raise OSError('synthetic replace failure')
    monkeypatch.setattr(service.os, 'replace', fail)
    assert save(client, 'Changed').status_code == 500
    assert service.PROFILE_PATH.read_bytes() == before
    assert not list(service.PROFILE_PATH.parent.glob('.web-profile-*.tmp'))


def test_profile_requires_auth_for_read_and_write_and_accepts_bearer(client, monkeypatch):
    monkeypatch.setenv('WEBUI_PASSWORD', 'test-password')
    assert client.get('/api/profile-appearance').status_code == 401
    assert save(client).status_code == 401
    assert not service.PROFILE_PATH.exists()
    headers = {'Authorization': f'Bearer {webui_auth.create_token()}'}
    assert client.get('/api/profile-appearance', headers=headers).status_code == 200
    response = client.put('/api/profile-appearance', data={'display_name': 'Signed in'},
                          content_type='multipart/form-data', headers=headers)
    assert response.status_code == 200


def test_save_notifies_connected_clients_without_broadcasting_private_pixels(client):
    from jarvis_appearance_test.socket_auth import AuthenticatedSocketIO

    socket = AuthenticatedSocketIO(client.application, async_mode='threading')
    browser = socket.test_client(client.application)
    companion = socket.test_client(client.application)
    try:
        assert save(client, payload=image_bytes()).status_code == 200
        for connection in (browser, companion):
            assert connection.get_received() == [{'name': 'profile:changed', 'args': [{}], 'namespace': '/'}]
        assert save(client, payload=b'invalid').status_code == 400
        assert not browser.get_received()
        assert not companion.get_received()
    finally:
        browser.disconnect()
        companion.disconnect()
