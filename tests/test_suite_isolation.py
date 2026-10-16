"""Observable boundaries of the deterministic suite's config isolation."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest
import suite_isolation
from suite_isolation import ROOT, config_modules, guard_env_reader, isolated_test_state


def test_inherited_model_mode_and_credentials_are_removed_before_collection():
    env = dict(os.environ, JARVIS_MODE='local', JARVIS_OVERRIDE_LLM_MODEL='operator-model',
               OLLAMA_MODEL='operator-model', OPENAI_API_KEY='fixture-secret',
               JARVIS_TEST_LONG_ENCODE='1', JARVIS_TEST_VIDEO='/fixture/video.mp4',
               JARVIS_TEST_IMAGE='/fixture/image.png')
    result = subprocess.run([sys.executable, '-c', """
import os
import sys
sys.path.insert(0, 'tests')
from suite_isolation import install_default_isolation
install_default_isolation()
assert not any(key in os.environ for key in (
    'JARVIS_MODE', 'JARVIS_OVERRIDE_LLM_MODEL', 'OLLAMA_MODEL', 'OPENAI_API_KEY',
))
assert os.environ['JARVIS_TEST_LONG_ENCODE'] == '1'
assert os.environ['JARVIS_TEST_VIDEO'] == '/fixture/video.mp4'
assert os.environ['JARVIS_TEST_IMAGE'] == '/fixture/image.png'
"""], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_private_mode_files_are_not_read_but_fixture_files_use_the_real_parser(tmp_path):
    fixture = tmp_path / 'cloud.env'
    fixture.write_text('LLM_MODEL=fixture-model\n')
    for module in config_modules():
        assert module.load_env_file(ROOT / 'config' / 'cloud.env') == {}
        assert module.load_env_file(ROOT / 'config' / 'local.env') == {}
        assert module.load_env_file(fixture) == {'LLM_MODEL': 'fixture-model'}


def test_blocked_config_file_never_reaches_reader(tmp_path):
    operator = tmp_path / 'operator.env'
    reader = Mock(return_value={'LLM_MODEL': 'fixture-model'})
    guarded = guard_env_reader(reader, [operator])
    assert guarded(operator) == {}
    reader.assert_not_called()
    fixture = tmp_path / 'fixture.env'
    assert guarded(fixture) == {'LLM_MODEL': 'fixture-model'}
    reader.assert_called_once_with(fixture)


def test_environment_and_both_request_scopes_are_restored_after_failure(monkeypatch):
    monkeypatch.setenv('JARVIS_MODE', 'local')
    modules = config_modules()
    before = [module.get_scoped_config() for module in modules]
    with pytest.raises(RuntimeError, match='fixture failure'), isolated_test_state():
        os.environ['JARVIS_MODE'] = 'cloud'
        os.environ['JARVIS_OVERRIDE_LLM_MODEL'] = 'leaked-model'
        for module in modules:
            module._scoped_config.set(module._ScopedConfig('cloud', {}, {'LLM_MODEL': 'leaked-model'}))
        raise RuntimeError('fixture failure')
    assert os.environ['JARVIS_MODE'] == 'local'
    assert 'JARVIS_OVERRIDE_LLM_MODEL' not in os.environ
    assert [module.get_scoped_config() for module in modules] == before


@pytest.mark.parametrize('module', config_modules(), ids=lambda module: module.__name__)
def test_redacted_mode_ownership_blocks_process_fallthrough_but_allows_overrides(module, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'process-value')
    monkeypatch.setenv('SUITE_UNOWNED_SETTING', 'unowned-process-value')
    assert module.get_config_value('OPENAI_API_KEY') == 'process-value'
    with module.config_scope('cloud') as snapshot:
        assert 'OPENAI_API_KEY' in snapshot.mode_keys
        assert 'OPENAI_API_KEY' not in snapshot.config
        assert module.get_config_value('OPENAI_API_KEY', 'caller-default') == 'caller-default'
        assert module.get_config_value('SUITE_UNOWNED_SETTING') == 'unowned-process-value'
        assert 'OPENAI_API_KEY' not in module.export_config_environment('cloud')
        with module.config_override_scope({'OPENAI_API_KEY': 'request-value'}):
            assert module.get_config_value('OPENAI_API_KEY') == 'request-value'
            assert module.export_config_environment('cloud')['OPENAI_API_KEY'] == 'request-value'
    monkeypatch.setenv('JARVIS_OVERRIDE_OPENAI_API_KEY', 'process-override')
    with module.config_scope('local'):
        assert module.get_config_value('OPENAI_API_KEY') == 'process-override'
        child = module.export_config_environment('local')
        assert child['JARVIS_OVERRIDE_OPENAI_API_KEY'] == 'process-override'


@pytest.mark.parametrize('module', config_modules(), ids=lambda module: module.__name__)
def test_temporary_mode_files_keep_their_exact_production_ownership(module, monkeypatch, tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'cloud.env').write_text('OPENAI_API_KEY=cloud-file\n')
    (tmp_path / 'config' / 'local.env').write_text('OLLAMA_MODEL=local-file\n')
    monkeypatch.setattr(module, 'get_project_root', lambda: tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'stale-cloud-process-value')
    monkeypatch.setenv('SUITE_UNOWNED_SETTING', 'unowned-process-value')
    with module.config_scope('cloud') as snapshot:
        assert snapshot.mode_keys == {'OPENAI_API_KEY', 'OLLAMA_MODEL'}
        assert module.get_config_value('OPENAI_API_KEY') == 'cloud-file'
    with module.config_scope('local'):
        assert module.get_config_value('OPENAI_API_KEY', 'caller-default') == 'caller-default'
        assert module.get_config_value('OLLAMA_MODEL') == 'local-file'
        assert module.get_config_value('SUITE_UNOWNED_SETTING') == 'unowned-process-value'
        child = module.export_config_environment('local')
        assert 'OPENAI_API_KEY' not in child
        assert child['OLLAMA_MODEL'] == 'local-file'


@pytest.mark.parametrize('module', config_modules(), ids=lambda module: module.__name__)
def test_explicit_mode_loader_fixture_is_authoritative_without_private_reads(module, monkeypatch):
    configs = {
        'cloud': {'TTS_PROVIDER': 'elevenlabs'},
        'local': {'TTS_PROVIDER': 'kokoro'},
    }
    monkeypatch.setattr(module, '_load_mode_config', lambda mode: dict(configs[mode]))
    monkeypatch.setenv('TTS_PROVIDER', 'stale-process-provider')
    with module.config_scope('local') as snapshot:
        assert snapshot.mode_keys == {'TTS_PROVIDER'}
        assert module.get_config_value('TTS_PROVIDER') == 'kokoro'
        child = module.export_config_environment('local')
        assert child['TTS_PROVIDER'] == 'kokoro'
    child = module.export_config_environment('local')
    assert child['TTS_PROVIDER'] == 'kokoro'


def test_live_browser_flag_does_not_disable_isolation_for_other_tests():
    env = dict(os.environ, JARVIS_LIVE_BROWSER_TEST='1', OLLAMA_MODEL='operator-model',
               OPENAI_API_KEY='operator-secret')
    result = subprocess.run([sys.executable, '-c', """
import os
import sys
sys.path.insert(0, 'tests')
from suite_isolation import ROOT, config_modules, install_default_isolation
install_default_isolation()
assert os.environ['JARVIS_LIVE_BROWSER_TEST'] == '1'
assert 'OLLAMA_MODEL' not in os.environ
assert 'OPENAI_API_KEY' not in os.environ
for module in config_modules():
    assert module.load_env_file(ROOT / 'config/cloud.env') == {}
    os.environ['OPENAI_API_KEY'] = 'later-process-value'
    with module.config_scope('cloud'):
        assert module.get_config_value('OPENAI_API_KEY', 'masked') == 'masked'
"""], cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_live_configuration_reader_is_explicit_and_does_not_hydrate_globals(monkeypatch):
    reader = Mock(return_value={
        'OLLAMA_MODEL': 'explicit-live-fixture', 'STASH_DIR': '${HOME}/live-fixture',
    })
    monkeypatch.setattr(suite_isolation, '_ORIGINAL_MODE_READER', reader)
    monkeypatch.delenv('JARVIS_LIVE_BROWSER_TEST', raising=False)
    with pytest.raises(RuntimeError, match='requires'):
        suite_isolation.load_live_mode_config('cloud')
    reader.assert_not_called()
    monkeypatch.setenv('JARVIS_LIVE_BROWSER_TEST', '1')
    monkeypatch.setenv('HOME', '/fixture/home')
    before = os.environ.copy()
    assert suite_isolation.load_live_mode_config('cloud') == {
        'OLLAMA_MODEL': 'explicit-live-fixture', 'STASH_DIR': '/fixture/home/live-fixture',
    }
    reader.assert_called_once_with(ROOT / 'config/cloud.env')
    assert os.environ == before
