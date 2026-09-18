"""Optional worker entrypoint, supervisor contract and profile isolation."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from test_background_tasks import admission, receipt
from test_background_tasks import config_root as config_root
from test_background_tasks import store as store

from lib.background_tasks import TaskStore
from lib.background_tasks.worker import TaskWorker

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin/jarvis-task-worker'


@pytest.mark.parametrize('python_flags', [[], ['-I']], ids=['normal', 'isolated'])
def test_clean_clone_status_and_unit_have_no_database_side_effects(tmp_path, python_flags):
    db = tmp_path / 'not-created/tasks.db'
    status = subprocess.run([sys.executable, *python_flags, str(CLI), 'status', '--db', str(db)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert status.returncode == 1
    assert json.loads(status.stdout)['settings']['background_enabled'] is False
    unit = subprocess.run([sys.executable, *python_flags, str(CLI), 'unit', '--db', str(db)], cwd=tmp_path,
                          capture_output=True, text=True, check=True, timeout=10).stdout
    assert f'WorkingDirectory={ROOT}\n' in unit
    assert 'Restart=on-failure' in unit and 'KillMode=control-group' in unit
    assert f'"{CLI}" "run" "--db" "{db}"' in unit
    assert not db.parent.exists()


@pytest.mark.parametrize('action', ['start', 'stop', 'restart'])
def test_native_operations_target_only_the_optional_service(tmp_path, action):
    marker = tmp_path / 'called'
    command = tmp_path / 'systemctl'
    command.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$WORKER_TEST_MARKER"\n')
    command.chmod(0o700)
    subprocess.run([sys.executable, str(CLI), action], env={**os.environ, 'PATH':str(tmp_path),
                    'WORKER_TEST_MARKER':str(marker)}, check=True, timeout=10)
    assert marker.read_text().splitlines() == ['--user', action, 'jarvis-task-worker.service']


@pytest.mark.parametrize('python_flags', [[], ['-I']], ids=['normal', 'isolated'])
@pytest.mark.parametrize('enabled', [False, True])
def test_real_worker_entrypoint_health_singleton_and_clean_stop(tmp_path, python_flags, enabled):
    db = tmp_path / 'control/tasks.db'
    store = TaskStore(db)
    if enabled:
        store.initialize()
        store.configure(background_enabled=True, background_tools=['convert_file'])
    log = tmp_path / 'worker.log'
    with log.open('w') as output:
        process = subprocess.Popen([sys.executable, *python_flags, str(CLI), 'run', '--db', str(db)], cwd=tmp_path,
                                   stdout=subprocess.DEVNULL, stderr=output, text=True)
    try:
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(log.read_text())
            health = subprocess.run([sys.executable,str(CLI),'status','--db',str(db)],
                                    capture_output=True,text=True,timeout=5)
            if json.loads(health.stdout)['ready']:
                break
            time.sleep(.05)
        assert store.healthy_workers()
        assert store.settings()['background_enabled'] is enabled
        # Visible while still alive, with no jobs and no Settings toggle needed.
        while 'New background tasks:' not in log.read_text() and time.monotonic() < deadline:
            time.sleep(.01)
        started = log.read_text()
        assert 'Starting Jarvis task worker' in started and 'Task worker ready' in started
        assert f"New background tasks: {'enabled' if enabled else 'disabled'}" in started
        assert f"saved tools={'convert_file' if enabled else 'none'}" in started
        second = subprocess.run([sys.executable, str(CLI), 'run', '--db', str(db)], cwd=tmp_path,
                                capture_output=True, text=True, timeout=5)
        assert second.returncode != 0 and 'Another supervised worker' in second.stderr
        process.terminate()
        assert process.wait(timeout=6) == 0
        assert store.healthy_workers() == []
        assert store.conversation_jobs() == []
        assert 'Task worker stopped' in log.read_text()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_parallel_modes_and_per_adapter_capacity(store, config_root):
    store.configure(max_running=3, max_per_adapter=1)
    seen, release = [], threading.Event()
    def work(context):
        seen.append((context.claim.job['adapter'], context.claim.job['mode'], context.environment['FIXTURE_TOKEN']))
        while not release.wait(.01):
            context.checkpoint()
        return {'ok':True}
    for index, (adapter, mode) in enumerate([('a','local'),('a','cloud'),('b','cloud')]):
        job = store.admit(admission(adapter=adapter, mode=mode, invocation_id=f'call-{index}'))
        store.release(job['id'], receipt(job))
    stop = threading.Event()
    worker = TaskWorker(store, {'a':work,'b':work}, poll_seconds=.05)
    thread = threading.Thread(target=worker.run_forever, args=(stop,))
    thread.start()
    try:
        deadline = time.monotonic()+5
        while len(seen)<2 and time.monotonic()<deadline:
            time.sleep(.01)
        assert len(seen) == 2
        assert {item[0] for item in seen} == {'a','b'}
        assert all(mode==value for _,mode,value in seen)
        store.configure(background_enabled=False)
        release.set()
        deadline=time.monotonic()+5
        while any(j['state']!='succeeded' for j in store.conversation_jobs()) and time.monotonic()<deadline:
            time.sleep(.01)
        assert len(seen)==3
        assert all(j['state']=='succeeded' for j in store.conversation_jobs())
    finally:
        release.set()
        stop.set()
        thread.join(6)
    assert not thread.is_alive()


def test_compose_worker_is_opt_in_shared_storage_and_separate_from_init():
    compose = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    services = compose['services']
    worker = services['jarvis-task-worker']
    assert worker['profiles'] == ['background-tasks']
    assert worker['command'] == ['task-worker']
    assert worker['init'] and worker['restart'] == 'unless-stopped'
    assert './data:/app/data' in worker['volumes']
    assert worker['user'] == services['jarvis-web']['user']
    assert not worker.get('ports') and not worker.get('depends_on')
    for name, service in services.items():
        if name != 'jarvis-task-worker':
            assert 'jarvis-task-worker' not in service.get('depends_on', {})
    entrypoint = (ROOT / 'docker/entrypoint.sh').read_text().split('  task-worker)')[1].split(';;')[0]
    assert 'exec ./bin/jarvis-task-worker run' in entrypoint
    assert 'run_init' not in entrypoint


def test_scheduler_failure_stops_active_work_before_pool_join(store, config_root, monkeypatch):
    started = threading.Event()
    def adapter(context):
        started.set()
        while True:
            context.checkpoint()
            time.sleep(.01)
    job = store.admit(admission())
    store.release(job['id'], receipt(job))
    settings = store.settings
    def scheduler_settings():
        if started.is_set():
            raise OSError('Injected scheduler failure')
        return settings()
    monkeypatch.setattr(store, 'settings', scheduler_settings)
    stop = threading.Event()
    worker = TaskWorker(store, {'local_fixture':adapter}, poll_seconds=.05)
    with pytest.raises(OSError, match='Injected scheduler failure'):
        worker.run_forever(stop)
    assert stop.is_set()
    assert store.get(job['id'])['state']=='needs_attention'
    assert store.healthy_workers()==[]


def test_healthcheck_handles_store_initialization_window(tmp_path):
    db = tmp_path / 'initializing.db'
    db.touch(mode=0o600)
    status = subprocess.run([sys.executable,str(CLI),'status','--db',str(db)],
                            capture_output=True,text=True,timeout=5)
    assert status.returncode==1
    assert json.loads(status.stdout)['ready'] is False
    assert not status.stderr


@pytest.fixture
def tmux_cli(tmp_path):
    """Run the real management entrypoint against an isolated tmux double."""
    fake_bin = tmp_path / 'commands'
    fake_bin.mkdir()
    state, log = tmp_path / 'session', tmp_path / 'tmux.jsonl'
    tmux = fake_bin / 'tmux'
    tmux.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
state = pathlib.Path(os.environ['TEST_TMUX_STATE'])
with open(os.environ['TEST_TMUX_LOG'], 'a') as out:
    out.write(json.dumps(sys.argv[1:]) + '\\n')
command = sys.argv[1]
if command == 'has-session':
    sys.exit(0 if state.exists() else 1)
if command == 'new-session':
    state.touch()
elif command == 'kill-session' or (command == 'send-keys' and not os.environ.get('TEST_TMUX_STUCK')):
    state.unlink(missing_ok=True)
''')
    tmux.chmod(0o700)
    env = {**os.environ, 'PATH': str(fake_bin) + os.pathsep + os.environ['PATH'],
           'TEST_TMUX_STATE': str(state), 'TEST_TMUX_LOG': str(log),
           'JARVIS_VENV': str(tmp_path / 'runtime with spaces')}
    store = TaskStore(tmp_path / 'data with spaces/tasks.db')

    def run(action):
        return subprocess.run([sys.executable, str(CLI), action, '--tmux', '--db', str(store.path)],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)

    from types import SimpleNamespace
    return SimpleNamespace(run=run, state=state, store=store, env=env,
                           commands=lambda: [json.loads(line) for line in log.read_text().splitlines()])


def test_tmux_start_uses_normal_runtime_and_quotes_paths(tmux_cli):
    import shlex

    h = tmux_cli
    result = h.run('start')
    assert result.returncode == 0, result.stderr
    command = next(args[-1] for args in h.commands() if args[0] == 'new-session')
    tokens = shlex.split(command)
    assert tokens[:2] == ['source', h.env['JARVIS_VENV'] + '/bin/activate']
    assert tokens[tokens.index('exec') + 1:] == [h.env['JARVIS_VENV'] + '/bin/python',
                                              str(CLI), 'run', '--db', str(h.store.path)]
    assert 'JARVIS_MODE=' not in command and 'read -p' not in command
    assert not h.store.path.exists()  # The management call cannot enable admission.


@pytest.mark.parametrize('managed', [False, True])
def test_tmux_start_reuses_healthy_worker_and_status_identifies_supervisor(tmux_cli, managed):
    h = tmux_cli
    h.store.initialize()
    h.store.touch_worker('already-running', {'local_skill_v1'})
    if managed:
        h.state.touch()
    result = h.run('start')
    assert result.returncode == 0 and 'already ready' in result.stdout
    result = h.run('status')
    assert result.returncode == 0 and 'RUNNING' in result.stdout
    assert ('managed outside tmux' in result.stdout) is not managed
    assert not any(args[0] in {'new-session', 'send-keys', 'kill-session'} for args in h.commands())
    assert h.store.settings()['background_enabled'] is False


def test_tmux_stale_session_does_not_launch_another_worker(tmux_cli):
    h = tmux_cli
    h.state.touch()
    result = h.run('start')
    assert result.returncode == 0 and 'not ready' in result.stdout
    result = h.run('status')
    assert result.returncode == 1 and 'NOT READY' in result.stdout
    assert not any(args[0] == 'new-session' for args in h.commands())
    assert not h.store.path.exists()


@pytest.mark.parametrize('action', ['stop', 'restart'])
def test_tmux_shutdown_uses_graceful_worker_signal(tmux_cli, action):
    h = tmux_cli
    h.state.touch()
    result = h.run(action)
    assert result.returncode == 0, result.stderr
    commands = h.commands()
    assert ['send-keys', '-t', 'jarvis-task-worker', 'C-c'] in commands
    assert not any(args[0] == 'kill-session' for args in commands)
    assert h.state.exists() is (action == 'restart')
    if action == 'restart':
        assert next(i for i, args in enumerate(commands) if args[0] == 'send-keys') < next(
            i for i, args in enumerate(commands) if args[0] == 'new-session')


def test_tmux_stop_does_not_signal_external_worker(tmux_cli):
    h = tmux_cli
    h.store.initialize()
    h.store.touch_worker('external-worker', {'local_skill_v1'})
    result = h.run('stop')
    assert result.returncode == 0, result.stderr
    assert all(args[0] == 'has-session' for args in h.commands())
    assert h.store.healthy_workers()


def test_tmux_shutdown_escalates_only_after_grace_period(tmux_cli, monkeypatch, capsys):
    from lib.background_tasks import cli

    h = tmux_cli
    h.state.touch()
    for key in ('PATH', 'TEST_TMUX_STATE', 'TEST_TMUX_LOG'):
        monkeypatch.setenv(key, h.env[key])
    monkeypatch.setenv('TEST_TMUX_STUCK', '1')
    waits = []
    monkeypatch.setattr(cli.time, 'sleep', waits.append)
    assert cli.manage_tmux('stop', h.store) == 0
    assert sum(waits) == 10
    commands = h.commands()
    assert commands[-1] == ['kill-session', '-t', 'jarvis-task-worker']
    assert 'Interrupted work may need attention' in capsys.readouterr().out
