"""The canonical runner must preserve failures and distinguish blocked fixtures."""

import errno
import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('jarvis_full_suite_runner', str(ROOT / 'bin/test-suite'))
spec = importlib.util.spec_from_loader(loader.name, loader)
runner = importlib.util.module_from_spec(spec)
loader.exec_module(runner)


def test_child_uses_test_python_without_inherited_test_selection_or_live_flags(tmp_path):
    python = Path(sys.executable)
    env = runner.child_environment(python, {
        'PATH': '/usr/bin', 'PYTEST_ADDOPTS': '-k nothing', 'PYTEST_PLUGINS': 'private_plugin',
        'JARVIS_LIVE_BROWSER_TEST': '1', 'JARVIS_TEST_LONG_ENCODE': '1',
        'JARVIS_TEST_VIDEO': '/private/video.mp4', 'JARVIS_TEST_IMAGE': '/private/image.png',
        'PYTHONPATH': '/private/modules', 'PYTHONHOME': '/wrong/python',
        'PYTEST_CURRENT_TEST': 'outer test', 'PYTEST_XDIST_WORKER': 'gw9',
        'PYTEST_XDIST_WORKER_COUNT': '10', 'PYTEST_XDIST_TESTRUNUID': 'outer-run',
        'PYTEST_XDIST_AUTO_NUM_WORKERS': '10',
    })
    result = subprocess.run([str(python), '-c', """
import os, shutil, sys
assert os.path.samefile(shutil.which('python3'), sys.executable)
assert not any(key in os.environ for key in (
    'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'JARVIS_LIVE_BROWSER_TEST',
    'JARVIS_TEST_LONG_ENCODE', 'PYTHONPATH', 'PYTHONHOME',
    'JARVIS_TEST_VIDEO', 'JARVIS_TEST_IMAGE',
    'PYTEST_CURRENT_TEST', 'PYTEST_XDIST_WORKER', 'PYTEST_XDIST_WORKER_COUNT',
    'PYTEST_XDIST_TESTRUNUID', 'PYTEST_XDIST_AUTO_NUM_WORKERS',
))
"""], env=env, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('returncode', [2, 3])
def test_preflight_preserves_dependency_failure_vs_permission_denial(monkeypatch, tmp_path, capsys, returncode):
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, returncode, '', 'fixture error'))
    assert runner.preflight(Path(sys.executable), {}, tmp_path) == returncode
    captured = capsys.readouterr()
    assert 'fixture error' in captured.err
    assert ('ENVIRONMENT BLOCKED' in captured.out) == (returncode == 3)


@pytest.mark.parametrize('workers', [1, 2])
def test_preflight_requires_xdist_only_for_parallel_mode(monkeypatch, tmp_path, capsys, workers):
    block_xdist = '''
import builtins
original_import = builtins.__import__
def import_without_xdist(name, *args, **kwargs):
    if name == 'xdist':
        raise ImportError('simulated missing pytest-xdist')
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_xdist
'''
    monkeypatch.setattr(runner, 'PREFLIGHT', block_xdist + runner.PREFLIGHT)
    python = Path(sys.executable)
    assert runner.preflight(python, runner.child_environment(python), tmp_path, workers) == (
        2 if workers == 2 else 0
    )
    captured = capsys.readouterr()
    if workers == 2:
        assert 'simulated missing pytest-xdist' in captured.err
        assert 'uv sync --dev --frozen' in captured.err
    else:
        assert 'fixtures are available' in captured.out


@pytest.mark.parametrize('fixture', ['socket', 'async HTTP'])
@pytest.mark.parametrize('error_number', [errno.EPERM, errno.EACCES, errno.EADDRINUSE])
def test_probe_classifies_only_concrete_fixture_permission_errors(tmp_path, fixture, error_number):
    script = '''
import os, socket
from contextlib import nullcontext
from types import SimpleNamespace
import fastapi.testclient

def fail():
    raise OSError(ERROR_NUMBER, os.strerror(ERROR_NUMBER))

def bind(address):
    if FIXTURE == 'socket':
        fail()

def client(app):
    fail()

socket.socket = lambda: nullcontext(SimpleNamespace(bind=bind))
fastapi.testclient.TestClient = client
exec(PROBE)
'''
    source = f'ERROR_NUMBER={error_number!r}\nFIXTURE={fixture!r}\nPROBE={runner.PREFLIGHT!r}\n' + script
    result = subprocess.run(
        [sys.executable, '-c', source], cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    expected = 3 if error_number in (errno.EPERM, errno.EACCES) else 2
    assert result.returncode == expected, (result.stdout, result.stderr)
    assert os.strerror(error_number) in result.stderr
    assert f'Local {fixture} fixture unavailable' in result.stderr


@pytest.mark.parametrize('phase', ['dependency imports', 'local async HTTP fixture'])
def test_preflight_timeout_reports_phase_without_assuming_permission_denial(monkeypatch, tmp_path, capsys, phase):
    (tmp_path / '.venv' / 'bin').mkdir(parents=True)
    (tmp_path / '.venv' / 'bin' / 'python').symlink_to(sys.executable)
    monkeypatch.setattr(runner, 'ROOT', tmp_path)

    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 10
        raise subprocess.TimeoutExpired(
            args[0], kwargs['timeout'],
            output=f'Preflight phase: {phase}\n'.encode(), stderr=b'probe diagnostic\n',
        )

    monkeypatch.setattr(runner.subprocess, 'run', timeout)
    monkeypatch.setattr(runner, 'run_tests', lambda *a: pytest.fail('pytest started after timed-out preflight'))
    assert runner.main([]) == 4
    captured = capsys.readouterr()
    assert f'exceeded 10 seconds during {phase}' in captured.out
    assert 'No tests ran' in captured.out
    assert 'timeout alone does not establish a sandbox restriction' in captured.out
    assert 'outside the sandbox' not in captured.out
    assert 'ENVIRONMENT BLOCKED' not in captured.out
    assert 'probe diagnostic' in captured.err
    assert not (tmp_path / 'logs').exists()


def test_concrete_permission_denial_requests_host_rerun_without_starting_pytest(monkeypatch, tmp_path, capsys):
    (tmp_path / '.venv' / 'bin').mkdir(parents=True)
    (tmp_path / '.venv' / 'bin' / 'python').symlink_to(sys.executable)
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a, 3, 'Preflight phase: local TCP socket\n',
        'Local socket fixture unavailable: [Errno 1] Operation not permitted\n',
    ))
    monkeypatch.setattr(runner, 'run_tests', lambda *a: pytest.fail('pytest started despite permission denial'))
    assert runner.main([]) == 3
    captured = capsys.readouterr()
    assert 'No tests ran' in captured.out
    assert 'outside the sandbox' in captured.out
    assert 'EPERM or EACCES' in captured.out
    assert not (tmp_path / 'logs').exists()


@pytest.mark.parametrize('passing', [False, True])
@pytest.mark.parametrize('workers', [1, 2])
def test_real_pytest_exit_and_evidence_are_preserved(monkeypatch, tmp_path, passing, workers):
    (tmp_path / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_fixture.py').write_text(f'''
import pytest

def test_fixture(subtests):
    for value in (1, 2):
        with subtests.test(value=value):
            assert value > 0
    assert {passing!r}

@pytest.mark.skip(reason='explicit optional fixture')
def test_optional_fixture():
    pytest.fail('optional fixture unexpectedly ran')
''')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'preflight', lambda *args: 0)
    monkeypatch.setenv('PYTEST_ADDOPTS', '-k nonexistent')
    reports = tmp_path / 'evidence'
    arguments = ['--report-dir', str(reports)]
    if workers == 2:
        arguments.extend(['--workers', '2'])
    code = runner.main(arguments)
    assert code == (0 if passing else 1)
    summary = json.loads((reports / 'summary.json').read_text())
    assert summary['exit_code'] == code
    assert summary['scope'] == 'full'
    assert summary['workers'] == workers
    assert summary['distribution'] == ('loadfile' if workers == 2 else 'no')
    if workers == 2:
        assert summary['command'][-5:] == [
            '-n', '2', '--dist', 'loadfile', '--max-worker-restart=0',
        ]
    else:
        assert '-n' not in summary['command']
    assert summary['status'] == ('passed' if passing else 'failed')
    assert summary['junit']['available'] is True
    assert summary['junit']['testcase_counts'] == {
        'total': 2, 'passed': 1 if passing else 0, 'failures': 0 if passing else 1,
        'errors': 0, 'skipped': 1,
    }
    assert summary['junit']['skips'] == [{
        'classname': 'tests.test_fixture', 'name': 'test_optional_fixture',
        'type': 'pytest.skip', 'reason': 'explicit optional fixture',
    }]
    assert (reports / 'results.xml').is_file()
    assert ('1 passed' if passing else '1 failed') in (reports / 'pytest.log').read_text()
    assert '2 subtests passed' in (reports / 'pytest.log').read_text()


@pytest.mark.parametrize('workers', ['0', '3', '-1', 'auto'])
def test_worker_count_is_bounded_before_starting_preflight(monkeypatch, workers):
    monkeypatch.setattr(runner, 'preflight', lambda *args: pytest.fail('preflight ran'))
    with pytest.raises(SystemExit) as error:
        runner.main(['--workers', workers])
    assert error.value.code == 2


def test_two_workers_execute_distinct_files_without_splitting_them(monkeypatch, tmp_path):
    (tmp_path / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    (tmp_path / 'tests').mkdir()
    records = tmp_path / 'records'
    records.mkdir()
    source = '''
import json, os
from pathlib import Path
import pytest

@pytest.mark.parametrize('step', [1, 2])
def test_record_worker(step):
    record = {'pid': os.getpid(), 'worker': os.environ['PYTEST_XDIST_WORKER']}
    name = Path(__file__).stem + str(step) + '.json'
    (Path(RECORDS) / name).write_text(json.dumps(record))
'''
    for name in ('test_first.py', 'test_second.py'):
        (tmp_path / 'tests' / name).write_text(f'RECORDS={str(records)!r}\n' + source)
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'preflight', lambda *args: 0)
    reports = tmp_path / 'evidence'
    assert runner.main(['--workers', '2', '--report-dir', str(reports)]) == 0
    observed = []
    for name in ('first', 'second'):
        rows = [json.loads((records / f'test_{name}{step}.json').read_text()) for step in (1, 2)]
        assert rows[0] == rows[1], f'Test file {name} was split between workers'
        observed.append(rows[0])
    assert {row['worker'] for row in observed} == {'gw0', 'gw1'}
    assert len({row['pid'] for row in observed}) == 2
    summary = json.loads((reports / 'summary.json').read_text())
    assert summary['junit']['testcase_counts']['passed'] == 4


@pytest.mark.parametrize('contents', [None, '<testsuites><broken>'])
def test_missing_or_incomplete_junit_keeps_counts_unavailable(tmp_path, contents):
    path = tmp_path / 'results.xml'
    if contents is not None:
        path.write_text(contents)
    evidence = runner.junit_evidence(path)
    assert evidence['available'] is False
    assert 'testcase_counts' not in evidence
    assert evidence['error']


def test_timeout_stops_child_and_cannot_report_pass(tmp_path):
    result = runner.run_tests(
        [sys.executable, '-c', 'import time; time.sleep(60)'], os.environ.copy(),
        tmp_path, tmp_path / 'timeout.log', timeout=0.1,
    )
    assert result == 124


def test_termination_cleans_up_child_process(tmp_path):
    child_pid = tmp_path / 'child.pid'
    detached_pid = tmp_path / 'detached.pid'
    script = '''
import importlib.machinery, importlib.util, os, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('runner', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
runner = importlib.util.module_from_spec(spec)
loader.exec_module(runner)
actor = "import os, time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); time.sleep(60)" % sys.argv[3]
child = "import os, subprocess, sys, time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); subprocess.Popen([sys.executable, '-c', %r], start_new_session=True); time.sleep(60)" % (sys.argv[2], actor)
raise SystemExit(runner.run_tests([sys.executable, '-c', child], os.environ.copy(), Path.cwd(), Path('run.log'), 60))
'''
    process = subprocess.Popen(
        [sys.executable, '-c', script, str(ROOT / 'bin/test-suite'), str(child_pid), str(detached_pid)],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not detached_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert detached_pid.exists(), 'Detached fixture grandchild did not start'
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 143, (stdout, stderr)
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_pid.read_text()), 0)
        try:
            assert psutil.Process(int(detached_pid.read_text())).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        for path in (child_pid, detached_pid):
            if path.exists():
                try:
                    os.killpg(int(path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_termination_cleans_up_both_workers_and_their_detached_children(tmp_path):
    tests = tmp_path / 'tests'
    tests.mkdir()
    source = '''
import json, os, subprocess, sys, time
from pathlib import Path

def test_blocking_fixture():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             start_new_session=True)
    record = {'worker': os.getpid(), 'controller': os.getppid(), 'child': child.pid}
    Path(os.environ['PYTEST_XDIST_WORKER'] + '.json').write_text(json.dumps(record))
    time.sleep(60)
'''
    for name in ('test_first.py', 'test_second.py'):
        (tests / name).write_text(source)
    script = '''
import importlib.machinery, importlib.util, os, sys
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('runner', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
runner = importlib.util.module_from_spec(spec)
loader.exec_module(runner)
command = [sys.executable, '-m', 'pytest', 'tests', '-q', '-n', '2', '--dist', 'loadfile',
           '--max-worker-restart=0']
raise SystemExit(runner.run_tests(command, runner.child_environment(Path(sys.executable)),
                                 Path.cwd(), Path('run.log'), 60))
'''
    process = subprocess.Popen(
        [sys.executable, '-c', script, str(ROOT / 'bin/test-suite')],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    owned = []
    try:
        markers = [tmp_path / f'gw{number}.json' for number in (0, 1)]
        deadline = time.monotonic() + 15
        while not all(marker.exists() for marker in markers) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(marker.exists() for marker in markers), 'Both worker fixtures did not start'
        records = [json.loads(marker.read_text()) for marker in markers]
        owned = [psutil.Process(pid) for pid in {pid for row in records for pid in row.values()}]
        process.terminate()
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 143, (stdout, stderr)
        for child in owned:
            try:
                assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        for marker in tmp_path.glob('gw*.json'):
            for pid in json.loads(marker.read_text()).values():
                try:
                    child = psutil.Process(pid)
                    if child.is_running():
                        child.kill()
                except psutil.NoSuchProcess:
                    pass
