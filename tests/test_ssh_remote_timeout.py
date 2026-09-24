"""SSH command deadlines, sudo input, and package timeout reporting."""

import shlex
from types import SimpleNamespace

import pytest

from skills import ssh_remote


class _Channel:
    def __init__(self, *, stdout=b'', stderr=b'', completes=True):
        self.stdout = [stdout] if stdout else []
        self.stderr = [stderr] if stderr else []
        self.completes = completes
        self.closed = False
        self.status_read = False

    def recv_ready(self):
        return bool(self.stdout)

    def recv(self, _size):
        return self.stdout.pop(0)

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv_stderr(self, _size):
        return self.stderr.pop(0)

    def exit_status_ready(self):
        return self.completes and not self.stdout and not self.stderr

    def recv_exit_status(self):
        assert not self.stdout and not self.stderr, 'output must drain before exit wait'
        self.status_read = True
        return 0

    def close(self):
        self.closed = True


def test_run_command_drains_both_streams_before_exit_status():
    channel = _Channel(stdout=b'first\nsecond\n', stderr=b'notice\n')
    client = SimpleNamespace(exec_command=lambda _command, **_options: (
        None, SimpleNamespace(channel=channel), None))

    result = ssh_remote.run_command(client, 'uptime', timeout=2)

    assert result['success'] is True
    assert result['stdout'] == 'first\nsecond\n'
    assert result['stderr'] == 'notice\n'
    assert channel.status_read and channel.closed


def test_run_command_has_wall_clock_deadline_even_without_output(monkeypatch):
    channel = _Channel(completes=False)
    client = SimpleNamespace(exec_command=lambda _command, **_options: (
        None, SimpleNamespace(channel=channel), None))
    ticks = iter([0.0, 1.1])
    monkeypatch.setattr(ssh_remote, 'time', SimpleNamespace(
        monotonic=lambda: next(ticks), sleep=lambda _duration: None))

    with pytest.raises(TimeoutError, match='exceeded 1 seconds'):
        ssh_remote.run_command(client, 'sleep forever', timeout=1)
    assert channel.closed


def test_run_command_deadline_applies_while_output_keeps_arriving(monkeypatch):
    channel = _Channel(completes=False)
    channel.recv_ready = lambda: True
    channel.recv = lambda _size: b'continuing\n'
    client = SimpleNamespace(exec_command=lambda _command, **_options: (
        None, SimpleNamespace(channel=channel), None))
    ticks = iter([0.0, 1.1])
    monkeypatch.setattr(ssh_remote, 'time', SimpleNamespace(
        monotonic=lambda: next(ticks), sleep=lambda _duration: None))

    with pytest.raises(TimeoutError, match='exceeded 1 seconds'):
        ssh_remote.run_command(client, 'yes', timeout=1)
    assert channel.closed


def test_sudo_password_is_sent_on_stdin_and_shell_command_is_quoted():
    channel = _Channel(stdout=b'done\n')
    commands = []
    written = []
    stdin = SimpleNamespace(write=lambda text: written.append(text),
                            close=lambda: written.append('[stdin closed]'))

    def exec_command(command, **_options):
        commands.append(command)
        return stdin, SimpleNamespace(channel=channel), None

    command = "printf '%s' 'quoted value'"
    result = ssh_remote.run_command(SimpleNamespace(exec_command=exec_command),
                                    command, sudo=True, sudo_password='backend-only')

    assert result['success'] is True
    assert commands == [f'sudo -S bash -c {shlex.quote(command)}']
    assert 'backend-only' not in commands[0]
    assert written == ['backend-only\n', '[stdin closed]']


def test_apt_timeout_names_uncertain_remote_stage(monkeypatch):
    class Client:
        def close(self):
            pass

    monkeypatch.setattr(ssh_remote, 'get_host_config', lambda _host: {'sudo_env': None})
    monkeypatch.setattr(ssh_remote, 'connect_ssh', lambda _config: Client())
    calls = []

    def run_command(_client, command, **_options):
        calls.append(command)
        if command == ssh_remote.SSH_APT_UPGRADE_COMMAND:
            raise TimeoutError('Remote command exceeded 600 seconds')
        return {'success': True, 'stdout': 'package available\n', 'stderr': '', 'exit_code': 0}

    monkeypatch.setattr(ssh_remote, 'run_command', run_command)
    result = ssh_remote.apt_update('vps2')

    assert calls[-1] == ssh_remote.SSH_APT_UPGRADE_COMMAND
    assert result['ok'] is False
    assert result['data']['stage'] == 'upgrade'
    assert 'may still be running' in result['speech']
