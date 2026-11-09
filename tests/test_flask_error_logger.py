"""Real HTTP error logging stays isolated even for apps registered before a test."""

from __future__ import annotations

import importlib
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask


def make_app(module, service_name, log_dir=None):
    app = Flask(f'error-log-test-{service_name}')

    @app.get('/api/failure/<int:status>')
    def failure(status):
        return {'ok': False, 'error': 'Synthetic rejected request'}, status

    @app.get('/api/ok')
    def ok():
        return {'ok': True}

    @app.get('/api/health')
    def health():
        return {'ok': False}, 503

    @app.get('/asset.svg')
    def asset():
        return '', 404

    module.setup_error_logging(app, service_name, log_dir=log_dir)
    return app


@pytest.fixture(scope='session', params=['flask_error_logger', 'lib.flask_error_logger'])
def registered_app(request, tmp_path_factory):
    # Session setup runs before the per-test isolation fixture. Keep even a
    # regressed, eagerly captured destination temporary during this setup.
    module = importlib.import_module(request.param)
    registration_root = tmp_path_factory.mktemp('flask-log-registration') / 'logs'
    with patch.object(module, 'LOGS_DIR', registration_root):
        app = make_app(module, 'fixture-ui')
    return SimpleNamespace(module=module, app=app, registration_root=registration_root)


@pytest.fixture
def client(registered_app, tmp_path, monkeypatch):
    # Fail before making a rejected request if the shared isolation is broken.
    assert registered_app.module.LOGS_DIR == tmp_path / 'logs'

    class Clock:
        @staticmethod
        def now():
            return datetime(2026, 11, 9, 12, 0)

    monkeypatch.setattr(registered_app.module, 'datetime', Clock)
    return registered_app.app.test_client()


@pytest.mark.parametrize('status', [400, 500])
def test_pre_registered_hooks_write_real_errors_to_each_tests_current_root(
    registered_app, client, tmp_path, status,
):
    response = client.get(f'/api/failure/{status}?mode=local')

    assert response.status_code == status
    path = tmp_path / 'logs/fixture-ui/errors-2026-11-09.jsonl'
    entry, = [json.loads(line) for line in path.read_text().splitlines()]
    assert entry['service'] == 'fixture-ui'
    assert entry['method'] == 'GET'
    assert entry['path'] == f'/api/failure/{status}'
    assert entry['query'] == 'mode=local'
    assert entry['status'] == status
    assert json.loads(entry['response_body']) == response.get_json()
    assert not registered_app.registration_root.exists()


def test_explicit_log_directory_stays_authoritative(registered_app, tmp_path):
    explicit = tmp_path / 'explicit-error-logs'
    app = make_app(registered_app.module, 'explicit-ui', log_dir=explicit)
    assert not explicit.exists()

    response = app.test_client().get('/api/failure/400')

    assert response.status_code == 400
    path, = explicit.glob('errors-*.jsonl')
    assert json.loads(path.read_text())['status'] == 400
    assert not (tmp_path / 'logs').exists()


@pytest.mark.parametrize('path', ['/api/ok', '/api/health', '/asset.svg'])
def test_success_and_excluded_requests_do_not_create_log_directories(
    registered_app, client, tmp_path, path,
):
    client.get(path)

    assert not (tmp_path / 'logs').exists()
    assert not registered_app.registration_root.exists()


def test_log_storage_failure_keeps_the_http_response(registered_app, tmp_path, capsys):
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('fixture file')
    app = make_app(registered_app.module, 'blocked-ui', log_dir=blocked / 'logs')

    response = app.test_client().get('/api/failure/500')

    assert response.status_code == 500
    assert response.get_json()['error'] == 'Synthetic rejected request'
    assert 'Failed to write error log' in capsys.readouterr().out
    assert blocked.read_text() == 'fixture file'
