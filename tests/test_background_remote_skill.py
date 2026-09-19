"""Shared remote-work semantics with disposable stores, processes and provider fixtures."""

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_background_local_skill import NAME, probe as probe
from test_background_tasks import config_root as config_root
from test_background_tasks import receipt, store as store
from test_web_background_tasks import eventually

from lib.background_tasks import AdmissionDenied, TaskError, production
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.local_contract import ADAPTER, REMOTE_ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import TaskWorker

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ('generate_image', 'generate_video', 'generate_music', 'create_social_clip')


@pytest.fixture
def remote(probe):
    p = probe
    manifest = json.loads(p.manifest.read_text())
    manifest['permissions']['network'] = True
    manifest['execution']['background'].update(adapter=REMOTE_ADAPTER, completion_scope='remote_work')
    p.manifest.write_text(json.dumps(manifest))
    p.runner = LocalSkillRunner(p.root, {NAME: REMOTE_ADAPTER})

    def admit(args=None, mode='cloud'):
        schema, policy = p.runner.policy(NAME)
        service = BackgroundAdmissionService(p.store, adapters={NAME: REMOTE_ADAPTER},
                                            validate_source=lambda _: True, ready=lambda: True)
        p.store.touch_worker('remote-worker', {REMOTE_ADAPTER})
        registry = SimpleNamespace(list_tools=lambda: [NAME], get_tool=lambda _: schema)
        context = service.authorize({'operator': 'installation', 'source': 'web',
            'conversation_id': 'conversation-1', 'generation': 1, 'request_id': 'request-1',
            'mode': mode, 'selected': [NAME], 'tool_policy': 'auto',
            'tool_policies': {NAME: policy}}, registry)
        result = context.admit(NAME, args or {'label': 'remote'}, 'remote-call', schema)
        job = p.store.get(result['job_id'])
        return p.store.release(job['id'], receipt(job))

    p.admit = admit
    return p


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_production_bindings_and_reviewed_manifest_policies(config_root, mode):
    from config_loader import config_scope
    from jsonschema import ValidationError
    from lib.background_tasks.local_skill import validate_arguments
    assert production.bindings() == {'convert_file': ADAPTER, **dict.fromkeys(MEDIA, REMOTE_ADAPTER),
                                     'browser_use': 'http_callback_v1'}
    with config_scope(mode, {'JARVIS_TOOL_PROFILE': 'default',
                            'MONEYPRINTER_API_URL': 'https://moneyprinter.invalid'}):
        runner = production.runner()
        for name, budget in zip(MEDIA, (900, 1200, 2100, 2100)):
            schema, evidence = runner.policy(name)
            assert schema.permissions['network'] is True
            assert schema.background_adapter == evidence['adapter'] == REMOTE_ADAPTER
            assert schema.background_execution['completion_scope'] == 'remote_work'
            assert evidence['timeout_seconds'] == budget
            arguments = {('subject' if name == 'create_social_clip' else 'prompt'): 'Fixture media'}
            validate_arguments(schema, arguments)
            with pytest.raises(ValidationError):
                validate_arguments(schema, {**arguments, 'save': False})
            if name == 'create_social_clip':
                for invalid in ({'video_count': 2}, {'paragraph_number': 11},
                                {'clip_duration': 0}, {'subject': ''}, {'undeclared': True}):
                    with pytest.raises(ValidationError):
                        validate_arguments(schema, {**arguments, **invalid})
        assert runner.policy('convert_file')[1]['adapter'] == ADAPTER
        with pytest.raises(AdmissionDenied):
            runner.policy('analyze_video')


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_remote_skill_uses_shared_runner_and_never_replays(remote, mode):
    p = remote
    job = p.admit(mode=mode)
    assert job['admission']['timeout_seconds'] == 37
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['result']['data']['mode'] == mode
    assert saved['delivery_state'] == 'pending'
    assert not worker.run_once()
    assert len(list(p.output.glob('*.started'))) == 1


@pytest.mark.parametrize('behavior', ['failure', 'oversized_success'])
def test_ambiguous_remote_result_reserves_attention_without_replay(remote, behavior):
    p = remote
    job = p.admit({'label': 'remote', 'behavior': behavior})
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result'] is None and saved['delivery_state'] is None
    assert p.store.counts()['reserved'] == 1
    assert not worker.run_once()
    assert len(list(p.output.glob('*.started'))) == 1


@pytest.mark.parametrize('error', ['timeout', 'output_limit'])
def test_lost_remote_response_is_not_a_known_failure(remote, monkeypatch, error):
    import tool_process
    original = tool_process.run_local_process

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)  # An actual child ran; its response is lost.
        if error == 'timeout':
            raise subprocess.TimeoutExpired('fixture', 1)
        raise tool_process.OutputLimitExceeded('fixture')

    monkeypatch.setattr(tool_process, 'run_local_process', lost_response)
    job = remote.admit()
    worker = TaskWorker(remote.store, {REMOTE_ADAPTER: remote.runner})
    worker.run_once()
    saved = remote.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert 'Provider work may continue' in saved['attention_reason']
    assert not worker.run_once()


def test_prelaunch_schema_failure_is_known_and_unbound_adapter_cannot_bypass_policy(remote):
    p = remote
    job = p.admit({'label': '../bad'})
    TaskWorker(p.store, {REMOTE_ADAPTER: p.runner}).run_once()
    assert p.store.get(job['id'])['state'] == 'failed'
    assert p.store.counts()['reserved'] == 0 and not p.output.exists()
    schema, policy = p.runner.policy(NAME)
    assert not p.runner._matches_policy(ADAPTER, policy, policy)
    p.runner.bindings[NAME] = ADAPTER
    with pytest.raises(AdmissionDenied):
        p.runner.policy(NAME)


def test_shutdown_stops_only_observer_and_leaves_provider_work_uncertain(remote):
    """A separate provider actor completes AFTER the supervised observer stops."""
    p = remote
    submitted, release, completed = (p.root / name for name in ('submitted', 'release', 'completed'))
    # File transport avoids external APIs; the provider has a separate process
    # group and lifetime, just like work owned by a remote service.
    provider_code = (
        'import pathlib,time\n'
        f'submitted=pathlib.Path({str(submitted)!r})\nrelease=pathlib.Path({str(release)!r})\n'
        'while not submitted.exists(): time.sleep(.01)\n'
        'while not release.exists(): time.sleep(.01)\n'
        f'pathlib.Path({str(completed)!r}).write_text("provider finished")\n'
    )
    observer = p.manifest.with_suffix('').with_suffix('.py')
    observer.write_text('import pathlib,time\n'
                       f'pathlib.Path({str(submitted)!r}).touch()\n'
                       'time.sleep(30)\n')
    job = p.admit()
    provider = subprocess.Popen([sys.executable, '-c', provider_code], start_new_session=True)
    stop = threading.Event()
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: p.runner})
    thread = threading.Thread(target=worker.run_once, args=(stop,))
    thread.start()
    try:
        eventually(submitted.exists)
        current = p.store.get(job['id'])
        with pytest.raises(TaskError):
            p.store.request_cancel(job['id'], current['revision'], supported_adapters={ADAPTER})
        stop.set()
        thread.join(6)
        assert not thread.is_alive()
        saved = p.store.get(job['id'])
        assert saved['state'] == 'needs_attention' and saved['cancelled'] == 0
        assert provider.poll() is None and not completed.exists()
        assert not worker.run_once()
        release.touch()
        provider.wait(timeout=5)
        assert completed.read_text() == 'provider finished'
        assert p.store.get(job['id'])['state'] == 'needs_attention'
    finally:
        stop.set()
        release.touch()
        thread.join(6)
        if provider.poll() is None:
            provider.terminate()
        provider.wait(timeout=5)


def test_queued_remote_cancel_is_still_safe(remote):
    job = remote.admit()
    cancelled = remote.store.request_cancel(job['id'], job['revision'], supported_adapters={ADAPTER})
    assert cancelled['state'] == 'cancelled'
    assert not TaskWorker(remote.store, {REMOTE_ADAPTER: remote.runner}).run_once()
    assert not remote.output.exists()


@pytest.mark.parametrize('gate', ['manifest', 'profile', 'environment', 'web_block'])
def test_social_clip_rechecks_blocks_before_starting_accepted_work(probe, monkeypatch, gate):
    import executor
    import tool_profiles
    from config_loader import config_scope

    p, name = probe, 'create_social_clip'
    for suffix in ('.py', '.tool.json'):
        shutil.copyfile(ROOT / 'skills' / (name + suffix), p.root / 'skills' / (name + suffix))
    runner = LocalSkillRunner(p.root, {name: REMOTE_ADAPTER})
    profiles = p.root / 'skills/profiles'
    profiles.mkdir()
    monkeypatch.setattr(tool_profiles, 'get_profiles_dir', lambda: profiles)
    values = {'JARVIS_TOOL_PROFILE': 'social-test',
              'MONEYPRINTER_API_URL': 'https://moneyprinter.invalid'}
    with config_scope('cloud', values):
        schema, policy = runner.policy(name)
    service = BackgroundAdmissionService(p.store, adapters={name: REMOTE_ADAPTER},
                                        validate_source=lambda _: True, ready=lambda: True)
    p.store.touch_worker('social-worker', {REMOTE_ADAPTER})
    p.store.configure(background_tools=[name])
    context = service.authorize({'operator': 'installation', 'source': 'web',
        'conversation_id': 'conversation-1', 'generation': 1, 'request_id': 'social-request',
        'mode': 'cloud', 'selected': [name], 'tool_policy': 'auto',
        'tool_policies': {name: policy}},
        SimpleNamespace(list_tools=lambda: [name], get_tool=lambda _: schema))
    accepted = context.admit(name, {'subject': 'Fixture media'}, 'social-call', schema)
    job = p.store.get(accepted['job_id'])
    p.store.release(job['id'], receipt(job))
    if gate == 'manifest':
        path = p.root / 'skills' / (name + '.tool.json')
        path.write_text(json.dumps({**json.loads(path.read_text()), 'enabled': False}))
    elif gate == 'profile':
        (profiles / 'social-test.json').write_text(json.dumps({'overrides': {name: False}}))
    elif gate == 'environment':
        values['MONEYPRINTER_API_URL'] = ''
    else:
        config = p.root / 'jarvis-web/config/web_config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'tools': {'blocked': [name]}}))
    monkeypatch.setattr(executor.ToolExecutor, '_execute_foreground',
                        lambda *a, **kw: pytest.fail('Blocked work must not start a provider request'))
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: runner}, deployment_overrides=values)
    assert worker.run_once()
    assert p.store.get(job['id'])['state'] == 'failed'
    assert p.store.counts()['reserved'] == 0
    assert not worker.run_once()


def test_killed_remote_worker_fences_attempt_without_replay(remote, config_root):
    from tool_process import group_alive

    p = remote
    job = p.admit({'label': 'killed', 'delay': 10})
    program = f'''
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = {[str(ROOT), str(ROOT / 'lib'), str(ROOT / 'orchestrator')]!r}
import config_loader, executor
from lib import config_loader as package_config
config_loader.get_project_root = package_config.get_project_root = lambda: Path({str(config_root)!r})
executor.get_logger = lambda mode: SimpleNamespace(log_tool_call=lambda **kwargs: None)
from lib.background_tasks import TaskStore
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import TaskWorker
TaskWorker(TaskStore({str(p.store.path)!r}),
    {{{REMOTE_ADAPTER!r}: LocalSkillRunner({str(p.root)!r}, {{{NAME!r}: {REMOTE_ADAPTER!r}}})}},
    lease_seconds=1, heartbeat_seconds=.1).run_once()
'''
    process = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    try:
        started = p.output / 'killed.started'
        eventually(started.exists)
        pid = int(started.read_text())
        process.kill()
        process.communicate(timeout=5)
        eventually(lambda: not group_alive(SimpleNamespace(pid=pid, poll=lambda: None)))
        time.sleep(1.1)
        p.store.reconcile()
        saved = p.store.get(job['id'])
        assert saved['state'] == 'needs_attention' and saved['cancelled'] == 0
        assert p.store.counts()['reserved'] == 1
        assert not TaskWorker(p.store, {REMOTE_ADAPTER: p.runner}).run_once()
        assert len(p.store.job_detail(job['id'])['attempts']) == 1
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize('completion,state,reserved', [
    ('rejected', 'failed', 0), ('completed', 'failed', 0),
    ('unknown', 'needs_attention', 1), (None, 'needs_attention', 1),
    ('success', 'needs_attention', 1),
])
def test_explicit_remote_failure_evidence_controls_capacity(remote, completion, state, reserved):
    p = remote
    script = p.manifest.with_suffix('').with_suffix('.py')
    result = {'ok': False, 'error': 'Scripted provider failure'}
    if completion is not None:
        result['completion'] = completion
    script.write_text('print(' + repr(json.dumps(result)) + ')\n')
    p.store.configure(max_running=1)
    job = p.admit()
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == state
    assert p.store.counts()['reserved'] == reserved
    assert len(p.store.pending_deliveries()) == (1 if state == 'failed' else 0)
    if state == 'failed':
        assert saved['result']['completion'] == completion
    assert not worker.run_once()  # Failure evidence never requests a replay.
