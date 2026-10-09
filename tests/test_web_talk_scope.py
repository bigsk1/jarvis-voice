"""Real chat admission and request scopes with temporary history and a fake LLM."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_web_attachment_bundle_chat import chat, web_config
from test_web_attachment_bundle_chat import journey as bundle_journey

journey = bundle_journey


def test_talk_admission_history_and_scope_do_not_change_next_text_turn(journey, monkeypatch):
    import orchestrator_v2
    from config_loader import get_config_value

    monkeypatch.setattr(web_config, 'load_web_config', lambda: {
        'cloud': {'response_style': 'detailed', 'qa_word_limit': 310, 'multi_turn_word_limit': 220},
    })
    observed = []
    process = orchestrator_v2.Orchestrator.process

    def capture(self, *args, **kwargs):
        observed.append((get_config_value('JARVIS_RESPONSE_STYLE'),
                         get_config_value('JARVIS_QA_WORD_LIMIT'),
                         get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT')))
        return process(self, *args, **kwargs)

    monkeypatch.setattr(orchestrator_v2.Orchestrator, 'process', capture)
    journey.send(message='A spoken question.', input_mode='talk', tool_policy='none')
    journey.process()
    cid = journey.handler.sessions['client']['conversation_id']
    assert journey.store.get_conversation(cid)['messages'][0]['content'] == 'A spoken question.'
    journey.send(message='An ordinary follow-up.', conversation_id=cid)
    journey.process()
    assert observed == [('casual', '310', '220'), ('detailed', '310', '220')]
    assert journey.routes[0][1]['tool_policy'] == 'none'
    assert journey.routes[1][1]['conversation_history'][0]['content'] == 'A spoken question.'


def test_concurrent_talk_and_text_requests_keep_independent_preferences(monkeypatch):
    from config_loader import get_config_value

    monkeypatch.setattr(web_config, 'load_web_config', lambda: {
        'local': {'response_style': 'detailed', 'qa_word_limit': 310},
    })
    barrier = Barrier(2)

    @chat._scoped_by_mode
    def read(mode, prompt_meta):
        barrier.wait(timeout=10)
        return (get_config_value('JARVIS_RESPONSE_STYLE'), get_config_value('JARVIS_QA_WORD_LIMIT'))

    with ThreadPoolExecutor(max_workers=2) as pool:
        talk = pool.submit(read, 'local', {'input_mode': 'talk'})
        text = pool.submit(read, 'local', {'input_mode': 'unknown'})
        assert talk.result(timeout=15) == ('casual', '310')
        assert text.result(timeout=15) == ('detailed', '310')


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('web_blocks', [[], ['mcp_fetch_fetch', 'mcp_brave_search_brave_web_search']])
def test_web_mcp_blocks_add_to_mode_policy_without_changing_process_environment(monkeypatch, mode, web_blocks):
    import os

    import config_loader
    from config_loader import get_config_value
    monkeypatch.setenv('BLOCKED_TOOLS', 'process-sentinel')
    monkeypatch.delenv('JARVIS_OVERRIDE_BLOCKED_TOOLS', raising=False)
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda selected: {
        'BLOCKED_TOOLS': f'{selected}_mode_block,mcp_fetch_fetch',
    })
    monkeypatch.setattr(web_config, 'load_web_config', lambda: {
        'tools': {'blocked': web_blocks},
    })
    @chat._scoped_by_mode
    def read(mode):
        return get_config_value('BLOCKED_TOOLS'), os.environ['BLOCKED_TOOLS']
    scoped, process = read(mode)
    assert set(scoped.split(',')) == {f'{mode}_mode_block', 'mcp_fetch_fetch'} | set(web_blocks)
    assert process == 'process-sentinel'
    assert os.environ['BLOCKED_TOOLS'] == 'process-sentinel'


def test_web_request_passes_combined_blocks_to_existing_execution_path(journey, monkeypatch):
    import config_loader
    import orchestrator_v2
    monkeypatch.delenv('JARVIS_OVERRIDE_BLOCKED_TOOLS', raising=False)
    load_mode = config_loader._load_mode_config
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda mode: {
        **load_mode(mode), 'BLOCKED_TOOLS': 'mcp_fetch_fetch',
    })
    settings = web_config.load_web_config()
    settings.setdefault('tools', {})['blocked'] = ['web_only']
    monkeypatch.setattr(web_config, 'load_web_config', lambda: settings)
    observed = []
    process = orchestrator_v2.Orchestrator.process
    def capture(self, *args, **kwargs):
        observed.append(set(kwargs.get('excluded_tools', [])))
        return process(self, *args, **kwargs)
    monkeypatch.setattr(orchestrator_v2.Orchestrator, 'process', capture)
    journey.send(message='Answer in chat.', tool_policy='none')
    journey.process()
    assert observed == [{'mcp_fetch_fetch', 'web_only'}]


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('source', ['mode_env', 'web', 'default'])
def test_talk_inherits_word_limits_from_normal_config_precedence(monkeypatch, mode, source):
    import config_loader

    for key in ('JARVIS_QA_WORD_LIMIT', 'JARVIS_MULTI_TURN_WORD_LIMIT'):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f'JARVIS_OVERRIDE_{key}', raising=False)
    mode_values = {
        'cloud': {'JARVIS_QA_WORD_LIMIT': '120', 'JARVIS_MULTI_TURN_WORD_LIMIT': '150'},
        'local': {'JARVIS_QA_WORD_LIMIT': '40', 'JARVIS_MULTI_TURN_WORD_LIMIT': '50'},
    }
    monkeypatch.setattr(config_loader, '_load_mode_config', lambda selected: (
        {} if source == 'default' else mode_values[selected]
    ))
    monkeypatch.setattr(web_config, 'load_web_config', lambda: (
        {mode: {'qa_word_limit': 95}} if source == 'web' else {}
    ))

    @chat._scoped_by_mode
    def read(mode, prompt_meta):
        return (
            config_loader.get_config_value('JARVIS_RESPONSE_STYLE'),
            config_loader.get_config_value(
                'JARVIS_QA_WORD_LIMIT', str(config_loader.DEFAULT_JARVIS_QA_WORD_LIMIT)),
            config_loader.get_config_value(
                'JARVIS_MULTI_TURN_WORD_LIMIT', str(config_loader.DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)),
        )

    expected = ('75', '75') if source == 'default' else (
        '95' if source == 'web' else mode_values[mode]['JARVIS_QA_WORD_LIMIT'],
        mode_values[mode]['JARVIS_MULTI_TURN_WORD_LIMIT'],
    )
    assert read(mode, {'input_mode': 'talk'}) == ('casual', *expected)
