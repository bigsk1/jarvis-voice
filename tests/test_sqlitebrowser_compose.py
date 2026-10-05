"""Validate the opt-in browser's mount and startup boundaries without a daemon."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which('docker')
pytestmark = pytest.mark.skipif(not DOCKER, reason='Optional browser needs Docker Compose')


@pytest.fixture
def setup(tmp_path):
    directory = tmp_path / 'sqlitebrowser'
    directory.mkdir()
    (tmp_path / 'databases').mkdir()
    for name in ('compose.yaml', 'start'):
        shutil.copy2(ROOT / 'sqlitebrowser' / name, directory / name)
    (directory / '.env').write_text('SQLITEBROWSER_PASSWORD=synthetic-test-password\nSQLITEBROWSER_READ_ONLY=false\n')
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT', 'DOCKER_CONFIG') if key in os.environ}
    env['SQLITEBROWSER_DATABASE_PATH'] = '../databases'
    return directory, env


def config(directory, env):
    result = subprocess.run([DOCKER, 'compose', 'config', '--format', 'json'], cwd=directory,
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)['services']['sqlitebrowser']


def test_fresh_config_is_read_only_and_requires_password(setup):
    directory, env = setup
    (directory / '.env').unlink()
    failed = subprocess.run([DOCKER, 'compose', 'config', '--quiet'], cwd=directory, env=env,
                            capture_output=True, text=True, timeout=15)
    assert failed.returncode != 0 and 'SQLITEBROWSER_PASSWORD' in failed.stderr
    service = config(directory, {**env, 'SQLITEBROWSER_PASSWORD': 'synthetic-test-password'})
    database = next(v for v in service['volumes'] if v['target'] == '/databases')
    assert database['read_only'] is True and database['bind']['create_host_path'] is False
    assert service['ports'][0]['host_ip'] == '127.0.0.1'
    assert len(service['ports']) == 1 and service['ports'][0]['target'] == 3001
    assert service['environment']['CUSTOM_USER'] == 'admin'
    assert service['environment']['HARDEN_DESKTOP'] == 'true'
    assert service['environment']['SELKIES_ENABLE_SHARING'] == 'false|locked'
    assert not service.get('privileged') and not service.get('devices')
    assert not any(v['target'] == '/var/run/docker.sock' for v in service['volumes'])


@pytest.mark.parametrize('flag,read_only', [('--edit', False), ('--read-only', True), (None, False)])
def test_start_flag_overrides_env_without_rewriting_it(setup, tmp_path, flag, read_only):
    directory, env = setup
    original = (directory / '.env').read_bytes()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    record = tmp_path / 'started.json'
    # Run real Compose interpolation, but intercept the actual service launch.
    fake = bin_dir / 'docker'
    fake.write_text('#!/usr/bin/env python3\n' + f'''import json, os, subprocess, sys
real = {DOCKER!r}
if sys.argv[1:] == ['compose', 'config', '--quiet']:
    sys.exit(subprocess.call([real] + sys.argv[1:]))
assert sys.argv[1:] == ['compose', 'up', '-d', 'sqlitebrowser']
result = subprocess.run([real, 'compose', 'config', '--format', 'json'], capture_output=True, text=True, check=True)
service = json.loads(result.stdout)['services']['sqlitebrowser']
volume = next(v for v in service['volumes'] if v['target'] == '/databases')
with open({str(record)!r}, 'w') as handle:
    json.dump({{'read_only': volume.get('read_only', False)}}, handle)
''')
    fake.chmod(0o755)
    args = ['bash', str(directory / 'start')] + ([flag] if flag else [])
    result = subprocess.run(args, cwd=tmp_path, env={**env, 'PATH': str(bin_dir) + os.pathsep + env['PATH']},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(record.read_text())['read_only'] is read_only
    assert (directory / '.env').read_bytes() == original
    assert (directory / 'data').is_dir()


def test_bad_start_flag_does_not_create_state(setup):
    directory, env = setup
    result = subprocess.run(['bash', str(directory / 'start'), '--unknown'], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and 'Usage:' in result.stderr
    assert not (directory / 'data').exists()


def test_ignored_runtime_files_and_public_example():
    for relative, ignored in [('sqlitebrowser/.env', True), ('sqlitebrowser/data/settings', True),
                              ('sqlitebrowser/.env.example', False), ('sqlitebrowser/compose.yaml', False)]:
        result = subprocess.run(['git', 'check-ignore', relative], cwd=ROOT, capture_output=True, timeout=5)
        assert (result.returncode == 0) is ignored
    assert 'sqlitebrowser/' in (ROOT / '.dockerignore').read_text().splitlines()
