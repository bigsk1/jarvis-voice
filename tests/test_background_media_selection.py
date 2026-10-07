"""Media choices survive admission and the real supervised child-process path."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_background_tasks import config_root as config_root, receipt, store as store
from lib.background_tasks import AdmissionDenied, Conflict
from lib.background_tasks.admission import BackgroundAdmissionService
from lib.background_tasks.local_contract import REMOTE_ADAPTER
from lib.background_tasks.local_skill import LocalSkillRunner
from lib.background_tasks.worker import TaskWorker

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Local supervision requires Linux')


@pytest.fixture(params=['image', 'video', 'music'])
def media_job(request, store, config_root, tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / 'lib'))
    sys.path.insert(0, str(ROOT / 'orchestrator'))
    import config_loader
    import executor

    media_type = request.param
    name = f'generate_{media_type}'
    model = {'image': 'gemini-nano-banana-2.1', 'video': 'veo-3.1-fast-generate-preview',
             'music': 'lyria-3-clip-preview'}[media_type]
    provider_key = f'{media_type.upper()}_TOOL_PROVIDER'
    model_key = f'GEMINI_{media_type.upper()}_MODEL'
    default_provider = {'image': 'openai', 'video': 'xai', 'music': 'elevenlabs'}[media_type]
    monkeypatch.setattr(config_loader, 'get_project_root', lambda: config_root)
    monkeypatch.setattr(executor, 'get_logger', lambda mode: SimpleNamespace(log_tool_call=lambda **kw: None))
    monkeypatch.setenv('PATH', str(ROOT / '.venv/bin') + os.pathsep + os.environ['PATH'])
    for mode in ('cloud', 'local'):
        (config_root / 'config' / f'{mode}.env').write_text(
            'IMAGE_TOOL_PROVIDER=openai\nGEMINI_IMAGE_MODEL=gemini-3.1-flash-image\n'
            'VIDEO_TOOL_PROVIDER=xai\nGEMINI_VIDEO_MODEL=veo-3.1-generate-preview\n'
            'MUSIC_TOOL_PROVIDER=elevenlabs\n'
            'OPENAI_API_KEY=fixture-openai\nGEMINI_API_KEY=fixture-gemini\nJARVIS_TOOL_PROFILE=default\n'
        )

    installation = tmp_path / 'installation'
    skills = installation / 'skills'
    skills.mkdir(parents=True)
    (skills / f'{name}.tool.json').write_bytes((ROOT / 'skills' / f'{name}.tool.json').read_bytes())
    # Exercise the actual dispatcher/SDK request builder in a fresh child. Only
    # reference resolution and provider transport are fixtures; no paid API calls.
    script = '''import base64, importlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, REPO_SKILLS)
sys.path.insert(0, REPO_LIB)
tool = importlib.import_module(TOOL_MODULE)
import config_loader
config_loader.get_project_root = lambda: Path(CONFIG_ROOT)
config_loader.load_config()
assert os.environ['JARVIS_OVERRIDE_' + PROVIDER_KEY] == 'gemini'
from google import genai
from google.genai import types

class Models:
    def generate_content(self, **kwargs):
        assert kwargs['model'] == EXPECTED_MODEL
        assert kwargs['contents'].parts[0].inline_data.data == b'reference'
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role='model', parts=[types.Part(inline_data=types.Blob(data=b'edited', mime_type='image/png'))]))])
    def generate_videos(self, **kwargs):
        assert kwargs['model'] == EXPECTED_MODEL
        assert kwargs['image'].image_bytes == b'reference'
        assert kwargs['config'].aspect_ratio == '9:16'
        assert kwargs['config'].duration_seconds == 8
        assert kwargs['config'].resolution == '1080p'
        video = SimpleNamespace(video_bytes=b'clip', uri=None, url=None)
        return SimpleNamespace(done=True, response=SimpleNamespace(generated_videos=[SimpleNamespace(video=video)]))

class Client:
    models = Models()
    files = SimpleNamespace(download=lambda **kwargs: b'clip')
    def __enter__(self): return self
    def __exit__(self, *args): return False

genai.Client = lambda **kwargs: Client()
def wrong_provider(*args, **kwargs):
    raise AssertionError('Media selection reached a non-Gemini provider')
tool.requests.post = wrong_provider
tool._resolve_image_to_base64 = lambda source: (base64.b64encode(b'reference').decode(), 'image/jpeg')
tool._load_video_image_bytes = lambda source: (b'reference', 'image/jpeg')
if TOOL_MODULE == 'generate_music':
    tool.generate_music_gemini = lambda **kwargs: {'provider': 'gemini', 'model': EXPECTED_MODEL}
    tool.generate_music_elevenlabs = wrong_provider
result = getattr(tool, TOOL_MODULE)(**json.loads(sys.argv[1]))
data = {key: result[key] for key in ('provider', 'model')}
data['has_reference'] = result.get('is_edit', result.get('from_image', False))
print(json.dumps({'ok': True, 'data': data}))
'''
    for marker, value in {
        'REPO_SKILLS': str(ROOT / 'skills'), 'REPO_LIB': str(ROOT / 'lib'),
        'CONFIG_ROOT': str(config_root), 'EXPECTED_MODEL': model, 'TOOL_MODULE': name,
        'PROVIDER_KEY': provider_key,
    }.items():
        script = script.replace(marker, repr(value))
    (skills / f'{name}.py').write_text(script)
    runner = LocalSkillRunner(installation, {name: REMOTE_ADAPTER})
    store.configure(background_tools=[name])
    store.touch_worker('media-worker', {REMOTE_ADAPTER})
    service = BackgroundAdmissionService(store, adapters={name: REMOTE_ADAPTER},
                                        validate_source=lambda _: True, ready=lambda: True)
    return SimpleNamespace(store=store, runner=runner, service=service, config=config_loader,
                           media_type=media_type, name=name, model=model,
                           provider_key=provider_key, model_key=model_key, default_provider=default_provider)


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('selection', ['saved_web', 'modal'])
def test_background_media_retains_per_job_choice(media_job, mode, selection):
    p = media_job
    schema, policy = p.runner.policy(p.name)
    registry = SimpleNamespace(list_tools=lambda: [p.name], get_tool=lambda _: schema)
    context = p.service.authorize({
        'operator': 'installation', 'source': 'web', 'conversation_id': 'image-conversation',
        'generation': 1, 'request_id': 'image-request', 'mode': mode,
        'selected': [p.name], 'tool_policy': 'auto',
        'tool_policies': {p.name: policy},
    }, registry)
    if p.media_type == 'image':
        args = {'prompt': 'Change the hair to blond', 'reference_image': 'stash://fixture/image', 'image_size': '2K'}
    elif p.media_type == 'video':
        args = {'prompt': 'Animate the reference', 'image_url': 'stash://fixture/image',
                'aspect_ratio': '9:16', 'duration': 8, 'resolution': '1080p'}
    else:
        args = {'prompt': 'Instrumental jazz', 'instrumental': True}
    if selection == 'modal':
        args.update(provider='gemini')
        if p.media_type != 'music':
            args['model'] = p.model
        # The Web decorator creates this trusted scope from modal settings.
        overrides = {p.provider_key: 'gemini', p.model_key: p.model}
    else:
        overrides = {p.provider_key: 'gemini', p.model_key: p.model}
    before = dict(os.environ)
    with p.config.config_scope(mode, overrides):
        accepted = context.admit(p.name, args, 'media-call', schema)
    job = p.store.get(accepted['job_id'])
    expected = {**args, 'provider': 'gemini'}
    if p.media_type != 'music':
        expected['model'] = p.model
    assert job['admission']['arguments'] == expected
    assert 'fixture-gemini' not in json.dumps(job['admission'])
    assert 'fixture-openai' not in json.dumps(job['admission'])

    # The modal scope is gone and the worker sees another provider. Redelivery
    # must still reuse the same receipt rather than changing the queued choice.
    with p.config.config_scope(mode):
        assert p.config.get_config_value(p.provider_key) == p.default_provider
        assert context.admit(p.name, args, 'media-call', schema) == accepted
        with pytest.raises(Conflict):
            context.admit(p.name, {**args, 'prompt': 'Different edit'}, 'media-call', schema)
    assert dict(os.environ) == before

    p.store.release(job['id'], receipt(job))
    worker = TaskWorker(p.store, {REMOTE_ADAPTER: p.runner},
                        deployment_overrides={p.provider_key: p.default_provider})
    assert worker.run_once()
    finished = p.store.get(job['id'])
    assert finished['state'] == 'succeeded', finished.get('attention_reason') or finished.get('result')
    assert finished['result']['data'] == {'provider': 'gemini', 'model': p.model,
                                        'has_reference': p.media_type != 'music'}
    assert dict(os.environ) == before


def _context(p):
    schema, policy = p.runner.policy(p.name)
    registry = SimpleNamespace(list_tools=lambda: [p.name], get_tool=lambda _: schema)
    context = p.service.authorize({
        'operator': 'installation', 'source': 'web', 'conversation_id': 'media-conversation',
        'generation': 1, 'request_id': 'media-request', 'mode': 'cloud',
        'selected': [p.name], 'tool_policy': 'auto', 'tool_policies': {p.name: policy},
    }, registry)
    return context, schema


def test_chat_provider_argument_cannot_replace_saved_selection(media_job):
    p = media_job
    context, schema = _context(p)
    with p.config.config_scope('cloud', {p.provider_key: p.default_provider}):
        accepted = context.admit(p.name, {'prompt': 'A request', 'provider': 'gemini'}, 'call', schema)
    queued = p.store.get(accepted['job_id'])['admission']['arguments']
    assert queued['provider'] == p.default_provider
    if p.media_type != 'music':
        assert queued['model'] != p.model


def test_known_model_from_another_provider_is_not_queued(media_job):
    p = media_job
    if p.media_type == 'music':
        pytest.skip('Music has no model argument')
    context, schema = _context(p)
    with p.config.config_scope('cloud', {p.provider_key: p.default_provider}):
        with pytest.raises(AdmissionDenied, match='belongs to gemini.*selected provider'):
            context.admit(p.name, {'prompt': 'A request', 'provider': 'gemini', 'model': p.model}, 'call', schema)
    assert not context.receipts
    assert p.store.counts()['reserved'] == 0


def test_unknown_custom_model_id_is_preserved(media_job):
    p = media_job
    if p.media_type == 'music':
        pytest.skip('Music has no model argument')
    context, schema = _context(p)
    with p.config.config_scope('cloud', {p.provider_key: p.default_provider}):
        accepted = context.admit(p.name, {'prompt': 'A request', 'model': 'future-custom-model'}, 'call', schema)
    assert p.store.get(accepted['job_id'])['admission']['arguments']['model'] == 'future-custom-model'
