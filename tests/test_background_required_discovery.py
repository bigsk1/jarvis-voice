"""Background-only discovery uses request exclusions without mutating Tool RAG."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'lib'), str(ROOT / 'orchestrator')]

from test_task_callbacks import configured  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402

from lib.background_tasks.admission import (  # noqa: E402
    BackgroundAdmissionService,
    background_only_exclusions,
)


@pytest.fixture
def discovery(tmp_path):
    integration, source, credential, now = configured(tmp_path)
    store = integration.store
    required = ToolSchema('callback_probe', 'Background-only browser research', {'type': 'object'}, '/never',
                         execution={'background': {'supported': True, 'required': True, 'adapter': 'http_callback_v1'}})
    ordinary = ToolSchema('convert_file', 'Convert a file', {'type': 'object'}, '/never',
                         execution={'background': {'supported': True, 'adapter': 'local_skill_v1'}})
    tools = {tool.name: tool for tool in (required, ordinary)}
    registry = SimpleNamespace(tools=tools, get_tool=tools.get, list_tools=lambda: list(tools),
                               find_tools=lambda *a, **kw: list(tools.values()))
    state = {'coordinator': True, 'source_current': True, 'helper': True}
    store.touch_worker('worker', {'http_callback_v1'})
    service = BackgroundAdmissionService(store, adapters={'callback_probe': 'http_callback_v1'},
        callback_sources={'callback_probe': source['id']}, ready=lambda: state['coordinator'],
        callback_readiness={'callback_probe': lambda: state['helper']},
        validate_source=lambda _: state['source_current'])
    context = service.authorize({'source': 'web', 'selected': ['callback_probe'], 'tool_policy': 'auto'}, registry)
    return SimpleNamespace(integration=integration, source=source, credential=credential, now=now,
                           store=store, registry=registry, state=state, context=context, service=service)


@pytest.mark.parametrize('condition', [
    'ready', 'background_off', 'unselected', 'receiver_off', 'source_paused', 'source_revoked',
    'untested', 'missing_failure_event', 'expired_credential', 'revoked_credential', 'missing_key',
    'worker_off', 'wrong_adapter', 'coordinator_off', 'helper_off', 'source_changed', 'unmapped', 'non_web',
])
def test_required_tool_is_hidden_until_all_execution_requirements_hold(discovery, monkeypatch, condition):
    from tool_search_runtime import search_tools_runtime
    h = discovery
    if condition == 'background_off':
        h.store.configure(background_enabled=False)
    elif condition == 'unselected':
        h.store.configure(background_tools=[])
    elif condition == 'receiver_off':
        h.integration.configure(False)
    elif condition == 'source_paused':
        h.integration.update_source(h.source['id'], h.source['revision'], enabled=False)
    elif condition == 'source_revoked':
        h.integration.update_source(h.source['id'], h.source['revision'], revoke=True)
    elif condition == 'untested':
        h.integration.update_source(h.source['id'], h.source['revision'], submit_url='http://127.0.0.1:9002/submit')
    elif condition == 'missing_failure_event':
        with h.store._connection(write=True) as conn:
            conn.execute('UPDATE task_integrations SET events_json=?', (json.dumps(['task.completed']),))
    elif condition == 'expired_credential':
        with h.store._connection(write=True) as conn:
            conn.execute('UPDATE task_credentials SET expires_at=0 WHERE probe=0')
    elif condition == 'revoked_credential':
        h.integration.revoke_credential(h.source['id'], h.credential['id'])
    elif condition == 'missing_key':
        h.integration.keys.path.unlink()
    elif condition == 'worker_off':
        h.store.touch_worker('worker', {'http_callback_v1'}, draining=True)
    elif condition == 'wrong_adapter':
        h.store.touch_worker('worker', {'local_skill_v1'})
    elif condition == 'coordinator_off':
        h.state['coordinator'] = False
    elif condition == 'helper_off':
        h.state['helper'] = False
    elif condition == 'source_changed':
        h.state['source_current'] = False
    elif condition == 'unmapped':
        h.service.callback_sources.clear()
    elif condition == 'non_web':
        h.context = None

    expected = set() if condition == 'ready' else {'callback_probe'}
    assert background_only_exclusions(h.registry, h.context) == expected
    # The same stale indexed rows remain present through every setting change.
    indexed = [{'name': 'callback_probe', 'similarity': .99}, {'name': 'convert_file', 'similarity': .8}]
    db = SimpleNamespace(search_tools=lambda *a, **kw: indexed, close=lambda: None)
    monkeypatch.setattr('tool_search_runtime.get_memory_db', lambda: db)
    for lookup in ({'query': 'browser research'}, {'tool_names': ['callback_probe', 'convert_file']}, {}):
        result = search_tools_runtime(registry=h.registry, background_context=h.context, **lookup)
        assert {item['name'] for item in result['data']['matches']} == set(h.registry.tools) - expected
    assert set(h.registry.tools) == {'callback_probe', 'convert_file'}
    with h.store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM authorizations').fetchone()[0] == 0


def test_receiver_toggle_updates_discovery_without_sync_and_is_rechecked_at_admission(discovery):
    from lib.background_tasks import TaskError
    h = discovery
    assert not background_only_exclusions(h.registry, h.context)
    h.integration.configure(False)
    # The current turn keeps its discovery snapshot; a new turn sees the toggle.
    assert not background_only_exclusions(h.registry, h.context)
    # A model already holding the schema cannot queue after the toggle changes.
    with pytest.raises(TaskError, match='receiver is disabled'):
        h.context.admit('callback_probe', {}, 'late-call', h.registry.get_tool('callback_probe'))
    h.context = h.service.authorize({'source': 'web', 'selected': ['callback_probe'],
                                     'tool_policy': 'auto'}, h.registry, defer_readiness=True)
    assert background_only_exclusions(h.registry, h.context) == {'callback_probe'}
    h.integration.configure(True)
    h.context = h.service.authorize({'source': 'web', 'selected': ['callback_probe'],
                                     'tool_policy': 'auto'}, h.registry, defer_readiness=True)
    assert not background_only_exclusions(h.registry, h.context)


def test_reviewed_callback_timeout_is_persisted_at_admission(discovery):
    h = discovery
    h.context.authorization.update({
        'conversation_id': 'conversation', 'generation': 0, 'request_id': 'request', 'mode': 'cloud',
        'tool_policies': {'callback_probe': {'timeout_seconds': 7200}},
    })
    receipt = h.context.admit('callback_probe', {}, 'long-callback', h.registry.get_tool('callback_probe'))
    job = h.store.get(receipt['job_id'])
    assert job['admission']['timeout_seconds'] == 7200
    assert job['deadline'] - job['created_at'] == 7200


def test_browser_readiness_is_computed_once_for_route_and_tool_search(discovery, monkeypatch):
    from tool_search_runtime import search_tools_runtime

    h = discovery
    checks = []
    original = h.context.service.check_ready

    def checked(context, name, schema):
        checks.append(name)
        return original(context, name, schema)

    monkeypatch.setattr(h.context.service, 'check_ready', checked)
    assert background_only_exclusions(h.registry, h.context) == set()
    assert background_only_exclusions(h.registry, h.context) == set()
    search_tools_runtime(registry=h.registry, background_context=h.context, tool_names=['callback_probe'])
    assert checks == ['callback_probe']


def test_selected_browser_readiness_denial_is_logged_once(discovery, caplog):
    h = discovery
    h.state['helper'] = False
    assert background_only_exclusions(h.registry, h.context) == {'callback_probe'}
    assert background_only_exclusions(h.registry, h.context) == {'callback_probe'}
    messages = [record.message for record in caplog.records if 'Background-only tool hidden' in record.message]
    assert len(messages) == 1 and 'callback service is stopped' in messages[0]


@pytest.mark.parametrize('available,manual_block', [(False, False), (True, False), (True, True)])
def test_router_never_sends_excluded_required_schema_even_with_exact_hint_or_ghost(discovery, monkeypatch, available, manual_block):
    from config_loader import config_scope
    from router_v2 import LLMRouter
    h = discovery
    if not available:
        h.integration.configure(False)
    router = LLMRouter.__new__(LLMRouter)
    router.mode, router.registry = 'cloud', h.registry
    calls = []
    def answer(**kwargs):
        calls.append(kwargs)
        return 'Answer', None, None, None
    router.provider = SimpleNamespace(chat_with_tools=answer)
    router.provider_type, router.model_name = 'openai', 'test'
    router.timezone = ZoneInfo('UTC')
    router.prompt_override = None
    router._system_prompt_base = 'Router system'
    router._provider_override = router._model_override = None
    router.system_prompt_version = 'test'
    monkeypatch.setattr('thinking.should_enable_thinking', lambda **_: False)
    monkeypatch.setattr('llm_logger.get_logger', lambda *_: SimpleNamespace(log_llm_call=lambda **_: None))
    with config_scope('cloud', overrides={'TOOL_RAG_TRACE_ENABLED': 'false', 'GHOST_TOOLS': 'callback_probe'}):
        result = router.route('Use callback_probe to research this page.', background_context=h.context,
                              excluded_tools=['callback_probe'] if manual_block else [])
    offered = {item['function']['name'] for item in calls[0]['tools']}
    assert ('callback_probe' in offered) == (available and not manual_block)
    assert 'convert_file' in offered
    assert set(result['available_tools']) == offered
