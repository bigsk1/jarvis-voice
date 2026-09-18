"""Provider evidence uses structured submission/terminal responses, never prose."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills'))
sys.path.insert(0, str(ROOT / 'lib'))
from remote_completion import (RemoteCompletionError, completion_for_error,
                               gemini_interactions_options, submit)


@pytest.mark.parametrize('code,expected', [(400, 'rejected'), (403, 'rejected'), (429, 'rejected'),
                                           (408, 'unknown'), (500, 'unknown'), (503, 'unknown')])
def test_sdk_submission_status_is_explicit(code, expected):
    class APIError(Exception):
        pass
    error = APIError('fixture response')
    error.code = code
    with pytest.raises(Exception) as caught:
        submit(lambda: (_ for _ in ()).throw(error))
    assert completion_for_error(caught.value) == expected
    assert completion_for_error(RuntimeError('quota 429 rejected')) == 'unknown'


@pytest.mark.parametrize('tool', ['generate_image', 'generate_video', 'generate_music', 'create_social_clip'])
@pytest.mark.parametrize('failure,expected', [('rejected', 'rejected'), ('terminal', 'completed'),
                                              ('timeout', 'unknown'), ('save', 'completed')])
def test_skill_cli_preserves_completion_evidence(tool, failure, expected, monkeypatch, capsys):
    skill = importlib.import_module(tool)
    monkeypatch.setattr(skill, 'load_config', lambda: None)
    args = {'prompt': 'fixture', 'subject': 'fixture', 'save': True}
    monkeypatch.setattr(sys, 'argv', [tool, json.dumps(args)])
    if tool == 'generate_music':
        monkeypatch.setattr(skill, 'resolve_music_provider', lambda *a: 'elevenlabs')
    if tool == 'create_social_clip':
        monkeypatch.setattr(skill, 'get_api_base', lambda: 'https://fixture.invalid')
        monkeypatch.setattr(skill, 'build_payload', lambda args: {})
        monkeypatch.setattr(skill, 'create_task', lambda *a: 'fixture-task')
    function = 'poll_task' if tool == 'create_social_clip' else tool
    def generate(*a, **kw):
        if failure == 'save':
            return {'video_url': 'https://fixture.invalid/file', 'videos': ['/file']}
        if failure == 'timeout':
            raise TimeoutError('response lost')
        raise RemoteCompletionError('fixture failure', 'rejected' if failure == 'rejected' else 'completed')
    monkeypatch.setattr(skill, function, generate)
    def save(*a, **kw):
        raise OSError('fixture disk unavailable')
    monkeypatch.setattr(skill, 'save_to_stash', save)
    if hasattr(skill, 'download_video'):
        monkeypatch.setattr(skill, 'download_video', save)
    with pytest.raises(SystemExit):
        skill.main()
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] is False and result['completion'] == expected


@pytest.mark.parametrize('provider', ['openai', 'xai', 'elevenlabs'])
def test_http_quota_rejection_at_real_provider_submission(provider, monkeypatch):
    skill = importlib.import_module('generate_music' if provider == 'elevenlabs' else 'generate_image')
    monkeypatch.setattr(skill, 'get_config_value', lambda key, default=None: 'fixture-key' if key.endswith('API_KEY') else default)
    response = SimpleNamespace(status_code=429, text='quota', json=lambda: {})
    monkeypatch.setattr(skill.requests, 'post', lambda *a, **kw: response)
    call = getattr(skill, 'generate_music_elevenlabs' if provider == 'elevenlabs' else 'generate_image_' + provider)
    with pytest.raises(RemoteCompletionError) as caught:
        call('fixture prompt')
    assert caught.value.completion == 'rejected'


@pytest.mark.parametrize('phase', ['submit', 'poll', 'failed', 'timeout'])
def test_xai_video_submission_is_distinct_from_polling(phase, monkeypatch):
    import grpc
    import xai_sdk
    import generate_video
    from xai_sdk.proto import deferred_pb2

    class QuotaError(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.RESOURCE_EXHAUSTED

    class Video:
        def start(self, **kw):
            if phase == 'submit':
                raise QuotaError()
            return SimpleNamespace(request_id='fixture')
        def get(self, request_id):
            if phase == 'poll':
                raise QuotaError()
            if phase == 'timeout':
                raise TimeoutError('lost response')
            return SimpleNamespace(status=deferred_pb2.DeferredStatus.FAILED)

    def client(**kw):
        assert kw['channel_options'] == [('grpc.enable_retries', 0)]
        return SimpleNamespace(video=Video())
    monkeypatch.setattr(xai_sdk, 'Client', client)
    monkeypatch.setattr(generate_video, 'get_config_value', lambda key, default=None:
        {'XAI_API_KEY': 'fixture', 'JARVIS_BACKGROUND_DEADLINE': '9999999999'}.get(key, default))
    with pytest.raises(Exception) as caught:
        generate_video.generate_video_xai('fixture')
    assert completion_for_error(caught.value) == {
        'submit': 'rejected', 'poll': 'unknown', 'failed': 'completed', 'timeout': 'unknown',
    }[phase]


@pytest.mark.parametrize('first,expected', [(429, 'rejected'), (503, 'unknown'), ('timeout', 'unknown')])
def test_real_gemini_sdk_cannot_resubmit_then_misclassify_a_later_rejection(first, expected):
    import httpx
    from google import genai

    requests = []
    def transport(request):
        requests.append(request)
        if first == 'timeout':
            raise httpx.ReadTimeout('lost submission response', request=request)
        return httpx.Response(first if len(requests) == 1 else 429,
            json={'error': {'code': 429, 'message': 'fixture quota'}}, request=request)

    options = gemini_interactions_options()
    options['client_args']['transport'] = httpx.MockTransport(transport)
    options['retry_options']['initial_delay'] = 0.001
    with genai.Client(api_key='fixture', http_options=options) as client:
        with pytest.raises(Exception) as caught:
            submit(client.interactions.create, model='fixture', input='fixture')
    assert len(requests) == 1
    assert completion_for_error(caught.value) == expected


@pytest.mark.parametrize('tool', ['generate_music', 'generate_video'])
@pytest.mark.parametrize('status,expected', [(None, 'unknown'), ('failed', 'completed'), ('completed', 'completed')])
def test_gemini_missing_status_is_unknown_and_background_uses_submission_hooks(tool, status, expected, monkeypatch):
    from google import genai
    skill = importlib.import_module(tool)
    config = {'GEMINI_API_KEY': 'fixture', 'JARVIS_BACKGROUND_DEADLINE': '9999999999',
              'GEMINI_VIDEO_MODEL': 'gemini-omni-flash-preview'}
    monkeypatch.setattr(skill, 'get_config_value', lambda key, default=None: config.get(key, default))
    def client(**kwargs):
        assert set(kwargs['http_options']['client_args']['event_hooks']) == {'request', 'response'}
        return SimpleNamespace(interactions=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(status=status)))
    monkeypatch.setattr(genai, 'Client', client)
    with pytest.raises(Exception) as caught:
        getattr(skill, tool + '_gemini')('fixture')
    assert completion_for_error(caught.value) == expected


def test_bounded_failure_keeps_confirmed_remote_evidence():
    from lib.background_tasks.local_skill import bounded_failure
    result = bounded_failure({'ok': False, 'completion': 'rejected', 'error': 'x' * (2 * 1024**2)})
    assert result['completion'] == 'rejected'
    assert result['diagnostics_truncated'] and len(json.dumps(result)) < 10000


@pytest.mark.parametrize('provider', ['openai', 'xai', 'gemini'])
def test_empty_image_response_is_not_completion_proof(provider, monkeypatch):
    import generate_image
    from google import genai
    from unittest.mock import MagicMock

    monkeypatch.setattr(generate_image, 'get_config_value', lambda key, default=None:
        'fixture' if key.endswith('API_KEY') else default)
    monkeypatch.setattr(generate_image.requests, 'post', lambda *a, **kw:
        SimpleNamespace(status_code=200, json=lambda: {}, text='{}'))
    client = MagicMock()
    client.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(candidates=[])
    monkeypatch.setattr(genai, 'Client', lambda **kw: client)
    with pytest.raises(Exception) as caught:
        getattr(generate_image, 'generate_image_' + provider)('fixture')
    assert completion_for_error(caught.value) == 'unknown'


def test_gemini_image_safety_response_is_confirmed_completion(monkeypatch):
    import generate_image
    from google import genai
    from unittest.mock import MagicMock

    monkeypatch.setattr(generate_image, 'get_config_value', lambda key, default=None:
        'fixture' if key.endswith('API_KEY') else default)
    client = MagicMock()
    client.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(
        candidates=[], prompt_feedback=SimpleNamespace(block_reason='SAFETY'))
    monkeypatch.setattr(genai, 'Client', lambda **kw: client)
    with pytest.raises(RemoteCompletionError) as caught:
        generate_image.generate_image_gemini('fixture')
    assert completion_for_error(caught.value) == 'completed'
