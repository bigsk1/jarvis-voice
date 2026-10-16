"""Canvas imports coexist with other apps and preserve the real launcher contract."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from config_loader import config_scope
from server_package_utils import load_canvas_server_package, load_server_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('canvas_first', [True, False], ids=['canvas-first', 'memory-first'])
def test_canvas_coexists_with_another_app_and_unrelated_module_names(
    canvas_first, tmp_path, monkeypatch, request,
):
    sentinels = {}
    for name in ('server', 'server.pages', 'server.routes', 'config'):
        sentinel = ModuleType(name)
        sentinel.__path__ = []
        sentinels[name] = sentinel
        monkeypatch.setitem(sys.modules, name, sentinel)

    import flask_error_logger

    monkeypatch.setattr(flask_error_logger, 'LOGS_DIR', tmp_path / 'logs')
    suffix = 'canvas_first' if canvas_first else 'memory_first'
    canvas_alias = f'canvas_coexist_{suffix}'
    memory_alias = f'memory_coexist_{suffix}'

    def remove_owned_modules():
        for name in tuple(sys.modules):
            if any(name == alias or name.startswith(f'{alias}.')
                   for alias in (canvas_alias, memory_alias)):
                del sys.modules[name]

    request.addfinalizer(remove_owned_modules)

    def load_canvas():
        load_canvas_server_package(canvas_alias)
        return importlib.import_module(f'{canvas_alias}.app')

    def load_memory():
        load_server_package(memory_alias, ROOT / 'jarvis-memory' / 'server')
        return importlib.import_module(f'{memory_alias}.app')

    with config_scope('cloud', overrides={'STASH_DIR': str(tmp_path / 'stash')}):
        if canvas_first:
            canvas_app, memory_app = load_canvas(), load_memory()
        else:
            memory_app, canvas_app = load_memory(), load_canvas()
        monkeypatch.setattr(canvas_app, 'is_auth_enabled', lambda: True)
        app = canvas_app.create_app('cloud')
        pages = importlib.import_module(f'{canvas_alias}.pages')
        pages.save_page({'id': 'page_import_test', 'title': 'Import test', 'content': 'Saved'})

        with app.test_client() as client:
            health = client.get('/api/health')
            assert health.status_code == 200
            assert health.json['service'] == 'jarvis-canvas'
            assert health.json['pages'] == 1
            assert client.get('/gallery').status_code == 302
            assert client.get('/login').status_code == 200
            assert client.get('/static/fonts/InterVariable.woff2').data[:4] == b'wOF2'
        with memory_app.app.test_client() as client:
            response = client.get('/assets/jarvis-voice.png')
            assert response.status_code == 200
            assert response.data == (ROOT / 'jarvis-web/client/assets/jarvis-voice.png').read_bytes()

    assert canvas_app.__name__ == f'{canvas_alias}.app'
    assert memory_app.__name__ == f'{memory_alias}.app'
    assert canvas_app is not memory_app
    for name, sentinel in sentinels.items():
        assert sys.modules[name] is sentinel


LAUNCHER_CHECK = r'''
import importlib
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

from flask import Flask

checkout = Path(sys.argv[1])
mode = sys.argv[2]
sys.path.insert(0, str(checkout / 'lib'))

calls = []
def check_run(app, **kwargs):
    calls.append(kwargs)
    assert app.config['JARVIS_STARTUP_MODE'] == mode
    assert kwargs == {'host': '127.0.0.1', 'port': 19090, 'debug': False, 'threaded': True}
    assert app.template_folder == str(checkout / 'jarvis-canvas/client/templates')
    assert app.static_folder == str(checkout / 'jarvis-canvas/client/static')
    with app.test_client() as client:
        response = client.get('/api/health')
        assert response.status_code == 200
        assert response.json['startup_mode'] == mode
        assert response.json['pages'] == 0
        assert client.get('/gallery').status_code == 302
        assert client.get('/login').status_code == 200

sys.argv = [str(checkout / 'bin/jarvis-canvas'), mode, '--host', '127.0.0.1', '--port', '19090']
with patch.object(Flask, 'run', check_run):
    runpy.run_path(sys.argv[0], run_name='__main__')
assert len(calls) == 1

config = importlib.import_module('server.config')
assert config.PROJECT_ROOT == checkout
assert config.CANVAS_DIR == checkout / 'data/canvas'
assert config.STATIC_DIR == checkout / 'docs/images'
assert config.GENERATED_IMAGES_DIR == checkout / 'data/generated_images'
assert config.GENERATED_VIDEOS_DIR == checkout / 'data/generated_videos'
assert config.GENERATED_AUDIO_DIR == checkout / 'data/generated_music'
assert config.STASH_DIR == checkout / 'test-stash'
assert config.DEFAULT_HOST == '0.0.0.0'
assert config.DEFAULT_PORT == 8890
for name in ('CANVAS_DIR', 'GENERATED_IMAGES_DIR', 'GENERATED_VIDEOS_DIR', 'GENERATED_AUDIO_DIR'):
    assert getattr(config, name).is_dir()
assert importlib.import_module('server.pages').CANVAS_DIR == config.CANVAS_DIR
sys.path.insert(0, str(checkout))
outer_package = importlib.import_module('jarvis-canvas')
assert callable(outer_package.create_app)
assert outer_package.DEFAULT_HOST == config.DEFAULT_HOST
assert outer_package.DEFAULT_PORT == config.DEFAULT_PORT
assert 'config' not in sys.modules
print('Verified real Canvas launcher: ' + mode)
'''


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_real_canvas_launcher_uses_package_config_and_original_paths(tmp_path, mode):
    # The literal server launcher contract belongs in its own interpreter.
    # Copy its Python sources so config reads, mkdir and logs stay in this fixture.
    checkout = tmp_path / 'checkout'
    for directory in ('lib', 'jarvis-canvas/server'):
        for source in (ROOT / directory).rglob('*.py'):
            target = checkout / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (checkout / 'bin').mkdir()
    shutil.copy2(ROOT / 'bin/jarvis-canvas', checkout / 'bin')
    shutil.copy2(ROOT / 'jarvis-canvas/__init__.py', checkout / 'jarvis-canvas')
    shutil.copytree(
        ROOT / 'jarvis-canvas/client/templates', checkout / 'jarvis-canvas/client/templates',
    )
    shutil.copy2(ROOT / 'VERSION', checkout)
    (checkout / 'config').mkdir()
    for config_mode in ('cloud', 'local'):
        (checkout / 'config' / f'{config_mode}.env').write_text('WEBUI_PASSWORD=fixture-password\n')

    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith('JARVIS_'):
            env.pop(key)
    env['STASH_DIR'] = str(checkout / 'test-stash')
    result = subprocess.run(
        [sys.executable, '-I', '-c', LAUNCHER_CHECK, str(checkout), mode],
        cwd=checkout, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'Verified real Canvas launcher: {mode}' in result.stdout
