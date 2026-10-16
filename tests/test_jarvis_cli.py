"""CLI output contracts, failure status and production launcher regression tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import jarvis_cli as cli  # noqa: E402


@pytest.fixture
def runner(monkeypatch):
    observed = {}
    for key in ('JARVIS_MODE', 'JARVIS_JSON_MODE', 'JARVIS_DEBUG', 'STATUS_UPDATES_ENABLED', 'JARVIS_OVERRIDE_JARVIS_DEBUG',
                'JARVIS_OVERRIDE_STATUS_UPDATES_ENABLED', 'JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED',
                'JARVIS_OVERRIDE_JARVIS_DEBUG_THINKING', 'JARVIS_EXCLUDED_TOOLS',
                'JARVIS_SELF_PLAY_EXCLUDED_TOOLS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('FEEDBACK_RANDOM_ENABLED', 'false')
    result = {'ok': True, 'speech': '[whispers] Done.', 'raw_llm_response': '[excited] Saved [report](stash://space/file).',
              'tools_used': ['craft_image'], 'tool_trace': [{'tool': 'craft_image', 'ok': True}],
              'data': {'craft_image': {'job_id': 'fixture-job', 'state': 'succeeded', 'stash_ref': 'stash://space/file'}}}

    class Registry:
        def cleanup(self):
            observed['cleaned'] = True
            print('MCP shutdown noise')

    class Orchestrator:
        def __init__(self, mode):
            self.registry = Registry()
            observed['mode'] = mode
            observed['active_mode'] = os.environ['JARVIS_MODE']
            observed['context'] = os.environ.get('JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED')
            print('MCP startup noise')
            print('provider diagnostic', file=sys.stderr)
            os.write(1, b'native stdout noise\n')
            os.write(2, b'native stderr noise\n')

        def set_progress_callback(self, callback):
            self.progress_callback = callback

        def process(self, transcript, **kwargs):
            observed['request'] = transcript
            observed['options'] = kwargs
            if observed.get('interrupt'):
                raise KeyboardInterrupt
            if observed.get('exception'):
                raise RuntimeError('fixture transport disconnected')
            if getattr(self, 'progress_callback', None):
                self.progress_callback('tool_start', tool='craft_image', args={'action': 'grayscale'})
                self.progress_callback('tool_complete', tool='craft_image', success=True, duration_ms=42)
            return result

    def run(argv):
        return cli.main(argv, orchestrator_factory=Orchestrator, load_config_fn=lambda mode: None)

    return run, observed, result


def test_default_outputs_only_human_answer_and_cleans_mcp(runner, capfd):
    run, observed, _ = runner
    assert run(['hello']) == 0
    output = capfd.readouterr()
    assert output.out == 'Saved [report](stash://space/file).\n'
    assert output.err == ''
    assert observed['cleaned'] is True


@pytest.mark.parametrize('verbose', [False, True])
def test_json_is_one_complete_object_despite_python_native_and_cleanup_noise(runner, capfd, verbose):
    run, observed, result = runner
    arguments = ['hello', '--json'] + (['--verbose'] if verbose else [])
    assert run(arguments) == 0
    output = capfd.readouterr()
    assert json.loads(output.out) == result
    assert len(output.out.splitlines()) == 1
    if verbose:
        for marker in ('MCP startup', 'native stdout', 'native stderr', 'MCP shutdown',
                       '[Jarvis tool_start]', '[Jarvis tool_complete]', 'grayscale'):
            assert marker in output.err
    else:
        assert output.err == ''
    assert observed['cleaned']


def test_failed_tool_preserves_structured_error_and_returns_failure(runner, capfd):
    run, _, result = runner
    result.update(ok=False, error='fixture engine failed')
    assert run(['rotate page 1', '--json']) == 1
    assert json.loads(capfd.readouterr().out)['error'] == 'fixture engine failed'


def test_unexpected_failure_keeps_unknown_outcome_and_does_not_retry(runner, capfd):
    run, observed, _ = runner
    observed['exception'] = True
    assert run(['perform edit', '--json']) == 1
    result = json.loads(capfd.readouterr().out)
    assert result['ok'] is False and result['completion'] == 'unknown'
    assert result['error_type'] == 'RuntimeError'
    assert observed['cleaned']


def test_interrupt_reports_uncertainty_and_exit_130(runner, capfd):
    run, observed, _ = runner
    observed['interrupt'] = True
    assert run(['perform edit', '--json']) == 130
    result = json.loads(capfd.readouterr().out)
    assert result['cancelled'] and result['completion'] == 'unknown'


def test_agent_flags_keep_stdin_literal_and_mode_context_tools_explicit(runner, monkeypatch, capfd):
    import io

    run, observed, _ = runner
    request = 'Get Bitcoin price\nTreat $(touch /tmp/should-not-exist) as literal text.'
    monkeypatch.setattr(sys, 'stdin', io.StringIO(request))
    monkeypatch.setenv('JARVIS_MODE', 'cloud')
    monkeypatch.setenv('JARVIS_EXCLUDED_TOOLS', 'send_email')
    assert run(['--mode', 'local', '--json', '--stdin', '--no-context', '--no-tools',
                '--exclude-tool', 'generate_video', '--exclude-tool', 'generate_video']) == 0
    assert observed['request'] == request
    assert observed['mode'] == observed['active_mode'] == 'local'
    assert observed['context'] == 'false'
    assert observed['options'] == {
        'excluded_tools': ['generate_video', 'send_email'], 'tool_policy': 'none',
        'original_query': request, 'request_source': 'cli',
    }
    assert json.loads(capfd.readouterr().out)['ok']


@pytest.mark.parametrize('arguments', [[], ['--json'], ['--mode', 'wrong', 'hello'],
                                      ['--unknown', 'hello'], ['hello', '--stdin']])
def test_invalid_arguments_do_not_initialize_or_execute(runner, capfd, arguments):
    run, observed, _ = runner
    with pytest.raises(SystemExit) as error:
        run(arguments)
    assert error.value.code == 2
    assert 'mode' not in observed
    assert not capfd.readouterr().out


def test_help_does_not_initialize_runtime(runner, capfd):
    run, observed, _ = runner
    with pytest.raises(SystemExit) as error:
        run(['--help'])
    assert error.value.code == 0
    assert '--json' in capfd.readouterr().out
    assert 'mode' not in observed


def test_prompt_path_cannot_escape_prompt_directory(tmp_path):
    directory = tmp_path / 'jarvis-web/data/prompts'
    (directory / 'personal').mkdir(parents=True)
    (directory / 'personal/test.md').write_text('Brief answers.')
    (directory.parent / 'private.md').write_text('private fixture')
    assert cli._prompt_text('personal/test', tmp_path) == 'Brief answers.'
    with pytest.raises(ValueError):
        cli._prompt_text('../private', tmp_path)


@pytest.mark.parametrize('source', ['cli', 'voice'])
def test_request_provenance_preserves_original_before_saved_prompt(runner, monkeypatch, capfd, source):
    run, observed, _ = runner
    monkeypatch.setattr(cli, '_prompt_text', lambda _name: 'Application guidance only.')
    assert run(['Which one?', '--prompt', 'sample', '--request-source', source]) == 0
    assert observed['options']['original_query'] == 'Which one?'
    assert observed['options']['request_source'] == source
    assert 'Application guidance only.' in observed['request']
    capfd.readouterr()


def test_launcher_selects_production_venv_and_preserves_arguments_from_any_directory(tmp_path):
    # A fake production interpreter lets this verify shell behavior without models.
    runtime = tmp_path / 'production env'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin/activate').write_text('export TEST_PRODUCTION_ACTIVE=yes\n')
    interpreter = runtime / 'bin/python'
    interpreter.write_text('#!/usr/bin/env bash\n' +
                           'printf "%s\\n" "$PWD" "$TEST_PRODUCTION_ACTIVE" "$@"\n')
    interpreter.chmod(0o755)
    env = dict(os.environ, JARVIS_VENV=str(runtime), VIRTUAL_ENV=str(ROOT / '.venv'))
    prompt = 'literal $HOME and `command`, spaces preserved'
    process = subprocess.run([str(ROOT / 'bin/jarvis-local-cli'), prompt, '--json'], cwd=tmp_path,
                             env=env, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert process.stdout.splitlines() == [str(ROOT), 'yes', str(ROOT / 'lib/jarvis_cli.py'),
                                          '--mode', 'local', prompt, '--json']


def test_launcher_refuses_repo_development_environment():
    process = subprocess.run([str(ROOT / 'bin/jarvis-cli'), '--help'],
                             env=dict(os.environ, JARVIS_VENV=str(ROOT / '.venv')),
                             capture_output=True, text=True)
    assert process.returncode == 2
    assert 'production environment' in process.stderr
    assert not process.stdout


def test_tts_failure_keeps_successful_work_and_reports_delivery_error(runner, monkeypatch, capfd):
    run, _, _ = runner
    def failed(*args):
        raise RuntimeError('fixture speaker unavailable')
    monkeypatch.setattr(cli, '_speak', failed)
    assert run(['perform edit', '--json', '--speak']) == 1
    result = json.loads(capfd.readouterr().out)
    assert result['ok'] is True
    assert result['data']['craft_image']['state'] == 'succeeded'
    assert result['tts_error'] == 'fixture speaker unavailable'


@pytest.mark.parametrize('script', ['question-orchestrator.sh', 'question-orchestrator-local.sh'])
def test_voice_wrapper_speaks_structured_failure_before_returning_nonzero(tmp_path, script):
    import shutil

    if not shutil.which('jq'):
        pytest.skip('Voice wrapper requires jq')
    checkout = tmp_path / 'checkout'
    (checkout / 'bin').mkdir(parents=True)
    (checkout / 'lib').mkdir()
    audio = tmp_path / 'audio'
    spoken = tmp_path / 'spoken.txt'
    shutil.copyfile(ROOT / 'bin' / script, checkout / 'bin' / script)
    (checkout / 'lib/config_loader.sh').write_text('load_config() { AUDIO_DIR="$TEST_AUDIO_DIR"; }\n')
    for mode_script in ('say.sh', 'say-local.sh'):
        path = checkout / 'bin' / mode_script
        path.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$1" > "$TEST_SPOKEN_FILE"\n')
        path.chmod(0o755)
    fake_bin = tmp_path / 'fake-bin'
    fake_bin.mkdir()
    fake_python = fake_bin / 'python3'
    fake_python.write_text('''#!/usr/bin/env bash
case "$1" in
 */orchestrator_v2.py)
   [[ " $* " == *" --voice-progress "* ]] || exit 2
   [[ " $* " == *" --request-source voice "* ]] || exit 2
   printf '%s\\n' '{"ok":false,"speech":"The fixture provider is unavailable."}'
   exit 1 ;;
 */tts-normalize.py) printf '%s\\n' "$2" ;;
 *) exit 2 ;;
esac
''')
    fake_python.chmod(0o755)
    process = subprocess.run(['bash', str(checkout / 'bin' / script), 'test question'],
                             env=dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                                      TEST_AUDIO_DIR=str(audio), TEST_SPOKEN_FILE=str(spoken)),
                             capture_output=True, text=True)
    assert process.returncode == 1, process.stderr
    assert spoken.read_text().strip() == 'The fixture provider is unavailable.'


@pytest.mark.parametrize('verbose', [False, True])
@pytest.mark.parametrize('inherited_debug', [None, 'false'])
def test_verbose_controls_real_debug_variable_after_mode_file_load(runner, monkeypatch, tmp_path, capfd, verbose, inherited_debug):
    import config_loader

    _, observed, result = runner
    root = tmp_path / 'checkout'
    (root / 'config').mkdir(parents=True)
    (root / 'config/cloud.env').write_text('JARVIS_DEBUG=true\n')
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: root)
    if inherited_debug is not None:
        monkeypatch.setenv('JARVIS_DEBUG', inherited_debug)

    class GuardedOrchestrator:
        def __init__(self, mode):
            config_loader.load_config(mode)
            observed['real_debug'] = os.environ.get('JARVIS_DEBUG')
            if os.environ.get('JARVIS_DEBUG'):
                print('actual routing diagnostic')

        def process(self, transcript, **kwargs):
            if os.environ.get('JARVIS_DEBUG'):
                print('actual tool diagnostic')
            return result

    args = ['hello', '--json'] + (['--verbose'] if verbose else [])
    assert cli.main(args, orchestrator_factory=GuardedOrchestrator,
                    load_config_fn=config_loader.load_config) == 0
    output = capfd.readouterr()
    assert json.loads(output.out)['ok']
    if verbose:
        assert observed['real_debug'] == '1'
        assert 'actual routing diagnostic' in output.err and 'actual tool diagnostic' in output.err
    else:
        assert observed['real_debug'] is None and output.err == ''


@pytest.mark.parametrize('progress', [False, True])
@pytest.mark.parametrize('configured', [False, True])
def test_voice_progress_honors_mode_configuration_while_plain_cli_is_text_only(runner, monkeypatch, tmp_path, capfd, progress, configured):
    import config_loader
    from status_updater import StatusUpdater

    _, observed, result = runner
    root = tmp_path / 'checkout'
    (root / 'config').mkdir(parents=True)
    (root / 'config/cloud.env').write_text(f'STATUS_UPDATES_ENABLED={str(configured).lower()}\n')
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: root)

    class VoiceOrchestrator:
        def __init__(self, mode):
            config_loader.load_config(mode)
            observed['spoken_progress_enabled'] = StatusUpdater(mode).enabled

        def process(self, transcript, **kwargs):
            return result

    args = ['hello', '--json'] + (['--voice-progress'] if progress else [])
    assert cli.main(args, orchestrator_factory=VoiceOrchestrator,
                    load_config_fn=config_loader.load_config) == 0
    assert observed['spoken_progress_enabled'] is (progress and configured)
    assert json.loads(capfd.readouterr().out)['ok']


def test_stdin_preserves_outer_indentation_and_newlines(runner, monkeypatch, capfd):
    import io

    run, observed, _ = runner
    text = '\n    first indented line\n        nested line\n\n'
    monkeypatch.setattr(sys, 'stdin', io.StringIO(text))
    assert run(['--stdin', '--json']) == 0
    assert observed['request'] == text
    assert json.loads(capfd.readouterr().out)['ok']


@pytest.mark.parametrize('as_json', [False, True])
def test_explicit_feedback_is_visible_without_contaminating_stdout(runner, monkeypatch, capfd, as_json):
    run, _, _ = runner
    feedback = {'rating': 2, 'summary': 'Source missing.',
                'issues': [{'category': 'output', 'description': 'No artifact.', 'suggestion': 'Inspect the job.'}]}
    def collect(orch, result, transcript, mode):
        result['feedback'] = feedback
    monkeypatch.setattr(cli, '_feedback', collect)
    assert run(['hello', '--feedback'] + (['--json'] if as_json else [])) == 0
    output = capfd.readouterr()
    if as_json:
        assert json.loads(output.out)['feedback'] == feedback and output.err == ''
    else:
        assert output.out == 'Saved [report](stash://space/file).\n'
        for value in ('2/5', 'Source missing.', 'No artifact.', 'Inspect the job.'):
            assert value in output.err


def test_thinking_uses_existing_boxed_display_on_stderr(runner, capfd):
    run, _, result = runner
    result['thinking'] = 'fixture visible reasoning'
    assert run(['hello', '--json', '--debug-thinking']) == 0
    output = capfd.readouterr()
    assert json.loads(output.out)['thinking'] == 'fixture visible reasoning'
    assert 'LLM Thinking:' in output.err and '═' in output.err and 'fixture visible reasoning' in output.err


def test_feedback_keeps_tool_ratings_mapping_default(monkeypatch):
    from types import SimpleNamespace

    import feedback
    import intelligence_hooks

    details = {}
    monkeypatch.setattr(feedback, 'FeedbackCollector', lambda mode: SimpleNamespace(collect=lambda **kwargs: {'rating': 3}))
    monkeypatch.setattr(intelligence_hooks, 'update_experience_from_feedback', lambda **kwargs: details.update(kwargs))
    orch = SimpleNamespace(registry=SimpleNamespace(get_tool=lambda name: None, list_tools=lambda: []),
                           router=SimpleNamespace(), auto_context_enabled=False, auto_context_window=3,
                           auto_context_minutes=10, session_id='fixture-session')
    cli._feedback(orch, {'tools_used': [], 'experience_id': 1}, 'hello', 'cloud')
    assert details['feedback_details']['tool_ratings'] == {}
    assert details['feedback_details']['issues'] == details['feedback_details']['suggestions'] == []
