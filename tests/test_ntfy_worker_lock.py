"""Process-level regressions for lock contention in the supervised ntfy daemon."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX daemon shutdown signals')

ROOT = Path(__file__).resolve().parents[1]
WORKER = """
import os
import sys
from pathlib import Path
from services import ntfy_notifications as service

service.PROJECT_ROOT = Path(sys.argv[1])
service.LOCK_RETRY_SECONDS = float(sys.argv[2])
service.sys.argv = ['ntfy-worker']
original_load = service.load_config
def observed_load(path):
    (service.PROJECT_ROOT / f'scanned-{os.getpid()}').touch()
    return original_load(path)
service.load_config = observed_load
raise SystemExit(service.main())
"""


def wait_until(predicate, process, log):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        assert process.poll() is None, log.read_text()
        time.sleep(0.01)
    pytest.fail(f"Worker did not reach expected state: {log.read_text()}")


@pytest.fixture
def workers(tmp_path):
    processes = []
    (tmp_path / 'data').mkdir()

    def spawn(retry_seconds=0.05):
        log = tmp_path / f'worker-{len(processes)}.log'
        with log.open('w') as output:
            process = subprocess.Popen(
                [sys.executable, '-u', '-c', WORKER, str(tmp_path), str(retry_seconds)], cwd=ROOT,
                env={**os.environ, 'JARVIS_MODE': 'cloud'},
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            )
        processes.append(process)
        return process, log, tmp_path / f'scanned-{process.pid}'

    yield spawn
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize('shutdown_signal', [signal.SIGTERM, signal.SIGINT])
def test_contending_daemon_stays_alive_without_scanning_and_stops_cleanly(
    tmp_path, workers, shutdown_signal
):
    with FileLock(tmp_path / 'data/ntfy_notifications.db.lock'):
        process, log, scanned = workers(retry_seconds=15)
        wait_until(lambda: 'owns the delivery lock; waiting' in log.read_text(), process, log)
        # The production-length wait must stay alive and be interrupted by the signal.
        time.sleep(0.2)
        assert process.poll() is None
        assert log.read_text().count('owns the delivery lock; waiting') == 1
        assert not scanned.exists()
        assert not (tmp_path / 'data/ntfy_notifications.db').exists()
        assert not (tmp_path / 'logs/ntfy_notifications.status.json').exists()
        process.send_signal(shutdown_signal)
        assert process.wait(timeout=5) == 0
        assert not scanned.exists()


def test_waiting_daemon_takes_over_after_owner_stops_and_releases_lock(tmp_path, workers):
    owner, owner_log, owner_scanned = workers()
    wait_until(owner_scanned.exists, owner, owner_log)
    standby, standby_log, standby_scanned = workers()
    wait_until(lambda: 'owns the delivery lock; waiting' in standby_log.read_text(),
               standby, standby_log)
    # Several retries must not flood logs or terminate the standby daemon.
    time.sleep(0.2)
    assert standby.poll() is None
    assert (tmp_path / 'logs/ntfy_notifications.status.json').exists()
    assert standby_log.read_text().count('owns the delivery lock; waiting') == 1
    assert not standby_scanned.exists()
    lock = FileLock(tmp_path / 'data/ntfy_notifications.db.lock')
    with pytest.raises(Timeout):
        lock.acquire(timeout=0)
    owner.terminate()
    assert owner.wait(timeout=5) == 0
    wait_until(standby_scanned.exists, standby, standby_log)
    assert 'delivery lock acquired; resuming worker' in standby_log.read_text()
    assert standby.poll() is None
    with pytest.raises(Timeout):
        lock.acquire(timeout=0)
    standby.terminate()
    assert standby.wait(timeout=5) == 0
    assert json.loads((tmp_path / 'logs/ntfy_notifications.status.json').read_text())['state'] == 'stopped'
    with lock.acquire(timeout=0):
        pass
