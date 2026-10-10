"""Web Completion Guard must use one provider/model pair in UI and execution."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
load_server_package('guard_selection_test_server', ROOT / 'jarvis-web/server')
settings_module = importlib.import_module('guard_selection_test_server.services.settings_manager')
policy_module = importlib.import_module('guard_selection_test_server.services.completion_guard')
chat_module = importlib.import_module('guard_selection_test_server.sockets.chat')


@pytest.fixture
def runtime(monkeypatch):
    import config_loader
    import llm_provider

    configs = {
        'cloud': {
            'LLM_PROVIDER': 'ollama', 'OLLAMA_CLOUD_MODEL': 'sample-chat:cloud',
            'XAI_MODEL': 'grok-env-model', 'OPENAI_MODEL': 'gpt-env-model',
            'ANTHROPIC_MODEL': 'claude-env-model', 'OLLAMA_API_KEY': 'test-ollama-key',
            'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER': 'ollama',
            'JARVIS_COMPLETION_GUARD_EVAL_MODEL': 'sample-evaluator:cloud',
        },
        'local': {
            'LLM_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'sample-local-chat',
            'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER': 'ollama',
            'JARVIS_COMPLETION_GUARD_EVAL_MODEL': 'sample-local-evaluator',
        },
    }
    web = {'cloud': {'llm_provider': 'ollama', 'llm_model': 'sample-new-chat',
                     'completion_guard_eval_provider': 'xai', 'completion_guard_eval_model': None},
           'local': {}}
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda mode: dict(configs[mode]))
    monkeypatch.setattr(settings_module, 'load_web_config', lambda: web)
    monkeypatch.setattr(policy_module, 'load_web_config', lambda: web)
    monkeypatch.setattr(settings_module.SettingsManager, '_get_provider_models', lambda self: {})
    monkeypatch.setattr(settings_module.SettingsManager, 'get_provider_availability', lambda self: {})
    monkeypatch.setattr(settings_module.SettingsManager, '_xai_uses_oauth', lambda self: False)
    calls = []

    def create(provider, **kwargs):
        calls.append((provider, kwargs))
        return SimpleNamespace(model=kwargs['model'])

    monkeypatch.setattr(llm_provider, 'create_provider', create)
    return SimpleNamespace(configs=configs, web=web, calls=calls, scope=config_loader.config_scope)


def selection(mode):
    handler = chat_module.ChatHandler.__new__(chat_module.ChatHandler)
    ui = settings_module.SettingsManager(mode).get_settings_for_ui()['completion_guard']
    policy = handler._get_completion_guard_config(mode)
    provider, model, _ = handler._create_completion_guard_eval_provider(mode, policy)
    return ui, policy, provider, model


@pytest.mark.parametrize('provider,expected', [
    ('xai', 'grok-env-model'), ('openai', 'gpt-env-model'), ('anthropic', 'claude-env-model'),
])
def test_changed_web_provider_uses_its_default_in_ui_and_runtime(runtime, provider, expected):
    runtime.web['cloud']['completion_guard_eval_provider'] = provider
    with runtime.scope('cloud'):
        ui, policy, selected, model = selection('cloud')
    assert ui['eval_provider']['value'] == policy['eval_provider'] == selected == provider
    assert ui['eval_model']['value'] == ui['eval_model']['default'] == policy['eval_model'] == model == expected
    assert ui['eval_model']['is_override'] is False


def test_opposite_provider_switch_uses_cloud_ollama_default(runtime):
    runtime.configs['cloud'].update(JARVIS_COMPLETION_GUARD_EVAL_PROVIDER='xai',
                                   JARVIS_COMPLETION_GUARD_EVAL_MODEL='grok-dedicated-evaluator')
    runtime.web['cloud']['completion_guard_eval_provider'] = 'ollama'
    with runtime.scope('cloud'):
        ui, policy, provider, model = selection('cloud')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'sample-chat:cloud'
    assert provider == 'ollama'


def test_same_provider_keeps_dedicated_env_evaluator_separate_from_chat(runtime):
    runtime.web['cloud']['completion_guard_eval_provider'] = 'ollama'
    with runtime.scope('cloud'):
        ui, policy, provider, model = selection('cloud')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'sample-evaluator:cloud'
    assert provider == 'ollama'
    assert runtime.web['cloud']['llm_model'] == 'sample-new-chat'


def test_explicit_web_evaluator_model_wins(runtime):
    runtime.web['cloud']['completion_guard_eval_model'] = 'grok-explicit-evaluator'
    with runtime.scope('cloud'):
        ui, policy, provider, model = selection('cloud')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'grok-explicit-evaluator'
    assert ui['eval_model']['default'] == 'grok-env-model'
    assert ui['eval_model']['is_override'] is True and provider == 'xai'


def test_blank_env_evaluator_model_uses_configured_provider_model(runtime):
    runtime.web['cloud'] = {}
    runtime.configs['cloud']['JARVIS_COMPLETION_GUARD_EVAL_MODEL'] = ''
    with runtime.scope('cloud'):
        ui, policy, provider, model = selection('cloud')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'sample-chat:cloud'
    assert provider == 'ollama'


def test_local_scope_does_not_borrow_cloud_evaluator_or_web_settings(runtime):
    with runtime.scope('local'):
        ui, policy, provider, model = selection('local')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'sample-local-evaluator'
    assert provider == 'ollama'


def test_admitted_guard_selection_survives_later_web_setting_change(runtime):
    handler = chat_module.ChatHandler.__new__(chat_module.ChatHandler)
    with runtime.scope('cloud'):
        admitted = handler._get_completion_guard_config('cloud')
        runtime.web['cloud']['completion_guard_eval_provider'] = 'ollama'
        provider, model, _ = handler._create_completion_guard_eval_provider('cloud', admitted)
    assert provider == 'xai' and model == 'grok-env-model'


def test_stale_cloud_model_from_other_provider_is_not_sent(runtime):
    runtime.web['cloud']['completion_guard_eval_model'] = 'stale-ollama-evaluator:cloud'
    with runtime.scope('cloud'):
        ui, policy, provider, model = selection('cloud')
    assert ui['eval_model']['value'] == policy['eval_model'] == model == 'grok-env-model'
    assert ui['eval_model']['is_override'] is False and provider == 'xai'


def test_missing_guard_snapshot_uses_current_web_selection(runtime):
    handler = chat_module.ChatHandler.__new__(chat_module.ChatHandler)
    with runtime.scope('cloud'):
        provider, model, _ = handler._create_completion_guard_eval_provider('cloud')
    assert provider == 'xai' and model == 'grok-env-model'


def test_old_guard_snapshot_with_mismatched_model_is_resolved_before_execution(runtime):
    handler = chat_module.ChatHandler.__new__(chat_module.ChatHandler)
    with runtime.scope('cloud'):
        provider, model, _ = handler._create_completion_guard_eval_provider('cloud', {
            'eval_provider': 'xai', 'eval_model': 'old-ollama-evaluator:cloud',
        })
    assert provider == 'xai' and model == 'grok-env-model'


def test_web_evaluator_selection_does_not_change_env_foreground_provider(runtime):
    import llm_provider

    with runtime.scope('cloud'):
        _, _, guard_provider, guard_model = selection('cloud')
        native_provider, native_model, _ = llm_provider.create_configured_provider(mode='cloud')
    assert guard_provider == 'xai' and guard_model == 'grok-env-model'
    assert native_provider == 'ollama' and native_model == 'sample-chat:cloud'


def test_evaluator_construction_disables_native_search_and_leaves_env_config_intact(runtime):
    import config_loader

    with runtime.scope('cloud'):
        before = (config_loader.get_config_value('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER'),
                  config_loader.get_config_value('JARVIS_COMPLETION_GUARD_EVAL_MODEL'))
        selection('cloud')
        after = (config_loader.get_config_value('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER'),
                 config_loader.get_config_value('JARVIS_COMPLETION_GUARD_EVAL_MODEL'))
    assert before == after == ('ollama', 'sample-evaluator:cloud')
    assert runtime.calls[-1][1]['enable_search'] is False
