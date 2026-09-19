"""Settings, real media CLIs, foreground overlap and late artifact delivery without paid APIs."""

import json
import shutil
import threading
from pathlib import Path

import pytest
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks import production
from lib.background_tasks.local_contract import ADAPTER, REMOTE_ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import TaskWorker
from lib.background_tasks import AdmissionDenied

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ('generate_image', 'generate_video', 'generate_music', 'create_social_clip')


@pytest.mark.parametrize('name', MEDIA)
@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_media_settings_admit_chat_then_late_artifact(web_tasks, monkeypatch, name, mode):
    import config_loader
    import llm_provider
    from config_loader import config_scope

    h = web_tasks
    installation = h.tmp / 'media-installation'
    skills = installation / 'skills'
    skills.mkdir(parents=True)
    for tool in MEDIA:
        shutil.copyfile(ROOT / 'skills' / (tool + '.tool.json'), skills / (tool + '.tool.json'))
        shutil.copyfile(ROOT / 'tests/fixtures/background_media_skill.py', skills / (tool + '.py'))
    runner = LocalSkillRunner(installation, dict.fromkeys(MEDIA, REMOTE_ADAPTER))
    monkeypatch.setattr(production, 'runner', lambda: runner)
    h.background.adapters = production.bindings()
    with config_scope(mode, {'JARVIS_TOOL_PROFILE': 'default',
                            'MONEYPRINTER_API_URL': 'https://moneyprinter.invalid'}):
        schemas = {tool: runner.policy(tool)[0] for tool in MEDIA}
    old_get = h.background.registry.get_tool
    h.background.registry.get_tool = lambda tool: schemas.get(tool) or old_get(tool)
    h.background.registry.list_tools = lambda: [*MEDIA, 'get_time']
    monkeypatch.setattr(llm_provider, 'create_configured_provider',
                        lambda **kwargs: ('test', 'test-model', object()))
    h.tasks.touch_worker('media-ready', {REMOTE_ADAPTER})
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    http = h.app.test_client()
    response = http.patch('/api/background-tasks', headers=headers,
                          json={'background_enabled': True, 'background_tools': [name]})
    assert response.status_code == 200
    assert response.json['settings']['background_tools'] == [name]
    status = http.get('/api/background-tasks?mode=' + mode, headers=headers).json
    assert status['tool_details'][name] == {'remote_work': True, 'worker_ready': True}
    output, stash = h.tmp / 'media-output', h.tmp / 'media-stash'
    output.mkdir()
    if name == 'create_social_clip':
        # Auth is created in the chat thread's own mode scope.
        monkeypatch.setattr(config_loader, '_load_mode_config', lambda _: {
            'JARVIS_TOOL_PROFILE': 'default', 'MONEYPRINTER_API_URL': 'https://moneyprinter.invalid'})
    arguments = {('subject' if name == 'create_social_clip' else 'prompt'): 'Fixture media'}
    h.client.emit('chat:send', {'message': 'Generate fixture media', 'mode': mode,
        'tool_action': {'tool': name, 'arguments': arguments}})
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    cid = job['conversation_id']
    eventually(lambda: h.tasks.get(job['id'])['dispatch_state'] == 'ready')
    assert job['adapter'] == REMOTE_ADAPTER
    assert h.store.get_conversation(cid)['run']['status'] == 'completed'
    assert not (output / 'provider.started').exists()
    worker = TaskWorker(h.tasks, {REMOTE_ADAPTER: runner}, deployment_overrides={
        'STASH_DIR': str(stash), 'JARVIS_TOOL_PROFILE': 'default',
        'MONEYPRINTER_API_URL': 'https://moneyprinter.invalid',
        'FIXTURE_JARVIS_ROOT': str(ROOT), 'FIXTURE_MEDIA_OUTPUT': str(output),
        'FIXTURE_CONFIG_ROOT': str(h.tmp / 'config-root')})
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    try:
        eventually((output / 'provider.started').exists)
        current = h.tasks.get(job['id'])
        assert current['state'] == 'running'
        assert h.background.card(current)['remote_work'] is True
        assert h.background.card(current)['can_cancel'] is False
        denied = http.post(f"/api/background-jobs/{job['id']}/actions", headers=headers,
                           json={'action': 'cancel', 'revision': current['revision']})
        assert denied.status_code == 409
        h.client.emit('chat:send', {'conversation_id': cid, 'message': 'What time is it?', 'mode': mode})
        eventually(lambda: (h.root / 'foreground_started').exists())
        assert h.tasks.get(job['id'])['state'] == 'running'
        (h.root / 'foreground_finish').touch()
        eventually(lambda: h.store.get_conversation(cid)['run']['status'] == 'completed')
        (output / 'provider.release').touch()
        eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded', timeout=10)
        eventually(lambda: h.tasks.get(job['id'])['delivery_state'] == 'delivered')
        result = h.tasks.get(job['id'])['result']
        assert result['ok'] is True
        if name == 'create_social_clip':
            assert result['data']['task_id'] == 'fixture-social-task'
            assert (output / 'download.started').exists()
        else:
            assert result['data']['model'] == 'fixture-model'
        saved = result['data']['saved']
        assert saved['stash_ref'].startswith('stash://')
        artifact = Path(saved['path'])
        assert artifact.is_relative_to(output) and artifact.stat().st_size > 0
        assert list(stash.glob('space_*'))
        messages = h.store.get_conversation(cid)['messages']
        assert len(messages) == 5 and messages[3]['tools_used'] == ['get_time']
        assert messages[-1]['data']['_kind'] == 'continuation'
        assert messages[-1]['data']['_background_mode'] == mode
        assert len(h.tasks.job_detail(job['id'])['attempts']) == 1
        assert not worker.run_once()
    finally:
        (output / 'provider.release').touch()
        thread.join(10)
    assert not thread.is_alive()


def test_old_local_worker_does_not_claim_remote_readiness(web_tasks):
    h = web_tasks
    # This fixture only installs the shared manifests; an operator may also
    # have ignored personal callback bindings in the live checkout.
    public_bindings = dict(production.TRUSTED_BINDINGS)
    h.background.adapters = public_bindings
    from tool_schema import ToolSchema
    h.background.registry.list_tools = lambda: list(public_bindings)
    h.background.registry.get_tool = lambda name: ToolSchema.from_json_file(
        str(ROOT / 'skills' / (name + '.tool.json')))
    h.tasks.touch_worker('old-local-worker', {ADAPTER})
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    status = h.app.test_client().get('/api/background-tasks', headers=headers).json
    assert status['worker_ready'] is True
    assert status['tool_details']['convert_file']['worker_ready'] is True
    for name in MEDIA:
        assert status['tool_details'][name]['worker_ready'] is False


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('gate', ['available', 'manifest', 'profile', 'environment', 'web_block'])
def test_social_clip_options_and_admission_follow_mode_policy(web_tasks, monkeypatch, mode, gate):
    import config_loader
    from config_loader import config_scope, get_active_config_mode
    from jarvis_bundle_chat_test import config as web_config
    from lib.background_tasks.admission import BackgroundAdmissionService
    from tool_schema import ToolRegistry
    import tool_profiles

    h = web_tasks
    name = 'create_social_clip'
    skills = h.tmp / 'gated-skills'
    skills.mkdir()
    manifest = json.loads((ROOT / 'skills' / (name + '.tool.json')).read_text())
    manifest['enabled'] = gate != 'manifest'
    (skills / (name + '.tool.json')).write_text(json.dumps(manifest))
    profiles = h.tmp / 'profiles'
    profiles.mkdir()
    (profiles / 'social-test.json').write_text(json.dumps({
        'overrides': {name: False} if gate == 'profile' else {}}))
    monkeypatch.setattr(tool_profiles, 'get_profiles_dir', lambda: profiles)
    # The other mode is unavailable: status must honor the query mode,
    # rather than the caller's ambient/global configuration.
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda selected: {
        'JARVIS_TOOL_PROFILE': 'social-test', 'MONEYPRINTER_API_URL':
        'https://moneyprinter.invalid' if selected == mode and gate != 'environment' else ''})
    old_setting = web_config.get_web_setting
    blocked = [name] if gate == 'web_block' else []
    monkeypatch.setattr(web_config, 'get_web_setting', lambda key, default=None:
                        blocked if key == 'tools.blocked' else old_setting(key, default))
    registries = []

    def registry(requested_mode):
        assert requested_mode == get_active_config_mode() == mode
        registries.append(ToolRegistry(str(skills)))
        return registries[-1]

    monkeypatch.setattr(h.background, 'get_registry', registry)
    h.background.adapters = production.bindings()
    h.tasks.configure(background_tools=[name])  # Saved intent cannot bypass a block.
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    with config_scope('local' if mode == 'cloud' else 'cloud'):
        response = h.app.test_client().get('/api/background-tasks?mode=' + mode, headers=headers)
    assert response.status_code == 200
    status = response.json
    assert name in status['configured_tools']
    assert status['settings']['background_tools'] == [name]
    assert (name in status['tools']) == (gate == 'available')
    if gate != 'available':
        service = BackgroundAdmissionService(h.tasks, adapters=production.bindings(),
                                            ready=lambda: True, validate_source=lambda _: True)
        with pytest.raises(AdmissionDenied, match='no supported background adapter'):
            service.authorize({'selected': [name], 'source': 'web', 'tool_policy': 'auto',
                               'blocked': blocked}, registries[-1])
    assert not h.tasks.conversation_jobs()
