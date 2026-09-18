"""Generic local runner gate, using real processes and disposable authorization."""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))
sys.path.insert(0, str(ROOT / "lib"))
from test_background_tasks import receipt
from test_background_tasks import config_root as config_root
from test_background_tasks import store as store

from lib.background_tasks import AdmissionDenied, Conflict, production
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.local_contract import ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import TaskWorker

NAME = 'local_skill_probe'
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Local supervision requires Linux')


@pytest.fixture
def probe(store, config_root, tmp_path, monkeypatch):
    import executor
    store.configure(background_tools=[NAME])

    root = tmp_path / 'installation'
    skills = root / 'skills'
    skills.mkdir(parents=True)
    for suffix in ('.py', '.tool.json'):
        shutil.copyfile(ROOT / 'tests/fixtures' / (NAME + suffix), skills / (NAME + suffix))
    output = tmp_path / 'probe-output'
    for mode in ('local', 'cloud'):
        (config_root / 'config' / f'{mode}.env').write_text(
            f'FIXTURE_OUTPUT_ROOT={output}\nFIXTURE_TOKEN={mode}\nJARVIS_TOOL_PROFILE=default\n')
    monkeypatch.setattr(executor, 'get_logger', lambda mode: SimpleNamespace(log_tool_call=lambda **kw: None))
    runner = LocalSkillRunner(root, {NAME: ADAPTER})
    schema, evidence = runner.policy(NAME)
    registry = SimpleNamespace(list_tools=lambda: [NAME], get_tool=lambda name: schema)
    service = BackgroundAdmissionService(store, adapters={NAME: ADAPTER},
                                        validate_source=lambda payload: True, ready=lambda: True)
    store.touch_worker('probe-worker', {ADAPTER})

    def authorize(mode='cloud'):
        return service.authorize({'operator': 'installation', 'source': 'web',
            'conversation_id': 'conversation-1', 'generation': 1, 'request_id': 'request-1',
            'mode': mode, 'selected': [NAME], 'tool_policy': 'auto',
            'tool_policies': {NAME: evidence}}, registry)

    def admit(args=None, mode='cloud'):
        context = authorize(mode)
        accepted = context.admit(NAME, args or {'label': 'probe'}, 'probe-call', schema)
        job = store.get(accepted['job_id'])
        return job

    return SimpleNamespace(root=root, output=output, store=store, runner=runner, schema=schema,
                           admit=admit, authorize=authorize, manifest=skills / (NAME + '.tool.json'))


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_second_skill_admits_held_then_uses_shared_runner_and_manifest_budgets(probe, mode, monkeypatch):
    import tool_process

    p = probe
    calls = []
    progress = []
    original_progress = p.store.progress

    def record_progress(claim, value):
        progress.append(value)
        original_progress(claim, value)

    monkeypatch.setattr(p.store, 'progress', record_progress)
    run = tool_process.run_local_process

    def capture(cmd, *args, **kwargs):
        calls.append(kwargs)
        return run(cmd, *args, **kwargs)

    monkeypatch.setattr(tool_process, 'run_local_process', capture)
    job = p.admit(mode=mode)
    assert job['admission']['timeout_seconds'] == 37
    assert job['deadline'] == job['created_at'] + 37
    worker = TaskWorker(p.store, {ADAPTER: p.runner})
    assert not worker.run_once() and not p.output.exists()
    p.store.release(job['id'], receipt(job))
    # Pausing admissions must still drain previously accepted work.
    p.store.configure(background_enabled=False)
    assert worker.run_once()
    finished = p.store.get(job['id'])
    assert finished['state'] == 'succeeded', finished['result']
    data = finished['result']['data']
    assert data['mode'] == data['token'] == mode
    assert data['conversation'] == 'conversation-1'
    assert data['memory_limit'] == 268435456 and data['file_limit'] == 1048576
    assert data['input_limit'] == '4096' and float(data['deadline']) == job['deadline']
    assert data['cwd'] == data['tmpdir'] and not Path(data['cwd']).exists()
    env = calls[0]['tool_env']
    assert env['FIXTURE_TOKEN'] == mode
    assert 'JARVIS_OVERRIDE_FIXTURE_TOKEN' not in env
    assert 'JARVIS_OVERRIDE_FIXTURE_OUTPUT_ROOT' not in env
    assert 'JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE' not in env
    assert env['JARVIS_BACKGROUND_MAX_INPUT_BYTES'] == '4096'
    assert env['JARVIS_OVERRIDE_JARVIS_BACKGROUND_MAX_INPUT_BYTES'] == '4096'
    assert 0 < calls[0]['timeout'] <= 37
    assert calls[0]['max_output_bytes'] == 2097152
    assert progress[0]['phase'] == 'Checking local execution'
    assert len(p.store.pending_deliveries()) == 1
    assert not worker.run_once()
    assert len(list(p.output.glob('*.started'))) == 1
    assert NAME not in production.bindings()


def test_generic_identity_is_preserved_at_admission(probe):
    p = probe
    context = p.authorize()
    first = context.admit(NAME, {'label': 'one'}, 'same', p.schema)
    assert context.admit(NAME, {'label': 'one'}, 'same', p.schema) == first
    with pytest.raises(Conflict):
        context.admit(NAME, {'label': 'two'}, 'same', p.schema)
    assert not p.output.exists()


def test_admission_timeout_comes_from_current_authorization_not_cached_schema(probe):
    probe.schema.background_execution['timeout_seconds'] = 86400
    job = probe.admit()
    assert job['admission']['timeout_seconds'] == 37
    probe.store.release(job['id'], receipt(job))
    assert TaskWorker(probe.store, {ADAPTER: probe.runner}).run_once()
    assert probe.store.get(job['id'])['state'] == 'succeeded'


def test_schema_references_cannot_fetch_remote_documents(probe, monkeypatch):
    import urllib.request

    from referencing.exceptions import Unresolvable

    from lib.background_tasks.local_skill import argument_validators

    def forbidden(*args, **kwargs):
        pytest.fail('JSON Schema validation must not fetch external documents')

    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    schema = {'type': 'object', '$ref': 'https://example.invalid/schema.json'}
    with pytest.raises(Unresolvable):
        argument_validators(schema, None)[0].validate({'label': 'test'})
    assert not probe.output.exists()


def test_invalid_background_settings_keep_foreground_schema_available(probe):
    from tool_schema import ToolSchema

    manifest = json.loads(probe.manifest.read_text())
    manifest['execution']['background']['limits']['output_bytes'] = -1
    probe.manifest.write_text(json.dumps(manifest))
    schema = ToolSchema.from_json_file(str(probe.manifest))
    assert schema.name == NAME and schema.to_openai_format()['function']['name'] == NAME
    with pytest.raises(AdmissionDenied):
        probe.runner.policy(NAME)


@pytest.mark.parametrize('args', [
    {'label': 'x', 'extra': True}, {'label': '../escape'}, {'label': 'x', 'delay': True},
    {'label': 'x', 'behavior': 'unknown'}, {'delay': 1},
])
def test_generic_schema_rejects_invalid_work_before_spawn(probe, args):
    p = probe
    job = p.admit(args)
    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {ADAPTER: p.runner})
    assert worker.run_once()
    assert p.store.get(job['id'])['state'] == 'failed'
    assert p.store.counts()['reserved'] == 0 and not p.output.exists()
    assert not worker.run_once()


@pytest.mark.parametrize('mutation', ['unbound', 'path', 'special', 'network', 'dangerous',
                                      'adapter', 'limits', 'timeout', 'scope', 'schema'])
def test_manifest_cannot_grant_itself_execution_or_bypass_review(probe, mutation):
    p = probe
    manifest = json.loads(p.manifest.read_text())
    if mutation == 'unbound':
        p.runner.bindings.clear()
    elif mutation == 'path':
        manifest['script'] = '../other.py'
    elif mutation == 'special':
        p.runner.bindings['workflow'] = ADAPTER
        with pytest.raises(AdmissionDenied):
            p.runner.policy('workflow')
        return
    elif mutation in {'network', 'dangerous'}:
        manifest['permissions'][mutation] = True
    elif mutation == 'adapter':
        manifest['execution']['background']['adapter'] = 'arbitrary.module:execute'
    elif mutation == 'limits':
        manifest['execution']['background']['limits']['output_bytes'] = -1
    elif mutation == 'timeout':
        manifest['execution']['background']['timeout_seconds'] = True
    elif mutation == 'scope':
        manifest['execution']['background']['completion_scope'] = 'remote_job'
    else:
        manifest['parameters']['type'] = 'invalid-schema-type'
    p.manifest.write_text(json.dumps(manifest))
    with pytest.raises(AdmissionDenied):
        p.runner.policy(NAME)
    assert not p.output.exists()


@pytest.mark.parametrize('change', ['script', 'permissions', 'blocked', 'authorization'])
def test_policy_changes_after_admission_fail_without_launching(probe, change):
    p = probe
    job = p.admit()
    if change == 'script':
        with p.manifest.with_name(NAME + '.py').open('a') as script:
            script.write('\n# changed after authorization\n')
    elif change == 'permissions':
        manifest = json.loads(p.manifest.read_text())
        manifest['permissions']['auto_approve'] = False
        p.manifest.write_text(json.dumps(manifest))
    elif change == 'blocked':
        config = p.root / 'jarvis-web/config/web_config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'tools': {'blocked': [NAME]}}))
    else:
        with p.store._connection(write=True) as conn:
            conn.execute('DELETE FROM authorizations')
    p.store.release(job['id'], receipt(job))
    assert TaskWorker(p.store, {ADAPTER: p.runner}).run_once()
    assert p.store.get(job['id'])['state'] == 'failed'
    assert not p.output.exists()


@pytest.mark.parametrize('behavior,state,reserved', [
    ('failure', 'failed', 0), ('oversized_success', 'needs_attention', 1),
])
def test_result_handling_is_shared_without_replaying_uncertain_work(probe, behavior, state, reserved):
    p = probe
    job = p.admit({'label': 'result', 'behavior': behavior})
    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {ADAPTER: p.runner})
    assert worker.run_once()
    saved = p.store.get(job['id'])
    assert saved['state'] == state
    assert p.store.counts()['reserved'] == reserved
    if state == 'failed':
        assert saved['result']['diagnostics_truncated']
        assert 'head' in saved['result']['error'] and 'tail' in saved['result']['error']
        assert len(p.store.pending_deliveries()) == 1
    else:
        assert not p.store.pending_deliveries()
    assert not worker.run_once()
