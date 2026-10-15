"""Exercise the real dashboard's inline CLI path and existing service launches."""

import asyncio
import importlib.machinery
import importlib.util
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dashboard(monkeypatch):
    loader = importlib.machinery.SourceFileLoader('jarvis_dashboard_test', str(ROOT / 'bin/jarvis-dashboard'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, loader.name, module)
    loader.exec_module(module)
    return module


def output_text(app, dashboard):
    return '\n'.join(line.text for line in app.query_one('#output-log', dashboard.RichLog).lines)


def test_cli_entries_use_foreground_launchers_without_runtime_overrides(dashboard):
    entries = [command for command in dashboard.COMMANDS if command.category == '💬 CLI']
    assert len(entries) == 7
    for command in entries:
        arguments = shlex.split(command.command)
        assert arguments[0] in {'./bin/jarvis-cli', './bin/jarvis-local-cli'}
        assert not set(arguments) & {'--interactive', '--no-context', '--no-tools', '--prompt', '--exclude-tool'}
        assert command.literal_output and not command.interactive
        assert ('--stdin' in arguments) == command.prompt_for_request


@pytest.mark.parametrize('size', [(80, 24), (160, 50)])
def test_tui_mount_switch_tabs_and_filter_commands(dashboard, size):
    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=size) as pilot:
            tabs = app.query_one('#tabs', dashboard.TabbedContent)
            tabs.active = 'tab-cli'
            await pilot.pause()
            assert len(app.query_one('#list-cli', dashboard.ListView).children) == 7
            assert not app.query_one('#cli-question', dashboard.Input).display
            search = app.query_one('#search-box', dashboard.Input)
            search.value = 'Personalization'
            await pilot.pause()
            assert len(app.query_one('#list-cli', dashboard.ListView).children) == 2
            search.value = ''
            await pilot.pause()
            tabs.active = 'tab-core'
            await pilot.pause()
            assert any(item.command_obj.name == 'Start Jarvis (Cloud)'
                       for item in app.query_one('#list-core', dashboard.ListView).children)
            tabs.active = 'tab-cli'
            await pilot.pause()
            assert len(app.query_one('#list-cli', dashboard.ListView).children) == 7
    asyncio.run(exercise())


class Stdin:
    def __init__(self):
        self.data = b''
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True


class Process:
    def __init__(self, stdout=b'', stderr=b'', returncode=0):
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.stdin = Stdin()
        self.returncode = returncode

    async def wait(self):
        return self.returncode


@pytest.mark.parametrize('command_name', ['User Context (Cloud)', 'User Context (Local)',
    'Personalization Check (Cloud)', 'Personalization Check (Local)', 'CLI Help'])
def test_selecting_cli_preset_shows_answer_in_right_pane_without_tmux(dashboard, monkeypatch, command_name):
    calls = []
    async def child(command, **kwargs):
        calls.append(command)
        return Process(b'Jarvis answer: [literal] user preferences\n')
    async def never_tmux(*_args):
        pytest.fail('A CLI question must not open a tmux session')
    monkeypatch.setattr(dashboard.asyncio, 'create_subprocess_shell', child)
    monkeypatch.setattr(dashboard.CommandRunner, 'run_interactive_command', never_tmux)

    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=(160, 50)) as pilot:
            app.query_one('#tabs', dashboard.TabbedContent).active = 'tab-cli'
            await pilot.pause()
            view = app.query_one('#list-cli', dashboard.ListView)
            view.focus()
            view.index = next(i for i, item in enumerate(view.children) if item.command_obj.name == command_name)
            await pilot.press('enter')
            await pilot.pause()
            output = output_text(app, dashboard)
            assert 'Jarvis answer: [literal] user preferences' in output
            assert 'Finished' in output
            assert 'To attach:' not in output and 'tmux' not in output
            assert len(calls) == 1 and './bin/jarvis-' in calls[0]
    asyncio.run(exercise())


@pytest.mark.parametrize('mode', ['Cloud', 'Local'])
def test_custom_question_is_entered_in_tui_and_sent_literally_on_stdin(dashboard, monkeypatch, mode):
    calls, processes = [], []
    request = 'What do you know about me? [literal] $(touch /tmp/never-run)'
    async def child(command, **kwargs):
        calls.append((command, kwargs))
        process = Process(b'Your configured preferences guide this answer.\n')
        processes.append(process)
        return process
    monkeypatch.setattr(dashboard.asyncio, 'create_subprocess_shell', child)

    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one('#tabs', dashboard.TabbedContent).active = 'tab-cli'
            await pilot.pause()
            view = app.query_one('#list-cli', dashboard.ListView)
            view.focus()
            view.index = 0 if mode == 'Cloud' else 1
            await pilot.press('enter')
            await pilot.pause()
            question = app.query_one('#cli-question', dashboard.Input)
            assert question.display and question.has_focus and not calls
            assert mode in question.placeholder
            await pilot.press('q', 'c', '/')
            assert question.value == 'qc/'  # App shortcuts must not consume question text.
            question.value = request
            await pilot.pause()
            assert len(view.children) == 7  # Typing must not filter command lists.
            await pilot.press('enter')
            await pilot.pause()
            assert not question.display
            assert 'Your configured preferences guide this answer.' in output_text(app, dashboard)
            assert len(calls) == 1 and request not in calls[0][0]
            assert calls[0][1]['stdin'] == asyncio.subprocess.PIPE
            assert processes[0].stdin.data.decode() == request and processes[0].stdin.closed
            expected = './bin/jarvis-cli' if mode == 'Cloud' else './bin/jarvis-local-cli'
            assert expected + ' --stdin' in calls[0][0]
    asyncio.run(exercise())


def test_cancelling_or_empty_question_does_not_start_cli(dashboard, monkeypatch):
    async def never_run(*_args, **_kwargs):
        pytest.fail('Cancelled/empty question launched a process')
    monkeypatch.setattr(dashboard.asyncio, 'create_subprocess_shell', never_run)

    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=(100, 30)) as pilot:
            command = next(item for item in dashboard.COMMANDS if item.name == 'Ask Jarvis (Cloud)')
            await app.run_command(command)
            await pilot.pause()
            question = app.query_one('#cli-question', dashboard.Input)
            question.value = '   '
            await pilot.press('enter')
            await pilot.pause()
            assert question.display
            await pilot.press('escape')
            await pilot.pause()
            assert not question.display and app._pending_cli_command is None
    asyncio.run(exercise())


def test_failed_cli_prints_error_in_same_output_pane(dashboard, monkeypatch):
    async def child(*_args, **_kwargs):
        return Process(b'Jarvis could not complete the request.\n', b'[provider] unavailable\n', 1)
    monkeypatch.setattr(dashboard.asyncio, 'create_subprocess_shell', child)
    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=(100, 30)):
            command = next(item for item in dashboard.COMMANDS if item.name == 'User Context (Cloud)')
            await app.run_command(command)
            output = output_text(app, dashboard)
            assert 'could not complete' in output and '[provider] unavailable' in output
            assert 'Failed (Code 1)' in output and 'Finished' not in output
    asyncio.run(exercise())


@pytest.mark.parametrize('inside_tmux', [True, False])
def test_existing_service_tmux_flow_stays_available(dashboard, monkeypatch, inside_tmux):
    if inside_tmux:
        monkeypatch.setenv('TMUX', 'fixture-session')
    else:
        monkeypatch.delenv('TMUX', raising=False)
    calls = []
    async def child(command, **kwargs):
        calls.append(command)
        return Process()
    monkeypatch.setattr(dashboard.asyncio, 'create_subprocess_shell', child)
    command = next(item for item in dashboard.COMMANDS if item.name == '🚀 Start All Services')
    async def exercise():
        app = dashboard.CommandRunner()
        async with app.run_test(size=(100, 30)):
            await app.run_command(command)
    asyncio.run(exercise())
    assert len(calls) == 2 and calls[0] == 'which tmux'
    arguments = shlex.split(calls[1])
    assert arguments[:2] == ['tmux', 'new-window' if inside_tmux else 'new-session']
    assert 'read -p' not in arguments[-1]
