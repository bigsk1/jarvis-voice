"""Saved speech recovery uses the same authenticated Web media boundary."""

import importlib
import sys
from pathlib import Path

import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
NAME = 'speech_recovery_20261027_000000_' + 'a' * 32 + '.mp3'


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'path', list(sys.path))
    load_server_package('speech_recovery_web', ROOT / 'jarvis-web/server')
    api = importlib.import_module('speech_recovery_web.routes.api')
    monkeypatch.setattr(api, 'GENERATED_AUDIO_PATH', tmp_path)
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return api, app, tmp_path


def test_recovery_recording_serves_bytes_and_range_requests(web):
    _, app, root = web
    (root / NAME).write_bytes(b'ID3audio-recording')
    with app.test_client() as client:
        response = client.get('/api/generated-audio/' + NAME)
        assert response.status_code == 200
        assert response.data == b'ID3audio-recording'
        assert response.mimetype == 'audio/mpeg'
        response = client.get('/api/generated-audio/' + NAME, headers={'Range': 'bytes=3-7'})
        assert response.status_code == 206
        assert response.data == b'audio'


@pytest.mark.parametrize('filename', ['../private.mp3', 'speech_private.json', 'speech_private.txt',
                                      'other.mp3', NAME + '.json', NAME.replace('.mp3', '.ogg')])
def test_recovery_route_does_not_expose_arbitrary_files(web, filename):
    _, app, _ = web
    with app.test_client() as client:
        assert client.get('/api/generated-audio/' + filename).status_code == 404


def test_recovery_route_rejects_symlink_escape(web, tmp_path):
    _, app, root = web
    outside = tmp_path.parent / 'outside-speech.mp3'
    outside.write_bytes(b'private')
    (root / NAME).symlink_to(outside)
    with app.test_client() as client:
        assert client.get('/api/generated-audio/' + NAME).status_code == 404


def test_recovery_route_rejects_symlinked_storage_root(web, tmp_path, monkeypatch):
    api, app, root = web
    (root / NAME).write_bytes(b'private')
    alias = tmp_path.parent / 'speech-symlink-root'
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(api, 'GENERATED_AUDIO_PATH', alias)
    with app.test_client() as client:
        assert client.get('/api/generated-audio/' + NAME).status_code == 404


def test_recovery_route_honors_shared_stash_restricted_read_policy(web, monkeypatch):
    _, app, root = web
    (root / NAME).write_bytes(b'private')
    import paths

    monkeypatch.setattr(paths, 'get_restricted_read_paths', lambda: [str(root)])
    with app.test_client() as client:
        assert client.get('/api/generated-audio/' + NAME).status_code == 404


def test_recovery_route_inherits_production_web_authentication(web, monkeypatch):
    api, _, root = web
    (root / NAME).write_bytes(b'ID3saved')
    server = importlib.import_module('speech_recovery_web.app')
    monkeypatch.setattr(server, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(server, 'verify_token', lambda token: token == 'fixture-valid')
    monkeypatch.setattr(server, 'get_token_from_request', lambda request: request.headers.get('Authorization'))
    # Use the production middleware and route together, with disposable auth.
    app = Flask(__name__)
    app.before_request(server.check_auth)
    app.register_blueprint(api.api_bp)
    with app.test_client() as client:
        for token in [None, 'wrong']:
            headers = {'Authorization': token} if token else {}
            assert client.get('/api/generated-audio/' + NAME, headers=headers).status_code == 401
        assert client.get('/api/generated-audio/' + NAME,
                          headers={'Authorization': 'fixture-valid'}).status_code == 200
