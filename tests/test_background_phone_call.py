"""Reviewed outbound-call binding, without dialing or contacting Vapi."""

import copy
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_background_local_skill import probe as probe
from test_background_tasks import config_root as config_root
from test_background_tasks import receipt
from test_background_tasks import store as store

from lib.background_tasks import AdmissionDenied, production
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.local_contract import ADAPTER, REMOTE_ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner, restrict_child_environment
from lib.background_tasks.worker import TaskWorker

ROOT = Path(__file__).resolve().parents[1]
NAME = 'phone_call'
CALL_ID = 'phone-fixture-call-1'
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Local supervision requires Linux')


@pytest.fixture
def phone(probe, config_root):
    p = probe
    manifest = p.root / 'skills' / f'{NAME}.tool.json'
    shutil.copyfile(ROOT / 'skills' / manifest.name, manifest)
    definition = json.loads(manifest.read_text())
    definition['permissions'] = production.TRUSTED_PERMISSION_POLICIES[NAME]['permissions']
    definition['execution'] = {'background': {
        'supported': True, 'adapter': REMOTE_ADAPTER, 'completion_scope': 'remote_work',
        'timeout_seconds': 1200,
        'argument_constraints': {
            'required': ['recipient', 'task'],
            'properties': {
                'action': {'const': 'call'},
                'recipient': {'minLength': 1}, 'task': {'minLength': 1},
            },
        },
    }}
    manifest.write_text(json.dumps(definition))
    script = p.root / 'skills' / f'{NAME}.py'
    submitted = p.root / 'submitted'
    script.write_text(
        'import json,os,sys\nfrom pathlib import Path\n'
        'args=json.loads(sys.argv[1])\n'
        f'with Path({str(submitted)!r}).open("a") as output: output.write("submitted\\n")\n'
        f'call_id={CALL_ID!r}\n'
        'behavior=args["task"]\n'
        'pending=behavior in ("pending", "premature_success")\n'
        'data={"call_id":call_id,"status":"in-progress" if pending else "ended",'
        '"mode":os.environ["JARVIS_MODE"]}\n'
        'result={"ok":behavior not in ("pending","failed","rejected"),'
        '"completion":"unknown" if behavior=="pending" else "completed", "data":data}\n'
        'if behavior=="failed": data["status"]="failed"\n'
        'if behavior=="rejected": result={"ok":False,"completion":"rejected"}\n'
        'if behavior=="missing_completion": result.pop("completion")\n'
        'print("__JARVIS_TOOL_PROGRESS__:"+json.dumps({"phase":"Talking",'
        '"recovery":{"task_id":call_id}}),file=sys.stderr,flush=True)\n'
        'print(json.dumps(result))\n'
    )
    runner = LocalSkillRunner(
        p.root, {NAME: REMOTE_ADAPTER},
        child_environment_policies=production.CHILD_ENVIRONMENT_POLICIES,
        permission_policies=production.TRUSTED_PERMISSION_POLICIES,
    )
    p.store.configure(background_tools=[NAME])
    p.store.touch_worker('phone-worker', {REMOTE_ADAPTER})
    for mode in ('cloud', 'local'):
        with (config_root / 'config' / f'{mode}.env').open('a') as config_file:
            config_file.write(f'VAPI_API_KEY=fixture-{mode}\nVAPI_WAIT_FOR_CALL=false\n'
                              'UNRELATED_PROVIDER_KEY=not-for-phone\n')

    def admit(args=None, mode='cloud'):
        schema, policy = runner.policy(NAME)
        service = BackgroundAdmissionService(
            p.store, adapters={NAME: REMOTE_ADAPTER},
            validate_source=lambda _: True, ready=lambda: True,
        )
        registry = SimpleNamespace(list_tools=lambda: [NAME], get_tool=lambda _: schema)
        context = service.authorize({
            'operator': 'installation', 'source': 'web', 'conversation_id': 'conversation-1',
            'generation': 1, 'request_id': 'phone-request', 'mode': mode,
            'selected': [NAME], 'tool_policy': 'auto', 'tool_policies': {NAME: policy},
        }, registry)
        accepted = context.admit(
            NAME, args or {'action': 'call', 'recipient': '(212) 555-0199', 'task': 'completed'},
            'phone-invocation', schema,
        )
        job = p.store.get(accepted['job_id'])
        return p.store.release(job['id'], receipt(job))

    return SimpleNamespace(root=p.root, store=p.store, runner=runner, manifest=manifest,
                           script=script, submitted=submitted, admit=admit)


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_production_phone_binding_preserves_reviewed_permissions(config_root, mode):
    from config_loader import config_scope
    from jsonschema import ValidationError

    from lib.background_tasks.local_skill import validate_arguments

    with config_scope(mode, {'JARVIS_TOOL_PROFILE': 'default'}):
        assert production.bindings()[NAME] == REMOTE_ADAPTER
        schema, policy = production.runner().policy(NAME)
        assert schema.permissions == {
            'dangerous': True, 'auto_approve': False, 'network': True,
            'bash': False, 'filesystem': True,
        }
        assert schema.background_adapter == REMOTE_ADAPTER
        assert policy['timeout_seconds'] == 1200
        assert policy['permission_policy_sha256']
        arguments = {'recipient': '(212) 555-0199', 'task': 'Ask when they close.'}
        validate_arguments(schema, arguments)
        validate_arguments(schema, {**arguments, 'action': 'call'})
        for action in ('status', 'list', 'contacts'):
            with pytest.raises(ValidationError):
                validate_arguments(schema, {**arguments, 'action': action})


@pytest.mark.parametrize('mutation', ['dangerous', 'auto_approve', 'network', 'bash', 'filesystem'])
def test_phone_permission_exception_requires_exact_reviewed_values(phone, mutation):
    manifest = json.loads(phone.manifest.read_text())
    manifest['permissions'][mutation] = not manifest['permissions'][mutation]
    phone.manifest.write_text(json.dumps(manifest))
    with pytest.raises(AdmissionDenied, match='policy'):
        phone.runner.policy(NAME)


def test_phone_exception_cannot_be_selected_by_manifest_or_cloned_for_another_tool(phone):
    unreviewed = LocalSkillRunner(phone.root, {NAME: REMOTE_ADAPTER},
                                 child_environment_policies=production.CHILD_ENVIRONMENT_POLICIES)
    with pytest.raises(AdmissionDenied, match='policy'):
        unreviewed.policy(NAME)
    name = 'another_phone'
    manifest = json.loads(phone.manifest.read_text())
    manifest.update(name=name, script=f'{name}.py')
    (phone.root / 'skills' / f'{name}.tool.json').write_text(json.dumps(manifest))
    shutil.copyfile(phone.script, phone.root / 'skills' / f'{name}.py')
    runner = LocalSkillRunner(
        phone.root, {name: REMOTE_ADAPTER},
        child_environment_policies={name: production.CHILD_ENVIRONMENT_POLICIES[NAME]},
        permission_policies={name: production.TRUSTED_PERMISSION_POLICIES[NAME]},
    )
    with pytest.raises(AdmissionDenied, match='policy'):
        runner.policy(name)


def test_phone_exception_cannot_be_used_for_local_process_completion(phone):
    manifest = json.loads(phone.manifest.read_text())
    manifest['execution']['background'].update(adapter=ADAPTER, completion_scope='process_group')
    phone.manifest.write_text(json.dumps(manifest))
    phone.runner.bindings[NAME] = ADAPTER
    with pytest.raises(AdmissionDenied, match='policy'):
        phone.runner.policy(NAME)


@pytest.mark.parametrize('arguments', [
    {'action': 'status', 'recipient': '2125550199', 'task': 'completed'},
    {'action': 'list', 'recipient': '2125550199', 'task': 'completed'},
    {'action': 'contacts', 'recipient': '2125550199', 'task': 'completed'},
    {'recipient': '', 'task': 'completed'}, {'recipient': '2125550199', 'task': ''},
    {'recipient': '2125550199'}, {'task': 'completed'},
])
def test_only_valid_outbound_calls_can_be_admitted(phone, arguments):
    with pytest.raises(AdmissionDenied, match='no task was queued'):
        phone.admit(arguments)
    assert not phone.submitted.exists()
    assert phone.store.counts()['reserved'] == 0


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_phone_worker_uses_originating_mode_and_delivers_one_terminal_result(phone, mode, monkeypatch):
    import tool_process

    progress = []
    environments = []
    original_progress = phone.store.progress
    original_run = tool_process.run_local_process

    def capture_progress(claim, value):
        progress.append(value)
        return original_progress(claim, value)

    def capture_process(*args, **kwargs):
        environments.append(kwargs['tool_env'])
        return original_run(*args, **kwargs)

    monkeypatch.setattr(phone.store, 'progress', capture_progress)
    monkeypatch.setattr(tool_process, 'run_local_process', capture_process)
    job = phone.admit({'recipient': '2125550199', 'task': 'completed'}, mode)
    worker = TaskWorker(phone.store, {REMOTE_ADAPTER: phone.runner})
    assert worker.run_once()
    saved = phone.store.get(job['id'])
    assert saved['state'] == 'succeeded'
    assert saved['delivery_state'] == 'pending'
    assert saved['result']['data']['mode'] == mode
    assert saved['result']['data']['call_id'] == CALL_ID
    assert any(value.get('recovery', {}).get('task_id') == CALL_ID for value in progress)
    assert environments[0]['VAPI_API_KEY'] == f'fixture-{mode}'
    assert environments[0]['VAPI_WAIT_FOR_CALL'] == 'false'
    assert environments[0]['JARVIS_BACKGROUND_DEADLINE']
    assert environments[0]['JARVIS_RESTRICTED_TOOL_ENV'] == '1'
    assert 'UNRELATED_PROVIDER_KEY' not in environments[0]
    assert not worker.run_once()
    assert phone.submitted.read_text().splitlines() == ['submitted']


@pytest.mark.parametrize('behavior', ['pending', 'premature_success', 'missing_completion'])
def test_unconfirmed_phone_result_reserves_attention_and_never_redials(phone, behavior):
    job = phone.admit({'recipient': '2125550199', 'task': behavior})
    worker = TaskWorker(phone.store, {REMOTE_ADAPTER: phone.runner})
    assert worker.run_once()
    saved = phone.store.get(job['id'])
    assert saved['state'] == 'needs_attention'
    assert saved['result']['data']['call_id'] == CALL_ID
    assert saved['progress']['recovery']['task_id'] == CALL_ID
    assert phone.store.counts()['reserved'] == 1
    assert not worker.run_once()
    assert phone.submitted.read_text().splitlines() == ['submitted']


@pytest.mark.parametrize('behavior', ['failed', 'rejected'])
def test_confirmed_phone_failure_releases_capacity_without_retry(phone, behavior):
    job = phone.admit({'recipient': '2125550199', 'task': behavior})
    worker = TaskWorker(phone.store, {REMOTE_ADAPTER: phone.runner})
    assert worker.run_once()
    assert phone.store.get(job['id'])['state'] == 'failed'
    assert phone.store.counts()['reserved'] == 0
    assert not worker.run_once()
    assert phone.submitted.read_text().splitlines() == ['submitted']


@pytest.mark.parametrize('mutation', ['script', 'permission', 'authorization', 'policy_fingerprint'])
def test_phone_worker_rechecks_fresh_authorization_before_submitting(phone, monkeypatch, mutation):
    import executor

    job = phone.admit()
    if mutation == 'script':
        phone.script.write_text(phone.script.read_text() + '\n# Changed after admission\n')
    elif mutation == 'permission':
        manifest = json.loads(phone.manifest.read_text())
        manifest['permissions']['auto_approve'] = True
        phone.manifest.write_text(json.dumps(manifest))
    else:
        original = phone.store.authorization

        def unauthorized(reference):
            result = copy.deepcopy(original(reference))
            if mutation == 'authorization':
                result['selected'] = []
            else:
                result['tool_policies'][NAME]['permission_policy_sha256'] = 'changed-policy'
            return result

        monkeypatch.setattr(phone.store, 'authorization', unauthorized)
    monkeypatch.setattr(executor.ToolExecutor, '_execute_foreground',
                        lambda *_args, **_kwargs: pytest.fail('Unapproved call must not start'))
    worker = TaskWorker(phone.store, {REMOTE_ADAPTER: phone.runner})
    assert worker.run_once()
    assert phone.store.get(job['id'])['state'] == 'failed'
    assert not phone.submitted.exists()


def test_phone_child_environment_keeps_only_reviewed_call_and_artifact_settings(tmp_path):
    policy = production.CHILD_ENVIRONMENT_POLICIES[NAME]
    values = {
        'PATH': '/fixture/bin', 'VAPI_API_KEY': 'phone-only', 'VAPI_FEMALE_VOICE_ID': 'female',
        'VAPI_WAIT_FOR_CALL': 'false', 'STASH_DIR': str(tmp_path / 'stash'),
        'JARVIS_OVERRIDE_STASH_DIR': str(tmp_path / 'override-stash'),
        'CANVAS_INTERNAL_URL': 'http://canvas.invalid', 'OLLAMA_API_KEY': 'embeddings',
        'REQUESTS_CA_BUNDLE': '/fixture/ca.pem', 'HTTPS_PROXY': 'http://proxy.invalid',
        'OPENAI_API_KEY': 'not-for-phone', 'ELEVENLABS_API_KEY': 'not-for-phone',
        'JARVIS_API_KEY': 'not-for-phone', 'UNRELATED_PROVIDER_KEY': 'not-for-phone',
        'JARVIS_OVERRIDE_OPENAI_API_KEY': 'not-for-phone',
    }
    env = restrict_child_environment(values, policy, {}, tmp_path)
    assert env['VAPI_API_KEY'] == 'phone-only'
    assert env['VAPI_FEMALE_VOICE_ID'] == 'female'
    assert env['STASH_DIR'] == values['STASH_DIR']
    assert env['JARVIS_OVERRIDE_STASH_DIR'] == values['JARVIS_OVERRIDE_STASH_DIR']
    assert env['CANVAS_INTERNAL_URL'] == values['CANVAS_INTERNAL_URL']
    assert env['REQUESTS_CA_BUNDLE'] == values['REQUESTS_CA_BUNDLE']
    assert env['HTTPS_PROXY'] == values['HTTPS_PROXY']
    assert env['HOME'] == str(tmp_path)
    assert env['JARVIS_RESTRICTED_TOOL_ENV'] == '1'
    assert not any('not-for-phone' == value for value in env.values())


@pytest.mark.parametrize('action', [None, 'call', 'status', 'list', 'contacts'])
def test_executor_background_selection_admits_calls_and_keeps_checks_foreground(
        config_root, monkeypatch, action):
    from executor import ToolExecutor

    from lib.background_tasks.admission import WebTaskContext

    paths = []
    schema = SimpleNamespace(background_adapter=REMOTE_ADAPTER)
    context = WebTaskContext(
        SimpleNamespace(admit=lambda *_args: paths.append('background') or {'ok': True}),
        'phone-authorization', (NAME,),
    )
    executor = ToolExecutor(
        'cloud', SimpleNamespace(get_tool=lambda _name: schema), load_runtime_config=False,
    )
    monkeypatch.setattr(
        executor, '_execute_foreground',
        lambda *_args, **_kwargs: paths.append('foreground') or {'ok': True},
    )
    arguments = {'recipient': '2125550199', 'task': 'Ask when they close.'}
    if action is not None:
        arguments['action'] = action
    assert executor.execute(
        NAME, arguments, background_context=context, invocation_id='phone-invocation',
    )['ok']
    assert paths == (['foreground'] if action in ('status', 'list', 'contacts') else ['background'])


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('configured, expected', [(None, 1350), ('120', 570)])
def test_phone_foreground_timeout_keeps_artifact_collection_headroom(
        config_root, monkeypatch, mode, configured, expected):
    from config_loader import config_scope
    from executor import ToolExecutor

    monkeypatch.delenv('VAPI_WAIT_TIMEOUT', raising=False)
    monkeypatch.delenv('JARVIS_OVERRIDE_VAPI_WAIT_TIMEOUT', raising=False)
    overrides = {} if configured is None else {'VAPI_WAIT_TIMEOUT': configured}
    with config_scope(mode, overrides):
        executor = ToolExecutor(mode, SimpleNamespace(), load_runtime_config=False)
        assert executor._get_subprocess_timeout(NAME) == expected
