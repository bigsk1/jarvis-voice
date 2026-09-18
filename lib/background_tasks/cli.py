"""Native and container worker operations. One separately supervised service."""

import argparse
import json
import logging
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from filelock import FileLock, Timeout

from .models import TaskError
from .production import worker_adapters
from .store import TaskStore, default_store_path
from .worker import TaskWorker

TMUX_SESSION = 'jarvis-task-worker'


def _tmux(*arguments, check=False):
    return subprocess.run(['tmux', *arguments], capture_output=True, text=True,
                          check=check, timeout=10)


def _tmux_exists():
    return _tmux('has-session', '-t', TMUX_SESSION).returncode == 0


def _worker_ready(store):
    try:
        return bool(store.healthy_workers())
    except (OSError, sqlite3.Error, TaskError):
        return False


def manage_tmux(action, store):
    """Own native worker lifecycle; the start groups only delegate commands."""
    if action == 'status':
        ready, managed = _worker_ready(store), _tmux_exists()
        state = 'RUNNING' if ready else 'NOT READY' if managed else 'STOPPED'
        detail = 'shared worker' if ready else ''
        if ready and not managed:
            detail += ' (managed outside tmux)'
        print(f'  {TMUX_SESSION:<18} {state}  {detail}')
        return 0 if ready else 1
    if action in {'stop', 'restart'} and _tmux_exists():
        # The pane execs Python. Ctrl+C allows supervision to stop its child
        # group before the worker exits and the session closes.
        _tmux('send-keys', '-t', TMUX_SESSION, 'C-c', check=True)
        for _ in range(40):
            if not _tmux_exists():
                break
            time.sleep(.25)
        else:
            print(f'{TMUX_SESSION} did not stop within 10s; ending its session. '
                  'Interrupted work may need attention.')
            _tmux('kill-session', '-t', TMUX_SESSION, check=True)
        print(f'Stopped {TMUX_SESSION}')
    if action == 'stop':
        return 0
    if _worker_ready(store):
        print(f'{TMUX_SESSION} already ready (shared by cloud and local)')
        return 0
    if _tmux_exists():
        print(f'{TMUX_SESSION} exists but is not ready; inspect its logs or restart it')
        return 0
    if sys.platform != 'linux':
        print('Background worker requires Linux; UI services remain available')
        return 0
    root = Path(__file__).resolve().parents[2]
    venv = Path(os.environ.get('JARVIS_VENV') or Path.home() / 'jarvis-venv')
    command = (f'source {shlex.quote(str(venv / "bin/activate"))} '
               f'&& cd {shlex.quote(str(root))} && exec '
               + shlex.join([str(venv / 'bin/python'), str(root / 'bin/jarvis-task-worker'),
                             'run', '--db', str(store.path)]))
    _tmux('new-session', '-d', '-s', TMUX_SESSION, '-n', 'task-worker', command, check=True)
    print(f'{TMUX_SESSION} started (background admission still follows Settings → Tools)')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Optional local background worker; no admission is enabled automatically')
    parser.add_argument('action', choices=('run', 'status', 'unit', 'start', 'stop', 'restart'))
    parser.add_argument('--db', type=Path, default=default_store_path())
    parser.add_argument('--tmux', action='store_true',
                        help='Manage the native tmux worker; plain start/stop/restart use systemd')
    args = parser.parse_args()
    store = TaskStore(args.db)
    if args.tmux:
        if args.action not in {'start', 'stop', 'restart', 'status'}:
            parser.error('--tmux supports start, stop, restart, or status')
        try:
            raise SystemExit(manage_tmux(args.action, store))
        except (OSError, subprocess.SubprocessError) as exc:
            parser.exit(1, f'Task worker tmux command failed: {exc}\n')
    if args.action == 'status':
        try:
            workers = store.healthy_workers()
            report = {'ready': bool(workers), 'workers': workers, 'settings': store.settings(),
                      'counts': store.counts()}
        except (OSError, sqlite3.Error, TaskError):
            report = {'ready': False, 'error': 'Task storage is initializing or unavailable'}
        print(json.dumps(report))
        raise SystemExit(0 if report['ready'] else 1)
    if args.action == 'unit':
        root = Path(__file__).resolve().parents[2]
        # Print a reviewable portable unit; installation is an explicit operator step.
        def quote(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
        print('[Unit]\nDescription=Jarvis background task worker\nAfter=network.target\n\n[Service]')
        print('Type=simple\nUMask=0077')
        # WorkingDirectory is a single path directive, not an ExecStart argument.
        print('WorkingDirectory=' + str(root).replace('%', '%%'))
        print('ExecStart=' + ' '.join(map(quote, [sys.executable, root / 'bin/jarvis-task-worker', 'run', '--db', store.path])))
        print('Restart=on-failure\nRestartSec=5\nTimeoutStopSec=20\nKillMode=control-group\n\n[Install]\nWantedBy=default.target')
        return
    if args.action in {'start', 'stop', 'restart'}:
        # systemd owns restart policy independently of the regular Jarvis daemon
        # registry. An explicit stop stays stopped, including when admission is off.
        raise SystemExit(subprocess.call(['systemctl', '--user', args.action, 'jarvis-task-worker.service']))
    if not worker_adapters():
        parser.error('This worker requires Linux and a trusted local skill binding; foreground tools remain available')
    os.umask(0o077)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    ownership = FileLock(str(store.path) + '.worker.lock', timeout=0)
    try:
        ownership.acquire()
    except Timeout:
        parser.error('Another supervised worker owns this task store')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger(__name__).info('Starting Jarvis task worker pid=%s database=%s', os.getpid(), store.path)
    store.events.emit('worker_starting', component='worker')
    try:
        store.initialize()
        # Only deployment filesystem/profile settings may override both modes;
        # inherited provider/request overrides never become job authority.
        overrides = {key: os.environ['JARVIS_OVERRIDE_' + key]
                     for key in ('STASH_DIR', 'JARVIS_TOOL_PROFILE')
                     if 'JARVIS_OVERRIDE_' + key in os.environ}
        TaskWorker(store, worker_adapters(), deployment_overrides=overrides).run_forever(stop)
    except Exception as exc:
        store.events.emit('worker_run_failed', component='worker', level='ERROR', error_type=type(exc).__name__)
        raise
    finally:
        ownership.release()
