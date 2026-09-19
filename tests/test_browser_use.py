"""Browser runtime selection, proxy policy, and durable callback-service contracts."""
import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'lib'), str(ROOT / 'orchestrator')]

from lib.background_tasks import TaskError, TaskStore  # noqa: E402
from lib.webhook_integrations.browser import callback_sources, provision, read_config  # noqa: E402
from lib.webhook_integrations.browser_service import BrowserService, child_environment  # noqa: E402


def browser_cli():
    loader = importlib.machinery.SourceFileLoader(
        f'jarvis_browser_use_cli_{time.time_ns()}', str(ROOT / 'bin/jarvis-browser-use'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TmuxStore:
    def __init__(self, path, active=False):
        self.path = path
        self.active = active

    def list_jobs(self, *, tool, state, limit):
        assert tool == 'browser_use' and limit == 1
        return {'total': int(self.active and state == 'running')}


def exercise_tmux(monkeypatch, tmp_path, *, action, managed, ready, active=False):
    cli = browser_cli()
    state = {'managed': managed, 'ready': ready}
    commands = []

    def tmux(*arguments, check=False):
        commands.append(list(arguments))
        if arguments[0] == 'send-keys':
            state.update(managed=False, ready=False)
        elif arguments[0] == 'new-session':
            state.update(managed=True, ready=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, 'tmux', tmux)
    monkeypatch.setattr(cli, 'tmux_exists', lambda: state['managed'])
    monkeypatch.setattr(cli, 'service_ready', lambda store: state['ready'])
    monkeypatch.setattr(cli, 'read_config', lambda store: {})
    result = cli.manage_tmux(action, TmuxStore(tmp_path / 'tasks.db', active))
    return result, commands, state


def test_browser_tmux_restart_starts_again_after_stopping_healthy_helper(monkeypatch, tmp_path):
    result, commands, state = exercise_tmux(
        monkeypatch, tmp_path, action='restart', managed=True, ready=True)
    assert result == 0 and state == {'managed': True, 'ready': True}
    assert next(i for i, command in enumerate(commands) if command[0] == 'send-keys') < next(
        i for i, command in enumerate(commands) if command[0] == 'new-session')


def test_browser_tmux_start_heals_stale_managed_session(monkeypatch, tmp_path):
    result, commands, state = exercise_tmux(
        monkeypatch, tmp_path, action='start', managed=True, ready=False)
    assert result == 0 and state == {'managed': True, 'ready': True}
    assert [command[0] for command in commands] == ['send-keys', 'new-session']


def test_browser_tmux_start_leaves_healthy_helper_running(monkeypatch, tmp_path):
    result, commands, state = exercise_tmux(
        monkeypatch, tmp_path, action='start', managed=True, ready=True, active=True)
    assert result == 0 and state == {'managed': True, 'ready': True}
    assert commands == []


def test_browser_tmux_restart_refuses_to_interrupt_active_research(monkeypatch, tmp_path):
    result, commands, state = exercise_tmux(
        monkeypatch, tmp_path, action='restart', managed=True, ready=True, active=True)
    assert result == 1 and state == {'managed': True, 'ready': True}
    assert commands == []


def test_browser_tmux_stop_preserves_active_research_if_grace_expires(monkeypatch, tmp_path):
    cli = browser_cli()
    commands = []
    monkeypatch.setattr(cli, 'tmux', lambda *args, **_kwargs: (
        commands.append(args) or SimpleNamespace(returncode=0)))
    monkeypatch.setattr(cli, 'tmux_exists', lambda: True)
    monkeypatch.setattr(cli, 'service_ready', lambda _store: True)
    monkeypatch.setattr(cli, 'browser_work_active', lambda _store: True)
    monkeypatch.setattr(cli.time, 'sleep', lambda _delay: None)
    assert cli.manage_tmux('stop', TmuxStore(tmp_path / 'tasks.db', True)) == 1
    assert [args[0] for args in commands] == ['send-keys']


def test_browser_retry_delivery_cli_does_not_require_docker(monkeypatch, tmp_path, capsys):
    import browser_agent

    from lib.webhook_integrations import browser_service

    cli = browser_cli()
    monkeypatch.setattr(sys, 'argv', ['jarvis-browser-use', 'retry-delivery', '--db',
                                     str(tmp_path / 'tasks.db'), '--attempt-id', 'attempt-1'])
    monkeypatch.setattr(browser_agent, 'check_runtime', lambda: pytest.fail('Docker is not required to retry a callback'))
    monkeypatch.setattr(cli, 'read_config', lambda _store: {})
    calls = []
    monkeypatch.setattr(browser_service.BrowserService, 'retry_rejected', staticmethod(
        lambda path, attempt: calls.append((path, attempt)) or 1))
    prior_umask = os.umask(0o077)
    try:
        cli.main()
    finally:
        os.umask(prior_umask)
    assert calls == [(tmp_path / 'browser-use.db', 'attempt-1')]
    assert 'no browser work restarted' in capsys.readouterr().out


@pytest.fixture
def browser_executor(monkeypatch):
    import executor
    import tool_process
    from tool_schema import ToolSchema

    schema = ToolSchema.from_json_file(str(ROOT / 'skills/browser_use.tool.json'))
    registry = SimpleNamespace(get_tool=lambda name: schema if name == schema.name else None)
    monkeypatch.setattr(executor, 'get_logger', lambda *_: None)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: pytest.fail('foreground child must not start'))
    return executor.ToolExecutor(registry=registry, load_runtime_config=False)


@pytest.mark.parametrize('context_kind', ['none', 'empty', 'other_tool', 'forged'])
def test_browser_requires_selected_server_web_context(browser_executor, context_kind):
    from lib.background_tasks.admission import WebTaskContext

    contexts = {
        'none': None,  # Voice, Talk, Firefox, query API, CLI and workflow callers.
        'empty': WebTaskContext(None, 'unused', ()),  # Web preferences disabled.
        'other_tool': WebTaskContext(None, 'unused', ('convert_file',)),
        'forged': {'selected': ['browser_use']},
    }
    result = browser_executor.execute('browser_use', {'task': 'Research', 'url': 'https://example.com'},
                                      background_context=contexts[context_kind])
    assert result['ok'] is False
    if context_kind != 'forged':
        assert result['error_code'] == 'background_execution_required'
        assert 'Jarvis Web text chat' in result['speech'] and 'No work was started' in result['speech']


@pytest.mark.parametrize('supervised', [False, True])
def test_foreground_seam_cannot_bypass_required_background(browser_executor, supervised):
    result = browser_executor._execute_foreground('browser_use', {}, skip_permission_check=True,
                                                  supervision=object() if supervised else None)
    assert result['error_code'] == 'background_execution_required'


def test_failed_web_admission_never_falls_back(browser_executor):
    from lib.background_tasks.admission import WebTaskContext

    def unavailable(*_):
        raise TaskError('Callback service is unavailable')
    context = WebTaskContext(SimpleNamespace(admit=unavailable), 'authorization', ('browser_use',))
    result = browser_executor.execute('browser_use', {}, background_context=context, invocation_id='call')
    assert not result['ok'] and result['error'] == 'Callback service is unavailable'


def test_workflow_step_cannot_start_browser_work(browser_executor, monkeypatch):
    import pipeline_executor

    monkeypatch.setattr(pipeline_executor, 'load_config', lambda *_: None)
    monkeypatch.setattr(pipeline_executor, 'ToolLogger', lambda: None)
    monkeypatch.setattr(pipeline_executor, 'LLMLogger', lambda: None)
    pipeline = pipeline_executor.PipelineExecutor('cloud', browser_executor, provider=object())
    result = pipeline._execute_single({'params': {'task': 'Research', 'url': 'https://example.com'}},
                                     'browser_use', '', {}, {}, {})
    assert result['error_code'] == 'background_execution_required'


def test_required_metadata_denies_even_without_a_usable_adapter(browser_executor):
    from tool_schema import ToolSchema

    schema = ToolSchema('required_probe', 'Probe', {}, '/must-not-execute',
                        execution={'background': {'required': True, 'supported': False}})
    browser_executor.registry = SimpleNamespace(get_tool=lambda _: schema)
    assert schema.background_adapter is None
    result = browser_executor.execute('required_probe', {})
    assert result['error_code'] == 'background_execution_required'


def test_direct_browser_skill_rejects_caller_supplied_background_flags(tmp_path):
    result = subprocess.run([sys.executable, '-I', str(ROOT / 'skills/browser_use.py'),
                             json.dumps({'background': True, 'source': 'web', 'task': 'Research',
                                         'url': 'https://example.com'})],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['error_code'] == 'background_execution_required'


@pytest.mark.parametrize('failure', ['missing_image', 'missing_docker'])
def test_known_preflight_failure_delivers_failed_callback_and_releases_slot(tmp_path, monkeypatch, capsys, failure):
    import browser_agent
    import tool_process
    from test_task_callbacks import bound, configured, deliver

    from lib.webhook_integrations import browser_job

    integration, source, credential, _ = configured(tmp_path, clock=time.time)
    claim, submission = bound(integration, source)
    assert integration.store.counts()['running'] == 1
    config = {'callback_url': source['endpoint'], 'credential': credential}
    host = BrowserService(tmp_path / 'browser.db', config)
    payload = {**{key: submission[key] for key in ('job_id', 'attempt_id', 'idempotency_key',
                                                 'callback_url', 'callback_capability')},
               'arguments': {'task': 'Research', 'url': 'https://example.com'},
               'runtime': {'mode': 'cloud', 'provider': 'ollama', 'model': 'test:cloud',
                           'deadline': time.time() + 600, 'proxy_policy': 'inherit'}}
    monkeypatch.setattr(browser_job, 'load_config', lambda *_: None)
    private_request = {'arguments': payload['arguments'], 'job_id': payload['job_id'],
                       'attempt_id': payload['attempt_id']}
    monkeypatch.setattr(sys, 'argv', ['browser_job.py', json.dumps(private_request)])
    def inspect_image(command, **kwargs):
        assert command[:3] == ['docker', 'image', 'inspect']
        if failure == 'missing_docker':
            raise FileNotFoundError('docker')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(browser_agent.subprocess, 'run', inspect_image)
    monkeypatch.setattr(browser_agent, 'create_configured_provider', lambda **_: pytest.fail('no model before preflight'))
    assert browser_job.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['completion'] == 'rejected' and result['error_code'] == 'browser_preflight_failed'
    assert 'Docker' in result['speech'] and 'No browser work was started' in result['speech']
    def execute_child(command, *args, **kwargs):
        assert command[1] == '-I' and command[2].endswith('/lib/webhook_integrations/browser_job.py')
        return output, '', False
    monkeypatch.setattr(tool_process, 'run_local_process', execute_child)
    assert host.accept(payload)[1] == 202
    assert host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        raw = conn.execute('SELECT body FROM browser_events').fetchone()[0].encode()
    assert json.loads(raw)['type'] == 'task.failed'
    deliver(integration, source, credential, submission, raw)
    assert integration.drain() == 1
    assert integration.store.get(claim.job_id)['state'] == 'failed'
    assert integration.store.counts()['running'] == 0
    assert len(integration.store.pending_deliveries()) == 1


@pytest.fixture
def browser_host(tmp_path):
    store = TaskStore(tmp_path / 'tasks.db')
    provision(store, 'http://127.0.0.1:8880', 'http://127.0.0.1:8790/submit')
    config = read_config(store)
    service = BrowserService(tmp_path / 'browser.db', config)
    payload = {'job_id': 'job-1', 'attempt_id': 'attempt-1', 'idempotency_key': 'attempt-1',
               'callback_url': config['callback_url'], 'callback_capability': 'c' * 43,
               'arguments': {'task': 'Find the test fact.', 'url': 'https://example.com', 'max_steps': 3},
               'runtime': {'mode': 'cloud', 'provider': 'ollama', 'model': 'test:cloud',
                           'deadline': time.time() + 600, 'proxy_policy': 'inherit'}}
    return service, payload, store


def test_real_callback_child_boot_and_missing_docker_return_known_failure(browser_host, monkeypatch, tmp_path):
    host, payload, _ = browser_host
    config = tmp_path / 'config-root' / 'config'
    config.mkdir(parents=True)
    (config / 'cloud.env').write_text('')
    monkeypatch.setattr('lib.webhook_integrations.browser_service.child_environment', lambda *_: {
        'PATH': str(tmp_path / 'no-docker'), 'JARVIS_MODE': 'cloud',
        'JARVIS_CONFIG_ROOT': str(config.parent), 'JARVIS_JSON_MODE': '1',
    })
    host.accept(payload)
    assert host.execute_one()  # Real fresh Python child and imports; no model/Docker call.
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        event = json.loads(conn.execute('SELECT body FROM browser_events').fetchone()[0])
    assert event['type'] == 'task.failed'
    assert 'Docker Engine is unavailable' in event['result']['summary']
    assert 'No browser work was started' in event['result']['summary']


def test_provisioning_is_opt_in_private_and_not_repeatable(browser_host):
    host, _, store = browser_host
    assert callback_sources(store) == {'browser_use': host.config['source_id']}
    assert not store.settings()['background_enabled']
    assert not store.settings()['webhooks_enabled']
    with pytest.raises(TaskError):
        provision(store, 'http://127.0.0.1:8880', 'http://127.0.0.1:8790/submit')
    config_file = store.path.parent / 'secrets/browser-use.json'
    config_file.chmod(0o644)
    assert callback_sources(store) == {}


def test_explicit_setup_downloads_missing_pinned_runtime(monkeypatch):
    import browser_agent

    calls = []
    inspections = iter([1, 0, 0])

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['docker', 'image', 'inspect']:
            return SimpleNamespace(returncode=next(inspections), stderr='')
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr(browser_agent.subprocess, 'run', run)
    assert browser_agent.install_runtime() is True
    assert ['docker', 'info'] in calls
    pull = next(command for command in calls if command[:3] == ['docker', 'compose', '-f'])
    assert pull[-2:] == ['pull', 'browser']
    assert browser_agent.install_runtime() is False


def test_submission_is_durable_idempotent_and_conflicting_work_is_rejected(browser_host):
    host, payload, _ = browser_host
    assert host.accept(payload)[1] == 202
    assert host.accept(payload)[1] == 200
    changed = {**payload, 'arguments': {**payload['arguments'], 'task': 'Different work'}}
    with pytest.raises(TaskError, match='Conflicting'):
        host.accept(changed)
    reopened = BrowserService(host.path, host.config)
    assert reopened.accept(payload)[1] == 200
    with reopened.connection() as conn:
        assert conn.execute('SELECT count(*) FROM browser_jobs').fetchone()[0] == 1


def test_crash_never_requeues_started_browser_work(browser_host):
    host, payload, _ = browser_host
    host.accept(payload)
    with host.connection() as conn:
        conn.execute("UPDATE browser_jobs SET state='running'")
    reopened = BrowserService(host.path, host.config)
    assert not reopened.execute_one()
    with reopened.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'uncertain'


@pytest.mark.parametrize('field,value', [
    ('callback_url', 'http://127.0.0.1:7777/wrong'),
    ('idempotency_key', 'other-attempt'),
    ('callback_capability', 'short'),
    ('arguments', {'task': 'x', 'url': 'https://example.com', 'llm_provider': 'evil'}),
    ('runtime', {'mode': 'cloud'}),
])
def test_submission_rejects_unreviewed_destination_or_runtime(browser_host, field, value):
    host, payload, _ = browser_host
    with pytest.raises(Exception):
        host.accept({**payload, field: value})


@pytest.mark.parametrize('mode,model,key', [
    ('cloud', 'selected-cloud:cloud', 'OLLAMA_CLOUD_MODEL'),
    ('local', 'selected-local:9b', 'OLLAMA_MODEL'),
])
def test_child_uses_originating_mode_and_selected_model_not_parent_overrides(monkeypatch, mode, model, key):
    monkeypatch.setenv('JARVIS_OVERRIDE_OLLAMA_CLOUD_MODEL', 'wrong:cloud')
    monkeypatch.setenv('JARVIS_OVERRIDE_GEMINI_API_KEY', 'parent-secret')
    runtime = {'mode': mode, 'provider': 'ollama', 'model': model,
               'deadline': time.time() + 100, 'proxy_policy': 'require'}
    env = child_environment(runtime)
    assert env['JARVIS_MODE'] == mode
    assert env['JARVIS_OVERRIDE_' + key] == model
    assert env['JARVIS_OVERRIDE_LLM_PROVIDER'] == 'ollama'
    assert env['JARVIS_OVERRIDE_JARVIS_TOOL_PROXY_POLICY'] == 'require'
    assert 'JARVIS_OVERRIDE_GEMINI_API_KEY' not in env
    assert env.get('GEMINI_API_KEY') != 'parent-secret'


def test_helper_provider_is_supported_without_promoting_parent_secrets(monkeypatch, browser_host):
    host, payload, _ = browser_host
    payload['runtime']['provider'] = 'helper'
    payload['runtime']['model'] = 'selected-helper:latest'
    assert host.accept(payload)[1] == 202
    monkeypatch.setenv('JARVIS_OVERRIDE_JARVIS_HELPER_LLM_MODEL', 'wrong')
    env = child_environment(payload['runtime'])
    assert env['JARVIS_OVERRIDE_LLM_PROVIDER'] == 'helper'
    assert env['JARVIS_OVERRIDE_JARVIS_HELPER_LLM_MODEL'] == 'selected-helper:latest'
    assert env['JARVIS_HELPER_LLM_MODEL'] == 'selected-helper:latest'
    from browser_agent import invoke_model
    class Provider:
        def chat_with_tools(self, messages, tools, system_prompt):
            assert 'input_schema' in tools[0]
            return None, {'name': 'browser_response', 'arguments': {'answer': 'observed'}}, None, None
    result = invoke_model(Provider(), 'helper', {'messages': [{'role': 'user', 'content': 'research'}],
        'schema': {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}})
    assert result == {'answer': 'observed'}


@pytest.mark.parametrize('policy,expected', [
    ('inherit', ['http://one:3128', 'http://two:3128', None]),
    ('prefer', ['http://one:3128', 'http://two:3128', None]),
    ('require', ['http://one:3128', 'http://two:3128']),
    ('off', [None]),
])
def test_browser_uses_existing_proxy_chain_policy(monkeypatch, policy, expected):
    from config_loader import config_scope

    with config_scope('cloud', overrides={'LOCAL_PROXY': 'http://one:3128', 'LOCAL_PROXY2': 'http://two:3128',
                                         'JARVIS_TOOL_PROXY_POLICY': policy}):
        from http_client import build_proxy_url_attempts
        assert build_proxy_url_attempts(direct_fallback_default=True) == expected



def test_browser_rejects_private_destinations_and_non_web_schemes(monkeypatch):
    import browser_agent

    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('127.0.0.1', 80))])
    from stash_helper import SecurityError
    with pytest.raises(SecurityError):
        browser_agent.validate_url('https://public-looking.example/')
    with pytest.raises(ValueError):
        browser_agent.validate_url('file:///etc/passwd')
    assert browser_agent.validate_url('http://127.0.0.1:9000/', allowed_hosts=('127.0.0.1',))


def test_callback_retry_keeps_exact_event_identity_and_bypasses_proxy(browser_host, monkeypatch):
    host, payload, _ = browser_host
    host.accept(payload)
    host.event(payload, 'task.completed', {'summary': 'Observed result'})
    calls, statuses = [], iter([503, 202])

    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            assert not self.trust_env
            assert kwargs['allow_redirects'] is False
            calls.append((url, kwargs['data'], kwargs['headers']))
            status = next(statuses)
            class Response:
                status_code = status
                def __enter__(self): return self
                def __exit__(self, *args): pass
            return Response()

    monkeypatch.setattr('lib.webhook_integrations.browser_service.requests.Session', Session)
    assert host.deliver_one()
    with host.connection() as conn:
        assert conn.execute('SELECT delivered FROM browser_events').fetchone()[0] == 0
        conn.execute('UPDATE browser_events SET retry_at=0')
    reopened = BrowserService(host.path, host.config)
    assert reopened.deliver_one()
    assert calls[0][1] == calls[1][1]
    assert calls[0][2]['X-Jarvis-Task-Capability'] == payload['callback_capability']
    assert not reopened.deliver_one()


def test_skill_result_and_callback_commit_together(browser_host, monkeypatch):
    import tool_process

    host, payload, _ = browser_host
    host.accept(payload)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: (json.dumps({
        'ok': True, 'speech': 'Saved research: stash://space/report\n\nObserved fact',
        'stash_ref': 'stash://space/report', 'sources': ['https://example.com/source'],
        'provider': 'ollama', 'model': 'test:cloud',
    }), '', False))
    assert host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        body = json.loads(conn.execute('SELECT body FROM browser_events').fetchone()[0])
        assert body['type'] == 'task.completed'
        assert body['result']['summary'].endswith('Observed fact')
        assert body['result']['presentation'] == {
            'kind': 'browser_research', 'stash_ref': 'stash://space/report',
            'sources': ['https://example.com/source'], 'provider': 'ollama', 'model': 'test:cloud',
        }
        from lib.webhook_integrations.contracts import event_body
        assert event_body(json.dumps(body).encode())['result']['presentation']['kind'] == 'browser_research'
    assert not host.execute_one()


def test_terminal_partial_report_keeps_failed_state_and_research_presentation(browser_host, monkeypatch):
    import tool_process

    host, payload, _ = browser_host
    host.accept(payload)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: (json.dumps({
        'ok': False, 'speech': 'Saved research: stash://space/report\n\n## Evidence\n\nObserved partial fact.',
        'stash_ref': 'stash://space/report', 'sources': ['https://example.com/source'],
        'provider': 'ollama', 'model': 'test:cloud',
    }), '', False))
    assert host.execute_one()
    with host.connection() as conn:
        body = json.loads(conn.execute('SELECT body FROM browser_events').fetchone()[0])
    assert body['type'] == 'task.failed'
    assert body['result']['presentation'] == {
        'kind': 'browser_research', 'stash_ref': 'stash://space/report',
        'sources': ['https://example.com/source'], 'provider': 'ollama', 'model': 'test:cloud',
    }


def test_uncertain_process_outcome_emits_no_false_terminal_callback(browser_host, monkeypatch):
    import tool_process

    host, payload, _ = browser_host
    host.accept(payload)
    def lost(*args, **kwargs):
        raise tool_process.TerminationUnverified()
    monkeypatch.setattr(tool_process, 'run_local_process', lost)
    assert host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'uncertain'
        assert conn.execute('SELECT count(*) FROM browser_events').fetchone()[0] == 0


@pytest.mark.parametrize('provider_name', ['ollama', 'anthropic', 'openai', 'xai'])
def test_model_bridge_uses_existing_provider_tool_format(provider_name):
    from browser_agent import invoke_model

    class Provider:
        def chat_with_tools(self, messages, tools, system_prompt):
            assert messages == [{'role': 'user', 'content': 'Observed page'}]
            assert 'System rule' in system_prompt
            tool = tools[0]
            if provider_name in {'ollama', 'anthropic'}:
                assert tool['name'] == 'browser_response' and 'input_schema' in tool
            else:
                assert tool['function']['name'] == 'browser_response'
            return None, {'name': 'browser_response', 'arguments': {'answer': 'fact'}}, None, None

    value = invoke_model(Provider(), provider_name, {
        'messages': [{'role': 'system', 'content': 'System rule'},
                     {'role': 'user', 'content': [{'type': 'text', 'text': 'Observed page'}]}],
        'schema': {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']},
    })
    assert value == {'answer': 'fact'}


def test_model_bridge_does_not_send_images_to_text_only_runtime():
    from browser_agent import invoke_model
    with pytest.raises(ValueError, match='text-only'):
        invoke_model(object(), 'ollama', {'messages': [{'role': 'user', 'content': [{'type': 'image_url'}]}]})


def test_browser_fetch_preserves_redirect_for_a_new_url_check_and_bounds_output(monkeypatch):
    import browser_agent
    checks, requests = [], []
    monkeypatch.setattr(browser_agent, 'resolve_url', lambda url, **_: (checks.append(url) or url, '93.184.215.14'))
    class Response:
        status_code = 302
        headers = {'Location': 'http://127.0.0.1/private', 'Content-Encoding': 'gzip'}
        raw = None
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_content(self, _): yield b'hello'
    from contextlib import contextmanager
    @contextmanager
    def request(method, url, address, **kw):
        requests.append((url, address, kw))
        yield Response()
    monkeypatch.setattr(browser_agent, 'pinned_http_request', request)
    fetch = browser_agent.BrowserFetch(time.time()+30)
    result = fetch({'method': 'GET', 'url': 'https://example.com/', 'headers': {
        'Authorization': 'no', 'Cookie': 'page-cookie',
        'user-agent': 'Mozilla/5.0 Chrome/152.0.0.0',
        'sec-ch-ua': '"Chromium";v="152"', 'Sec-Fetch-Mode': 'navigate',
        'X-Unreviewed': 'drop-me',
    }})
    assert result['responseCode'] == 302
    assert {'name': 'Location', 'value': 'http://127.0.0.1/private'} in result['responseHeaders']
    assert not any(item['name'].lower() == 'content-encoding' for item in result['responseHeaders'])
    assert checks == ['https://example.com/']
    assert requests[0][:2] == ('https://example.com/', '93.184.215.14')
    assert requests[0][2]['allow_redirects'] is False
    assert requests[0][2]['headers'] == {
        'Cookie': 'page-cookie', 'User-Agent': 'Mozilla/5.0 Chrome/152.0.0.0',
        'sec-ch-ua': '"Chromium";v="152"', 'Sec-Fetch-Mode': 'navigate',
    }
    monkeypatch.setattr(browser_agent, 'MAX_RESOURCE', 2)
    with pytest.raises(ValueError, match='size limit'):
        fetch({'method': 'GET', 'url': 'https://example.com/'})


def test_browser_audit_records_safe_destinations_without_query_credentials(tmp_path, monkeypatch):
    import browser_agent

    from lib.webhook_integrations.browser_audit import BrowserAudit

    monkeypatch.setattr(browser_agent, 'resolve_url', lambda url, **_: (url, '93.184.215.14'))
    class Response:
        status_code = 200
        headers = {}
        raw = None
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_content(self, _): yield b'observed'
    from contextlib import contextmanager
    @contextmanager
    def request(*a, **k):
        yield Response()
    monkeypatch.setattr(browser_agent, 'pinned_http_request', request)
    audit = BrowserAudit(directory=tmp_path / 'browser-use')
    fetch = browser_agent.BrowserFetch(time.time() + 30, audit=audit,
                                       audit_context={'job_id': 'job-1', 'attempt_id': 'attempt-1'})
    fetch({'method': 'GET', 'resource_type': 'Document',
           'url': 'https://user:secret@example.com/research/item?token=private#fragment'})
    path = next((tmp_path / 'browser-use').glob('*.jsonl'))
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    serialized = json.dumps(entries)
    assert 'user' not in serialized and 'secret' not in serialized and 'private' not in serialized
    assert entries[-1]['destination'] == 'https://example.com/research/item'
    assert entries[-1]['status_code'] == 200 and entries[-1]['bytes'] == 8
    with pytest.raises(ValueError, match='read-only'):
        fetch({'method': 'POST', 'resource_type': 'Document',
               'url': 'https://example.com/write?csrf=private'})
    latest = json.loads(path.read_text().splitlines()[-1])
    assert latest['event'] == 'request_rejected'
    assert latest['destination'] == 'https://example.com/write'


def test_browser_audit_records_proxy_policy_without_headers(tmp_path):
    from lib.webhook_integrations.browser_audit import BrowserAudit

    audit = BrowserAudit(directory=tmp_path / 'browser-use')
    audit.emit('job_started', job_id='job-1', proxy_policy='inherit',
               user_agent='must-not-be-logged', authorization='must-not-be-logged')
    path = next((tmp_path / 'browser-use').glob('*.jsonl'))
    entry = json.loads(path.read_text())
    assert entry['proxy_policy'] == 'inherit'
    assert 'user_agent' not in entry and 'authorization' not in entry


def test_research_archive_keeps_page_dom_literal():
    from browser_agent import ResearchArchive

    saved = {}
    archive = object.__new__(ResearchArchive)
    archive.task = 'Research <untrusted> & report'
    archive.pages = []
    archive.ref = None
    archive.files = SimpleNamespace(save_text=lambda content, *args, **kwargs:
                                    saved.update(content=content) or {'ref': 'stash://space/file'})
    archive.checkpoint(snapshot={'title': 'News <script>', 'url': 'https://example.com/?a=1&b=2',
                                 'text': '[1]<div onclick="bad">\n``` nested fence'})
    content = saved['content']
    assert '# Browser research\n\nResearch &lt;untrusted&gt; &amp; report' in content
    assert '## Source 1\n\n**Page:** News &lt;script&gt;' in content
    assert '````text\n[1]<div onclick="bad">\n``` nested fence\n````' in content
    assert '## Source 1: News' not in content


def test_container_agent_tolerates_transient_failures_and_requires_partial_done():
    source = (ROOT / 'docker/browser-use/agent.py').read_text()
    assert 'max_failures=5' in source
    assert 'call done with the best supported partial report' in source
    assert "'step_count': step_count" in source and "'error_count': len(errors)" in source
    manifest = json.loads((ROOT / 'skills/browser_use.tool.json').read_text())
    assert 'Prefer a direct publisher or topic page' in manifest['parameters']['properties']['url']['description']


@pytest.mark.parametrize('method,resource_type', [('POST', 'Document'), ('GET', 'WebSocket'), ('GET', 'Media')])
def test_browser_fetch_rejects_actions_outside_research_before_http(monkeypatch, method, resource_type):
    import browser_agent
    monkeypatch.setattr(browser_agent, 'resolve_url', lambda url, **_: (url, '93.184.215.14'))
    monkeypatch.setattr(browser_agent, 'pinned_http_request', lambda *a, **k: pytest.fail('must not make a request'))
    with pytest.raises(ValueError, match='read-only'):
        browser_agent.BrowserFetch(time.time()+30)({'method': method, 'resource_type': resource_type, 'url': 'https://example.com'})


def test_unknown_container_outcome_does_not_emit_false_failure_callback(browser_host, monkeypatch):
    import tool_process

    from lib.webhook_integrations import browser_service
    host, payload, _ = browser_host
    host.accept(payload)
    monkeypatch.setattr(browser_service, 'stop_browser_container', lambda _name: False)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: (
        json.dumps({'ok': False, 'completion': 'unknown', 'speech': 'Partial research saved'}), '', False))
    host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'uncertain'
        assert conn.execute('SELECT count(*) FROM browser_events').fetchone()[0] == 0


def test_final_report_is_saved_before_success_and_failed_observation_retains_partial(monkeypatch):
    from browser_agent import research
    from config_loader import config_scope
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.215.14', 443))])
    class Archive:
        ref = 'stash://test/report'
        space = type('Space', (), {'space_id': 'test'})()
        def __init__(self, task): self.saved = []
        def checkpoint(self, snapshot=None, report=None):
            self.saved.append(report)
            return self.ref
    archives = []
    def archive(task):
        archives.append(Archive(task))
        return archives[-1]
    class Provider:
        model = 'selected:local'
    def runner(config, **kw):
        assert config['model'] == 'selected:local'
        assert kw['provider_name'] == 'ollama'
        return {'ok': True, 'report': 'Verified fact', 'sources': ['https://example.com']}
    with config_scope('local', overrides={'BROWSER_USE_ALLOWED_HOSTS': 'example.com'}):
        result = research({'task': 'Research', 'url': 'https://example.com'}, provider=Provider(), provider_name='ollama', container_runner=runner, archive_factory=archive)
        assert result['ok'] and archives[0].saved == [None, 'Verified fact']
        def failed(*a, **k): raise TimeoutError()
        result = research({'task': 'Research', 'url': 'https://example.com'}, provider=Provider(), provider_name='ollama', container_runner=failed, archive_factory=archive)
        assert not result['ok'] and result['completion'] == 'failed' and result['stash_ref']
        assert result['speech'].startswith('Saved research: stash://test/report')


def test_browser_preflight_is_inert_when_image_is_missing(monkeypatch):
    import browser_agent
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return type('Result', (), {'returncode': 1})()
    monkeypatch.setattr(browser_agent.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='image or Docker Engine unavailable'):
        browser_agent.check_runtime()
    assert calls[0][:3] == ['docker', 'image', 'inspect']
    assert '@sha256:' in calls[0][3]


def test_multibyte_completion_is_bounded_before_callback_insert(browser_host, monkeypatch):
    import tool_process
    host, payload, _ = browser_host
    host.accept(payload)
    monkeypatch.setattr(tool_process, 'run_local_process', lambda *a, **k: (
        json.dumps({'ok': True, 'speech': 'Saved research: stash://test/report\n' + '界' * 28000}), '', False))
    host.execute_one()
    with host.connection() as conn:
        assert conn.execute('SELECT state FROM browser_jobs').fetchone()[0] == 'finished'
        raw = conn.execute('SELECT body FROM browser_events').fetchone()[0]
        assert len(raw.encode()) < 65536
        assert json.loads(raw)['result']['summary'].startswith('Saved research: stash://')
