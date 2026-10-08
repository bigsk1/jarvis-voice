"""Cookie-free runtime setup and explicit opt-in transcript fallback."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('youtube_reliability', ROOT / 'skills/auto-tools/youtube_transcript.py')
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)
URL = 'https://www.youtube.com/watch?v=abcdefghijk'
SRT = '1\n00:01:01,000 --> 00:01:08,000\nProject one.\n'
SEGMENTS = [{'start_ms': 61000, 'start_time_text': '1:01', 'snippet': 'Project one.'},
            {'start_ms': 86000, 'start_time_text': '1:26', 'snippet': 'Project two.'}]


@pytest.mark.parametrize('enabled,key,profile,expected', [
    ('false', 'key', {}, False), ('true', '', {}, False),
    ('true', 'key', {'serpapi_youtube': False}, False), ('true', 'key', {}, True),
])
def test_fallback_requires_opt_in_key_and_effective_tool(monkeypatch, enabled, key, profile, expected):
    config = {'SERPAPI_YOUTUBE_FALLBACK': enabled, 'SERP_API_KEY': key}
    monkeypatch.setattr(TOOL, 'get_config_value', lambda name, default='': config.get(name, default))
    monkeypatch.setattr(TOOL, 'load_active_profile_overrides', lambda: profile)
    assert TOOL.serpapi_youtube_fallback_enabled() is expected


def test_single_download_fetches_title_and_subtitles_with_no_api_secrets(monkeypatch):
    calls = []
    monkeypatch.setenv('SERP_API_KEY', 'synthetic-secret')
    monkeypatch.setattr(TOOL, 'resolve_yt_dlp_command', lambda: ['python', '-m', 'yt_dlp'])
    monkeypatch.setattr(TOOL, 'runtime_args', lambda proxy: ['--js-runtimes', 'node:/usr/bin/node', '--proxy', proxy or ''])

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        output = Path(cmd[cmd.index('--output')+1])
        output.with_suffix('.en.srt').write_text(SRT)
        output.with_suffix('.info.json').write_text(json.dumps({'title': 'Example projects'}))
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(TOOL.subprocess, 'run', run)
    srt, title, error = TOOL.download_transcript(URL)
    assert srt == SRT and title == 'Example projects' and error is None
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[cmd.index('--proxy')+1] == ''
    assert '--no-playlist' in cmd and '--write-info-json' in cmd
    assert 'SERP_API_KEY' not in kwargs['env']


def test_caption_error_keeps_primary_error_and_redacts_proxy_credentials(monkeypatch):
    monkeypatch.setattr(TOOL.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stderr='WARNING: Extra noise\nERROR: HTTP 429 via http://tester:password@proxy.test:8000'))
    _, _, error = TOOL.download_transcript(URL)
    assert 'HTTP 429' in error and 'password' not in error and 'Extra noise' not in error


def test_fallback_uses_serpapi_transport_and_restores_parent_environment(monkeypatch):
    monkeypatch.setenv(TOOL.PROXY_POLICY_ENV, 'prefer')
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.test:8000')

    def fetch(*args):
        assert args == ('abcdefghijk', 'en', '', '', False)
        assert TOOL.os.environ[TOOL.PROXY_POLICY_ENV] == 'off'
        assert 'HTTPS_PROXY' not in TOOL.os.environ
        return {'transcript': SEGMENTS}
    monkeypatch.setattr(TOOL, 'fetch_transcript', fetch)
    assert TOOL.fetch_serpapi_fallback(URL)['transcript'] == SEGMENTS
    assert TOOL.os.environ[TOOL.PROXY_POLICY_ENV] == 'prefer'
    assert TOOL.os.environ['HTTPS_PROXY'] == 'http://proxy.test:8000'


def test_fallback_restores_environment_after_api_failure(monkeypatch):
    monkeypatch.setenv(TOOL.PROXY_POLICY_ENV, 'prefer')
    monkeypatch.setattr(TOOL, 'fetch_transcript', Mock(side_effect=RuntimeError('HTTP 429')))
    with pytest.raises(RuntimeError):
        TOOL.fetch_serpapi_fallback(URL)
    assert TOOL.os.environ[TOOL.PROXY_POLICY_ENV] == 'prefer'


@pytest.fixture
def main_setup(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['youtube_transcript.py', json.dumps({'url': URL})])
    monkeypatch.setattr(TOOL, 'load_config', lambda: None)
    monkeypatch.setattr(TOOL, 'build_proxy_url_attempts', lambda **kwargs: ['proxy-one', 'proxy-two', None])
    monkeypatch.setattr(TOOL, 'MemoryDB', lambda: SimpleNamespace(remember=lambda **kwargs: None))
    save = Mock(side_effect=lambda filename, content, space=None: (True, SimpleNamespace(space_id='space_test'), 'stash://space_test/' + filename))
    monkeypatch.setattr(TOOL, 'save_to_stash', save)
    monkeypatch.setattr(TOOL, 'serpapi_youtube_fallback_enabled', lambda: True)
    fetch = Mock(return_value={'transcript': SEGMENTS})
    monkeypatch.setattr(TOOL, 'fetch_serpapi_fallback', fetch)
    return save, fetch


def test_enabled_fallback_saves_both_artifacts_with_timestamped_markdown(monkeypatch, capsys, main_setup):
    save, fetch = main_setup
    monkeypatch.setattr(TOOL, 'download_transcript', lambda *a, **k: (None, None, 'HTTP 429'))
    TOOL.main()
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and result['data']['fallback_used']
    assert result['data']['source'] == 'SerpApi'
    assert result['data']['md_stash_ref'] == result['data']['transcript_stash_ref']
    assert save.call_count == 2 and fetch.call_count == 1
    assert '00:01:01,000 --> 00:01:26,000' in save.call_args_list[0].args[1]
    assert '**[1:01]** Project one.' in save.call_args_list[1].args[1]
    assert '**[1:26]** Project two.' in save.call_args_list[1].args[1]
    assert 'inferred' in result['data']['srt_timing']


def test_native_success_does_not_spend_api_credits(monkeypatch, capsys, main_setup):
    _, fetch = main_setup
    monkeypatch.setattr(TOOL, 'download_transcript', lambda *a, **k: (SRT, 'Example', None))
    TOOL.main()
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and not result['data']['fallback_used']
    fetch.assert_not_called()


@pytest.mark.parametrize('opt_in,transcript', [(False, {'transcript': SEGMENTS}), (True, {'transcript': []})])
def test_disabled_or_empty_fallback_never_claims_saved_transcript(monkeypatch, capsys, main_setup, opt_in, transcript):
    save, fetch = main_setup
    monkeypatch.setattr(TOOL, 'download_transcript', lambda *a, **k: (None, None, 'HTTP 429'))
    monkeypatch.setattr(TOOL, 'serpapi_youtube_fallback_enabled', lambda: opt_in)
    fetch.return_value = transcript
    with pytest.raises(SystemExit):
        TOOL.main()
    assert not json.loads(capsys.readouterr().out)['ok']
    save.assert_not_called()
    assert fetch.call_count == int(opt_in)


def test_missing_or_invalid_start_time_is_not_fabricated():
    with pytest.raises((KeyError, ValueError)):
        TOOL.transcript_segments_to_srt([{'snippet': 'Missing time'}])
    with pytest.raises(ValueError):
        TOOL.transcript_segments_to_srt([{'start_ms': -1, 'snippet': 'Bad time'}])
