"""yt-dlp gets the selected runtime/transport without Jarvis API credentials."""
import sys
from unittest.mock import patch

from lib import ytdlp_runtime


def test_active_module_beats_an_unrelated_path_binary():
    with patch.object(ytdlp_runtime.importlib.util, 'find_spec', return_value=object()):
        assert ytdlp_runtime.resolve_yt_dlp_command() == [sys.executable, '-m', 'yt_dlp']


def test_standalone_installation_remains_supported():
    with patch.object(ytdlp_runtime.importlib.util, 'find_spec', return_value=None), \
         patch.object(ytdlp_runtime.shutil, 'which', return_value='/tools/yt-dlp'):
        assert ytdlp_runtime.resolve_yt_dlp_command() == ['/tools/yt-dlp']


def test_node_is_enabled_and_direct_does_not_inherit_proxy():
    with patch.object(ytdlp_runtime.shutil, 'which', side_effect=lambda name: '/usr/bin/node' if name == 'node' else None):
        assert ytdlp_runtime.runtime_args(None) == ['--js-runtimes', 'node:/usr/bin/node', '--proxy', '']


def test_deno_preferred_and_explicit_proxy_preserved():
    with patch.object(ytdlp_runtime.shutil, 'which', return_value='/usr/bin/deno'):
        assert ytdlp_runtime.runtime_args('http://proxy.test:8000') == ['--js-runtimes', 'deno:/usr/bin/deno', '--proxy', 'http://proxy.test:8000']


def test_js_subprocess_preserves_runtime_tls_but_not_api_secrets(monkeypatch):
    monkeypatch.setenv('SERP_API_KEY', 'synthetic-serp-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-openai-key')
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.test:8000')
    monkeypatch.setenv('SSL_CERT_FILE', '/etc/test-ca.pem')
    env = ytdlp_runtime.subprocess_environment()
    assert 'SERP_API_KEY' not in env and 'OPENAI_API_KEY' not in env
    assert 'HTTPS_PROXY' not in env
    assert env['SSL_CERT_FILE'] == '/etc/test-ca.pem'
    assert 'PATH' in env
