"""Docker stdio sessions must survive another registry's discovery and cleanup."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import mcp_client  # noqa: E402
from mcp_client import MCPClient  # noqa: E402


@pytest.fixture
def docker(monkeypatch):
    containers = {}
    launches = []
    removals = []

    def run(args, **kwargs):
        if args[1] == "ps":
            name = args[-1].removeprefix("name=^").removesuffix("$")
            return SimpleNamespace(stdout=containers[name].docker_id[:12] if name in containers else "", stderr="", returncode=0)
        assert args[1:3] == ["rm", "-f"]
        name = args[-1]
        removals.append(name)
        process = containers.pop(name, None)
        if process is not None:
            process.returncode = 137
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    def popen(args, **kwargs):
        name = args[args.index("--name") + 1]
        assert name not in containers, "duplicate live container"
        process = Mock(returncode=None)
        process.docker_id = f"{len(launches) + 1:012x}" + "0" * 52
        process.poll.side_effect = lambda: process.returncode
        process.terminate.side_effect = lambda: setattr(process, "returncode", 0)
        process.kill.side_effect = lambda: setattr(process, "returncode", 137)
        process.wait.side_effect = lambda **_: process.returncode
        containers[name] = process
        launches.append(name)
        return process

    monkeypatch.setattr(mcp_client.subprocess, "run", run)
    monkeypatch.setattr(mcp_client.subprocess, "Popen", popen)
    monkeypatch.setattr(mcp_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(MCPClient, "_initialize", lambda _: None)
    monkeypatch.setattr(mcp_client, "owner_labels", lambda: {})
    return SimpleNamespace(containers=containers, launches=launches, removals=removals)


def client():
    return MCPClient("fetch", "docker", ["run", "--rm", "-i", "mcp/fetch"])


def test_same_server_clients_survive_each_others_start_and_cleanup(docker):
    first, second = client(), client()
    first.start()
    first_process = first.process
    second.start()

    assert first_process.poll() is None
    assert first._check_health()
    assert len(docker.containers) == 2

    first.stop()
    assert second.process.poll() is None
    assert second._check_health()
    second.stop()
    assert not docker.containers
    assert all(name != "jarvis-mcp-fetch" for name in docker.removals)


def test_unstarted_client_cleanup_cannot_remove_another_session(docker):
    running, unused = client(), client()
    running.start()
    unused.stop()
    assert running.process.poll() is None
    assert docker.removals == []
    running.stop()


def test_crash_restart_replaces_only_its_own_container(docker):
    first, second = client(), client()
    first.start()
    second.start()
    original_name = docker.launches[0]
    first.process.returncode = 137

    assert first._check_health()
    assert docker.launches[-1] == original_name
    assert docker.removals == [original_name]
    assert first.process.poll() is None
    assert second.process.poll() is None
    first.stop()
    second.stop()


def test_repeated_start_keeps_one_container_per_client(docker):
    running = client()
    running.start()
    process = running.process
    running.start()
    assert running.process is process
    assert len(docker.launches) == 1
    running.stop()


def test_force_reset_removes_only_its_owned_container_immediately(docker):
    first, second = client(), client()
    first.start()
    second.start()
    first_name = docker.launches[0]
    first._force_restart("test timeout")
    assert first.process is None
    assert first_name not in docker.containers
    assert second.process.poll() is None
    second.stop()


def test_owned_cleanup_retries_dockers_removal_in_progress(docker, monkeypatch):
    running = client()
    running.start()
    original = mcp_client.subprocess.run
    attempts = []
    def run(args, **kwargs):
        if args[1] == 'rm':
            attempts.append(args[-1])
            if len(attempts) == 1:
                return SimpleNamespace(stdout='', stderr='container removal is already in progress', returncode=1)
        return original(args, **kwargs)
    monkeypatch.setattr(mcp_client.subprocess, 'run', run)
    running.stop()
    assert attempts == [docker.launches[0], docker.launches[0]]
    assert not docker.containers


def test_inflight_reader_cannot_consume_a_successors_stdio(monkeypatch):
    import json
    import select
    running = client()
    old, successor = Mock(), Mock()
    old.poll.return_value = None
    old.stdout.readline.return_value = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'owner': 'old'}}) + '\n'
    successor.stdout.readline.return_value = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'owner': 'successor'}}) + '\n'
    running.process = old
    def readable(*_):
        running.process = successor
        return [old.stdout], [], []
    monkeypatch.setattr(select, 'select', readable)
    assert running._send_request('tools/list') == {'owner': 'old'}
    successor.stdout.readline.assert_not_called()


def test_concurrent_start_keeps_one_container_for_the_client(docker, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    entered, release, second_entered = Event(), Event(), Event()
    running = client()
    def build_env():
        entered.set()
        assert release.wait(2)
        return {}
    monkeypatch.setattr(running, "_build_env_with_substitution", build_env)
    def second_start():
        second_entered.set()
        running.start()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(running.start)
        assert entered.wait(1)
        second = pool.submit(second_start)
        try:
            assert second_entered.wait(1)
            with pytest.raises(TimeoutError):
                second.result(timeout=.05)
        finally:
            release.set()
        first.result(timeout=1)
        second.result(timeout=1)
    assert len(docker.launches) == 1
    running.stop()


def test_crashed_discovery_does_not_claim_a_cooldown():
    failed = client()
    failed._auto_restart = False
    failed.process = Mock()
    failed.process.poll.return_value = 137

    with pytest.raises(Exception, match="exited during discovery \\(code 137\\)") as error:
        failed._send_request("tools/list")
    assert "cooldown" not in str(error.value)
    assert not failed._in_cooldown


def test_real_cooldown_retains_its_reason():
    failed = client()
    failed.process = Mock()
    failed.process.poll.return_value = 137
    failed._in_cooldown = True
    failed._last_restart_time = mcp_client.time.time()
    with pytest.raises(Exception, match="cooldown after repeated crashes"):
        failed._send_request("tools/list")


def test_expired_probe_cannot_start_late_or_stop_a_successor(docker, monkeypatch):
    import time
    from threading import Event
    entered, release, stopped = Event(), Event(), Event()
    probe, successor = client(), client()
    def build_env():
        entered.set()
        assert release.wait(2)
        return {}
    original_stop = probe.stop
    def stop():
        original_stop()
        stopped.set()
    monkeypatch.setattr(probe, "_build_env_with_substitution", build_env)
    monkeypatch.setattr(probe, "stop", stop)
    started = time.monotonic()
    try:
        assert mcp_client.probe_stdio_tools(probe, timeout_seconds=.03) == []
        assert time.monotonic() - started < .2
        assert entered.is_set()
        successor.start()
    finally:
        release.set()
    assert stopped.wait(1)
    assert len(docker.launches) == 1
    assert successor.process.poll() is None
    successor.stop()
